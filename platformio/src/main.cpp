/**
 * TH.py (MicroPython) 的 C++ 移植版 —— ESP32-C3 / PlatformIO
 *
 * 功能完全对应原脚本：
 *   WiFi 连接 -> AHT20(温湿度) + BMP280(气压/二号温度) -> 每 5s 以 JSON 发 MQTT
 *   主题: sensor/terminal/<mac>   设备 ID: esp32c3_<mac>
 *   断线自动重连（WiFi / MQTT / 传感器）
 *
 * 串口: 使用 ESP32-C3 原生 USB CDC（Serial 即 USB），115200
 */

#include <Arduino.h>

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <Adafruit_BMP280.h>
#include <AHT20.h>
#include <ArduinoJson.h>
#include <esp_mac.h>

// ===================== 1. 基础配置区 =====================
static const char *WIFI_SSID = "swu-wifi(2.4G)";
static const char *WIFI_PASSWORD = "";

// MQTT 服务器（可以是局域网 IP 或域名）
static const char *MQTT_BROKER = "10.65.78.91";
static const uint16_t MQTT_PORT = 1883;
// 无鉴权的 broker 保持 nullptr 即可
static const char *MQTT_USER = nullptr;
static const char *MQTT_PASSWORD = nullptr;

static const uint32_t SEND_INTERVAL_MS = 5000;     // 上报周期
static const uint32_t RETRY_DELAY_MS = 5000;       // 出错后重试间隔
static const uint32_t WIFI_TIMEOUT_MS = 20000;     // 单次 WiFi 连接超时
static const uint8_t MQTT_CONNECT_TRIES = 3;       // 单轮 MQTT 连接尝试次数
static const uint16_t MQTT_KEEPALIVE_S = 60;       // 对应 Python keepalive=60
static const char *TIMEZONE = "CST-8";             // 东八区，日志时间戳用
// ========================================================

// ================ 2. 硬件引脚 (ESP32-C3 I2C0) ================
static const int8_t PIN_I2C_SDA = 4;
static const int8_t PIN_I2C_SCL = 5;
static const uint32_t I2C_FREQ_HZ = 100000;
static const uint8_t ADDR_AHT20 = 0x38;
static const uint8_t ADDR_BMP280 = 0x77;
// ===========================================================

static WiFiClient wifiClient;
static PubSubClient mqtt(wifiClient);
static AHT20 aht(ADDR_AHT20);
static Adafruit_BMP280 bmp(&Wire);

static char mqttClientId[32];  // esp32c3_aabbccddeeff
static char mqttTopic[48];     // sensor/terminal/aabbccddeeff
static bool ahtReady = false;
static bool bmpReady = false;

struct Sample {
  float ahtTemp = NAN;
  float ahtHumi = NAN;
  float bmpTemp = NAN;
  float bmpPress = NAN;  // Pa
};

// ---------------------- 小工具 ----------------------

static void logf(const char *fmt, ...) {
  char body[256];
  va_list args;
  va_start(args, fmt);
  vsnprintf(body, sizeof(body), fmt, args);
  va_end(args);

  char stamp[20];
  time_t now = time(nullptr);
  struct tm local;
  if (now > 1700000000 && localtime_r(&now, &local)) {
    strftime(stamp, sizeof(stamp), "%H:%M:%S", &local);
  } else {
    snprintf(stamp, sizeof(stamp), "%lu ms", (unsigned long)(millis() / 1000));
  }
  Serial.printf("[%s] %s\n", stamp, body);
}

static float round2(float value) { return roundf(value * 100.0f) / 100.0f; }

static const char *mqttStateName(int state) {
  switch (state) {
    case MQTT_CONNECTED: return "已连接";
    case MQTT_CONNECTION_TIMEOUT: return "连接超时";
    case MQTT_CONNECTION_LOST: return "连接丢失";
    case MQTT_CONNECT_FAILED: return "TCP 连接失败";
    case MQTT_DISCONNECTED: return "已断开";
    case MQTT_CONNECT_BAD_PROTOCOL: return "协议版本被拒";
    case MQTT_CONNECT_BAD_CLIENT_ID: return "Client ID 非法";
    case MQTT_CONNECT_UNAVAILABLE: return "broker 不可用";
    case MQTT_CONNECT_BAD_CREDENTIALS: return "用户名/密码错误";
    case MQTT_CONNECT_UNAUTHORIZED: return "未授权";
    default: return "未知错误";
  }
}

// 自动生成唯一标识，多设备直刷互不冲突（对应 Python 的 machine.unique_id()）
static void buildIdentity() {
  uint8_t mac[6] = {0};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char suffix[13];
  snprintf(suffix, sizeof(suffix), "%02x%02x%02x%02x%02x%02x", mac[0], mac[1],
           mac[2], mac[3], mac[4], mac[5]);
  snprintf(mqttClientId, sizeof(mqttClientId), "esp32c3_%s", suffix);
  snprintf(mqttTopic, sizeof(mqttTopic), "sensor/terminal/%s", suffix);
  logf("当前设备 Client ID: %s", mqttClientId);
  logf("发布的主题 Topic: %s", mqttTopic);
}

static void scanI2C() {
  logf("扫描 I2C 总线 (SDA=%d SCL=%d)...", PIN_I2C_SDA, PIN_I2C_SCL);
  uint8_t found = 0;
  for (uint8_t addr = 0x08; addr <= 0x77; ++addr) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      logf("  发现 I2C 设备: 0x%02x", addr);
      ++found;
    }
  }
  if (!found) logf("  未发现任何 I2C 设备，请检查接线");
}

// ---------------------- 网络 ----------------------

static bool connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  logf("正在连接 WiFi: %s ...", WIFI_SSID);
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // 关掉 modem sleep，MQTT 更稳
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED &&
         millis() - started < WIFI_TIMEOUT_MS) {
    delay(500);
    Serial.print('.');
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    logf("WiFi 连接超时");
    WiFi.disconnect(true, true);
    return false;
  }
  logf("WiFi 连通! IP: %s RSSI: %d dBm",
       WiFi.localIP().toString().c_str(), WiFi.RSSI());
  return true;
}

static bool connectMqtt() {
  for (uint8_t tryIdx = 1; tryIdx <= MQTT_CONNECT_TRIES; ++tryIdx) {
    logf("正在连接 MQTT Broker %s:%u (第 %u 次尝试)...", MQTT_BROKER, MQTT_PORT,
         tryIdx);
    if (mqtt.connect(mqttClientId, MQTT_USER, MQTT_PASSWORD)) {
      logf("MQTT Broker 连接成功！");
      return true;
    }
    logf("MQTT 连接失败: %s (state=%d)", mqttStateName(mqtt.state()),
         mqtt.state());
    delay(RETRY_DELAY_MS);
  }
  return false;
}

// ---------------------- 传感器 ----------------------

static bool initSensors() {
  if (!ahtReady) {
    ahtReady = aht.begin();
    logf(ahtReady ? "AHT20 就绪 (0x%02x)" : "⚠️ AHT20 无响应 (0x%02x)",
         ADDR_AHT20);
  }
  if (!bmpReady) {
    bmpReady = bmp.begin(ADDR_BMP280);
    if (bmpReady) {
      // 对应 MicroPython 的 oversample(BMP280_OS_HIGH) + 手持动态场景
      bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,
                      Adafruit_BMP280::SAMPLING_X16,
                      Adafruit_BMP280::SAMPLING_X16,
                      Adafruit_BMP280::FILTER_OFF,
                      Adafruit_BMP280::STANDBY_MS_1);
    }
    logf(bmpReady ? "BMP280 就绪 (0x%02x)" : "⚠️ BMP280 无响应 (0x%02x)",
         ADDR_BMP280);
  }
  return ahtReady && bmpReady;
}

static bool readSensors(Sample &sample) {
  if (ahtReady) {
    sample.ahtTemp = aht.getTemperature();
    sample.ahtHumi = aht.getHumidity();
  }
  if (bmpReady) {
    sample.bmpTemp = bmp.readTemperature();
    sample.bmpPress = bmp.readPressure();  // Pa，和 Python 版本一致
  }

  bool ok = ahtReady && bmpReady && !isnan(sample.ahtTemp) &&
            !isnan(sample.ahtHumi) && !isnan(sample.bmpTemp) &&
            !isnan(sample.bmpPress) && sample.bmpPress > 1000.0f;
  if (!ok) {
    // 读数异常多半是 I2C 掉线，下轮重新初始化
    ahtReady = false;
    bmpReady = false;
  }
  return ok;
}

// ---------------------- 上报 ----------------------

static bool publish(const Sample &sample) {
  JsonDocument doc;
  doc["device"] = mqttClientId;
  doc["temperature"] = round2(sample.ahtTemp);    // AHT20 温度
  doc["humidity"] = round2(sample.ahtHumi);       // AHT20 湿度
  doc["temperature_2"] = round2(sample.bmpTemp);  // BMP280 二号温度
  doc["pressure"] = round2(sample.bmpPress);      // BMP280 气压 (Pa)

  char payload[256];
  size_t len = serializeJson(doc, payload);
  if (len == 0 || len >= sizeof(payload)) {
    logf("JSON 序列化失败");
    return false;
  }
  if (!mqtt.publish(mqttTopic, reinterpret_cast<const uint8_t *>(payload),
                    static_cast<unsigned int>(len))) {
    return false;
  }
  logf("已发送: %s", payload);
  return true;
}

// ---------------------- 主流程 ----------------------

void setup() {
  Serial.begin(115200);
  uint32_t started = millis();
  while (!Serial && millis() - started < 3000) delay(10);  // 等 USB CDC 枚举
  Serial.println();
  logf("===== ESP32-C3 传感器上报节点启动（TH.py 移植）=====");

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, I2C_FREQ_HZ);
  scanI2C();
  initSensors();
  buildIdentity();

  setenv("TZ", TIMEZONE, 1);
  tzset();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);  // 域名会在连接时走 DNS
  mqtt.setKeepAlive(MQTT_KEEPALIVE_S);
  mqtt.setBufferSize(512);
  mqtt.setSocketTimeout(5);
  configTime(0, 0, "ntp.aliyun.com", "cn.pool.ntp.org", "pool.ntp.org");

  connectWifi();
}

void loop() {
  static uint32_t lastPublish = 0;

  if (!connectWifi()) {
    logf("5 秒后重试...");
    delay(RETRY_DELAY_MS);
    return;
  }

  if (!mqtt.connected() && !connectMqtt()) {
    logf("5 秒后重试...");
    delay(RETRY_DELAY_MS);
    return;
  }

  mqtt.loop();  // 维持 keepalive / 处理下行

  if (millis() - lastPublish >= SEND_INTERVAL_MS) {
    lastPublish = millis();
    Sample sample;
    if (!initSensors()) {
      logf("⚠️ 传感器尚未就绪，跳过本次上报");
    } else if (readSensors(sample)) {
      if (!publish(sample)) {
        logf("❌ 发布失败 (state=%d)，断开重连", mqtt.state());
        mqtt.disconnect();
      }
    } else {
      logf("⚠️ 传感器读数异常，跳过本次上报");
    }
  }

  delay(50);
}

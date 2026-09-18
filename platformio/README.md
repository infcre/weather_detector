# platformio —— TH.py 的 C++ (PlatformIO) 固件

`../TH.py`（MicroPython 版）的 Arduino-ESP32 移植：AHT20 + BMP280 → 每 5 秒向 MQTT 上报一条 JSON。

```
platformio/
├── platformio.ini      # ESP32-C3 / DIO / 40MHz flash / USB CDC
└── src/main.cpp        # 固件主程序（配置区在文件顶部）
```

## 1. 接线（I2C0）

| 传感器 | ESP32-C3 |
| ------ | -------- |
| SDA    | GPIO4    |
| SCL    | GPIO5    |
| VCC    | 3V3      |
| GND    | GND      |

AHT20 地址 `0x38`，BMP280 地址 `0x77`（与 MicroPython 版一致）。开机串口会打印 I2C 扫描结果，方便核对。

## 2. 修改配置

只改 `src/main.cpp` 顶部的「基础配置区」即可：`WIFI_SSID` / `WIFI_PASSWORD` / `MQTT_BROKER` / `MQTT_PORT`，
以及引脚、上报周期、重试间隔。Broker 有鉴权时填 `MQTT_USER` / `MQTT_PASSWORD`（默认 `nullptr` 表示匿名）。

Client ID 与主题仍由 MAC 自动生成：`esp32c3_<mac>`、`sensor/terminal/<mac>`，多设备直刷互不冲突，
`backend.py` 的 `sensor/terminal/+` 订阅不用改。

## 3. 编译 / 烧录 / 看日志

```bash
cd platformio
pio run                    # 编译
pio run -t upload          # 烧录（原生 USB 口通常是 /dev/ttyACM0）
pio device monitor         # 串口日志，已启用 USB CDC，115200
pio run -t upload -t monitor   # 一把梭
```

- 平台：`espressif32`，框架：`arduino`（ESP32-C3，RISC-V，160MHz）
- Flash：`DIO` + `40MHz` + `4MB`，分区表 `min_spiffs.csv`
- USB：`ARDUINO_USB_MODE=1` + `ARDUINO_USB_CDC_ON_BOOT=1`，所以 `Serial` 就是原生 USB 串口，
  烧录和日志走同一个口，不需要外接 UART 桥
- 如果板子是 ESP32-C3 SuperMini，可把 `board` 换成 `lolin_c3_mini`；只有 CH340/CP210x 串口芯片的板子
  把 `ARDUINO_USB_CDC_ON_BOOT` 改成 `0`，日志就走 UART0

## 4. 与 MicroPython 版的行为差异

| 项目            | TH.py (MicroPython)        | 本固件 (C++)                       |
| --------------- | -------------------------- | ---------------------------------- |
| MQTT 库         | `umqtt.simple`             | `knolleary/PubSubClient`           |
| 传感器库        | `ahtx0` / `bmp280`         | `dvarrel/AHT20` / `Adafruit BMP280` |
| BMP280 采样     | `OS_HIGH` + 手持动态场景   | `SAMPLING_X16` 温压双 16x，NORMAL  |
| 气压单位        | Pa                         | Pa（完全一致）                     |
| JSON            | `json.dumps(round(x, 2))`  | ArduinoJson + `round2()`，键名一致 |
| 断线处理        | 抛异常 + `sleep(5)` 重连   | WiFi/MQTT/传感器分层自愈，逻辑等价 |
| 额外能力        | —                          | NTP 对时（日志带真实时间）、I2C 扫描、RSSI 打印、看门狗友好的分步重试 |

传感器读数出现 `NaN`/越界时本轮跳过上报并重新初始化 I2C 设备，避免把脏数据写进数据库。

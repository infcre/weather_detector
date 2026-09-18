# weather_detector

一套简易的 **AI 微气象感知系统**：ESP32-C3 节点采集温湿度、气压，经 MQTT 上报，后端落库并提供接口，前端做可视化与降雨风险提示。

## 数据链路

```
AHT20 + BMP280  →  ESP32-C3 节点  →  MQTT Broker           →  backend.py  →  Flask API / 网页
 (I2C 0x38/0x77)   WiFi 每 5s 发一条   sensor/terminal/<mac>    SQLite 存储        ↓
                                                                  app.py (Streamlit 大屏)
```

## 目录说明

| 文件 / 目录 | 说明 |
| --- | --- |
| `TH.py` | 节点固件（MicroPython 版）。连 WiFi、读 AHT20 + BMP280，每 5 秒以 JSON 发布到 `sensor/terminal/<mac>`，断线自动重连 |
| `platformio/` | 同上功能的 C++ 移植版（PlatformIO / Arduino-ESP32，ESP32-C3、DIO、40MHz Flash、原生 USB CDC），编译烧录见 `platformio/README.md` |
| `backend.py` | MQTT 订阅 `sensor/terminal/+`，写入 SQLite（`weather_data.db`，默认保留 7 天），并起 Flask：`/`（自带网页）、`/api/data`（各设备最新值与在线状态）、`/api/history/<device_id>`（历史曲线） |
| `app.py` | Streamlit 可视化，5 秒自动刷新：A 点为真实设备数据，B 点为对比用的模拟数据（换成第二个节点即可双设备对比），输出温差、湿差、气压差与降雨风险评分 |

上报格式（单位与接口字段保持一致）：

```json
{"device": "esp32c3_aabbccddeeff", "temperature": 26.31, "humidity": 62.4,
 "temperature_2": 27.05, "pressure": 100932.18}
```

其中 `pressure` 单位为 **Pa**。

## 快速开始

1. **烧固件**：改 `TH.py` 顶部的 `WIFI_SSID` / `WIFI_PASSWORD` / `MQTT_BROKER`，用 mpremote 等方式刷入；
   或走 PlatformIO：`cd platformio && pio run -t upload && pio device monitor`
2. **装依赖**：`pip install flask paho-mqtt requests streamlit streamlit-autorefresh`
   （MicroPython 版还需设备端装 `ahtx0`、`bmp280`、`umqtt.simple`）
3. **起后端**：`python backend.py`，浏览器访问 `http://<服务器IP>:5000`
4. **起大屏**：`streamlit run app.py`

三处 MQTT 地址（节点 `TH.py`、`platformio/src/main.cpp`、`backend.py`）需指向同一个 Broker；
超过 30 秒未收到上报的后端会把设备标记为「离线」。

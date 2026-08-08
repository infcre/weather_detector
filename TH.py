import time
import network
import json
import machine
import binascii
from machine import Pin, I2C
import ahtx0
from bmp280 import BMP280, BMP280_CASE_HANDHELD_DYN, BMP280_OS_HIGH
from umqtt.simple import MQTTClient

# ====== 1. 基础配置区 ======
WIFI_SSID = "ssid_24"
WIFI_PASSWORD = "password"

# 填写你 MQTT 服务器的局域网 IP
MQTT_BROKER = "suyuke.f1.luyouxia.net" 
MQTT_PORT = 15494
# ==========================

# 2. 自动生成唯一标识，完美适配多设备直刷
mac_addr = binascii.hexlify(machine.unique_id()).decode('ascii')
MQTT_CLIENT_ID = f"esp32c3_{mac_addr}"
# MQTT频道名已修改为“terminal” (末端)
MQTT_TOPIC = f"sensor/terminal/{mac_addr}".encode() 

# 3. 初始化硬件 (ESP32-C3 需指定 I2C 编号 0)
i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=100000)

# 挂载 AHT20 传感器
aht = ahtx0.AHT20(i2c)

# 挂载 BMP280 传感器并配置
bmp = BMP280(i2c, addr=0x77)
bmp.use_case(BMP280_CASE_HANDHELD_DYN)
bmp.oversample(BMP280_OS_HIGH)

wlan = network.WLAN(network.STA_IF)

def connect_wifi():
    wlan.active(True)
    if not wlan.isconnected():
        print(f"正在连接 WiFi: {WIFI_SSID}...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        while not wlan.isconnected():
            time.sleep(1)
            print(".", end="")
    print(f"\nWiFi 连通! IP: {wlan.ifconfig()[0]}")

def main():
    while True:
        client = None
        try:
            connect_wifi()
            
            print(f"当前设备 Client ID: {MQTT_CLIENT_ID}")
            print(f"发布的主题 Topic: {MQTT_TOPIC.decode()}")
            
            client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT, keepalive=60)
            client.connect()
            print("MQTT Broker 连接成功！")

            while True:
                # 检查 WiFi 状态，断开则抛出异常触发重连
                if not wlan.isconnected():
                    raise OSError("WiFi 断开连接")

                # 读取 AHT20 温湿度
                aht_temp = aht.temperature
                aht_humi = aht.relative_humidity
                
                # 读取 BMP280 气压和二号温度
                bmp_temp = bmp.temperature
                bmp_press = bmp.pressure

                # 统一 JSON 数据格式
                data = {
                    "device": MQTT_CLIENT_ID,
                    "temperature": round(aht_temp, 2),        # AHT20 温度
                    "humidity": round(aht_humi, 2),           # AHT20 湿度
                    "temperature_2": round(bmp_temp, 2),      # BMP280 二号温度
                    "pressure": round(bmp_press, 2)           # BMP280 气压 (Pa)
                }
                
                payload = json.dumps(data).encode() # 转为 bytes
                client.publish(MQTT_TOPIC, payload)
                
                print(f"[{time.ticks_ms()}] 已发送: {payload.decode()}")
                time.sleep(5)

        except Exception as e:
            print(f"发生错误或断线: {e}")
            if client is not None:
                try:
                    client.disconnect()
                except:
                    pass
            print("5 秒后重试...")
            time.sleep(5)

if __name__ == "__main__":
    main()

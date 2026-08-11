import json
import time
import threading
import sqlite3
import os

from flask import Flask, jsonify, render_template_string, request
import paho.mqtt.client as mqtt


# ================= 配置区 =================
MQTT_BROKER = "frp-air.com"
MQTT_PORT = 64702

# 每个设备的主题格式：
# sensor/terminal/esp32c3_xxxxxxxxxxxx
#
# + 表示只接收 sensor/terminal/ 下一级的所有设备
MQTT_TOPIC = "sensor/terminal/+"

OFFLINE_SECONDS = 30
DATA_RETENTION_DAYS = 7
DB_PATH = "weather_data.db"
# ==========================================


app = Flask(__name__)

# 保存所有设备的最新数据
device_data = {}

# MQTT 线程和 Flask 线程会同时访问 device_data
data_lock = threading.Lock()

# 数据库锁
db_lock = threading.Lock()


# ================= 数据库操作 =================

def init_db():
    """初始化 SQLite 数据库"""
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sensor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device TEXT NOT NULL,
                temperature REAL,
                humidity REAL,
                temperature_2 REAL,
                pressure REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_device_timestamp 
            ON sensor_data(device, timestamp)
        ''')
        
        conn.commit()
        conn.close()

def insert_data(device_id, data):
    """插入传感器数据到数据库"""
    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO sensor_data 
                (device, temperature, humidity, temperature_2, pressure)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                device_id,
                data.get("temperature"),
                data.get("humidity"),
                data.get("temperature_2"),
                data.get("pressure")
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 数据库写入错误: {e}")

def cleanup_old_data():
    """清理超过保留期的旧数据"""
    while True:
        time.sleep(3600)  # 每小时检查一次
        
        with db_lock:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                
                cutoff_date = time.strftime('%Y-%m-%d %H:%M:%S', 
                                           time.localtime(time.time() - DATA_RETENTION_DAYS * 86400))
                
                cursor.execute(
                    'DELETE FROM sensor_data WHERE timestamp < ?',
                    (cutoff_date,)
                )
                
                deleted = cursor.rowcount
                conn.commit()
                conn.close()
                
                if deleted > 0:
                    print(f"🗑️ 清理了 {deleted} 条旧数据 ({cutoff_date} 之前)")
            except Exception as e:
                print(f"⚠️ 数据清理错误: {e}")


# ================= 数据处理 =================

def get_device_snapshot():
    """
    获取一份用于 API 和网页显示的数据副本。
    同时计算设备在线状态。
    """
    now = time.time()
    result = {}

    with data_lock:
        raw_data = {
            device_id: info.copy()
            for device_id, info in device_data.items()
        }

    for device_id, info in raw_data.items():
        last_update_time = info.get("_last_update_time", 0)
        is_online = (now - last_update_time) <= OFFLINE_SECONDS

        # 不把内部时间字段暴露给前端
        public_info = {
            key: value
            for key, value in info.items()
            if not key.startswith("_")
        }

        public_info["status"] = "在线" if is_online else "离线"
        public_info["status_color"] = "green" if is_online else "red"

        result[device_id] = public_info

    return result


# ================= MQTT 回调 =================

def on_connect(client, userdata, flags, reason_code, properties=None):
    """
    适配 paho-mqtt 2.x。
    """
    if not reason_code.is_failure:
        print("✅ 成功连接到 MQTT 服务器:", MQTT_BROKER)

        client.subscribe(MQTT_TOPIC)

        print("📡 已订阅主题:", MQTT_TOPIC)
    else:
        print("❌ MQTT 连接失败:", reason_code)


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)

        if not isinstance(data, dict):
            print("⚠️ 收到的数据不是 JSON 对象")
            return

        # 优先使用 JSON 中的 device
        # 如果没有，则使用 MQTT 主题最后一段作为设备 ID
        topic_device_id = msg.topic.rsplit("/", 1)[-1]
        device_id = data.get("device") or topic_device_id

        if device_id == "unknown":
            print("⚠️ 无法确定设备 ID，忽略数据")
            return

        # 写入数据库
        insert_data(device_id, data)

        current_data = {
            "device": device_id,

            # AHT20
            "temperature": data.get("temperature"),
            "humidity": data.get("humidity"),

            # BMP280
            "temperature_2": data.get("temperature_2"),
            "pressure": data.get("pressure"),

            # 最后更新时间
            "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),

            # 内部使用，不发送给前端
            "_last_update_time": time.time()
        }

        with data_lock:
            device_data[device_id] = current_data

        print("[{}] 更新成功: {}".format(device_id, current_data))

    except json.JSONDecodeError:
        print("⚠️ 收到非 JSON 数据:", msg.payload)

    except UnicodeDecodeError:
        print("⚠️ 收到无法解码的数据:", msg.payload)

    except Exception as e:
        print("⚠️ 处理 MQTT 消息时发生错误:", e)


# ================= MQTT 客户端 =================

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

client.on_connect = on_connect
client.on_message = on_message


# ================= Flask API =================

@app.route("/api/data", methods=["GET"])
def get_data():
    current_data = get_device_snapshot()

    return jsonify({
        "status": "success",
        "total_devices": len(current_data),
        "data": current_data
    })


@app.route("/api/history/<device_id>", methods=["GET"])
def get_history(device_id):
    """获取指定设备的历史数据
    
    参数:
        start: 开始时间 (ISO 8601格式)
        end: 结束时间 (ISO 8601格式)
        limit: 最大返回条数 (默认1000)
    """
    start = request.args.get('start')
    end = request.args.get('end')
    limit = int(request.args.get('limit', 1000))
    
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = 'SELECT * FROM sensor_data WHERE device = ?'
        params = [device_id]
        
        if start:
            query += ' AND timestamp >= ?'
            params.append(start)
        
        if end:
            query += ' AND timestamp <= ?'
            params.append(end)
        
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
    
    history = [dict(row) for row in rows]
    
    return jsonify({
        "status": "success",
        "device": device_id,
        "count": len(history),
        "data": history
    })


# ================= 网页 =================

@app.route("/", methods=["GET"])
def index():
    html_template = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="5">

        <title>所有单片机</title>

        <style>
            body {
                font-family: Arial, sans-serif;
                padding: 20px;
                background: #f4f6f8;
            }

            .card {
                background: white;
                padding: 20px;
                margin: 10px;
                width: 330px;
                display: inline-block;
                vertical-align: top;
            }

            h2 {
                color: #333;
            }

            h3 {
                margin-top: 0;
                padding-bottom: 10px;
                border-bottom: 1px solid #ddd;
                word-break: break-all;
            }

            .data {
                font-size: 18px;
                font-weight: bold;
                color: #007bff;
            }

            .status {
                float: right;
                color: white;
                padding: 3px 8px;
                font-size: 13px;
            }

            .time {
                font-size: 12px;
                color: #888;
                margin-top: 15px;
            }
        </style>
    </head>

    <body>
        <h2>所有单片机</h2>

        {% if device_data %}
            {% for device, info in device_data.items() %}
            <div class="card">
                <h3>
                    {{ device }}
                    <span
                        class="status"
                        style="background-color: {{ info.status_color }};"
                    >
                        {{ info.status }}
                    </span>
                </h3>

                <p>
                    AHT20 温度：
                    <span class="data">
                        {{ info.temperature }} °C
                    </span>
                </p>

                <p>
                    AHT20 湿度：
                    <span class="data">
                        {{ info.humidity }} %
                    </span>
                </p>

                <p>
                    BMP280 温度：
                    <span class="data">
                        {{ info.temperature_2 }} °C
                    </span>
                </p>

                <p>
                    BMP280 气压：
                    <span class="data">
                        {{ info.pressure }} Pa
                    </span>
                </p>

                <p class="time">
                    最后更新：{{ info.last_update }}
                </p>
            </div>
            {% endfor %}
        {% else %}
            <p>等待设备上传数据中...</p>
        {% endif %}
    </body>
    </html>
    """

    return render_template_string(
        html_template,
        device_data=get_device_snapshot()
    )


# ================= 启动程序 =================

if __name__ == "__main__":
    init_db()
    print("✅ 数据库初始化完成")
    
    cleanup_thread = threading.Thread(target=cleanup_old_data, daemon=True)
    cleanup_thread.start()
    print("✅ 数据清理线程已启动 (保留 {} 天)".format(DATA_RETENTION_DAYS))
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)

        # 在后台线程中持续接收 MQTT 消息
        client.loop_start()

        print("✅ MQTT 后台监听已启动")

    except Exception as e:
        print("❌ 无法连接到 MQTT 服务器:", e)

    # 关闭 Flask 调试模式，避免产生额外进程
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )

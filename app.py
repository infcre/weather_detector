import streamlit as st
import requests
import random
from datetime import datetime
from streamlit_autorefresh import st_autorefresh


# ============================================================
# 1. Flask 后端地址
# ============================================================

BACKEND_URL = "http://127.0.0.1:5000"


# ============================================================
# 2. 页面配置
# ============================================================

st.set_page_config(
    page_title="AI微气象感知系统",
    page_icon="🌦️",
    layout="wide"
)


# ============================================================
# 3. 每5秒自动刷新
# ============================================================

st_autorefresh(
    interval=5000,
    key="weather_refresh"
)


# ============================================================
# 4. 获取A地点真实传感器数据
# ============================================================

def get_sensor_data():

    try:

        response = requests.get(
            BACKEND_URL + "/api/data",
            timeout=3
        )

        if response.status_code != 200:

            st.error(
                "Flask接口错误：" +
                str(response.status_code)
            )

            return None

        result = response.json()

        devices = result.get("data", {})

        if len(devices) == 0:

            st.warning(
                "没有检测到传感器"
            )

            return None

        # 获取第一个ESP32设备
        device_id = list(devices.keys())[0]

        data = devices[device_id]

        return data

    except Exception as e:

        st.error(
            "连接Flask失败：" +
            str(e)
        )

        return None


# ============================================================
# 5. 获取A点数据
# ============================================================

data_a = get_sensor_data()


if data_a is None:

    st.error(
        "当前无法获取传感器数据"
    )

    st.stop()


# ============================================================
# 6. A点数据
# ============================================================

temperature_a = float(
    data_a.get("temperature", 0)
)

humidity_a = float(
    data_a.get("humidity", 0)
)

pressure_a = float(
    data_a.get("pressure", 0)
)

pressure_a_hpa = pressure_a / 100


# ============================================================
# 7. B点模拟数据
#
# 以后第二个ESP32接入以后，
# 只需要把这一部分替换成B点真实数据。
# ============================================================

temperature_b = round(
    temperature_a + random.uniform(-1.5, 1.5),
    2
)

humidity_b = round(
    humidity_a + random.uniform(-12, 12),
    2
)

humidity_b = max(
    0,
    min(100, humidity_b)
)

pressure_b_hpa = round(
    pressure_a_hpa + random.uniform(-3, 3),
    2
)


# ============================================================
# 8. A/B 两地差异
# ============================================================

temperature_diff = round(
    temperature_a - temperature_b,
    2
)

humidity_diff = round(
    humidity_a - humidity_b,
    2
)

pressure_diff = round(
    pressure_a_hpa - pressure_b_hpa,
    2
)


temperature_diff_abs = abs(
    temperature_diff
)

humidity_diff_abs = abs(
    humidity_diff
)

pressure_diff_abs = abs(
    pressure_diff
)


# ============================================================
# 9. AI降雨风险算法
# ============================================================

def calculate_rain_risk(
    temperature,
    humidity,
    pressure
):

    score = 0

    # 湿度
    if humidity >= 90:
        score += 55

    elif humidity >= 80:
        score += 40

    elif humidity >= 70:
        score += 25

    elif humidity >= 60:
        score += 10


    # 气压
    if pressure < 1000:
        score += 30

    elif pressure < 1010:
        score += 15


    # 温度 + 高湿度
    if temperature >= 28 and humidity >= 80:

        score += 15


    score = min(
        score,
        100
    )

    return score


rain_a = calculate_rain_risk(
    temperature_a,
    humidity_a,
    pressure_a_hpa
)

rain_b = calculate_rain_risk(
    temperature_b,
    humidity_b,
    pressure_b_hpa
)


# ============================================================
# 10. AI估算降雨量
# ============================================================

def estimate_rainfall(risk):

    if risk < 20:

        return "0～0.5 mm"

    elif risk < 40:

        return "0.5～2 mm"

    elif risk < 60:

        return "2～5 mm"

    elif risk < 80:

        return "5～10 mm"

    else:

        return "10～20 mm"


rainfall_a = estimate_rainfall(
    rain_a
)

rainfall_b = estimate_rainfall(
    rain_b
)


# ============================================================
# 11. AI估算降雨持续时间
# ============================================================

def estimate_duration(risk):

    if risk < 20:

        return "暂无明显降雨"

    elif risk < 40:

        return "10～20 分钟"

    elif risk < 60:

        return "20～40 分钟"

    elif risk < 80:

        return "30～60 分钟"

    else:

        return "40～90 分钟"


duration_a = estimate_duration(
    rain_a
)

duration_b = estimate_duration(
    rain_b
)


# ============================================================
# 12. 降雨趋势
# ============================================================

def rain_trend(risk):

    if risk >= 70:

        return "🌧️ 降雨增强"

    elif risk >= 40:

        return "🌦️ 可能形成降雨"

    elif risk >= 20:

        return "☁️ 降雨风险较低"

    else:

        return "☀️ 暂无明显降雨"


trend_a = rain_trend(
    rain_a
)

trend_b = rain_trend(
    rain_b
)


# ============================================================
# 13. 微气象差异指数
# ============================================================

difference_score = 0


# 湿度差异
if humidity_diff_abs >= 10:

    difference_score += 40

elif humidity_diff_abs >= 5:

    difference_score += 25

elif humidity_diff_abs >= 2:

    difference_score += 10


# 温度差异
if temperature_diff_abs >= 2:

    difference_score += 30

elif temperature_diff_abs >= 1:

    difference_score += 15


# 气压差异
if pressure_diff_abs >= 3:

    difference_score += 30

elif pressure_diff_abs >= 1:

    difference_score += 15


difference_score = min(
    difference_score,
    100
)


# ============================================================
# 14. 差异等级
# ============================================================

if difference_score >= 70:

    difference_level = (
        "🔴 显著"
    )

    difference_text = (
        "两地存在明显微气象差异"
    )

elif difference_score >= 40:

    difference_level = (
        "🟠 中等"
    )

    difference_text = (
        "两地存在一定微气象差异"
    )

else:

    difference_level = (
        "🟢 较小"
    )

    difference_text = (
        "两地当前气象条件较为接近"
    )


# ============================================================
# 15. 页面标题
# ============================================================

st.title(
    "🌦️ AI微气象感知系统"
)

st.caption(
    "实时局地天气监测与短临预测"
)


# ============================================================
# 16. 当前微气象状态
# ============================================================

st.divider()

st.header(
    "📍 当前微气象状态"
)


col_a, col_b = st.columns(2)


# ============================================================
# A点
# ============================================================

with col_a:

    st.subheader(
        "📍 A地点"
    )

    st.caption(
        "实时环境监测"
    )

    a1, a2, a3 = st.columns(3)

    a1.metric(
        "🌡 温度",
        f"{temperature_a:.2f} ℃"
    )

    a2.metric(
        "💧 湿度",
        f"{humidity_a:.2f} %"
    )

    a3.metric(
        "🌫 气压",
        f"{pressure_a_hpa:.2f} hPa"
    )


# ============================================================
# B点
# ============================================================

with col_b:

    st.subheader(
        "📍 B地点"
    )

    st.caption(
        "实时环境监测"
    )

    b1, b2, b3 = st.columns(3)

    b1.metric(
        "🌡 温度",
        f"{temperature_b:.2f} ℃"
    )

    b2.metric(
        "💧 湿度",
        f"{humidity_b:.2f} %"
    )

    b3.metric(
        "🌫 气压",
        f"{pressure_b_hpa:.2f} hPa"
    )


# ============================================================
# 17. AI短临预测
# ============================================================

st.divider()

st.header(
    "🤖 AI短临预测"
)


# A点
st.subheader(
    "📍 A地点未来30～60分钟"
)

a1, a2, a3, a4 = st.columns(4)

a1.metric(
    "🌧️ 降雨概率",
    f"{rain_a}%"
)

a2.metric(
    "💧 预计雨量",
    rainfall_a
)

a3.metric(
    "⏱️ 预计持续",
    duration_a
)

a4.metric(
    "📈 降雨趋势",
    trend_a
)


# B点
st.subheader(
    "📍 B地点未来30～60分钟"
)

b1, b2, b3, b4 = st.columns(4)

b1.metric(
    "🌧️ 降雨概率",
    f"{rain_b}%"
)

b2.metric(
    "💧 预计雨量",
    rainfall_b
)

b3.metric(
    "⏱️ 预计持续",
    duration_b
)

b4.metric(
    "📈 降雨趋势",
    trend_b
)


# ============================================================
# 18. 两地局地差异
# ============================================================

st.divider()

st.header(
    "📍 局地微气象差异分析"
)

d1, d2, d3, d4 = st.columns(4)


d1.metric(
    "🌡 温度差",
    f"{temperature_diff_abs:.2f} ℃"
)

d2.metric(
    "💧 湿度差",
    f"{humidity_diff_abs:.2f} %"
)

d3.metric(
    "🌫 气压差",
    f"{pressure_diff_abs:.2f} hPa"
)

d4.metric(
    "🎯 微气象差异指数",
    f"{difference_score}/100"
)


st.info(
    f"当前判断：{difference_level} —— {difference_text}"
)


# ============================================================
# 19. AI自动解释
# ============================================================

st.subheader(
    "🧠 AI分析"
)


if humidity_diff > 8:

    st.write(
        f"💧 A地点湿度比B地点高 "
        f"{humidity_diff_abs:.2f} 个百分点，"
        "A地点空气湿度明显更高。"
    )

elif humidity_diff < -8:

    st.write(
        f"💧 B地点湿度比A地点高 "
        f"{humidity_diff_abs:.2f} 个百分点，"
        "B地点空气湿度明显更高。"
    )

else:

    st.write(
        "💧 A、B两地点湿度差异较小。"
    )


if temperature_diff > 1:

    st.write(
        "🌡 A地点温度明显高于B地点。"
    )

elif temperature_diff < -1:

    st.write(
        "🌡 B地点温度明显高于A地点。"
    )

else:

    st.write(
        "🌡 A、B两地点温度较为接近。"
    )


if pressure_diff > 2:

    st.write(
        "🌫 A地点气压低于B地点，"
        "需要关注后续天气变化。"
    )

elif pressure_diff < -2:

    st.write(
        "🌫 B地点气压低于A地点，"
        "需要关注后续天气变化。"
    )

else:

    st.write(
        "🌫 A、B两地点气压差异较小。"
    )


# ============================================================
# 20. 局地天气预警
# ============================================================

st.divider()

st.header(
    "⚠️ 局地天气预警"
)


if rain_a >= 70:

    st.error(
        f"A地点：🌧️ 降雨风险较高，"
        f"预计雨量 {rainfall_a}，"
        f"持续 {duration_a}。"
    )

elif rain_a >= 40:

    st.warning(
        f"A地点：🌦️ 存在一定降雨风险，"
        f"预计雨量 {rainfall_a}。"
    )

else:

    st.success(
        "A地点：☀️ 当前降雨风险较低。"
    )


if rain_b >= 70:

    st.error(
        f"B地点：🌧️ 降雨风险较高，"
        f"预计雨量 {rainfall_b}，"
        f"持续 {duration_b}。"
    )

elif rain_b >= 40:

    st.warning(
        f"B地点：🌦️ 存在一定降雨风险，"
        f"预计雨量 {rainfall_b}。"
    )

else:

    st.success(
        "B地点：☀️ 当前降雨风险较低。"
    )


# ============================================================
# 21. 传统天气预报 vs 本系统
# ============================================================

st.divider()

st.header(
    "🔎 传统天气预报 vs AI微气象感知"
)


left, right = st.columns(2)


with left:

    st.subheader(
        "🌐 传统天气预报"
    )

    st.write(
        "该区域未来可能出现降雨。"
    )

    st.write(
        "空间尺度较大，"
        "难以反映相邻地点之间的局部差异。"
    )


with right:

    st.subheader(
        "🤖 本系统"
    )

    if rain_a > rain_b:

        st.write(
            f"A地点当前降雨风险高于B地点。"
        )

        st.write(
            f"A地点预计降雨概率约为 {rain_a}%，"
            f"B地点约为 {rain_b}%。"
        )

        st.write(
            "系统进一步分析两地点的温度、"
            "湿度和气压差异，识别局地微气象变化。"
        )

    else:

        st.write(
            f"B地点当前降雨风险高于A地点。"
        )

        st.write(
            f"B地点预计降雨概率约为 {rain_b}%，"
            f"A地点约为 {rain_a}%。"
        )

        st.write(
            "系统进一步分析两地点的温度、"
            "湿度和气压差异，识别局地微气象变化。"
        )


# ============================================================
# 22. 设备信息
# ============================================================

st.divider()

st.header(
    "📡 传感器信息"
)


info1, info2 = st.columns(2)


with info1:

    st.write(
        "A地点设备ID：",
        data_a.get(
            "device",
            "未知"
        )
    )

    st.write(
        "A地点更新时间：",
        data_a.get(
            "last_update",
            "未知"
        )
    )


with info2:

    st.write(
        "B地点设备ID：",
        "ESP32-B"
    )

    st.write(
        "B地点状态：",
        "在线"
    )


# ============================================================
# 23. 更新时间
# ============================================================

st.divider()

st.caption(
    "网页每5秒自动读取A、B两地数据"
)

st.caption(
    "网页刷新时间：" +
    datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
)
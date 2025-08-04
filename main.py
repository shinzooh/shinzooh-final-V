from flask import Flask, request
import requests
import json
from datetime import datetime, timezone
import os

# إعدادات تليجرام
TELEGRAM_BOT_TOKEN = '7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw'
TELEGRAM_CHAT_ID = '715830182'

# إعدادات Discord
DISCORD_WEBHOOK_URL = 'ضع Webhook Discord هنا (اختياري)'

# Rate limiting للرفض
REJECT_NOTIFY_LIMIT_SEC = 300
last_reject_notify = {'ts': datetime(1970, 1, 1, tzinfo=timezone.utc)}

# الرموز (بدون بادئات)
SYMBOL_PREFIXES = {
    'XAUUSD': '',
    'XAGUSD': '',
    'EURUSD': '',
    'GBPJPY': '',
    'EURCHF': '',
    'EURJPY': '',
    'GBPUSD': '',
    'USDJPY': '',
    'US100': '',
    'US30': '',
    'BTCUSD': '',
    'ETHUSD': ''
}

# حدود الفوليوم
VOLUME_THRESHOLDS = {
    'forex': 5000,
    'indices': 10000,
    'crypto': 2000
}

app = Flask(__name__)

# مسار الجذر للفحص الصحي
@app.route('/', methods=['GET'])
def home():
    return "Shinzooh Webhook شغالة!", 200

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"[Telegram Error] {e}")

def send_discord_message(text):
    if DISCORD_WEBHOOK_URL and DISCORD_WEBHOOK_URL.startswith('http'):
        try:
            data = {"content": text}
            response = requests.post(DISCORD_WEBHOOK_URL, json=data)
            response.raise_for_status()
        except Exception as e:
            print(f"[Discord Error] {e}")

def notify_rejection(reason, alert_data=None):
    now = datetime.now(timezone.utc)
    last_time = last_reject_notify.get('ts', datetime(1970, 1, 1, tzinfo=timezone.utc))
    if (now - last_time).total_seconds() > REJECT_NOTIFY_LIMIT_SEC:
        msg = f"⚠️ *Alert مرفوض*: {reason}"
        if alert_data and alert_data.get('interval') and alert_data.get('time'):
            msg += f"\nالفريم: `{alert_data.get('interval')}`\nالوقت: `{alert_data.get('time')}`"
        send_telegram_message(msg)
        send_discord_message(msg)
        last_reject_notify['ts'] = now

# دالة لحساب RSI بناءً على السعر الحالي والسابق
def calculate_rsi(current_price, previous_price=None):
    if previous_price is None:
        return "لا يوجد بيانات كافية لـ RSI"
    price_change = current_price - previous_price
    if price_change > 0:
        return "RSI: صعودي (قد يكون overbought)"
    elif price_change < 0:
        return "RSI: هابط (قد يكون oversold)"
    return "RSI: محايد"

# دالة لحساب MA (متوسط متحرك بسيط)
def calculate_ma(prices):
    if not prices or len(prices) == 0:
        return None
    return sum(prices) / len(prices)

# دالة لحساب MACD بفارق بين متوسطين متحركين
def calculate_macd(short_ma, long_ma):
    if short_ma is None or long_ma is None:
        return "لا يوجد بيانات كافية لـ MACD"
    macd_line = short_ma - long_ma
    if macd_line > 0:
        return "MACD: صعودي (إشارة شراء محتملة)"
    elif macd_line < 0:
        return "MACD: هابط (إشارة بيع محتملة)"
    return "MACD: محايد"

# دالة لتحليل ICT-SMC مبسط بناءً على الشمعة الحالية والسابقة
def analyze_ict_smc(high, low, close, prev_high=None, prev_low=None, prev_close=None):
    analysis = ""
    # Order Block صعودي أو هابط
    if prev_close and prev_high and prev_low:
        if close > prev_close and high > prev_high:
            analysis += f"📈 Order Block صعودي (دعم عند {low})\n"
        elif close < prev_close and low < prev_low:
            analysis += f"📉 Order Block هابط (مقاومة عند {high})\n"
        # Fair Value Gap مبسطة
        if (high - low) > (prev_high - prev_low) * 1.5:
            analysis += "⚠️ Fair Value Gap (فجوة سعرية)\n"
    return analysis.strip() if analysis else "لا يوجد إشارة ICT-SMC واضحة"

@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    data = request.json
    print(f"[DEBUG] Received Alert: {data}")
    price = data.get('close')
    open_ = data.get('open')
    timeframe = data.get('interval')
    timestamp = data.get('time')
    chart_url = data.get('chart_image_url') or data.get('screenshot_url')
    high = data.get('high')
    low = data.get('low')
    volume = data.get('volume')
    ticker = data.get('ticker')

    # حفظ البيانات السابقة في خاصية داخل التطبيق
    if not hasattr(app, 'prev_candle'):
        app.prev_candle = {'high': None, 'low': None, 'close': None}
    prev_high = app.prev_candle['high']
    prev_low = app.prev_candle['low']
    prev_close = app.prev_candle['close']
    # تحديث البيانات السابقة بالشمعة الحالية
    app.prev_candle = {'high': float(high) if high else None,
                       'low': float(low) if low else None,
                       'close': float(price) if price else None}

    # بناء رابط TradingView (بدون بادئة)
    tv_link = ""
    if ticker and timeframe:
        try:
            tf_num = ''.join([c for c in timeframe if c.isdigit()])
            tf_unit = ''.join([c for c in timeframe if not c.isdigit()])
            tf_final = tf_num + (tf_unit if tf_unit else "m")
            tv_link = f"https://www.tradingview.com/chart/?symbol={ticker}&interval={tf_final}"
        except Exception as e:
            print(f"[DEBUG] TV Link Error: {e}")
            tv_link = ""

    # التحقق من البيانات الأساسية
    if not price or not timeframe or not timestamp:
        notify_rejection("بيانات ناقصة من Alert", data)
        return json.dumps({"status": "error", "message": "بيانات ناقصة من Alert"}), 400

    # فلتر زمني ديناميكي
    if timeframe in ["1", "1m", "5", "5m"]:
        interval_sec = 30
    elif timeframe in ["15", "15m"]:
        interval_sec = 90
    else:
        interval_sec = 150

    now = datetime.now(timezone.utc)
    try:
        alert_time = (
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if isinstance(timestamp, str) and 'T' in timestamp
            else datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        )
    except Exception as e:
        print(f"[DEBUG] Timestamp Error: {e}")
        notify_rejection("تنسيق الوقت غير مفهوم", data)
        return json.dumps({"status": "error", "message": "تنسيق الوقت غير مفهوم"}), 400

    diff_sec = abs((now - alert_time).total_seconds())
    if diff_sec > interval_sec:
        notify_rejection(f"Alert قديم جداً ({int(diff_sec)} ثانية)", data)
        return json.dumps({"status": "error", "message": f"Alert قديم ({int(diff_sec)} ثواني)"}), 400

    # تحليلات إضافية
    current_price = float(price)
    rsi_analysis = calculate_rsi(current_price, prev_close)
    # MA نحسب متوسط بسيط للشمعة الحالية والسابقة إذا متوفر
    ma_value = None
    if prev_close is not None:
        ma_value = calculate_ma([current_price, prev_close])
    else:
        ma_value = None
    if ma_value is None:
        ma_analysis = "لا يوجد بيانات كافية لـ MA"
    else:
        ma_analysis = ma_value
    # MACD يعتمد على وجود MA، نأخذ MA طويل (مثلا 0.9 من القصير) كتجربة
    if isinstance(ma_analysis, (int, float)):
        macd_analysis = calculate_macd(ma_analysis, ma_analysis * 0.9)
    else:
        macd_analysis = "لا يوجد بيانات كافية لـ MACD"
    # تحليل ICT-SMC مبسط
    ict_analysis = analyze_ict_smc(float(high) if high else None,
                                   float(low) if low else None,
                                   current_price,
                                   prev_high,
                                   prev_low,
                                   prev_close)

    # تحليل الشمعة الكلاسيكية
    candle_analysis = ""
    if open_ and price:
        try:
            open_f = float(open_)
            close_f = current_price
            if close_f > open_f:
                candle_analysis = "🔵 شمعة صاعدة (Bullish)"
            elif close_f < open_f:
                candle_analysis = "🔴 شمعة هابطة (Bearish)"
            else:
                candle_analysis = "⚪️ شمعة محايدة (Doji)"
        except Exception as e:
            print(f"[DEBUG] Candle Analysis Error: {e}")
            candle_analysis = "❓ لم يتم تحديد اتجاه الشمعة"
    else:
        candle_analysis = "⚠️ لا توجد بيانات Open للتحليل"

    # تحليل قرب السعر من High/Low
    proximity_analysis = ""
    try:
        if high and low and price:
            high_f = float(high)
            low_f = float(low)
            close_f = current_price
            high_diff = abs(high_f - close_f) / (high_f - low_f + 1e-6)
            low_diff = abs(close_f - low_f) / (high_f - low_f + 1e-6)
            if high_diff <= 0.005:
                proximity_analysis = "📈 السعر قريب جدًا من قمة الشمعة"
            elif low_diff <= 0.005:
                proximity_analysis = "📉 السعر قريب جدًا من قاع الشمعة"
    except Exception as e:
        print(f"[DEBUG] Proximity Analysis Error: {e}")
        proximity_analysis = ""

    # تحليل الفوليوم
    liquidity_analysis = ""
    try:
        if volume and ticker:
            volume_f = float(volume)
            asset_type = (
                'forex' if ticker in ['XAUUSD','XAGUSD','EURUSD','GBPJPY','EURCHF','EURJPY','GBPUSD','USDJPY']
                else 'indices' if ticker in ['US100','US30']
                else 'crypto' if ticker in ['BTCUSD','ETHUSD']
                else 'forex'
            )
            volume_threshold = VOLUME_THRESHOLDS.get(asset_type, 5000)
            if volume_f > volume_threshold:
                liquidity_analysis = f"🚨 دخول سيولة قوية! ({volume_f:.0f})"
    except Exception as e:
        print(f"[DEBUG] Liquidity Analysis Error: {e}")
        liquidity_analysis = ""

    # نص الرسالة
    analysis = f"""*🚀 TradingView Live Alert*
الرمز: `{ticker if ticker else 'غير محدد'}`
الفريم: `{timeframe}`
السعر: `{price}`
الوقت: `{timestamp}`
{candle_analysis}
{proximity_analysis if proximity_analysis else ''}
{liquidity_analysis if liquidity_analysis else ''}
{ict_analysis}
{rsi_analysis}
MA: {ma_analysis if isinstance(ma_analysis, (int, float)) else ma_analysis}
{macd_analysis}
{'[صورة الشارت](%s)' % chart_url if chart_url else '❌ لا يوجد صورة'}
{('[شارت TradingView](%s)' % tv_link) if tv_link else ''}""".strip()

    send_telegram_message(analysis)
    send_discord_message(analysis)
    return json.dumps({"status": "success"}), 200

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.DEBUG)
    port = int(os.environ.get('PORT', 5000))
    print("🚀 Shinzooh TradingView Webhook is running! Check /webhook endpoint.")
    app.run(host='0.0.0.0', port=port)

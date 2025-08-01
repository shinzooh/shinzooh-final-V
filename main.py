from flask import Flask, request
import requests
import json
from datetime import datetime, timezone
import os

# ============ إعدادات تليجرام ============
TELEGRAM_BOT_TOKEN = '7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw'
TELEGRAM_CHAT_ID = '715830182'

# ============ إعدادات Discord ============
DISCORD_WEBHOOK_URL = 'ضع Webhook Discord هنا (اختياري)'

# ============ Rate Limiting للرفض ============
REJECT_NOTIFY_LIMIT_SEC = 300  # تنبيه رفض كل 5 دقائق
last_reject_notify = {'ts': datetime(1970, 1, 1, tzinfo=timezone.utc)}

# ============ قائمة الرموز والبادئات ============
SYMBOL_PREFIXES = {
    'XAUUSD': 'OANDA:',  # فوركس
    'XAGUSD': 'OANDA:',
    'EURUSD': 'OANDA:',
    'GBPJPY': 'OANDA:',
    'EURCHF': 'OANDA:',
    'EURJPY': 'OANDA:',
    'GBPUSD': 'OANDA:',
    'USDJPY': 'OANDA:',
    'US100': 'CASH:',  # مؤشرات
    'US30': 'CASH:',
    'BTCUSD': 'BINANCE:',  # كريبتو
    'ETHUSD': 'BINANCE:'
}

# ============ حدود الفوليوم للسيولة ============
VOLUME_THRESHOLDS = {
    'forex': 5000,  # للفوركس (XAUUSD, EURUSD, ...)
    'indices': 10000,  # للمؤشرات (US100, US30)
    'crypto': 2000  # للكريبتو (BTCUSD, ETHUSD)
}

app = Flask(__name__)

def send_telegram_message(text):
    """إرسال رسالة عبر بوت تيليجرام."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"[Telegram Error] {e}")

def send_discord_message(text):
    """إرسال رسالة عبر Discord Webhook."""
    if DISCORD_WEBHOOK_URL:
        try:
            data = {"content": text}
            response = requests.post(DISCORD_WEBHOOK_URL, json=data)
            response.raise_for_status()
        except Exception as e:
            print(f"[Discord Error] {e}")

def notify_rejection(reason, alert_data=None):
    """إشعار برفض التنبيه مع التحكم بالحد الزمني."""
    now = datetime.now(timezone.utc)
    last_time = last_reject_notify.get('ts', datetime(1970, 1, 1, tzinfo=timezone.utc))
    if (now - last_time).total_seconds() > REJECT_NOTIFY_LIMIT_SEC:
        msg = f"⚠️ *Alert مرفوض*: {reason}"
        if alert_data and alert_data.get('interval') and alert_data.get('time'):
            msg += f"\nالفريم: `{alert_data.get('interval')}`\nالوقت: `{alert_data.get('time')}`"
        send_telegram_message(msg)
        send_discord_message(msg)
        last_reject_notify['ts'] = now

@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    """نقطة استلام تنبيهات TradingView."""
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

    # ====== رابط TradingView إذا متوفر ======
    tv_link = ""
    if ticker and timeframe:
        try:
            tf_num = ''.join([c for c in timeframe if c.isdigit()])
            tf_unit = ''.join([c for c in timeframe if not c.isdigit()])
            prefix = SYMBOL_PREFIXES.get(ticker, 'OANDA:')  # افتراضي OANDA لو الرمز مو في القايمة
            symbol = ticker if ':' in ticker else f"{prefix}{ticker}"
            tf_final = tf_num + (tf_unit if tf_unit else "m")
            tv_link = f"https://www.tradingview.com/chart/?symbol={symbol}&interval={tf_final}"
        except Exception as e:
            print(f"[DEBUG] TV Link Error: {e}")
            tv_link = ""

    # ========== فلترة صارمة ==========
    if not price or not timeframe or not timestamp:
        notify_rejection("بيانات ناقصة من Alert", data)
        return json.dumps({"status": "error", "message": "بيانات ناقصة من Alert"}), 400

    # ========== فلتر زمني ديناميكي ==========
    if timeframe in ["1", "1m", "5", "5m"]:
        interval_sec = 30
    elif timeframe in ["15", "15m"]:
        interval_sec = 90
    else:
        interval_sec = 150
    now = datetime.now(timezone.utc)
    try:
        alert_time = (datetime.fromisoformat(timestamp.replace('Z', '+00:00')) if 'T' in timestamp
                     else datetime.utcfromtimestamp(int(timestamp)).replace(tzinfo=timezone.utc))
    except Exception as e:
        print(f"[DEBUG] Timestamp Error: {e}")
        notify_rejection("تنسيق الوقت غير مفهوم", data)
        return json.dumps({"status": "error", "message": "تنسيق الوقت غير مفهوم"}), 400
    diff_sec = abs((now - alert_time).total_seconds())
    if diff_sec > interval_sec:
        notify_rejection(f"Alert قديم جداً ({int(diff_sec)} ثانية)", data)
        return json.dumps({"status": "error", "message": f"Alert قديم ({int(diff_sec)} ثواني)"}), 400

    # ========== تحليل الشمعة ==========
    candle_analysis = ""
    if open_ and price:
        try:
            open_f = float(open_)
            close_f = float(price)
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

    # ========== تحليل High/Low ==========
    proximity_analysis = ""
    try:
        if high and low and price:
            high_f = float(high)
            low_f = float(low)
            close_f = float(price)
            high_diff = abs(high_f - close_f) / (high_f - low_f + 1e-6)
            low_diff = abs(close_f - low_f) / (high_f - low_f + 1e-6)
            if high_diff <= 0.005:
                proximity_analysis = "📈 السعر قريب جدًا من قمة الشمعة"
            elif low_diff <= 0.005:
                proximity_analysis = "📉 السعر قريب جدًا من قاع الشمعة"
    except Exception as e:
        print(f"[DEBUG] Proximity Analysis Error: {e}")
        proximity_analysis = ""

    # ========== تحليل السيولة (الفوليوم) ==========
    liquidity_analysis = ""
    try:
        if volume and ticker:
            volume_f = float(volume)
            # تحديد نوع الأصل
            asset_type = ('forex' if ticker in ['XAUUSD', 'XAGUSD', 'EURUSD', 'GBPJPY', 'EURCHF', 'EURJPY', 'GBPUSD', 'USDJPY']
                         else 'indices' if ticker in ['US100', 'US30']
                         else 'crypto' if ticker in ['BTCUSD', 'ETHUSD']
                         else 'forex')  # افتراضي
            volume_threshold = VOLUME_THRESHOLDS.get(asset_type, 5000)
            if volume_f > volume_threshold:
                liquidity_analysis = f"🚨 دخول سيولة قوية! ({volume_f:.0f})"
    except Exception as e:
        print(f"[DEBUG] Liquidity Analysis Error: {e}")
        liquidity_analysis = ""

    # ========== نص الرسالة ==========
    analysis = f"""*🚀 TradingView Live Alert*
الرمز: `{ticker if ticker else 'غير محدد'}`
الفريم: `{timeframe}`
السعر: `{price}`
الوقت: `{timestamp}`
{candle_analysis}
{proximity_analysis if proximity_analysis else ""}
{liquidity_analysis if liquidity_analysis else ""}
{'[صورة الشارت](%s)' % chart_url if chart_url else '❌ لا يوجد صورة'}
{f'[شارت TradingView]({tv_link})' if tv_link else ''}""".strip()

    send_telegram_message(analysis)
    send_discord_message(analysis)
    return json.dumps({"status": "success"}), 200

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.DEBUG)
    port = int(os.environ.get('PORT', 5000))  # توافق مع Render
    print("🚀 Shinzooh TradingView Webhook is running! Check /webhook endpoint.")
    app.run(host='0.0.0.0', port=port)

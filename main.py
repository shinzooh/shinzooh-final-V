from flask import Flask, request
import requests
import json
from datetime import datetime, timezone
import os
import logging

# إعدادات تليجرام
TELEGRAM_BOT_TOKEN = '7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw'
TELEGRAM_CHAT_ID = '715830182'

# إعدادات Discord
DISCORD_WEBHOOK_URL = ''  # غيّريها لو تبين

# Rate limiting
REJECT_NOTIFY_LIMIT_SEC = 300
last_reject_notify = {'ts': datetime(1970, 1, 1, tzinfo=timezone.utc)}

# حدود السيولة
VOLUME_THRESHOLDS = {
    'forex': 5000,
    'indices': 10000,
    'crypto': 2000
}

app = Flask(__name__)

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Shinzooh Webhook شغالة!", 200

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        logging.exception("[Telegram Error] %s", e)

def send_discord_message(text):
    if DISCORD_WEBHOOK_URL and DISCORD_WEBHOOK_URL.startswith('http'):
        try:
            data = {"content": text}
            response = requests.post(DISCORD_WEBHOOK_URL, json=data)
            response.raise_for_status()
        except Exception as e:
            logging.exception("[Discord Error] %s", e)

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

def parse_timestamp(ts):
    if ts is None:
        raise ValueError("Timestamp is None")
    if isinstance(ts, str) and ('T' in ts or '.' in ts):
        return datetime.fromisoformat(ts.replace('Z', '+00:00'))
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except ValueError:
        raise ValueError(f"Timestamp format not supported: {ts}")

def parse_plain_kv(text):
    """ يفك النص المختصر مثل: SYMB=XAUUSD,TF=5,C=3378.88,H=3379.805,L=3378.46,V=1333 """
    d = {}
    try:
        for part in text.strip().split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                d[k.strip().lower()] = v.strip()
    except Exception:
        pass
    return d

# دالة لحساب RSI مبسط
def calculate_rsi(current_price, previous_price=None):
    if previous_price is None:
        return "لا يوجد بيانات كافية لـ RSI"
    price_change = current_price - previous_price
    if price_change > 0:
        return "RSI: صعودي (قد يكون overbought)"
    elif price_change < 0:
        return "RSI: هابط (قد يكون oversold)"
    return "RSI: محايد"

# دالة لحساب MA
def calculate_ma(prices):
    if not prices or len(prices) == 0:
        return None
    return sum(prices) / len(prices)

# دالة لحساب MACD مبسط
def calculate_macd(short_ma, long_ma):
    if short_ma is None or long_ma is None:
        return "لا يوجد بيانات كافية لـ MACD"
    macd_line = short_ma - long_ma
    if macd_line > 0:
        return "MACD: صعودي (إشارة شراء محتملة)"
    elif macd_line < 0:
        return "MACD: هابط (إشارة بيع محتملة)"
    return "MACD: محايد"

# دالة لتحليل ICT-SMC مبسط (أساسي)
def analyze_ict_smc(high, low, close, prev_high=None, prev_low=None, prev_close=None):
    analysis = ""
    # Order Block
    if prev_close and prev_high and prev_low:
        if close > prev_close and high > prev_high:
            analysis += f"📈 Order Block صعودي (دعم عند {low})\n"
        elif close < prev_close and low < prev_low:
            analysis += f"📉 Order Block هابط (مقاومة عند {high})\n"
    # Fair Value Gap
    if prev_high and prev_low and (high - low) > (prev_high - prev_low) * 1.5:
        analysis += "⚠️ Fair Value Gap (فجوة سعرية - فرصة رجوع)\n"
    return analysis.strip() if analysis else "لا يوجد إشارة ICT-SMC واضحة"

@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    try:
        # استقبال البيانات بأي صيغة
        raw_data = request.data.decode('utf-8', errors='ignore').strip()
        logging.info(f"Raw data received: {raw_data}")
        try:
            data = json.loads(raw_data) if raw_data else {}
        except Exception:
            data = parse_plain_kv(raw_data)

        # حفظ البيانات السابقة للتحليل
        if not hasattr(app, 'prev_candle'):
            app.prev_candle = {'high': None, 'low': None, 'close': None}
        prev_high = app.prev_candle['high']
        prev_low = app.prev_candle['low']
        prev_close = app.prev_candle['close']
        app.prev_candle = {'high': float(high) if high else None, 'low': float(low) if low else None, 'close': float(price) if price else None}

        # قبول عدة مسميات للمتغيرات
        price = data.get('close') or data.get('c')
        open_ = data.get('open') or data.get('o')
        timeframe = data.get('interval') or data.get('tf')
        timestamp = data.get('time') or data.get('t')
        chart_url = data.get('chart_image_url') or data.get('screenshot_url') or data.get('img') or None
        high = data.get('high') or data.get('h')
        low = data.get('low') or data.get('l')
        volume = data.get('volume') or data.get('v')
        ticker = data.get('ticker') or data.get('symb') or data.get('symbol')

        if not price or not timeframe or not timestamp:
            notify_rejection("بيانات ناقصة من Alert", data)
            return json.dumps({"status": "error", "message": "بيانات ناقصة من Alert"}), 400

        # فلتر زمني للفريمات المطلوبة
        if timeframe in ["5", "5m"]:
            interval_sec = 300
        elif timeframe in ["15", "15m"]:
            interval_sec = 900
        elif timeframe in ["1h"]:
            interval_sec = 3600
        elif timeframe in ["4h"]:
            interval_sec = 14400
        elif timeframe in ["1d"]:
            interval_sec = 86400
        else:
            interval_sec = 150
        now = datetime.now(timezone.utc)
        try:
            alert_time = parse_timestamp(timestamp)
        except Exception as e:
            logging.exception("Timestamp Error: %s", e)
            notify_rejection("تنسيق الوقت غير مفهوم", data)
            return json.dumps({"status": "error", "message": "تنسيق الوقت غير مفهوم"}), 400
        diff_sec = abs((now - alert_time).total_seconds())
        if diff_sec > interval_sec:
            notify_rejection(f"Alert قديم جداً ({int(diff_sec)} ثانية)", data)
            return json.dumps({"status": "error", "message": f"Alert قديم ({int(diff_sec)} ثواني)"}), 400

        # تحليل ICT-SMC
        ict_analysis = analyze_ict_smc(float(high) if high else None, float(low) if low else None, float(price) if price else None, prev_high, prev_low, prev_close)

        # دخول السيولة
        liquidity_analysis = ""
        try:
            if volume and ticker:
                volume_f = float(volume)
                asset_type = ('forex' if ticker in ['XAUUSD', 'XAGUSD', 'EURUSD', 'GBPJPY', 'EURCHF', 'EURJPY', 'GBPUSD', 'USDJPY']
                             else 'indices' if ticker in ['US100', 'US30']
                             else 'crypto' if ticker in ['BTCUSD', 'ETHUSD']
                             else 'forex')
                volume_threshold = VOLUME_THRESHOLDS.get(asset_type, 5000)
                if volume_f > volume_threshold:
                    liquidity_analysis = f"🚨 دخول سيولة قوية! ({volume_f:.0f})"
        except Exception:
            pass

        # RSI
        rsi_analysis = calculate_rsi(float(price) if price else None, prev_close)

        # MA
        ma_value = calculate_ma([float(price) if price else 0, prev_close if prev_close else 0]) if prev_close else None
        ma_analysis = ma_value if ma_value is not None else "لا يوجد بيانات كافية لـ MA"

        # MACD
        macd_analysis = calculate_macd(ma_value, ma_value * 0.9 if ma_value else None) if ma_value is not None else "لا يوجد بيانات كافية لـ MACD"

        # تحليل الشمعة
        try:
            candle_analysis = ("🔵 شمعة صاعدة (Bullish)" if float(price) > float(open_) else
                              "🔴 شمعة هابطة (Bearish)" if float(price) < float(open_) else
                              "⚪️ شمعة محايدة (Doji)")
        except Exception:
            candle_analysis = "❓ لم يتم تحديد اتجاه الشمعة"

        # تحليل قرب السعر من High/Low
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
        except Exception:
            pass

        # بناء رابط TradingView
        tv_link = ""
        if ticker and timeframe:
            try:
                tf_num = ''.join([c for c in str(timeframe) if c.isdigit()])
                tf_unit = ''.join([c for c in str(timeframe) if not c.isdigit()])
                tf_final = tf_num + (tf_unit if tf_unit else "m")
                tv_link = f"https://www.tradingview.com/chart/?symbol={ticker}&interval={tf_final}"
            except Exception:
                pass

        # نص الرسالة
        analysis = f"""*🚀 TradingView Live Alert*
الرمز: `{ticker}`
الفريم: `{timeframe}`
السعر: `{price}`
الوقت: `{timestamp}`
ICT-SMC: {ict_analysis}
دخول السيولة: {liquidity_analysis if liquidity_analysis else 'لا يوجد سيولة قوية'}
RSI: {rsi_analysis}
MA: {ma_analysis if isinstance(ma_analysis, (int, float)) else ma_analysis}
MACD: {macd_analysis}
{candle_analysis}
{proximity_analysis if proximity_analysis else ''}
{'[صورة الشارت](%s)' % chart_url if chart_url else '❌ لا يوجد صورة'} [تأكد من تفعيل "Include screenshot"]
{('[شارت TradingView](%s)' % tv_link) if tv_link else ''}""".strip()

        send_telegram_message(analysis)
        send_discord_message(analysis)
        return json.dumps({"status": "success"}), 200
    except Exception as e:
        logging.exception("Unhandled exception in webhook: %s", e)
        notify_rejection("خطأ داخلي في الخادم", locals().get('data', None))
        return json.dumps({"status": "error", "message": "خطأ داخلي"}), 500

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    port = int(os.environ.get('PORT', 5000))
    print("🚀 Shinzooh TradingView Webhook is running! Check /webhook endpoint.")
    app.run(host='0.0.0.0', port=port)

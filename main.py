from flask import Flask, request
import requests
import json
import sqlite3
from datetime import datetime, timezone
import os
import logging

TELEGRAM_BOT_TOKEN = '7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw'
TELEGRAM_CHAT_ID = '715830182'
DISCORD_WEBHOOK_URL = ''  # غيّريها لو تبين

REJECT_NOTIFY_LIMIT_SEC = 300
last_reject_notify = {'ts': datetime(1970, 1, 1, tzinfo=timezone.utc)}

VOLUME_THRESHOLDS = {
    'forex': 5000,
    'indices': 10000,
    'crypto': 2000
}

DB_FILE = "shinzooh_alerts.db"

app = Flask(__name__)

# === DB FUNCTIONS ===
def db_init():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT,
        timeframe TEXT,
        price REAL,
        high REAL,
        low REAL,
        open REAL,
        volume REAL,
        alert_time TEXT,
        received_at TEXT,
        chart_url TEXT,
        raw TEXT
    )''')
    con.commit()
    con.close()

def db_insert(alert):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute('''INSERT INTO alerts 
        (ticker, timeframe, price, high, low, open, volume, alert_time, received_at, chart_url, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            alert.get('ticker'),
            alert.get('timeframe'),
            alert.get('price'),
            alert.get('high'),
            alert.get('low'),
            alert.get('open'),
            alert.get('volume'),
            alert.get('timestamp'),
            alert.get('received_at'),
            alert.get('chart_url'),
            alert.get('raw'),
        )
    )
    con.commit()
    con.close()

@app.before_first_request
def setup_db():
    db_init()

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
    d = {}
    try:
        for part in text.strip().split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                d[k.strip().lower()] = v.strip()
    except Exception:
        pass
    return d

@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    try:
        raw_data = request.data.decode('utf-8', errors='ignore').strip()
        try:
            data = json.loads(raw_data) if raw_data else {}
        except Exception:
            data = parse_plain_kv(raw_data)

        # يدعم جميع الأسماء الشائعة للنقاط المطلوبة
        price      = data.get('close')   or data.get('c')
        open_      = data.get('open')    or data.get('o')
        timeframe  = data.get('interval') or data.get('tf')
        timestamp  = data.get('time')    or data.get('t')
        chart_url  = data.get('chart_image_url') or data.get('screenshot_url') or data.get('img') or None
        high       = data.get('high')    or data.get('h')
        low        = data.get('low')     or data.get('l')
        volume     = data.get('volume')  or data.get('v')
        ticker     = data.get('ticker')  or data.get('symb') or data.get('symbol')

        # === تسجيل الإشارة للقاعدة
        alert_obj = {
            "ticker": ticker,
            "timeframe": timeframe,
            "price": float(price) if price else None,
            "high": float(high) if high else None,
            "low": float(low) if low else None,
            "open": float(open_) if open_ else None,
            "volume": float(volume) if volume else None,
            "timestamp": timestamp,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "chart_url": chart_url,
            "raw": raw_data[:5000]  # مسجّل أول 5000 حرف فقط (أمان)
        }
        db_insert(alert_obj)

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

        try:
            candle_analysis = ("🔵 شمعة صاعدة (Bullish)" if float(price) > float(open_) else
                              "🔴 شمعة هابطة (Bearish)" if float(price) < float(open_) else
                              "⚪️ شمعة محايدة (Doji)")
        except Exception:
            candle_analysis = "❓ لم يتم تحديد اتجاه الشمعة"

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

        tv_link = ""
        if ticker and timeframe:
            try:
                tf_num = ''.join([c for c in str(timeframe) if c.isdigit()])
                tf_unit = ''.join([c for c in str(timeframe) if not c.isdigit()])
                tf_final = tf_num + (tf_unit if tf_unit else "m")
                tv_link = f"https://www.tradingview.com/chart/?symbol={ticker}&interval={tf_final}"
            except Exception:
                pass

        analysis = f"""*🚀 TradingView Live Alert*
الرمز: `{ticker}`
الفريم: `{timeframe}`
السعر: `{price}`
الوقت: `{timestamp}`
{candle_analysis}
{proximity_analysis if proximity_analysis else ''}
{liquidity_analysis if liquidity_analysis else ''}
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
    db_init()
    port = int(os.environ.get('PORT', 5000))
    print("🚀 Shinzooh Webhook + SQLite Logger is running! Check /webhook endpoint.")
    app.run(host='0.0.0.0', port=port)

import os
import json
import time
import html
import hashlib
import requests
from threading import Thread
from datetime import datetime
from zoneinfo import ZoneInfo  # بديل pytz بدون حزمة خارجية

from flask import Flask, request, jsonify
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, ReadTimeout, Timeout
from requests.packages.urllib3.util.retry import Retry

# =========================
#        ENV & CONFIG
# =========================
XAI_API_KEY = os.getenv("XAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # حطها بالهيدر X-Webhook-Token في TradingView

KW_TZ = ZoneInfo("Asia/Kuwait")
CRYPTO_SYMBOLS = {
    "BTCUSD","ETHUSD","XRPUSD","LINKUSD","SOLUSD","MATICUSD",
    "DOGEUSD","HBARUSD","LTCUSD","COMPUSD","THEUSD"
}

# =========================
#      HTTP SESSION
# =========================
session = requests.Session()
retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST","GET"],
    raise_on_status=False
)
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retry)
session.mount('https://', adapter)
DEFAULT_TIMEOUT = (5, 30)  # connect, read

# =========================
#      FLASK + STATE
# =========================
app = Flask(__name__)
last_payloads = {}          # منع التكرار لكل Symbol
last_telegram_send_ts = 0.0 # ريت ليمت بسيط لتليجرام

# =========================
#        HELPERS
# =========================
def sanitize_html(msg: str) -> str:
    # لأننا نستخدم parse_mode=HTML
    return html.escape(msg or "", quote=False)

def tg_rate_limit():
    global last_telegram_send_ts
    now = time.time()
    delta = now - last_telegram_send_ts
    if delta < 0.7:
        time.sleep(0.7 - delta)
    last_telegram_send_ts = time.time()

def send_to_telegram(message: str):
    tg_rate_limit()
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': sanitize_html(message)[:4096],
        'parse_mode': 'HTML'
    }
    try:
        r = session.post(url, data=data, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"Telegram Text Error: {e}")
        return False

def check_secret(req) -> bool:
    if not WEBHOOK_SECRET:
        return True  # لو مو مفعل الحين
    token = req.headers.get("X-Webhook-Token", "")
    return token == WEBHOOK_SECRET

def is_crypto(symbol: str) -> bool:
    return symbol.upper() in CRYPTO_SYMBOLS

def is_weekend_for(symbol: str) -> bool:
    # السبت/الأحد بتوقيت الكويت، مع استثناء الكريبتو
    if is_crypto(symbol):
        return False
    wd = datetime.now(KW_TZ).weekday()  # 0=اثنين ... 5=سبت, 6=أحد
    return wd in (5, 6)

def is_fresh(payload: dict, max_age_sec: int = 180) -> bool:
    # فحص حداثة التنبيه من TradingView
    for k in ("timestamp", "time", "ts", "event_time"):
        if k in payload and str(payload[k]).strip():
            s = str(payload[k])
            if len(s) > 10:
                s = s[:10]  # لو ملي ثانية
            try:
                ts = int(s)
                age = time.time() - ts
                return (age >= 0) and (age <= max_age_sec)
            except:
                pass
    return True  # لو ما فيه وقت، نمشيها

# =========================
#     xAI ANALYSIS ONLY
# =========================
def get_xai_analysis(symbol: str, frame: str, data_str: str):
    start = time.time()
    prompt = (
        f"Analyze {symbol} on {frame} with ICT & SMC "
        "(liquidity, BOS, CHoCH, FVG, OB, Premium/Discount, candles with levels) with 95%+ accuracy. "
        "Start with a sentence like 'Current candle on {symbol} {frame} shows close at C, high at H, low at L, "
        "indicating a bullish/bearish candle with close above/below the midpoint.' "
        "Then write each SMC and Classic Indicator point as a clear bullet point with exact values from input, "
        "one per line, with a blank line after each bullet for spacing. No section headers, no markdown, no table. "
        "---"
        "At the end, ALWAYS output these EXACT 5 lines, in this order (no skipping, no change, no translation, no table):\n"
        "Type: Buy/Sell\nEntry: <value>\nTake Profit: <value>\nStop Loss: <value>\nReason: <one line only>\n"
        "If you cannot generate a full trade recommendation, write:\n"
        "Type: None\nEntry: -\nTake Profit: -\nStop Loss: -\nReason: No clear signal."
        f"\nData: {data_str}"
    )
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "grok-4",  # ثابت وآمن
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1200
    }
    try:
        r = session.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        print(f"xAI Time: {time.time() - start:.3f}s")
        return content
    except (ConnectionError, ReadTimeout, Timeout) as e:
        print(f"xAI Net Error: {e}  Time: {time.time() - start:.3f}s")
        return "⚠️ xAI Error: network"
    except Exception as e:
        print(f"xAI Error: {e}  Time: {time.time() - start:.3f}s")
        return "⚠️ xAI Error: unknown"

def format_outputs(xai_text: str):
    # نفصل التحليل عن الخمس سطور الأخيرة
    if not xai_text or xai_text.startswith("⚠️"):
        return None, "<b>🚦 التوصية التجارية (خطأ)</b>\nمافي توصية بسبب مشكلة في الاتصال أو الاستجابة."

    # نقسم على الـ '---' حسب البرومبت
    parts = xai_text.split('---', 1)
    analysis_block = parts[0].strip()
    tail = parts[1] if len(parts) > 1 else ""

    # ابحث عن الخمس سطور المطلوبة
    type_, entry, tp, sl, reason = "", "", "", "", ""
    for line in (tail or xai_text).splitlines():
        L = line.strip()
        low = L.lower()
        if low.startswith("type:"):
            type_ = L.split(':', 1)[-1].strip()
        elif low.startswith("entry:"):
            entry = L.split(':', 1)[-1].strip()
        elif low.startswith("take profit:"):
            tp = L.split(':', 1)[-1].strip()
        elif low.startswith("stop loss:"):
            sl = L.split(':', 1)[-1].strip()
        elif low.startswith("reason:"):
            reason = L.split(':', 1)[-1].strip()

    # صياغة التوصية
    if type_.lower() in ("buy", "sell"):
        rec_fmt = (
            f"<b>🚦 التوصية التجارية</b>\n"
            f"صفقة: <b>{'بيع' if type_.lower() == 'sell' else 'شراء'}</b>\n"
            f"نقاط الدخول: <b>{entry or '-'}</b>\n"
            f"نقاط جني الأرباح: <b>{tp or '-'}</b>\n"
            f"الستوب لوز: <b>{sl or '-'}</b>\n"
            f"السبب: {reason or '-'}"
        )
    else:
        rec_fmt = (
            "<b>🚦 التوصية التجارية (غير موجودة)</b>\n"
            "مافي توصية واضحة من xAI!\n"
            "يرجى مراجعة التحليل فوق أو تحقق من الإعدادات."
        )

    return analysis_block, rec_fmt

# =========================
#         ROUTES
# =========================
@app.get("/")
def root():
    return "OK", 200

@app.get("/healthz")
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    start = time.time()
    body = request.data.decode('utf-8', 'ignore')
    print("======= Raw Body =======\n" + body + "\n=========================")

    if not check_secret(request):
        return jsonify({"status": "forbidden"}), 403

    # Parse
    try:
        payload = json.loads(body)
    except:
        try:
            payload = dict(pair.split('=') for pair in body.split(',') if '=' in pair)
        except Exception as e:
            print(f"Parse Error: {str(e)}")
            payload = {}

    symbol = (payload.get("SYMB") or payload.get("ticker") or "XAUUSD").upper()
    tf = payload.get("TF") or payload.get("interval") or "1H"
    frame = f"{tf}m" if str(tf).isdigit() else str(tf)
    data_str = json.dumps(payload, ensure_ascii=False)
    msg_title = f"📊 <b>{symbol} {frame}</b>\n"

    # حداثة التنبيه
    if not is_fresh(payload):
        send_to_telegram(f"⚠️ تنبيه قديم لـ {symbol} تم تجاهله.")
        return jsonify({"status": "ok", "msg": "stale"})

    # منع التكرار خلال 10 ثواني لكل رمز
    payload_hash = hashlib.sha256(body.encode()).hexdigest()
    last = last_payloads.get(symbol, {'hash': '', 'time': 0})
    if payload_hash == last['hash'] and time.time() - last['time'] < 10:
        print("Duplicate webhook ignored")
        return jsonify({"status": "ok", "msg": "duplicate"})

    last_payloads[symbol] = {'hash': payload_hash, 'time': time.time()}

    # كتم الويكند (غير الكريبتو)
    if is_weekend_for(symbol):
        send_to_telegram(f"⚠️ السوق مسكّر لـ {symbol} (سبت/أحد) — لا توجد توصيات.")
        return jsonify({"status": "ok", "msg": "weekend"})

    # معالجة بالخلفية
    def process_analysis():
        xai_text = get_xai_analysis(symbol, frame, data_str)
        analysis_block, rec_fmt = format_outputs(xai_text)
        if analysis_block:
            send_to_telegram(msg_title + analysis_block)
        if rec_fmt:
            send_to_telegram(rec_fmt)
        print(f"Webhook Processing Time: {time.time() - start:.3f}s")

    Thread(target=process_analysis).start()
    return jsonify({"status": "ok", "msg": "received"})

# =========================
#        BOOT
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

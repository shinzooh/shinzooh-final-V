import os
import re
import json
import time
import html
import hashlib
import requests
from threading import Thread
from datetime import datetime
import pytz

from flask import Flask, request, jsonify
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# اختياري: جدولة التقارير اليومية
from apscheduler.schedulers.background import BackgroundScheduler

# =========================
#         CONFIG
# =========================
XAI_API_KEY = os.getenv("XAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")        # ضع نفس القيمة في TV Header: X-Webhook-Token
LANG_MODE = os.getenv("LANG_MODE", "ar").lower()        # ar | en | both
BYPASS_MUTE = os.getenv("BYPASS_MUTE", "false").lower() == "true"
MULTI_TF = [s.strip() for s in os.getenv("MULTI_TF", "").split(",") if s.strip()]  # مثال: 5m,15m,1H,4H,1D

# رموز التقارير المجدولة (عدّلها على لستتك النهائية v3.1)
REPORT_SYMBOLS = [
    "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US30.Spot",
    "NAS100.Spot", "SPX500.Spot", "BTCUSD", "ETHUSD", "DXY"
]

# منطقة التوقيت
KW_TZ = pytz.timezone("Asia/Kuwait")

# قائمة الكريبتو (24/7)
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
    raise_on_status=False
)
adapter = HTTPAdapter(max_retries=retry)
session.mount('https://', adapter)
DEFAULT_TIMEOUT = (5, 30)  # connect, read

# =========================
#        APP + STATE
# =========================
app = Flask(__name__)
last_payloads = {}                 # منع تكرار الـ payload
last_telegram_send_ts = 0.0        # ريت ليمت بسيط للتليجرام

# =========================
#      HELPERS / GUARDS
# =========================
def check_secret(req) -> bool:
    if not WEBHOOK_SECRET:
        return True  # لو ما تبي توثيق حالياً
    token = req.headers.get("X-Webhook-Token", "")
    return token == WEBHOOK_SECRET

def is_crypto(symbol: str) -> bool:
    return symbol.upper() in CRYPTO_SYMBOLS

def is_weekend_for(symbol: str) -> bool:
    if BYPASS_MUTE:
        return False
    if is_crypto(symbol):
        return False
    # 5=سبت, 6=أحد بتوقيت الكويت
    return datetime.now(KW_TZ).weekday() in (5, 6)

def is_fresh(payload: dict, max_age_sec: int = 180) -> bool:
    # جلب أي حقل توقيت محتمل من TradingView
    cand_keys = ["timestamp", "time", "ts", "event_time"]
    ts = None
    for k in cand_keys:
        if k in payload and str(payload[k]).strip():
            ts = payload[k]; break
    if ts is None:
        # إذا ما فيه وقت، نمشيها (أو خلّها False لو تبي التشدد)
        return True
    try:
        s = str(ts)
        if len(s) > 10:
            s = s[:10]  # تحجيم ميلي ثانية لثواني
        ts_int = int(s)
        age = time.time() - ts_int
        return (age >= 0) and (age <= max_age_sec)
    except:
        return True

def sanitize_html(msg: str) -> str:
    # بما أننا نستخدم parse_mode=HTML؛ نأمن النص
    return html.escape(msg, quote=False)

def tg_rate_limit():
    global last_telegram_send_ts
    now = time.time()
    delta = now - last_telegram_send_ts
    if delta < 0.7:
        time.sleep(0.7 - delta)
    last_telegram_send_ts = time.time()

def send_to_telegram(text: str):
    tg_rate_limit()
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    safe = sanitize_html(text)[:4096]
    data = {'chat_id': TELEGRAM_CHAT_ID, 'text': safe, 'parse_mode': 'HTML'}
    try:
        r = session.post(url, data=data, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"Telegram Text Error: {e}")
        return False

def safe_call(func, *args, retries=2, pause=1, **kwargs):
    out = None
    for i in range(retries + 1):
        out = func(*args, **kwargs)
        # نجاح لو ما فيها تحذير/خطأ
        if isinstance(out, str) and ("⚠️" not in out) and ("خطأ" not in out) and ("Error" not in out):
            return out
        time.sleep(pause * (i + 1))
    return out

# =========================
#    PROVIDER FUNCTIONS
# =========================
def gpt4o_analysis(symbol, timeframe, price_data):
    prompt_ar = f"""حلّل {symbol} على فريم {timeframe} (SMC/ICT + كلاسيكي):
- هيكل السوق، سيولة، BOS/CHoCH، FVG، OB، Premium/Discount
- EMA/RSI/MACD
- حدّد هل الصفقة سكالب أو سوينغ
البيانات:
{price_data}"""
    prompt_en = f"""Analyze {symbol} on {timeframe} (SMC/ICT + classic TA):
- Structure, Liquidity, BOS/CHoCH, FVG, OB, Premium/Discount
- EMA/RSI/MACD
- Decide if the trade is scalp or swing
Data:
{price_data}"""
    user_prompt = prompt_ar if LANG_MODE == "ar" else prompt_en
    if LANG_MODE == "both":
        user_prompt = prompt_ar + "\n\n---\n\n" + prompt_en

    try:
        r = session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": user_prompt}],
                "temperature": 0.2,
                "max_tokens": 900
            },
            timeout=DEFAULT_TIMEOUT
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"GPT Analysis Error: {e}")
        return "⚠️ خطأ في تحليل GPT: يرجى التحقق من المفتاح أو الاتصال."

def gpt4o_recommendation(symbol, timeframe, price_data):
    prompt_ar = f"""أعطني توصية مباشرة لـ {symbol} على فريم {timeframe}:
- نوع الصفقة (شراء/بيع)
- نقطة الدخول
- الهدف
- وقف الخسارة
- نجاح 95%+ وانعكاس < 30 نقطة
البيانات:
{price_data}"""
    prompt_en = f"""Give a direct trade for {symbol} on {timeframe}:
- Trade type (Buy/Sell)
- Entry
- Take Profit
- Stop Loss
- 95%+ success, max 30 pips drawdown
Data:
{price_data}"""
    user_prompt = prompt_ar if LANG_MODE == "ar" else prompt_en
    if LANG_MODE == "both":
        user_prompt = prompt_ar + "\n\n---\n\n" + prompt_en

    try:
        r = session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": user_prompt}],
                "temperature": 0.1,
                "max_tokens": 900
            },
            timeout=DEFAULT_TIMEOUT
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"GPT Recommendation Error: {e}")
        return "⚠️ خطأ في توصية GPT: يرجى التحقق من المفتاح أو الاتصال."

def xai_analysis(symbol, timeframe, price_data):
    prompt_ar = f"""حلّل {symbol} على {timeframe} بدقة 95%+:
- SMC/ICT: سيولة، BOS، CHoCH، FVG، OB، Premium/Discount
- كلاسيكي: EMA/RSI/MACD
- توصية نهائية (شراء/بيع)
البيانات:
{price_data}"""
    prompt_en = f"""Analyze {symbol} on {timeframe} with 95%+ accuracy:
- SMC/ICT: Liquidity, BOS/CHoCH, FVG, OB, Premium/Discount
- Classic: EMA/RSI/MACD
- Final call (Buy/Sell)
Data:
{price_data}"""
    user_prompt = prompt_ar if LANG_MODE == "ar" else prompt_en
    if LANG_MODE == "both":
        user_prompt = prompt_ar + "\n\n---\n\n" + prompt_en

    try:
        r = session.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            json={
                "model": "grok-beta",
                "messages": [{"role": "user", "content": user_prompt}],
                "temperature": 0.2,
                "max_tokens": 900
            },
            timeout=DEFAULT_TIMEOUT
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"xAI Error: {e}")
        return "⚠️ خطأ في تحليل xAI: يرجى التحقق من المفتاح أو الاتصال."

# =========================
#     CORE PROCESSING
# =========================
def process_symbol(symbol: str, frame: str, payload: dict):
    # عنوان الرسالة
    msg_title = f"📊 <b>{symbol} {frame}</b>\n"
    data_str = json.dumps(payload, ensure_ascii=False)

    # 1) تحليل (OpenAI → xAI Fallback)
    analysis = safe_call(gpt4o_analysis, symbol, frame, data_str, retries=2, pause=1)
    if "⚠️" in analysis or "Error" in analysis:
        # جرب xAI
        analysis = safe_call(xai_analysis, symbol, frame, data_str, retries=2, pause=1)
        if "⚠️" in analysis or "Error" in analysis:
            send_to_telegram(msg_title + "⚠️ تعذّر التحليل حالياً. نجرّب لاحقًا.")
            return

    send_to_telegram(msg_title + analysis)
    time.sleep(1)

    # 2) توصية (OpenAI فقط، أو أضف Fallback لو تبي)
    recommendation = safe_call(gpt4o_recommendation, symbol, frame, data_str, retries=2, pause=1)
    if "⚠️" in recommendation or "Error" in recommendation:
        send_to_telegram("⚠️ تعذّرت التوصية بسبب ضغط أو اتصال. جرّبنا أكثر من مرة.")
        return

    send_to_telegram(recommendation)

def handle_multi_tf(symbol: str, tf: str, payload: dict):
    # لو MULTI_TF محدد، نحلل عدّة فريمات؛ غيره نحلل فريم واحد
    if MULTI_TF:
        for frame in MULTI_TF:
            Thread(target=process_symbol, args=(symbol, frame, payload)).start()
            time.sleep(0.5)
    else:
        frame = f"{tf}m" if str(tf).isdigit() else tf
        Thread(target=process_symbol, args=(symbol, frame, payload)).start()

# =========================
#         ROUTES
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    req_id = hashlib.sha256((request.data.decode('utf-8', 'ignore') + str(time.time())).encode()).hexdigest()[:12]
    start = time.time()
    body = request.data.decode('utf-8', 'ignore')
    print(json.dumps({"req_id": req_id, "event": "raw_body", "body": body}) )

    if not check_secret(request):
        return jsonify({"status": "forbidden", "req_id": req_id}), 403

    # Parsing payload
    try:
        payload = json.loads(body)
    except:
        try:
            payload = dict(pair.split('=') for pair in body.split(',') if '=' in pair)
        except Exception as e:
            print(json.dumps({"req_id": req_id, "event": "parse_error", "err": str(e)}))
            payload = {}

    symbol = (payload.get("SYMB") or payload.get("symbol") or payload.get("ticker") or "XAUUSD").upper()
    tf = (payload.get("TF") or payload.get("interval") or "1H")

    # Freshness check
    if not is_fresh(payload):
        send_to_telegram(f"⚠️ تنبيه قديم لـ {symbol} تم تجاهله.")
        return jsonify({"status":"ok", "msg":"stale alert", "req_id": req_id})

    # Duplicate guard (10s window per symbol)
    payload_hash = hashlib.sha256(body.encode()).hexdigest()
    last = last_payloads.get(symbol, {'hash': '', 'time': 0})
    if payload_hash == last['hash'] and time.time() - last['time'] < 10:
        print(json.dumps({"req_id": req_id, "event":"dup_ignored", "symbol":symbol}))
        return jsonify({"status": "ok", "msg": "duplicate ignored", "req_id": req_id})

    last_payloads[symbol] = {'hash': payload_hash, 'time': time.time()}

    # Weekend mute (non-crypto)
    if is_weekend_for(symbol):
        send_to_telegram(f"⚠️ السوق مسكّر لـ {symbol} (سبت/أحد) — لا توجد توصيات.")
        return jsonify({"status": "ok", "msg": "weekend mute", "req_id": req_id})

    handle_multi_tf(symbol, tf, payload)

    print(json.dumps({"req_id": req_id, "event":"accepted", "symbol":symbol, "tf":str(tf), "elapsed": round(time.time()-start,3)}))
    return jsonify({"status": "ok", "msg": "received", "req_id": req_id})

# =========================
#    SCHEDULED REPORTS
# =========================
scheduler = BackgroundScheduler(timezone=str(KW_TZ))
def run_batch_report():
    stamp = datetime.now(KW_TZ).strftime("%Y-%m-%d %H:%M")
    print(json.dumps({"event":"batch_report", "time": stamp, "symbols": REPORT_SYMBOLS}))
    for sym in REPORT_SYMBOLS:
        fake_payload = {"SYMB": sym, "TF": "1H", "time": int(time.time())}
        if not is_weekend_for(sym):
            handle_multi_tf(sym, "1H", fake_payload)
        else:
            send_to_telegram(f"⚠️ (Scheduled) السوق مسكّر لـ {sym} — تم التجاهل.")

# أوقات التقارير اليومية
for hh, mm in [(4,30), (9,0), (14,0), (16,30)]:
    scheduler.add_job(run_batch_report, "cron", hour=hh, minute=mm)
scheduler.start()

# =========================
#        BOOT
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

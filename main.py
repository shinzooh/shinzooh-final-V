from fastapi import FastAPI, Request
import os, time, re, json, asyncio, datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- إعدادات التطبيق والمتغيرات الأساسية ---
app = FastAPI()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
PORT = int(os.getenv("PORT", "10000"))

# --- إعداد استراتيجية إعادة المحاولة للاتصالات ---
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"]
)
session = requests.Session()
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter )
session.mount("http://", adapter )

# --- دوال مساعدة ---
def now_str():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def _to_float_safe(s):
    if s is None: return None
    s = str(s).strip()
    if s in ("", "NaN", "nan", "null", "None", "{", "}", "{{rsi}}"): return None
    try:
        return float(s)
    except (ValueError, TypeError):
        s2 = re.sub(r"[^0-9\.\-\+eE]", "", s)
        try:
            return float(s2)
        except (ValueError, TypeError):
            return None

def parse_kv(raw: str) -> dict:
    d = {}
    for part in raw.split(","):
        if "=" not in part: continue
        k, v = part.split("=", 1)
        d[k.strip()] = v.strip()
    return d

def build_prompt_ar(n: dict) -> str:
    sym, tf, C = n.get("SYMB",""), n.get("TF",""), n.get("C")
    O, H, L, V = n.get("O"), n.get("H"), n.get("L"), n.get("V")
    RSI, EMA, MACD = n.get("RSI"), n.get("EMA"), n.get("MACD")
    return (
f"""حلّل زوج {sym} على فريم {tf} بأسلوب ICT/SMC بدقة عالية:
- المستويات: Liquidity / BOS / CHoCH / FVG / Order Block / Premium-Discount
- التحليل الكلاسيكي: RSI={RSI}, EMA={EMA}, MACD={MACD}
- بيانات الشمعة: O={O}, H={H}, L={L}, C={C}, V={V}
أعطني مخرجات مرتبة بالعربي بهذا الشكل فقط:
🔍 التحليل الفني الكلاسيكي
* السعر الحالي: {C}
* البيانات: O={O} / H={H} / L={L} / C={C}
* RSI: {RSI if RSI else 'na'}
* EMA20: {EMA if EMA else 'na'}
* MACD: {MACD if MACD else 'na'}
📌 التفسير: [يُملأ بواسطة AI]
📚 تحليل ICT / SMC
* BOS / CHoCH: [يُملأ بواسطة AI]
* FVG / OB: [يُملأ بواسطة AI]
* السيولة: [يُملأ بواسطة AI]
📌 التفسير: [يُملأ بواسطة AI]
🎯 التوصية النهائية
* نوع الصفقة: ...
* نقاط الدخول: ...
* TP1 / TP2 / TP3 / TP4: ...
* وقف الخسارة: ...
* السبب: ...
"""
    )

def ask_ai_model(session, url, headers, json_payload, timeout=22):
    try:
        r = session.post(url, headers=headers, json=json_payload, timeout=timeout)
        r.raise_for_status()
        return True, r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return False, f"API error: {e}"

def ask_xai(prompt: str):
    if not XAI_API_KEY: return False, "xAI API key missing"
    return ask_ai_model(session, "https://api.x.ai/v1/chat/completions", {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}, {"model": "grok-4-latest", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 1000} )

def ask_openai(prompt: str):
    if not OPENAI_API_KEY: return False, "OpenAI API key missing"
    return ask_ai_model(session, "https://api.openai.com/v1/chat/completions", {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}, {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 1000} )

def extract_trade_fields(text: str) -> dict:
    if not text: return {}
    def grab(pattern):
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""
    return {"direction": grab(r"نوع الصفقة\s*:\s*(.*)"), "entry": grab(r"نقاط الدخول\s*:\s*(.*)"), "tps": grab(r"TP1\s*\/\s*TP2\s*\/\s*TP3\s*\/\s*TP4\s*:\s*(.*)"), "sl": grab(r"وقف الخسارة\s*:\s*(.*)"), "reason": grab(r"السبب\s*:\s*(.*)"), "classic_analysis": grab(r"التحليل الفني الكلاسيكي\s*\n(.*?)📚"), "smc_analysis": grab(r"تحليل ICT / SMC\s*\n(.*?)🎯")}

def consensus(rec_a: dict, rec_b: dict) -> tuple:
    def norm_dir(d):
        s = (d or "").strip().lower()
        if "شراء" in s or "buy" in s: return "buy"
        if "بيع" in s or "sell" in s: return "sell"
        return ""
    da = norm_dir(rec_a.get("direction", ""))
    db = norm_dir(rec_b.get("direction", ""))
    if da and da == db: return True, da, rec_a
    if da and not db: return True, da, rec_a
    if db and not da: return True, db, rec_b
    return False, "", {}

def tgsend(text: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("[WARN] Telegram env missing, skip send.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=12 )
    except Exception as e:
        print(f"[WARN] Telegram send error: {e}")

_last_send = {}
MIN_GAP_SEC = 5

async def process_alert(raw_text: str):
    kv = parse_kv(raw_text)
    n = {"SYMB": kv.get("SYMB",""), "TF": kv.get("TF",""), "O": _to_float_safe(kv.get("O")), "H": _to_float_safe(kv.get("H")), "L": _to_float_safe(kv.get("L")), "C": _to_float_safe(kv.get("C")), "V": _to_float_safe(kv.get("V")), "RSI": _to_float_safe(kv.get("RSI")), "EMA": _to_float_safe(kv.get("EMA")), "MACD": _to_float_safe(kv.get("MACD"))}
    sym, tf = n["SYMB"], n["TF"]
    key = f"{sym}|{tf}"
    now_sec = time.time()
    if key in _last_send and (now_sec - _last_send[key]) < MIN_GAP_SEC:
        print(f"[INFO] Skip duplicate burst for {key}.")
        return
    _last_send[key] = now_sec
    if not sym or not tf or n["C"] is None:
        print("[INFO] Missing essentials (SYMB, TF, C), skip.")
        return
    if n["RSI"] and not (35 <= n["RSI"] <= 75):
        print(f"[INFO] RSI {n['RSI']} out of range (35-75), skip.")
        return
    prompt = build_prompt_ar(n)
    loop = asyncio.get_event_loop()
    ok_xai, txt_xai = await loop.run_in_executor(None, lambda: ask_xai(prompt))
    ok_oai, txt_oai = await loop.run_in_executor(None, lambda: ask_openai(prompt))
    rec_xai = extract_trade_fields(txt_xai if ok_xai else "")
    rec_oai = extract_trade_fields(txt_oai if ok_oai else "")
    agreed, final_dir, final_rec = consensus(rec_xai, rec_oai)
    openai_decision = "✅ شراء" if "buy" in rec_oai.get("direction", "").lower() else "❌ بيع" if "sell" in rec_oai.get("direction", "").lower() else "⚠️ محايد"
    xai_decision = "✅ شراء" if "buy" in rec_xai.get("direction", "").lower() else "❌ بيع" if "sell" in rec_xai.get("direction", "").lower() else "⚠️ محايد"
    message = f"""*تحليل {sym} | {tf}*
*التوقيت: {now_str()}*
---
{rec_oai.get('classic_analysis', '*🔍 التحليل الفني الكلاسيكي*').strip()}
{rec_oai.get('smc_analysis', '*📚 تحليل ICT / SMC*').strip()}
---
*🤖 ملخص النماذج*
| النموذج | القرار |
|:---|:---|
| OpenAI | {openai_decision} |
| xAI | {xai_decision} |
| Claude | ⚠️ محايد (لم يتم الربط) |
*⚠️ تحليل التوافق*
- *النتيجة:* `{'✅ توافق على ' + final_dir.upper() if agreed else '❌ تعارض بين النماذج.'}`
*🎯 التوصية النهائية*
- *نوع الصفقة:* `{final_rec.get('direction', 'لا يوجد') if agreed else 'لا يوجد'}`
- *نقاط الدخول:* `{final_rec.get('entry', '—') if agreed else '—'}`
- *أهداف الربح (TPs):* `{final_rec.get('tps', '—') if agreed else '—'}`
- *وقف الخسارة (SL):* `{final_rec.get('sl', '—') if agreed else '—'}`
- *السبب:* `{final_rec.get('reason', 'تعارض النماذج يمنع اتخاذ قرار.') if agreed else 'تعارض النماذج يمنع اتخاذ قرار.'}`
*⚡ شروط الأمان*
- *RSI (35-75):* `{'✅' if n['RSI'] and 35 <= n['RSI'] <= 75 else '❌'}`
"""
    tgsend(message)

@app.get("/")
def root():
    return {"ok": True, "service": "shinzooh-final-v", "ts": now_str()}

@app.post("/webhook")
async def webhook(request: Request):
    raw = await request.body()
    data = raw.decode(errors="ignore")
    print(f"[INFO] Raw Body (KV): {data[:300]}")
    asyncio.create_task(process_alert(data))
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

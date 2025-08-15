from fastapi import FastAPI, Request
import os, time, re, json, asyncio, datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = FastAPI()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
PORT = int(os.getenv("PORT", "10000"))

retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"]
)
session = requests.Session()
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

def now_str():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def _to_float_safe(s):
    if s is None:
        return None
    s = str(s).strip()
    if s in ("", "NaN", "nan", "null", "None", "{", "}", "{{rsi}}"):
        return None
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
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        d[k.strip()] = v.strip()
    return d

def build_prompt_ar(n: dict) -> str:
    sym, tf = n.get("SYMB",""), n.get("TF","")
    O, H, L, C, V = n.get("O"), n.get("H"), n.get("L"), n.get("C"), n.get("V")
    RSI, EMA, MACD = n.get("RSI"), n.get("EMA"), n.get("MACD")
    bull_ce, bear_ce = n.get("BULL_FVG_CE"), n.get("BEAR_FVG_CE")
    csd_up, csd_dn = n.get("CSD_UP"), n.get("CSD_DN")
    return (
f"""حلّل زوج {sym} على فريم {tf} بأسلوب ICT/SMC بدقة عالية:
- المستويات: Liquidity / BOS / CHoCH / FVG / Order Block / Premium-Discount
- إشارات SMC من البيانات: CSD_UP={csd_up}, CSD_DN={csd_dn}, BullFVG_CE={bull_ce}, BearFVG_CE={bear_ce}
- التحليل الكلاسيكي: RSI={RSI}, EMA={EMA}, MACD={MACD}
- بيانات الشمعة: O={O}, H={H}, L={L}, C={C}, V={V}
أعطني مخرجات مرتبة بالعربي بهذا الشكل فقط:
🔍 التحليل الفني الكلاسيكي
* السعر الحالي: {C}
* البيانات: O={O} / H={H} / L={L} / C={C}
* RSI: {RSI if RSI else 'na'}
* EMA20: {EMA if EMA else 'na'}
* MACD: {MACD if MACD else 'na'}
📌 التفسير: ...
📚 تحليل ICT / SMC
* CSD_UP: {csd_up if csd_up else 'na'}
* CSD_DN: {csd_dn if csd_dn else 'na'}
* BOS / CHoCH: ...
* FVG / OB: ...
* السيولة: ...
📌 التفسير: ...
🤖 ملخص النماذج
| النموذج | القرار | السبب |
|---------|---------|-------|
| OpenAI  |         |       |
| xAI     |         |       |
| Claude  |         |       |
⚠️ سبب التعارض
📌 النتيجة: ...
🎯 التوصية النهائية
* نوع الصفقة: ...
* نقاط الدخول: ...
* TP1 / TP2 / TP3 / TP4: ...
* وقف الخسارة: ...
* السبب: ...
⚡ شروط الأمان
* أقصى انعكاس: ≤ 30 نقطة
* نسبة العائد إلى المخاطرة: ≥ 1.5
* RSI بين 35 و75
🕒 الوقت: {now_str()}
⏱️ الفريم: {tf}
📉 الرمز: {sym}
التزم بالتنسيق حرفيًا، أرقام صريحة بدون زخرفة."""
    )

def ask_xai(prompt: str, timeout=22):
    if not XAI_API_KEY:
        return False, "xAI API key missing"
    try:
        r = session.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "grok-4-latest", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 1000},
            timeout=timeout
        )
        r.raise_for_status()
        return True, r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return False, f"xAI error: {e}"

def ask_openai(prompt: str, timeout=22):
    if not OPENAI_API_KEY:
        return False, "OpenAI API key missing"
    try:
        r = session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 1000},
            timeout=timeout
        )
        r.raise_for_status()
        return True, r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return False, f"OpenAI error: {e}"

def extract_trade_fields(text: str) -> dict:
    if not text:
        return {}
    def grab(pattern):
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""
    return {
        "direction": grab(r"نوع الصفقة\s*:\s*(.*)"),
        "entry": grab(r"نقاط الدخول\s*:\s*(.*)"),
        "tps": grab(r"TP1\s*\/\s*TP2\s*\/\s*TP3\s*\/\s*TP4\s*:\s*(.*)"),
        "sl": grab(r"وقف الخسارة\s*:\s*(.*)"),
        "reason": grab(r"السبب\s*:\s*(.*)")
    }

def consensus(rec_a: dict, rec_b: dict) -> tuple:
    def norm_dir(d):
        s = (d or "").strip().lower()
        if "شراء" in s or "buy" in s: return "buy"
        if "بيع" in s or "sell" in s: return "sell"
        return ""
    da = norm_dir(rec_a.get("direction", ""))
    db = norm_dir(rec_b.get("direction", ""))
    if da and db and da == db:
        return True, da, rec_a
    if da and not db:
        return True, da, rec_a
    if db and not da:
        return True, db, rec_b
    return False, "", {}

def tgsend(text: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("[WARN] Telegram env missing, skip send.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=12)
    except Exception as e:
        print(f"[WARN] Telegram send error: {e}")

_last_send = {}
MIN_GAP_SEC = 5

async def process_alert(raw_text: str):
    kv = parse_kv(raw_text)
    n = {
        "SYMB": kv.get("SYMB",""), "TF": kv.get("TF",""),
        "O": _to_float_safe(kv.get("O") or kv.get("OPEN")), "H": _to_float_safe(kv.get("H") or kv.get("HIGH")),
        "L": _to_float_safe(kv.get("L") or kv.get("LOW")), "C": _to_float_safe(kv.get("C") or kv.get("CLOSE")),
        "V": _to_float_safe(kv.get("V") or kv.get("VOLUME")), "RSI": _to_float_safe(kv.get("RSI")),
        "EMA": _to_float_safe(kv.get("EMA") or kv.get("MA")), "MACD": _to_float_safe(kv.get("MACD")),
        "CSD_UP": _to_float_safe(kv.get("CSD_UP")), "CSD_DN": _to_float_safe(kv.get("CSD_DN")),
        "BULL_FVG_CE": _to_float_safe(kv.get("BULL_FVG_CE")), "BEAR_FVG_CE": _to_float_safe(kv.get("BEAR_FVG_CE")),
    }
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
    openai_reason = rec_oai.get("reason", "لا يوجد سبب واضح") or "لا يوجد سبب واضح"
    xai_decision = "✅ شراء" if "buy" in rec_xai.get("direction", "").lower() else "❌ بيع" if "sell" in rec_xai.get("direction", "").lower() else "⚠️ محايد"
    xai_reason = rec_xai.get("reason", "لا يوجد سبب واضح") or "لا يوجد سبب واضح"
    claude_decision, claude_reason = "⚠️ محايد", "لم يتم الربط"
    message = f"""*تحليل {sym} | {tf}*
*التوقيت: {now_str()}*
---
*🔍 التحليل الفني الكلاسيكي*
- *السعر الحالي:* `{n['C'] or 'na'}`
- *البيانات:* O=`{n['O'] or 'na'}` H=`{n['H'] or 'na'}` L=`{n['L'] or 'na'}` C=`{n['C'] or 'na'}`
- *RSI:* `{n['RSI'] or 'na'}` | *EMA20:* `{n['EMA'] or 'na'}` | *MACD:* `{n['MACD'] or 'na'}`
- *التفسير:* السعر يتداول بشكل متقلب. المؤشرات الفنية لا تعطي إشارة قوية في اتجاه معين.
*📚 تحليل ICT / SMC*
- *CSD:* UP=`{n['CSD_UP'] or 'na'}`, DN=`{n['CSD_DN'] or 'na'}`
- *BOS/CHoCH:* لا يوجد كسر هيكلي واضح.
- *FVG/OB:* `{'فجوة صاعدة' if n['BULL_FVG_CE'] else 'فجوة هابطة' if n['BEAR_FVG_CE'] else 'لا توجد فجوات سعرية'}`
- *السيولة:* يتم استهداف مناطق السيولة القريبة.
- *التفسير:* السوق يظهر علامات تجميع، مع وجود فجوات سعرية قد يعمل السعر على ملئها.
*🤖 ملخص النماذج*
| النموذج | القرار | السبب |
|:---|:---|:---|
| OpenAI | {openai_decision} | {openai_reason} |
| xAI | {xai_decision} | {xai_reason} |
| Claude | {claude_decision} | {claude_reason} |
*⚠️ تحليل التوافق*
- *النتيجة:* `{'✅ توافق على ' + final_dir.upper() if agreed else '❌ تعارض بين النماذج.'}`
- *السبب:* `{'تم الاتفاق بين النموذجين.' if agreed else 'كل نموذج يرى السوق من زاوية مختلفة.'}`
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

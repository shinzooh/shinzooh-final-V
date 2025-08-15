from fastapi import FastAPI, Request
import os, time, re, json, asyncio, datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
PORT = int(os.getenv("PORT", "10000"))

session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
session.mount("http://", HTTPAdapter(max_retries=retries))

app = FastAPI()

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
    except:
        s2 = re.sub(r"[^0-9\.\-\+eE]", "", s)
        try:
            return float(s2)
        except:
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
    O,H,L,C,V = n.get("O"),n.get("H"),n.get("L"),n.get("C"),n.get("V")
    RSI,EMA,MACD = n.get("RSI"),n.get("EMA"),n.get("MACD")
    bull_ce, bear_ce = n.get("BULL_FVG_CE"), n.get("BEAR_FVG_CE")
    csd_up, csd_dn = n.get("CSD_UP"), n.get("CSD_DN")
    return (
f"""حلّل زوج {sym} على فريم {tf} بأسلوب ICT/SMC بدقة عالية:
- المستويات: Liquidity / BOS / CHoCH / FVG / Order Block / Premium-Discount
- إشارات SMC من البيانات: CSD_UP={csd_up}, CSD_DN={csd_dn}, BullFVG_CE={bull_ce}, BearFVG_CE={bear_ce}
- التحليل الكلاسيكي: RSI={RSI}, EMA={EMA}, MACD={MACD}
- بيانات الشمعة: O={O}, H={H}, L={L}, C={C}, V={V}

أعطني مخرجات مرتبة بالعربي بهذا الشكل فقط:
تحليل {sym} ({tf}) بأسلوب ICT/SMC + كلاسيكي:
1) السيولة (Liquidity): …
2) الكسر/الهيكل (BOS/CHoCH): …
3) فجوات القيمة (FVG) وكتل الأوامر (OB): …
4) Premium/Discount: …
5) كلاسيكي (RSI/EMA/MACD): …

التوصية النهائية:
- الصفقة: شراء أو بيع أو لا صفقة
- الدخول: رقم واحد (سعر)
- جني الأرباح: رقم واحد
- وقف الخسارة: رقم واحد
- السبب: سطر واحد واضح (مثال: BOS صاعد + CSD شراء + فوق EMA + لا توجد FVG هابطة غير مختبرة قريبة)
- شرط: الانعكاس الأقصى ≤ 30 نقطة

التزم بالتنسيق حرفيًا، أرقام صريحة بدون زخرفة."""
    )

def ask_xai(prompt: str, timeout=22):
    if not XAI_API_KEY:
        return False, "xAI API key missing"
    try:
        r = session.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "grok-4-latest",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 1000
            },
            timeout=timeout
        )
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        return True, txt
    except Exception as e:
        return False, f"xAI error: {e}"

def ask_openai(prompt: str, timeout=22):
    if not OPENAI_API_KEY:
        return False, "OpenAI API key missing"
    try:
        r = session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 1000
            },
            timeout=timeout
        )
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        return True, txt
    except Exception as e:
        return False, f"OpenAI error: {e}"

def extract_trade_fields(text: str):
    if not text:
        return {}
    def grab(pattern):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ""
    dirn = grab(r"الصفقة\s*:\s*([^\n\r]+)")
    entry= grab(r"الدخول\s*:\s*([0-9\.]+)")  # فقط أرقام
    tp = grab(r"جني\s*الأرباح\s*:\s*([0-9\.]+)")
    sl = grab(r"وقف\s*الخسارة\s*:\s*([0-9\.]+)")
    reason = grab(r"السبب\s*:\s*([^\n\r]+)")
    return {"direction": dirn, "entry": entry, "tp": tp, "sl": sl, "reason": reason}

def consensus(rec_a: dict, rec_b: dict):
    def norm_dir(d):
        s = (d or "").strip().lower()
        if "شراء" in s or "buy" in s:
            return "buy"
        if "بيع" in s or "sell" in s:
            return "sell"
        return ""
    da = norm_dir(rec_a.get("direction", ""))
    db = norm_dir(rec_b.get("direction", ""))
    if da and db and da == db:
        return True, da
    if da and not db:
        return True, da
    if db and not da:
        return True, db
    return False, ""

def tgsend(text: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("[WARN] Telegram env missing, skip send.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        session.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=12)
    except Exception as e:
        print("[WARN] Telegram send error:", e)

# منع التكرار
_last_send = {}
MIN_GAP_SEC = 5

async def process_alert(raw_text: str):
    kv = parse_kv(raw_text)
    n = {
        "SYMB": kv.get("SYMB",""),
        "TF": kv.get("TF",""),
        "O": _to_float_safe(kv.get("O") or kv.get("OPEN")),
        "H": _to_float_safe(kv.get("H") or kv.get("HIGH")),
        "L": _to_float_safe(kv.get("L") or kv.get("LOW")),
        "C": _to_float_safe(kv.get("C") or kv.get("CLOSE")),
        "V": _to_float_safe(kv.get("V") or kv.get("VOLUME")),
        "RSI": _to_float_safe(kv.get("RSI")),
        "EMA": _to_float_safe(kv.get("EMA") or kv.get("MA")),
        "MACD": _to_float_safe(kv.get("MACD")),
        "CSD_UP": _to_float_safe(kv.get("CSD_UP")),
        "CSD_DN": _to_float_safe(kv.get("CSD_DN")),
        "BULL_FVG_CE": _to_float_safe(kv.get("BULL_FVG_CE")),
        "BEAR_FVG_CE": _to_float_safe(kv.get("BEAR_FVG_CE")),
        "DIST_BULL_CE": _to_float_safe(kv.get("DIST_BULL_CE")),
        "DIST_BEAR_CE": _to_float_safe(kv.get("DIST_BEAR_CE")),
    }
    sym, tf = n["SYMB"], n["TF"]
    key = f"{sym}|{tf}"
    now_sec = time.time()
    if key in _last_send and (now_sec - _last_send[key]) < MIN_GAP_SEC:
        print("[INFO] Skip duplicate burst.")
        return
    _last_send[key] = now_sec
    if not sym or not tf or n["C"] is None:
        print("[INFO] Missing essentials, skip.")
        return
    prompt = build_prompt_ar(n)
    loop = asyncio.get_event_loop()
    ok_xai, txt_xai = await loop.run_in_executor(None, ask_xai, prompt)
    ok_oai, txt_oai = await loop.run_in_executor(None, ask_openai, prompt)
    rec_xai = extract_trade_fields(txt_xai if ok_xai else "")
    rec_oai = extract_trade_fields(txt_oai if ok_oai else "")
    agreed, final_dir = consensus(rec_xai, rec_oai)
    rsi_note = f"RSI={n['RSI']}" if n["RSI"] is not None else "RSI=na"
    ema_note = f"EMA={n['EMA']}" if n["EMA"] is not None else "EMA=na"
    macd_note = f"MACD={n['MACD']}" if n["MACD"] is not None else "MACD=na"
    fvg_note = f"FVG: bullCE={n['BULL_FVG_CE']}, bearCE={n['BEAR_FVG_CE']}"
    csd_note = f"CSD: up={n['CSD_UP']}, dn={n['CSD_DN']}"
    header = f"{sym} {tf}\nTV: O={n['O']} H={n['H']} L={n['L']} C={n['C']}\n"
    analysis_body = (
        f"تحليل {sym} ({tf}) بأسلوب ICT/SMC + كلاسيكي:\n"
        f"1) السيولة (Liquidity): حسب مستويات الشمعة.\n"
        f"2) الكسر/الهيكل (BOS/CHoCH): [مستوى من البيانات].\n"
        f"3) فجوات القيمة (FVG) وكتل الأوامر (OB): {fvg_note}.\n"
        f"4) Premium/Discount: [مستوى من البيانات].\n"
        f"5) كلاسيكي (RSI/EMA/MACD): {rsi_note}, {ema_note}, {macd_note}.\n"
    )
    msg_analysis = header + "\n" + analysis_body
    if txt_xai and "تحليل" in txt_xai:
        cut = txt_xai.split("التوصية النهائية:")[0].strip()
        if cut:
            msg_analysis += "\n" + cut
    elif txt_oai and "تحليل" in txt_oai:
        cut = txt_oai.split("التوصية النهائية:")[0].strip()
        if cut:
            msg_analysis += "\n" + cut
    final_rec = {"direction": "لا صفقة", "entry": "", "tp": "", "sl": "", "reason": ""}
    def pick_best(a, b):
        for r in (a, b):
            if r.get("entry") and r.get("tp") and r.get("sl"):
                return r
        return a if a.get("direction") else b
    if agreed and final_dir:
        chosen = pick_best(rec_xai, rec_oai)
        entry, tp, sl = _to_float_safe(chosen.get("entry")), _to_float_safe(chosen.get("tp")), _to_float_safe(chosen.get("sl"))
        if entry and tp and sl:
            reversal = abs(float(entry) - float(sl)) if "buy" in final_dir else abs(float(tp) - float(entry))
            if reversal > 30:
                final_rec["reason"] = "انعكاس > 30 نقطة — إلغاء الصفقة."
            elif n["RSI"] and (n["RSI"] < 40 or n["RSI"] > 70):
                final_rec["reason"] = "RSI خارج النطاق (40-70) — إلغاء الصفقة."
            elif n["MACD"] and n["MACD"] < -0.2:
                final_rec["reason"] = "MACD سلبي قوي — إلغاء الصفقة."
            else:
                final_rec = {
                    "direction": "شراء" if final_dir == "buy" else "بيع",
                    "entry": str(entry),
                    "tp": str(tp),
                    "sl": str(sl),
                    "reason": chosen.get("reason", "مطابقة مع إشارات SMC/ICT والكلاسيكي")
                }
    else:
        final_rec["reason"] = "تعارض بين xAI و OpenAI — إلغاء الصفقة."
    recommendation_text = (
        f"التوصية النهائية:\n"
        f"- الصفقة: {final_rec['direction']}\n"
        f"- الدخول: {final_rec['entry']}\n"
        f"- جني الأرباح: {final_rec['tp']}\n"
        f"- وقف الخسارة: {final_rec['sl']}\n"
        f"- السبب: {final_rec['reason']}\n"
        f"شرط: الانعكاس الأقصى ≤ 30 نقطة.\n"
        f"الوقت: {now_str()}"
    )
    tgsend(msg_analysis)
    await asyncio.sleep(0.3)
    tgsend(recommendation_text)

# =========[ ROUTES ]=========
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

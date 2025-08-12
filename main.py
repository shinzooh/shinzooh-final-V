# -*- coding: utf-8 -*-
import os, re, html, json, time, math, traceback, concurrent.futures, threading, logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
import requests
from flask import Flask, request, jsonify

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ========= ENV =========
XAI_API_KEY        = os.getenv("XAI_API_KEY", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
PORT               = int(os.getenv("PORT", "10000"))

ALLOWED_TF = {"5","15","30","1H","4H","1D"}

# ========= Flask & Logging =========
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("shinzooh")

# Rate limit للويبهوك (بدون تحذير التخزين)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
    default_limits=["200 per day", "50 per hour"]
)

# جلسة HTTP مع Retries (تشمل 429)
session = requests.Session()
retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=frozenset(["POST"])
)
adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)
session.mount("http://", adapter)

# ========= Telegram =========
_tg_lock = threading.Lock()
_last_tg_ts = 0.0

def tg(html_text: str):
    """إرسال منسّق لتليجرام مع rate-limit داخلي + تهريب HTML."""
    global _last_tg_ts
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        log.info("Telegram not configured.")
        return
    try:
        with _tg_lock:
            now = time.time()
            wait = 1.5 - (now - _last_tg_ts)  # رسالة كل 1.5 ثانية
            if wait > 0:
                time.sleep(wait)
            _last_tg_ts = time.time()

        r = session.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": html_text, "parse_mode": "HTML"},
            timeout=(5, 30)
        )
        if r.status_code != 200:
            log.warning("Telegram non-200: %s %s", r.status_code, r.text[:200])
    except Exception:
        log.exception("Telegram error")

# ========= Helpers =========
_last_sent_keys = set()  # منع تكرار نفس (symbol|tf|bar_time)

def esc(s: str) -> str:
    # نهرب < و > و & فقط، بدون المساس بعلامات الاقتباس
    return html.escape(s or "", quote=False)

def _to_float(x) -> Optional[float]:
    try:
        s = str(x).strip()
        if s == "" or s.startswith("{{"):
            return None
        return float(s.replace(",", ""))
    except:
        return None

def _parse_time_any(x) -> Optional[datetime]:
    if x is None:
        return None
    s = str(x).strip()
    if s.isdigit():
        t = int(s)
        if t > 1_000_000_000_000:
            t //= 1000
        return datetime.fromtimestamp(t, tz=timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except:
        return None

def normalize_tf(tf_raw: str) -> str:
    tf_raw = (tf_raw or "").strip()
    if tf_raw.isdigit():
        n = int(tf_raw)
        if n < 5:
            n = 5  # لا نسمح بأقل من 5m
        return {"5":"5","15":"15","30":"30","60":"1H","240":"4H"}.get(str(n), str(n))
    return {"D":"1D","1D":"1D","4H":"4H","1H":"1H","30":"30","15":"15","5":"5"}.get(tf_raw, tf_raw)

def parse_payload() -> Dict[str, str]:
    """يدعم JSON أو صيغة key=value."""
    raw = request.get_data(as_text=True) or ""
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    out = {}
    for part in re.split(r"[,\n]+", raw.strip()):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    log.info("Raw Body (KV): %s", raw[:200])
    return out

def normalize(p: Dict[str,str]) -> Dict[str, object]:
    sym  = (p.get("SYMB") or p.get("symbol") or "").upper()
    tf   = normalize_tf(p.get("TF") or p.get("interval") or "")
    o = _to_float(p.get("OPEN") or p.get("O"))
    h = _to_float(p.get("HIGH") or p.get("H"))
    l = _to_float(p.get("LOW")  or p.get("L"))
    c = _to_float(p.get("CLOSE")or p.get("C"))
    v = _to_float(p.get("VOLUME")or p.get("V"))
    # ثبّت الدقيقة لو ما في BAR_TIME
    bt = _parse_time_any(p.get("BAR_TIME") or p.get("time"))
    if bt is None:
        bt = _parse_time_any(p.get("NOW")) or datetime.now(timezone.utc)
        bt = bt.replace(second=0, microsecond=0)

    ex = {
        "PDH": _to_float(p.get("PDH")), "PDL": _to_float(p.get("PDL")), "PDC": _to_float(p.get("PDC")),
        "PWH": _to_float(p.get("PWH")), "PWL": _to_float(p.get("PWL")), "PWC": _to_float(p.get("PWC")),
        "PP": _to_float(p.get("PP")),   "R1": _to_float(p.get("R1")),   "S1": _to_float(p.get("S1")),
        "ATR14": _to_float(p.get("ATR14")), "TR": _to_float(p.get("TR")),
        "RANGE_MID": _to_float(p.get("RANGE_MID")),
        "ZONE": (str(p.get("ZONE")).strip() if p.get("ZONE") is not None else None),
        "SESSION": (str(p.get("SESSION")).strip() if p.get("SESSION") is not None else None),
        "BOS_UP": _to_float(p.get("BOS_UP")), "BOS_DN": _to_float(p.get("BOS_DN")), "CHOCH": _to_float(p.get("CHOCH")),
        "SWEEP_PDH": _to_float(p.get("SWEEP_PDH")), "SWEEP_PDL": _to_float(p.get("SWEEP_PDL")),
        "BODY_PCT": _to_float(p.get("BODY_PCT")), "WICK_TOP_PCT": _to_float(p.get("WICK_TOP_PCT")), "WICK_BOT_PCT": _to_float(p.get("WICK_BOT_PCT")),
        "CSD_UP": _to_float(p.get("CSD_UP")), "CSD_DN": _to_float(p.get("CSD_DN")),
        "BULL_FVG_CE": _to_float(p.get("BULL_FVG_CE")), "BEAR_FVG_CE": _to_float(p.get("BEAR_FVG_CE")),
        "DIST_BULL_CE": _to_float(p.get("DIST_BULL_CE")), "DIST_BEAR_CE": _to_float(p.get("DIST_BEAR_CE")),
    }
    return {"symbol": sym, "tf": tf, "open": o, "high": h, "low": l, "close": c, "volume": v, "bar_time": bt, "extras": ex}

def compute_sr(h,l,c):
    if any(v is None for v in (h,l,c)):
        return {"PP":None,"R1":None,"S1":None}
    pp = (h+l+c)/3.0
    r1 = 2*pp - l
    s1 = 2*pp - h
    return {"PP":pp,"R1":r1,"S1":s1}

def fmt_price(x): return "-" if x is None else f"{x:.3f}"

def zone_decode(z):
    if z in (None,""): return "-"
    s=str(z).strip()
    if s in ("1","Premium","premium"): return "Premium"
    if s in ("-1","Discount","discount"): return "Discount"
    if s in ("0","Mid","mid"): return "Mid"
    return s

def session_decode(sv):
    m={"1":"Asia","2":"London","3":"NY","0":"Other"}
    s=str(sv).strip() if sv is not None else ""
    return m.get(s, sv if sv else "-")

# ========= Safe HTTP =========
def safe_post(url, headers, json_body, timeout=(5, 30)):
    try:
        r = session.post(url, headers=headers, json=json_body, timeout=timeout)
        if r.status_code in (429, 500, 502, 503, 504):
            raise requests.HTTPError(f"{r.status_code}: {r.text[:160]}")
        return True, r.json()
    except Exception as e:
        return False, str(e)

# ========= LLM =========
def ask_xai(prompt: str):
    if not XAI_API_KEY: return False, "تعذّر تحليل xAI (لا يوجد مفتاح)."
    ok, res = safe_post(
        "https://api.x.ai/v1/chat/completions",
        {"Authorization": f"Bearer {XAI_API_KEY}"},
        {"model":"grok-4-0709","messages":[{"role":"user","content":prompt}],"temperature":0.2}
    )
    if not ok: return False, f"تعذّر تحليل xAI ({res})"
    try:
        txt = res["choices"][0]["message"]["content"].strip()
        return True, txt
    except Exception:
        return False, "تعذّر تحليل xAI (استجابة غير متوقعة)."

def ask_openai(prompt: str):
    if not OPENAI_API_KEY: return False, "تعذّر تحليل OpenAI (لا يوجد مفتاح)."
    ok, res = safe_post(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {OPENAI_API_KEY}"},
        {"model":"gpt-4o-mini","messages":[{"role":"user","content":prompt}],"temperature":0.2}
    )
    if not ok: return False, f"تعذّر تحليل OpenAI ({res})"
    try:
        txt = res["choices"][0]["message"]["content"].strip()
        return True, txt
    except Exception:
        return False, "تعذّر تحليل OpenAI (استجابة غير متوقعة)."

# ========= Extraction & Guards =========
def extract_fields(text: str):
    t=e=tp=sl=rsn=None
    for line in text.splitlines():
        low=line.strip().lower()
        if low.startswith(("trade:","type:","صفقة:","الصفقة:")):
            v=line.split(":",1)[-1].strip().lower()
            if "buy" in v or "شراء" in v: t="buy"
            elif "sell" in v or "بيع" in v: t="sell"
        elif low.startswith(("entry:","الدخول:","enter:")):       e=line.split(":",1)[-1].strip()
        elif low.startswith(("take profit:","tp:","جني","الهدف")): tp=line.split(":",1)[-1].strip()
        elif low.startswith(("stop loss:","sl:","ستوب","وقف")):    sl=line.split(":",1)[-1].strip()
        elif low.startswith(("reason:","سبب","السبب")):            rsn=line.split(":",1)[-1].strip()
    return t,e,tp,sl,rsn

def fallback_targets(direction: str, close: Optional[float], atr: Optional[float]):
    if close is None or atr is None or atr <= 0:
        return "-", "-"
    if direction=="buy":
        tp = close + 1.5*atr; sl = close - 0.8*atr
    else:
        tp = close - 1.5*atr; sl = close + 0.8*atr
    return f"{tp:.3f}", f"{sl:.3f}"

def mitigation_guard(extras: dict, direction: str, close: Optional[float], atr: Optional[float]) -> Tuple[bool, str]:
    """تأجيل/منع الصفقة لوجود CSD معاكس أو FVG غير مختبرة قريبة."""
    atr_v = atr if (atr is not None and atr > 0) else None
    near_mult = 0.6  # 60% من ATR

    csd_up = (extras.get("CSD_UP") or 0) == 1.0
    csd_dn = (extras.get("CSD_DN") or 0) == 1.0
    if direction == "buy" and csd_dn:
        return False, "CSD هبوطي ظاهر—تأجيل الشراء."
    if direction == "sell" and csd_up:
        return False, "CSD صعودي ظاهر—تأجيل البيع."

    if close is None:
        return True, ""

    bear_ce = extras.get("BEAR_FVG_CE")
    bull_ce = extras.get("BULL_FVG_CE")
    dist_bear = extras.get("DIST_BEAR_CE")
    dist_bull = extras.get("DIST_BULL_CE")

    if direction == "buy" and bear_ce is not None:
        if close < bear_ce and (atr_v is None or (dist_bear is not None and dist_bear <= near_mult*atr_v)):
            return False, f"انتظار ميتيجيشن BEAR FVG عند CE≈{bear_ce:.3f}."
    if direction == "sell" and bull_ce is not None:
        if close > bull_ce and (atr_v is None or (dist_bull is not None and dist_bull <= near_mult*atr_v)):
            return False, f"انتظار ميتيجيشن BULL FVG عند CE≈{bull_ce:.3f}."
    return True, ""

def consensus(xai_ok,xai_txt,oai_ok,oai_txt, close, atr, extras):
    fields=[]
    if xai_ok:
        t,e,tp,sl,rsn = extract_fields(xai_txt);  fields.append(("xai",t,e,tp,sl,rsn))
    if oai_ok:
        t,e,tp,sl,rsn = extract_fields(oai_txt);  fields.append(("openai",t,e,tp,sl,rsn))
    fields = [f for f in fields if f[1] in ("buy","sell")]

    if not fields:
        return "⚠️ لا توجد توصية واضحة."

    if len(fields)==1:
        src,t,e,tp,sl,rsn = fields[0]
        allowed, note = mitigation_guard(extras, t, close, atr)
        if not allowed:
            return f"⚠️ لا صفقة: {note}"
        if not (tp and sl):
            tp,sl = fallback_targets(t, close, atr)
        if not e: e = "-" if close is None else f"{close:.3f}"
        direction = "شراء" if t=="buy" else "بيع"
        return (f"🚦 <b>التوصية النهائية (مصدر واحد 95%)</b>\n"
                f"الصفقة: <b>{direction}</b>\nالدخول: <b>{e}</b>\n"
                f"الهدف: <b>{tp}</b>\nالستوب: <b>{sl}</b>")

    # مصدران
    t1=fields[0][1]; t2=fields[1][1]
    if t1==t2:
        t=t1
        allowed, note = mitigation_guard(extras, t, close, atr)
        if not allowed:
            return f"⚠️ لا صفقة: {note}"
        for _,tt,e,tp,sl,rsn in fields:
            if tt==t and e and tp and sl:
                direction = "شراء" if t=="buy" else "بيع"
                return (f"🚦 <b>التوصية النهائية (توافق 100%)</b>\n"
                        f"الصفقة: <b>{direction}</b>\nالدخول: <b>{e}</b>\n"
                        f"الهدف: <b>{tp}</b>\nالستوب: <b>{sl}</b>")
        e = fields[0][2] or fields[1][2] or (f"{close:.3f}" if close is not None else "-")
        tp,sl = fallback_targets(t, close, atr)
        direction = "شراء" if t=="buy" else "بيع"
        return (f"🚦 <b>التوصية النهائية (توافق 100%)</b>\n"
                f"الصفقة: <b>{direction}</b>\nالدخول: <b>{e}</b>\nالهدف: <b>{tp}</b>\nالستوب: <b>{sl}</b>")
    else:
        return "⚠️ تعارض بين xAI و OpenAI — لا صفقة مؤكدة."

# ========= Prompt =========
def build_prompt(sym, tf, o,h,l,c,v, ex):
    zone = zone_decode(ex.get("ZONE"))
    sess = session_decode(ex.get("SESSION"))
    piv  = compute_sr(h,l,c)
    PP = ex.get("PP") if ex.get("PP") is not None else piv["PP"]
    R1 = ex.get("R1") if ex.get("R1") is not None else piv["R1"]
    S1 = ex.get("S1") if ex.get("S1") is not None else piv["S1"]
    return f"""
Analyze {sym} on {tf} using ICT/SMC (Liquidity, BOS, CHOCH, FVG, OB) and classic TA (EMA/RSI/MACD).
STRICT FORMAT:
Trade: Buy or Sell
Entry: <number>
Take Profit: <number>
Stop Loss: <number>
Reason: <one line>
Data:
O={o} H={h} L={l} C={c} V={v}
PDH={ex.get('PDH')} PDL={ex.get('PDL')} PDC={ex.get('PDC')} | PWH={ex.get('PWH')} PWL={ex.get('PWL')} PWC={ex.get('PWC')}
PP={PP} R1={R1} S1={S1} | ATR14={ex.get('ATR14')} TR={ex.get('TR')}
RangeMid={ex.get('RANGE_MID')} Zone={zone} Session={sess}
Flags: BOS_UP={ex.get('BOS_UP')} BOS_DN={ex.get('BOS_DN')} CHOCH={ex.get('CHOCH')} SWEEP_PDH={ex.get('SWEEP_PDH')} SWEEP_PDL={ex.get('SWEEP_PDL')}
Constraint: confidence >= 95% and pullback <= 30 pips.
""".strip()

# ========= Background processing =========
def process_alert(n):
    try:
        sym, tf, bt = n["symbol"], n["tf"], n["bar_time"]
        o,h,l,c,v, ex = n["open"], n["high"], n["low"], n["close"], n["volume"], n["extras"]

        piv = compute_sr(h,l,c)
        PP = ex.get("PP") if ex.get("PP") is not None else piv["PP"]
        R1 = ex.get("R1") if ex.get("R1") is not None else piv["R1"]
        S1 = ex.get("S1") if ex.get("S1") is not None else piv["S1"]
        zone = zone_decode(ex.get("ZONE"))
        sess = session_decode(ex.get("SESSION"))

        sr_block = (f"📍 <b>مستويات الدعم والمقاومة</b>\n"
                    f"🟢 S1: {fmt_price(S1)}   🔴 R1: {fmt_price(R1)}\n"
                    f"⚖️ PP: {fmt_price(PP)}   •  Zone: {zone}  •  Session: {sess}\n")

        prompt = build_prompt(sym, tf, o,h,l,c,v, ex)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as exx:
            fx = exx.submit(ask_xai, prompt)
            fo = exx.submit(ask_openai, prompt)
            xai_ok, xai_raw = fx.result(timeout=35)
            oai_ok, oai_raw = fo.result(timeout=35)

        def clean_err(s: str) -> str:
            return re.sub(r"https?://\S+", "", s or "")

        # تهريب وحفظ المصدر
        if xai_ok:
            xai_txt = f"📡 <b>تحليل xAI</b>\n<pre>{esc(xai_raw)}</pre>"
        else:
            xai_txt = f"📡 <b>تحليل xAI</b>\n<pre>{esc(clean_err(xai_raw))}</pre>"

        if oai_ok:
            oai_txt = f"🤖 <b>تحليل OpenAI</b>\n<pre>{esc(oai_raw)}</pre>"
        else:
            oai_txt = f"🤖 <b>تحليل OpenAI</b>\n<pre>{esc(clean_err(oai_raw))}</pre>"

        final = consensus(xai_ok, xai_raw, oai_ok, oai_raw, c, ex.get("ATR14"), ex)

        header = f"🪙 <b>{esc(sym)}</b> — <b>{esc(tf)}</b>\n🕒 {bt.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        msg = f"{header}{sr_block}\n{xai_txt}\n\n{oai_txt}\n\n{final}"
        tg(msg)
    except Exception as e:
        log.exception("process_alert error")
        tg(f"❌ <b>خطأ</b>\n{esc(str(e))}")

# ========= Routes =========
@limiter.limit("120 per hour; 30 per minute")
@app.post("/webhook")
def webhook():
    try:
        p = parse_payload()
        n = normalize(p)

        sym, tf, bt = n["symbol"], n["tf"], n["bar_time"]
        if not sym or tf not in ALLOWED_TF:
            return jsonify({"status":"ignored"}), 200

        # منع تكرار نفس الشمعة
        key = f"{sym}|{tf}|{bt.isoformat()}"
        if key in _last_sent_keys:
            return jsonify({"status":"dup"}), 200
        _last_sent_keys.add(key)

        # ✅ التحليل بالخلفية – رد فوري
        threading.Thread(target=process_alert, args=(n,), daemon=True).start()
        return jsonify({"status":"queued"}), 200

    except Exception as e:
        log.exception("Webhook error")
        tg(f"❌ <b>خطأ</b>\n{esc(str(e))}")
        return jsonify({"status":"ok","handled_error":str(e)}), 200

@app.get("/")
def root():
    return jsonify({"ok":True,"service":"consensus-sr","ts":datetime.now(timezone.utc).isoformat()}),200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

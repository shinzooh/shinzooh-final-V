# -*- coding: utf-8 -*-
import os, re, json, traceback, concurrent.futures
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
import requests
from flask import Flask, request, jsonify

# ===== ENV =====
XAI_API_KEY        = os.getenv("XAI_API_KEY", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

ALLOWED_TF = {"5","15","30","1H","4H","1D"}  # فقط هذي

app = Flask(__name__)

# ===== Telegram =====
def tg(msg: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID): return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=15
        )
    except Exception as e:
        print("Telegram error:", e)

# ===== Parsing =====
def parse_payload() -> Dict[str, str]:
    raw = request.get_data(as_text=True) or ""
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    out = {}
    for part in re.split(r"[,\n]+", raw.strip()):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out

# ===== Helpers =====
def _to_float(x) -> Optional[float]:
    try:
        return float(str(x).replace(",", ""))
    except:
        return None

def _parse_time_any(x) -> Optional[datetime]:
    if x is None: return None
    s = str(x).strip()
    if s.isdigit():
        t = int(s)
        if t > 1_000_000_000_000: t //= 1000
        return datetime.fromtimestamp(t, tz=timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00"))
    except:
        return None

def normalize_tf(tf_raw: str) -> str:
    tf_raw = (tf_raw or "").strip()
    if tf_raw.isdigit():
        n = int(tf_raw)
        if n < 5: n = 5              # إصلاح 1 -> 5
        return {"5":"5","15":"15","30":"30","60":"1H","240":"4H"}.get(str(n), str(n))
    return {"D":"1D","1D":"1D","4H":"4H","1H":"1H","15":"15","30":"30","5":"5"}.get(tf_raw, tf_raw)

def normalize(payload: Dict[str, str]) -> Dict[str, object]:
    sym  = (payload.get("SYMB") or payload.get("symbol") or "").upper()
    tf   = normalize_tf(payload.get("TF") or payload.get("interval") or "")
    o = _to_float(payload.get("OPEN") or payload.get("O"))
    h = _to_float(payload.get("HIGH") or payload.get("H"))
    l = _to_float(payload.get("LOW")  or payload.get("L"))
    c = _to_float(payload.get("CLOSE")or payload.get("C"))
    v = _to_float(payload.get("VOLUME")or payload.get("V"))
    bt = _parse_time_any(payload.get("BAR_TIME") or payload.get("time") or payload.get("BAR") or payload.get("NOW")) or datetime.now(timezone.utc)

    # اختياري: قيم إضافية من Pine (لو وصلت)
    extras = {
        "PDH": _to_float(payload.get("PDH")), "PDL": _to_float(payload.get("PDL")), "PDC": _to_float(payload.get("PDC")),
        "PWH": _to_float(payload.get("PWH")), "PWL": _to_float(payload.get("PWL")), "PWC": _to_float(payload.get("PWC")),
        "PP": _to_float(payload.get("PP")), "R1": _to_float(payload.get("R1")), "S1": _to_float(payload.get("S1")),
        "ATR14": _to_float(payload.get("ATR14")), "TR": _to_float(payload.get("TR")),
        "RANGE_MID": _to_float(payload.get("RANGE_MID")),
        "ZONE": payload.get("ZONE"),
        "SESSION": payload.get("SESSION"),
        "BOS_UP": _to_float(payload.get("BOS_UP")),
        "BOS_DN": _to_float(payload.get("BOS_DN")),
        "CHOCH": _to_float(payload.get("CHOCH")),
        "SWEEP_PDH": _to_float(payload.get("SWEEP_PDH")),
        "SWEEP_PDL": _to_float(payload.get("SWEEP_PDL")),
        "BODY_PCT": _to_float(payload.get("BODY_PCT")),
        "WICK_TOP_PCT": _to_float(payload.get("WICK_TOP_PCT")),
        "WICK_BOT_PCT": _to_float(payload.get("WICK_BOT_PCT")),
    }
    return {"symbol": sym, "tf": tf, "open": o, "high": h, "low": l, "close": c, "volume": v, "bar_time": bt, "extras": extras}

# ===== Local S/R (fallback لو ما وصل من Pine) =====
def compute_sr(o,h,l,c):
    if any(v is None for v in (h,l,c)):  # نحتاج HLC
        return {"PP":None,"R1":None,"S1":None}
    pp  = (h + l + c) / 3.0
    r1  = 2*pp - l
    s1  = 2*pp - h
    return {"PP":pp,"R1":r1,"S1":s1}

def fmt_price(x): return "-" if x is None else f"{x:.3f}"

def zone_decode(z):
    if z in (None,""): return "-"
    s = str(z).strip()
    if s in ("1","Premium","premium"): return "Premium"
    if s in ("-1","Discount","discount"): return "Discount"
    if s in ("0","Mid","mid"): return "Mid"
    return s

def session_decode(sv):
    m = {"1":"Asia","2":"London","3":"NY","0":"Other"}
    s = str(sv).strip() if sv is not None else ""
    return m.get(s, sv if sv else "-")

# ===== LLM Calls =====
def ask_xai(prompt: str) -> str:
    if not XAI_API_KEY: return "📡 <b>تحليل xAI</b>\n(لا يوجد مفتاح XAI)"
    try:
        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            json={"model":"grok-4-0709","messages":[{"role":"user","content":prompt}],"temperature":0.2},
            timeout=25
        )
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"].strip()
        return f"📡 <b>تحليل xAI</b>\n{txt}"
    except Exception as e:
        return f"📡 <b>تحليل xAI</b>\nخطأ: {e}"

def ask_openai(prompt: str) -> str:
    if not OPENAI_API_KEY: return "🤖 <b>تحليل OpenAI</b>\n(لا يوجد مفتاح OpenAI)"
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model":"gpt-4o-mini","messages":[{"role":"user","content":prompt}],"temperature":0.2},
            timeout=25
        )
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"].strip()
        return f"🤖 <b>تحليل OpenAI</b>\n{txt}"
    except Exception as e:
        return f"🤖 <b>تحليل OpenAI</b>\nخطأ: {e}"

# ===== Extract & Consensus =====
def extract_fields(text: str) -> Tuple[Optional[str],Optional[str],Optional[str],Optional[str],Optional[str]]:
    t=e=tp=sl=rsn=None
    for line in text.splitlines():
        low=line.strip().lower()
        if low.startswith(("trade:","type:","صفقة:","الصفقة:")):
            val=line.split(":",1)[-1].strip().lower()
            if "buy" in val or "شراء" in val: t="buy"
            elif "sell" in val or "بيع" in val: t="sell"
        elif low.startswith(("entry:","الدخول:","enter:")):       e=line.split(":",1)[-1].strip()
        elif low.startswith(("take profit:","tp:","جني","الهدف")): tp=line.split(":",1)[-1].strip()
        elif low.startswith(("stop loss:","sl:","ستوب","وقف")):    sl=line.split(":",1)[-1].strip()
        elif low.startswith(("reason:","سبب","السبب")):            rsn=line.split(":",1)[-1].strip()
    return t,e,tp,sl,rsn

def fallback_targets(direction: str, close: Optional[float], atr: Optional[float]) -> Tuple[str,str]:
    # لو ناقص TP/SL نستخدم ATR: TP≈1.5*ATR, SL≈0.8*ATR
    if close is None or atr is None or atr <= 0:
        return ("-", "-")
    if direction=="buy":
        tp = close + 1.5*atr
        sl = close - 0.8*atr
    else:
        tp = close - 1.5*atr
        sl = close + 0.8*atr
    return (f"{tp:.3f}", f"{sl:.3f}")

def consensus_block(xai_txt: str, oai_txt: str, close: Optional[float], atr: Optional[float]) -> str:
    t1,e1,tp1,sl1,r1 = extract_fields(xai_txt)
    t2,e2,tp2,sl2,r2 = extract_fields(oai_txt)
    types=[t for t in (t1,t2) if t in ("buy","sell")]
    if not types:
        return "⚠️ لا توجد توصية واضحة."

    buy_pct=(types.count("buy")/len(types))*100.0
    if buy_pct >= 95:
        direction="شراء"; dir_en="buy"; conf=buy_pct
        e,tp,sl,rsn= (e1,tp1,sl1,r1) if t1=="buy" else (e2,tp2,sl2,r2)
    elif (100-buy_pct) >= 95:
        direction="بيع"; dir_en="sell"; conf=100-buy_pct
        e,tp,sl,rsn= (e1,tp1,sl1,r1) if t1=="sell" else (e2,tp2,sl2,r2)
    else:
        return f"⚠️ تعارض بين xAI و OpenAI ({buy_pct:.1f}% شراء) — لا صفقة مؤكدة."

    # Fallback للأهداف/الستوب
    if not tp or not sl:
        tp, sl = fallback_targets(dir_en, close, atr)

    if not e:  # لو ما في Entry، خذ الإغلاق الحالي كدخول تقريبي
        e = "-" if close is None else f"{close:.3f}"

    return (
        f"🚦 <b>التوصية النهائية (توافق {conf:.1f}%)</b>\n"
        f"الصفقة: <b>{direction}</b>\n"
        f"الدخول: <b>{e}</b>\n"
        f"الهدف: <b>{tp}</b>\n"
        f"الستوب: <b>{sl}</b>\n"
        f"السبب: {rsn or 'Confluence ICT/SMC + Classic & HTF context'}"
    )

# ===== Prompt =====
def build_prompt(sym: str, tf: str, o,h,l,c,v, ex: Dict[str,object]) -> str:
    zone = zone_decode(ex.get("ZONE"))
    sess = session_decode(ex.get("SESSION"))
    pivPP = ex.get("PP"); pivR1=ex.get("R1"); pivS1=ex.get("S1")
    # لو ما وصل من Pine، احسب محلياً
    if pivPP is None or pivR1 is None or pivS1 is None:
        sr_local = compute_sr(o,h,l,c)
        pivPP = pivPP if pivPP is not None else sr_local["PP"]
        pivR1 = pivR1 if pivR1 is not None else sr_local["R1"]
        pivS1 = pivS1 if pivS1 is not None else sr_local["S1"]

    base = f"""
Analyze {sym} on {tf} using ICT/SMC (Liquidity, BOS, CHoCH, FVG, OB, Premium/Discount) and classic TA (EMA/RSI/MACD).
STRICT OUTPUT FORMAT:
Trade: Buy or Sell
Entry: <number>
Take Profit: <number>
Stop Loss: <number>
Reason: <one line>

Data:
OHLCV: O={o} H={h} L={l} C={c} V={v}
HTF: PDH={ex.get('PDH')} PDL={ex.get('PDL')} PDC={ex.get('PDC')} | PWH={ex.get('PWH')} PWL={ex.get('PWL')} PWC={ex.get('PWC')}
Pivots: PP={pivPP} R1={pivR1} S1={pivS1}
ATR14={ex.get('ATR14')} TR={ex.get('TR')}
RangeMid={ex.get('RANGE_MID')} Zone={zone} Session={sess}
Struct: BOS_UP={ex.get('BOS_UP')} BOS_DN={ex.get('BOS_DN')} CHOCH={ex.get('CHOCH')}
Sweeps: PDH={ex.get('SWEEP_PDH')} PDL={ex.get('SWEEP_PDL')}
Candle: BODY%={ex.get('BODY_PCT')} WICK_TOP%={ex.get('WICK_TOP_PCT')} WICK_BOT%={ex.get('WICK_BOT_PCT')}
Constraints: confidence >= 95% and pullback <= 30 pips.
"""
    return base.strip()

# ===== Routes =====
@app.post("/webhook")
def webhook():
    try:
        p = parse_payload()
        n = normalize(p)

        sym, tf = n["symbol"], n["tf"]
        if not sym or tf not in ALLOWED_TF:
            return jsonify({"status":"ignored","reason":"bad TF/symbol"}), 200

        o,h,l,c,v = n["open"], n["high"], n["low"], n["close"], n["volume"]
        ex = n["extras"]  # قد تكون None لبعض القيم – ما في مشكلة
        atr = ex.get("ATR14")

        # بلوك S/R ملون
        sr_loc = compute_sr(o,h,l,c)
        S1 = ex.get("S1") if ex.get("S1") is not None else sr_loc["S1"]
        R1 = ex.get("R1") if ex.get("R1") is not None else sr_loc["R1"]
        PP = ex.get("PP") if ex.get("PP") is not None else sr_loc["PP"]
        zone = zone_decode(ex.get("ZONE"))
        sess = session_decode(ex.get("SESSION"))

        sr_block = (
            f"📍 مستويات الدعم والمقاومة\n"
            f"🟢 S1: {fmt_price(S1)}    🔴 R1: {fmt_price(R1)}\n"
            f"⚖️ PP: {fmt_price(PP)}   •  Zone: {zone}  •  Session: {sess}\n"
        )

        prompt = build_prompt(sym, tf, o,h,l,c,v, ex)

        # شغّل النموذجين بالتوازي
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as exx:
            fx = exx.submit(ask_xai, prompt)
            fo = exx.submit(ask_openai, prompt)
            xai_txt = fx.result(timeout=30)
            oai_txt = fo.result(timeout=30)

        final_rec = consensus_block(xai_txt, oai_txt, c, atr)

        header = f"📊 <b>{sym} — {tf}</b>\n🕒 {(n['bar_time']).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        body = f"{sr_block}\n{xai_txt}\n\n{oai_txt}\n\n{final_rec}"
        tg(header + body)
        return jsonify({"status":"ok"}), 200

    except Exception as e:
        traceback.print_exc()
        tg(f"❌ <b>خطأ</b>\n{e}")
        return jsonify({"status":"ok","handled_error":str(e)}), 200  # نرجّع 200 حتى لا يعيد TV الإرسال

@app.get("/")
def root():
    return jsonify({"ok":True,"service":"consensus-sr","ts":datetime.now(timezone.utc).isoformat()}),200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

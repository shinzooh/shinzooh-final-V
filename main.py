# -*- coding: utf-8 -*-
import os, traceback, concurrent.futures, json, re
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from flask import Flask, request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ========= Env =========
XAI_API_KEY        = os.getenv("XAI_API_KEY", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

MODEL_XAI  = os.getenv("XAI_MODEL", "grok-4-0709")
MODEL_OAI  = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
REQ_TIMEOUT = int(os.getenv("REQ_TIMEOUT", "20"))
ANALYSIS_OVERALL_TIMEOUT = int(os.getenv("ANALYSIS_OVERALL_TIMEOUT", "22"))

# ✅ الفريمات المسموحة فقط
ALLOWED_TF = {"5", "15", "30", "1H", "4H", "1D"}

# ========= HTTP session with retries =========
def make_session():
    s = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.5,
        status_forcelist=[429,500,502,503,504],
        allowed_methods=frozenset(["GET","POST"])
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    return s

SESSION = make_session()

# ========= App =========
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_prefix=1)

# ========= Helpers =========
def _to_float(x) -> Optional[float]:
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None

def _parse_time_any(x):
    if x is None: return None
    s = str(x)
    if s.isdigit():  # unix (s/ms)
        t = int(s)
        if t > 1_000_000_000_000:
            t //= 1000
        return datetime.fromtimestamp(t, tz=timezone.utc)
    try:
        s2 = s.replace("Z","+00:00")
        return datetime.fromisoformat(s2)
    except Exception:
        return None

def parse_kv_raw(raw: str) -> dict:
    """يقرا فورمات key=value للفصل الاحتياطي"""
    if not raw or raw.strip().startswith("{"):
        return {}
    items = re.split(r"[,\n]+", raw.strip())
    out = {}
    for it in items:
        if "=" in it:
            k, v = it.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def normalize_tv(payload: Dict[str,Any]) -> Dict[str,Any]:
    symb = str(payload.get("SYMB") or payload.get("symbol","")).strip()
    exch = str(payload.get("EXCHANGE") or payload.get("exchange","")).strip()
    tf_raw = str(payload.get("TF") or payload.get("tf","")).strip()

    tf_map = {
        "5": "5",
        "15": "15",
        "30": "30",
        "60": "1H", "1H": "1H",
        "240": "4H", "4H": "4H",
        "D": "1D", "1D": "1D"
    }
    tf = tf_map.get(tf_raw, tf_raw)
    if tf not in ALLOWED_TF:
        raise ValueError(f"Unsupported TF: {tf or 'EMPTY'}")

    def pick(*keys):
        for k in keys:
            if k in payload and payload[k] not in (None,""):
                return payload[k]
        return None

    o = _to_float(pick("OPEN","O","Open"))
    h = _to_float(pick("HIGH","H","High"))
    l = _to_float(pick("LOW","L","Low"))
    c = _to_float(pick("CLOSE","C","Close"))
    v = _to_float(pick("VOLUME","V","Volume"))

    bt = _parse_time_any(pick("BAR_TIME","time"))
    nowt = _parse_time_any(pick("NOW","now")) or datetime.now(timezone.utc)

    if not symb:
        raise ValueError("Missing SYMB")
    if not all([o,h,l,c,bt]):
        raise ValueError("Missing or bad OHLC/BAR_TIME from TradingView")

    return {
        "symbol": symb, "exchange": exch, "tf": tf,
        "open": o, "high": h, "low": l, "close": c, "volume": v,
        "bar_time": bt, "now_time": nowt,
        "image_url": payload.get("image_url") or payload.get("IMAGE_URL")
    }

def is_stale(nrm: Dict[str,Any], tolerance_sec=600) -> bool:
    return abs((nrm["now_time"] - nrm["bar_time"]).total_seconds()) > tolerance_sec

def build_prompts(n: Dict[str,Any]):
    p_ar = (
        f"حلّل {n['symbol']} ({n.get('exchange','')}) فريم {n['tf']} بأسلوب ICT/SMC:"
        f" Liquidity/BOS/CHoCH/FVG/OB + كلاسيكي RSI/EMA/MACD.\n"
        f"استخدم قيم TradingView حرفيًا: "
        f"OPEN={n['open']}, HIGH={n['high']}, LOW={n['low']}, CLOSE={n['close']}, VOLUME={n['volume']}.\n"
        "أعطني توصية نهائية بهذا التنسيق:\n"
        "- الصفقة: شراء/بيع\n- الدخول: رقم واحد\n- جني الأرباح: رقم واحد\n- وقف الخسارة: رقم واحد\n"
        "- السبب: سطر واحد واضح\n"
        "شرط: الانعكاس ≤ 30 نقطة ودقّة ≥ 90%."
    )
    p_en = (
        f"Analyze {n['symbol']} ({n.get('exchange','')}) on {n['tf']} using ICT/SMC "
        f"(Liquidity, BOS, CHoCH, FVG, OB) + RSI/EMA/MACD.\n"
        f"Use TradingView values exactly: "
        f"OPEN={n['open']}, HIGH={n['high']}, LOW={n['low']}, CLOSE={n['close']}, VOLUME={n['volume']}.\n"
        "Return FINAL signal format:\n"
        "- Trade: Buy/Sell\n- Entry: number\n- Take Profit: number\n- Stop Loss: number\n- Reason: one line\n"
        "Constraint: max pullback ≤ 30 pips, confidence ≥ 90%."
    )
    return p_ar, p_en

# ========= LLM clients =========
def ask_xai(prompt: str) -> str:
    if not XAI_API_KEY: raise RuntimeError("XAI_API_KEY missing")
    r = SESSION.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {XAI_API_KEY}"},
        json={"model": MODEL_XAI, "messages":[{"role":"user","content":prompt}], "temperature":0.2},
        timeout=REQ_TIMEOUT
    ); r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def ask_openai(prompt: str) -> str:
    if not OPENAI_API_KEY: raise RuntimeError("OPENAI_API_KEY missing")
    r = SESSION.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={"model": MODEL_OAI, "messages":[{"role":"user","content":prompt}], "temperature":0.2},
        timeout=REQ_TIMEOUT
    ); r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

PROMPT_SUFFIX_JSON_AR = (
    '\n\nأخرج النتيجة بصيغة JSON فقط بدون أي نص زائد بهذا الشكل الدقيق:'
    ' {"trade":"buy|sell","entry":1234.56,"tp":1234.56,"sl":1234.56,"reason":"text"}'
)
PROMPT_SUFFIX_JSON_EN = (
    '\n\nReturn ONLY valid JSON with no extra text:'
    ' {"trade":"buy|sell","entry":1234.56,"tp":1234.56,"sl":1234.56,"reason":"text"}'
)

def analyze_with_fallback_json(p_ar: str, p_en: str):
    candidates = [
        ("xAI", p_ar + PROMPT_SUFFIX_JSON_AR),
        ("xAI", p_en + PROMPT_SUFFIX_JSON_EN),
        ("OpenAI", p_ar + PROMPT_SUFFIX_JSON_AR),
        ("OpenAI", p_en + PROMPT_SUFFIX_JSON_EN),
    ]
    call = {"xAI": ask_xai, "OpenAI": ask_openai}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(call[src], prmpt):(src, prmpt) for src, prmpt in candidates}
        for fut in concurrent.futures.as_completed(futs, timeout=ANALYSIS_OVERALL_TIMEOUT):
            src, _ = futs[fut]
            try:
                txt = fut.result().strip().strip("`")
                data = json.loads(txt)
                if {"trade","entry","tp","sl","reason"} <= set(data.keys()):
                    t = str(data["trade"]).lower()
                    if t in ("buy","sell"):
                        return ({
                            "trade": "شراء" if t == "buy" else "بيع",
                            "entry": float(data["entry"]),
                            "tp": float(data["tp"]),
                            "sl": float(data["sl"]),
                            "reason": str(data["reason"])[:250]
                        }, src)
            except Exception:
                continue

    return ({
        "trade": "—",
        "entry": 0.0,
        "tp": 0.0,
        "sl": 0.0,
        "reason": "لا توجد توصية مؤكدة الآن (انتهت المهلة أو فشل التحليل)."
    }, "Fallback")

# ========= Telegram =========
def tg_send_message(html_text: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID): return
    try:
        SESSION.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": html_text, "parse_mode":"HTML"},
            timeout=10
        )
    except Exception as e:
        print("Telegram send error:", e)

def tg_send_photo(photo_url: str, caption_html: str = ""):
    if not photo_url or not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID): return
    try:
        SESSION.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "photo": photo_url, "caption": caption_html, "parse_mode":"HTML"},
            timeout=15
        )
    except Exception as e:
        print("Telegram photo error:", e)

def format_from_json(n: dict, j: dict, source_label: str) -> str:
    badge = {"xAI":"[xAI]", "OpenAI":"[OpenAI]"}.get(source_label, "[Fallback]")
    head = f"{badge} <b>{n['symbol']} {n['tf']}</b>\n"
    oh   = f"TV: O={n['open']} H={n['high']} L={n['low']} C={n['close']}\n\n"
    if j.get("trade") in ("شراء","بيع"):
        body = (
            f"<b>الصفقة:</b> {j['trade']}\n"
            f"<b>الدخول:</b> {j['entry']}\n"
            f"<b>جني الأرباح:</b> {j['tp']}\n"
            f"<b>الستوب:</b> {j['sl']}\n"
            f"<b>السبب:</b> {j['reason']}\n"
        )
    else:
        body = j.get("reason","لا توجد توصية")
    return head + oh + body

def send_error(e: Exception):
    tg_send_message(f"<b>التوصية التجارية (خطأ)</b>\n{str(e)}")

# ========= Routes =========
@app.get("/")
def root():
    return jsonify({"ok": True, "service":"shinzooh-final-v", "ts": datetime.now(timezone.utc).isoformat()})

@app.get("/health")
def health():
    return "ok", 200

@app.post("/webhook")
def webhook():
    raw = request.get_data(as_text=True) or ""
    body = request.get_json(silent=True, force=True) or {}
    if not body:
        body = parse_kv_raw(raw)

    print("RAW:", raw[:500])
    try:
        nrm = normalize_tv(body)
        if is_stale(nrm):
            print("STALE:", nrm["bar_time"], "now:", nrm["now_time"])
            return jsonify({"status":"ok","msg":"stale"}), 200

        p_ar, p_en = build_prompts(nrm)
        result_json, source_label = analyze_with_fallback_json(p_ar, p_en)
        final_msg = format_from_json(nrm, result_json, source_label)
        tg_send_message(final_msg)

        if nrm.get("image_url"):
            tg_send_photo(nrm["image_url"], "<b>Snapshot</b>")

        return jsonify({"status":"ok","msg":"sent", "source": source_label}), 200
    except Exception as e:
        print("ERROR:", e); traceback.print_exc()
        send_error(e)
        return jsonify({"status":"error","msg":str(e)}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","10000")), debug=True)

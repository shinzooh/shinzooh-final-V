# -*- coding: utf-8 -*-
import os, json, re, time, traceback
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ==== ENV ====
XAI_API_KEY        = os.getenv("XAI_API_KEY", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

ALLOWED_TF = {"5","15","30","60","240","1D"}  # عدّل لو تبي

# ==== Utils ====
def tg_send(text: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID): 
        print("[WARN] Telegram env missing; message:", text[:120])
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode":"HTML"},
            timeout=15
        )
    except Exception as e:
        print("[ERR] Telegram:", e)

def parse_kv(raw: str) -> dict:
    # يدعم: SYMB=XAUUSD,TF=5,C=..., أو أسطر متعددة
    out = {}
    for it in re.split(r"[,\n]+", raw.strip()):
        if "=" in it:
            k, v = it.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def get_payload():
    raw = request.get_data(as_text=True) or ""
    body = request.get_json(silent=True, force=True)
    if not body:
        # ممكن تكون الرسالة JSON-مثل لكن بدون أقواس
        if raw.strip().startswith("{") and raw.strip().endswith("}"):
            try:
                body = json.loads(raw)
            except Exception:
                body = parse_kv(raw)
        else:
            body = parse_kv(raw)
    return raw, body

def coerce_float(x, default=None):
    try:
        if x in (None,"","null"): return default
        return float(str(x).replace(",",""))
    except:
        return default

def now_unix():
    return int(time.time())

# ==== Models ====
def ask_xai(prompt: str) -> str:
    if not XAI_API_KEY: return "[xAI] مفتاح API مفقود."
    try:
        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            json={"model":"grok-4-0709","messages":[{"role":"user","content":prompt}], "temperature":0.2},
            timeout=30
        ); r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[xAI] خطأ: {e}"

def ask_openai(prompt: str) -> str:
    if not OPENAI_API_KEY: return "[OpenAI] مفتاح API مفقود."
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model":"gpt-4o-mini","messages":[{"role":"user","content":prompt}], "temperature":0.2},
            timeout=30
        ); r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[OpenAI] خطأ: {e}"

def build_prompt(symbol, tf, o,h,l,c,v,rsi,ma,macd):
    return (
        f"حلّل {symbol} فريم {tf} بأسلوب ICT/SMC (Liquidity/BOS/CHoCH/FVG/OB) + RSI/EMA/MACD.\n"
        f"قيم TradingView (قد تكون ناقصة): O={o} H={h} L={l} C={c} V={v} RSI={rsi} MA={ma} MACD={macd}\n"
        "أعطني النتيجة بصيغة نقاط مختصرة، وأنهِ بسطر توصية نهائية يتضمن: الصفقة (شراء/بيع)، الدخول، الهدف، الستوب."
    )

# ==== Routes ====
@app.get("/")
def root():
    return jsonify({"ok": True, "service": "shinzooh-final-v", "ts": now_unix()}), 200

@app.post("/webhook")
def webhook():
    raw, body = get_payload()
    try:
        # حقول متعددة الأسماء (JSON أو KV)
        sym = body.get("SYMB") or body.get("symbol") or body.get("ticker") or "UNKNOWN"
        tf  = body.get("TF")   or body.get("interval") or "UNKNOWN"

        # توحيد TF الشائعة من TV
        tf_map = {"60":"1H","240":"4H","D":"1D"}
        tf_std = tf_map.get(str(tf), str(tf))

        # فلترة TF غير مرغوبة (بدون تفجير)
        if ALLOWED_TF and tf_std not in ALLOWED_TF:
            print(f"[INFO] Ignore TF {tf_std}")
            return jsonify({"status":"ignored","tf":tf_std}), 200

        # OHLC (قد تكون ناقصة من TV في تنبيهات المؤشرات)
        O = coerce_float(body.get("O") or body.get("OPEN"))
        H = coerce_float(body.get("H") or body.get("HIGH"))
        L = coerce_float(body.get("L") or body.get("LOW"))
        C = coerce_float(body.get("C") or body.get("CLOSE"))
        V = coerce_float(body.get("V") or body.get("VOLUME"))
        RSI  = coerce_float(body.get("RSI"))
        MA   = coerce_float(body.get("MA") or body.get("sma"))
        MACD = coerce_float(body.get("MACD"))

        # BAR_TIME اختياري
        bar_time = body.get("BAR_TIME") or body.get("time") or now_unix()

        # نبني برومبت حتى لو في نقص
        prompt = build_prompt(sym, tf_std, O,H,L,C,V,RSI,MA,MACD)

        # تحليل xAI
        xai_text = ask_xai(prompt)
        if not xai_text.strip():
            xai_text = "[xAI] لا يوجد نص مُستلم."
        tg_send(f"[xAI] {sym} {tf_std}\n{xai_text}")

        # تحليل OpenAI
        oai_text = ask_openai(prompt)
        if not oai_text.strip():
            oai_text = "[OpenAI] لا يوجد نص مُستلم."
        tg_send(f"[OpenAI] {sym} {tf_std}\n{oai_text}")

        return jsonify({"status":"ok","source":["xAI","OpenAI"]}), 200

    except Exception as e:
        print("[ERR] webhook:", e); traceback.print_exc()
        tg_send(f"<b>خطأ في المعالجة</b>\n{str(e)}")
        # حتى لو صار خطأ، نرجّع 200 عشان TV ما يعيد الإرسال بشكل مزعج
        return jsonify({"status":"ok","msg":"handled_error"}), 200

if __name__ == "__main__":
    import socket
    port = int(os.getenv("PORT", "10000"))
    print("Listening on", socket.gethostbyname(socket.gethostname()), port)
    app.run(host="0.0.0.0", port=port)

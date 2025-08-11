import os
import requests
import json
import time
from flask import Flask, request, jsonify

# ====== إعدادات ======
XAI_API_KEY = os.getenv("XAI_API_KEY")  # مفتاح xAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # مفتاح OpenAI (اختياري)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MODEL_SOURCE = os.getenv("MODEL_SOURCE", "xai")  # xai أو openai

app = Flask(__name__)

# ====== إرسال Telegram ======
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

# ====== تحليل بالنموذج ======
def analyze_data(symbol, frame, data_str):
    prefix = "[تحليل xAI]" if MODEL_SOURCE.lower() == "xai" else "[تحليل OpenAI]"
    prompt = f"""{prefix}
حلل {symbol} على فريم {frame} بأسلوب ICT & SMC (سيولة/BOS/CHoCH/FVG/OB/Premium/Discount/شموع)
+ كلاسيكي (EMA/MA/RSI/MACD).
أعطني توصية شراء/بيع مع (دخول/هدف/ستوب) بنسبة نجاح 95%+ وانعكاس لا يتعدى 30 نقطة.
البيانات: {data_str}
"""
    if MODEL_SOURCE.lower() == "xai":
        url = "https://api.x.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "grok-2-latest",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
    else:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        resp = r.json()
        if MODEL_SOURCE.lower() == "xai":
            return resp["choices"][0]["message"]["content"]
        else:
            return resp["choices"][0]["message"]["content"]
    except Exception as e:
        return f"{prefix} خطأ في التحليل: {e}"

# ====== استقبال TradingView ======
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        raw = request.data.decode("utf-8").strip()
        print("RAW:", raw)

        # تحويل البيانات إلى dict
        parts = raw.split(",")
        data = {}
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                data[k.strip()] = v.strip()

        # التحقق من البيانات الأساسية
        required_keys = ["SYMB", "TF", "O", "H", "L", "C"]
        for key in required_keys:
            if key not in data or not data[key]:
                print(f"تحذير: {key} ناقص أو فاضي")
                data[key] = "N/A"

        # تجهيز البيانات للنموذج
        symbol = data.get("SYMB", "N/A")
        frame = data.get("TF", "N/A")
        data_str = json.dumps(data, ensure_ascii=False)

        # تحليل
        analysis = analyze_data(symbol, frame, data_str)

        # إرسال
        send_telegram(analysis)
        return jsonify({"status": "ok", "msg": "تم التحليل"}), 200

    except Exception as e:
        print("Error:", e)
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

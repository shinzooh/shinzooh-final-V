import os
import requests
from flask import Flask, request, jsonify
import time

app = Flask(__name__)

# ============ قراءة من .env ============
MODEL_SOURCE_XAI = os.getenv("MODEL_SOURCE_XAI", "xai")
MODEL_SOURCE_OPENAI = os.getenv("MODEL_SOURCE_OPENAI", "openai")
XAI_API_KEY = os.getenv("XAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ============ دوال الموديلات ============
def analyze_xai(symbol, frame, data_str):
    prompt = f"تحليل {symbol} ({frame}) باستخدام {MODEL_SOURCE_XAI}: ICT/SMC + RSI + EMA + MACD. توصية دخول/هدف/ستوب بدقة 95%."
    headers = {"Authorization": f"Bearer {XAI_API_KEY}"}
    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        json={
            "model": "grok-4-0709",
            "messages": [{"role": "user", "content": prompt + "\nبيانات: " + data_str}],
            "temperature": 0.3
        },
        headers=headers,
        timeout=60
    )
    return "تحليل xAI 📊\n" + resp.json().get("choices", [{}])[0].get("message", {}).get("content", "خطأ في التحليل")

def analyze_openai(symbol, frame, data_str):
    prompt = f"تحليل {symbol} ({frame}) باستخدام {MODEL_SOURCE_OPENAI}: ICT/SMC + RSI + EMA + MACD. توصية دخول/هدف/ستوب بدقة 95%."
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt + "\nبيانات: " + data_str}],
            "temperature": 0.3
        },
        headers=headers,
        timeout=60
    )
    return "تحليل OpenAI 🤖\n" + resp.json().get("choices", [{}])[0].get("message", {}).get("content", "خطأ في التحليل")

# ============ إرسال تليجرام ============
def send_telegram(msg):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    )

# ============ Webhook ============
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        symbol = data.get("SYMB", "Unknown")
        frame = data.get("TF", "Unknown")
        data_str = ",".join(f"{k}={v}" for k, v in data.items())

        # تحليل xAI
        xai_result = analyze_xai(symbol, frame, data_str)
        send_telegram(xai_result)

        # تحليل OpenAI
        openai_result = analyze_openai(symbol, frame, data_str)
        send_telegram(openai_result)

        return jsonify({"status": "ok", "msg": "تحليلات أُرسلت"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# ============ تشغيل ============
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

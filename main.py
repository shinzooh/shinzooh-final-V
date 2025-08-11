import os
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# إعدادات البيئة
XAI_API_KEY = os.getenv("XAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# الفريمات المسموحة فقط
ALLOWED_TF = ["5", "15", "30", "60", "240", "1D"]

# إرسال رسالة تليجرام مع صورة
def send_telegram_message(text, image_url=None):
    if image_url:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": text,
            "photo": image_url,
            "parse_mode": "HTML"
        }
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    else:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    requests.post(url, json=payload)

# تحليل xAI
def get_xai_analysis(symbol, frame, data_str):
    prompt = f"[xAI Analysis]\nحلل {symbol} على {frame} ICT & SMC دقة 95%+: سيولة/BOS/CHoCH/FVG/OB/Premium/Discount/شموع. كلاسيكي: EMA/MA/RSI/MACD (95%+). توصية شراء/بيع: دخول/هدف/ستوب (95%+ نجاح, max 30 نقطة انعكاس). بيانات: {data_str}"
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {XAI_API_KEY}"}
    payload = {
        "model": "grok-2-latest",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0
    }
    r = requests.post(url, headers=headers, json=payload)
    return r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()

# تحليل OpenAI
def get_openai_analysis(symbol, frame, data_str):
    prompt = f"[OpenAI Analysis]\nحلل {symbol} على {frame} بنفس أسلوب xAI مع تفاصيل ICT/SMC + EMA/MA/RSI/MACD وتوصية دقيقة"
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0
    }
    r = requests.post(url, headers=headers, json=payload)
    return r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()

# Webhook استقبال TradingView
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_json()
    symbol = body.get("SYMB")
    tf = body.get("TF")
    data_str = ",".join([f"{k}={v}" for k, v in body.items() if k not in ["SYMB", "TF"]])

    if tf not in ALLOWED_TF:
        return jsonify({"status": "ignored", "reason": "TF not allowed"})

    # رابط snapshot
    snapshot_url = f"https://www.tradingview.com/x/{symbol}_{tf}_snapshot.png"

    # تحليل xAI
    try:
        analysis_xai = get_xai_analysis(symbol, tf, data_str)
        send_telegram_message(analysis_xai, snapshot_url)
    except Exception as e:
        send_telegram_message(f"[xAI Error] {str(e)}")

    # تحليل OpenAI
    try:
        analysis_openai = get_openai_analysis(symbol, tf, data_str)
        send_telegram_message(analysis_openai, snapshot_url)
    except Exception as e:
        send_telegram_message(f"[OpenAI Error] {str(e)}")

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

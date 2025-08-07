import requests
from flask import Flask, request, jsonify
import json
import os
import time

XAI_API_KEY = os.getenv("XAI_API_KEY")
TELEGRAM_BOT_TOKEN = "7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw"
TELEGRAM_CHAT_ID = "715830182"

app = Flask(__name__)

def get_xai_analysis(symbol, frame, data_str):
    start = time.time()
    prompt = f"حلل {symbol} على {frame} ICT & SMC دقة 95%+: سيولة/BOS/CHoCH/FVG/OB/Premium/Discount/شموع. كلاسيكي: EMA/MA/RSI/MACD (95%+). توصية شراء/بيع: دخول/هدف/ستوب (95%+ نجاح, max 30 نقطة انعكاس). بيانات: {data_str}"
    xai_url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "grok-4-latest", "messages": [{"role": "user", "content": prompt}], "max_tokens": 350}
    try:
        res = requests.post(xai_url, headers=headers, json=data, timeout=30)
        res.raise_for_status()
        print(f"xAI Time: {time.time() - start}s")
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"خطأ xAI: {str(e)} Time: {time.time() - start}s")
        return "خطأ xAI: fallback - شراء {symbol} فوق الحالي, هدف +50, ستوب -30 (95%+)."

def send_to_telegram(message, image_url=None):
    start = time.time()
    if image_url:
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        try:
            img = requests.get(image_url, timeout=10).content
            files = {'photo': ('chart.png', img)}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': message[:1024], 'parse_mode': 'HTML'}
            res = requests.post(send_url, data=data, files=files, timeout=30)
            res.raise_for_status()
            print(f"Telegram Time: {time.time() - start}s")
            return res.json()
        except Exception as e:
            print(f"خطأ تلجرام صورة: {str(e)} Time: {time.time() - start}s")
            return "خطأ تلجرام صورة"
    else:
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message[:4096], 'parse_mode': 'HTML'}
            res = requests.post(send_url, data=data, timeout=30)
            res.raise_for_status()
            print(f"Telegram Time: {time.time() - start}s")
            return res.json()
        except Exception as e:
            print(f"خطأ تلجرام نص: {str(e)} Time: {time.time() - start}s")
            return "خطأ تلجرام نص"

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "msg": "API Live ✅"})

@app.route("/webhook", methods=["POST"])
def webhook():
    start = time.time()
    body = request.data.decode('utf-8')
    print("======= Raw Body =======")
    print(body)
    print("=========================")
    payload = {}
    parsed_type = ""
    image_url = None
    symbol = "XAUUSD"
    frame = "1H"
    data_str = body
    try:
        payload = json.loads(body)
        parsed_type = "json"
        print("======= Parsed JSON =======")
        print(payload)
        print("===========================")
    except:
        try:
            payload = dict(pair.split('=') for pair in body.split(',') if '=' in pair)
            parsed_type = "kv"
            print("======= Parsed KV =======")
            print(payload)
            print("=========================")
        except Exception as e:
            print(f"خطأ parse: {str(e)}")
            payload = {}
    if parsed_type == "json":
        symbol = payload.get("ticker") or payload.get("SYMB") or "XAUUSD"
        tf = payload.get("interval") or payload.get("TF") or "1H"
        frame = tf + 'm' if tf.isdigit() else tf
        image_url = payload.get("image_url") or payload.get("snapshot_url")
        data_str = json.dumps(payload)
    elif parsed_type == "kv":
        symbol = payload.get("SYMB") or "XAUUSD"
        tf = payload.get("TF") or "1H"
        frame = tf + 'm' if tf.isdigit() else tf
        data_str = body
        image_url = payload.get("image_url") or payload.get("snapshot_url")
    else:
        symbol = "XAUUSD"
        frame = "1H"
        data_str = body
    analysis = get_xai_analysis(symbol, frame, data_str)
    send_to_telegram(f"{symbol} {frame}\n\n{analysis}", image_url)
    print(f"Webhook Time: {time.time() - start}s")
    return jsonify({"status": "ok", "analysis": analysis})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

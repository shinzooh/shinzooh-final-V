import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from flask import Flask, request, jsonify
import json
import os
import time
from threading import Thread
import hashlib

XAI_API_KEY = os.getenv("XAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # لـ GPT-5
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHART_IMG_API_KEY = os.getenv("CHART_IMG_API_KEY")  # مفتاح chart-img.com

# retry setup
session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount('https://', adapter)

app = Flask(__name__)

last_payloads = {}

# ===== جلب صورة الشارت =====
def get_chart_image(symbol, timeframe):
    try:
        url = "https://api.chart-img.com/v1/tradingview/advanced-chart"
        params = {
            "symbol": symbol,
            "interval": timeframe,
            "width": 1280,
            "height": 720,
            "theme": "dark",
            "token": CHART_IMG_API_KEY
        }
        r = requests.get(url, params=params, timeout=30)
        return r.json().get("url", "")
    except Exception as e:
        print(f"Chart Image Error: {e}")
        return ""

# ===== إرسال مع صورة =====
def send_to_telegram_with_image(message, image_url):
    try:
        session.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message[:4096], "parse_mode": "HTML"},
            timeout=30
        )
        if image_url:
            session.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                json={"chat_id": TELEGRAM_CHAT_ID, "photo": image_url},
                timeout=30
            )
    except Exception as e:
        print(f"Telegram Send Error: {e}")

# ===== GPT-5 main =====
def gpt5_analysis(symbol, timeframe, price_data):
    prompt = f"""
حلل {symbol} على فريم {timeframe} باستخدام SMC و ICT:
- هيكل السوق
- مناطق السيولة
- BOS / CHoCH / FVG / OB
- تحليل كلاسيكي: EMA / RSI / MACD
- تحديد إذا الصفقة سكالب أو سوينغ
البيانات:
{price_data}
"""
    r = session.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={"model": "gpt-5", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 1800}
    )
    return r.json()["choices"][0]["message"]["content"]

# ===== GPT-5 nano =====
def gpt5_recommendation(symbol, timeframe, price_data):
    prompt = f"""
اعطني توصية مباشرة لـ {symbol} على فريم {timeframe}:
- نوع الصفقة (شراء / بيع)
- نقطة الدخول
- الهدف
- وقف الخسارة
- نسبة نجاح 95%+ وانعكاس أقل من 30 نقطة
البيانات:
{price_data}
"""
    r = session.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={"model": "gpt-5-nano", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 1800}
    )
    return r.json()["choices"][0]["message"]["content"]

# ===== xAI Grok =====
def xai_analysis(symbol, timeframe, price_data):
    prompt = f"""
حلل {symbol} على فريم {timeframe} بدقة 95%+:
- SMC/ICT: سيولة، BOS، CHoCH، FVG، OB، Premium/Discount
- كلاسيكي: EMA / RSI / MACD
- توصية نهائية (شراء أو بيع)
البيانات:
{price_data}
"""
    r = session.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {XAI_API_KEY}"},
        json={"model": "grok-4-latest", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 1800}
    )
    return r.json()["choices"][0]["message"]["content"]

@app.route("/webhook", methods=["POST"])
def webhook():
    start = time.time()
    body = request.data.decode('utf-8')
    print("======= Raw Body =======")
    print(body)
    print("=========================")
    try:
        payload = json.loads(body)
        print("======= Parsed JSON =======")
        print(payload)
        print("===========================")
    except:
        try:
            payload = dict(pair.split('=') for pair in body.split(',') if '=' in pair)
            print("======= Parsed KV =======")
            print(payload)
            print("=========================")
        except Exception as e:
            print(f"Parse Error: {str(e)}")
            payload = {}
    symbol = payload.get("SYMB") or payload.get("ticker") or "XAUUSD"
    tf = payload.get("TF") or payload.get("interval") or "1H"
    frame = f"{tf}m" if str(tf).isdigit() else tf
    data_str = json.dumps(payload, ensure_ascii=False)
    payload_hash = hashlib.sha256(body.encode()).hexdigest()
    last = last_payloads.get(symbol, {'hash': '', 'time': 0})
    if payload_hash == last['hash'] and time.time() - last['time'] < 10:
        return jsonify({"status": "ok", "msg": "Duplicate ignored"})
    last_payloads[symbol] = {'hash': payload_hash, 'time': time.time()}
    def process_all():
        chart_url = get_chart_image(symbol, frame)
        analysis = gpt5_analysis(symbol, frame, data_str)
        send_to_telegram_with_image(f"📊 <b>تحليل السوق ({symbol} - {frame})</b>\n{analysis}", chart_url)
        recommendation = gpt5_recommendation(symbol, frame, data_str)
        send_to_telegram_with_image(f"🎯 <b>توصية الصفقة ({symbol} - {frame})</b>\n{recommendation}", chart_url)
        xai_result = xai_analysis(symbol, frame, data_str)
        send_to_telegram_with_image(f"🤖 <b>تحليل xAI ({symbol} - {frame})</b>\n{xai_result}", chart_url)
    Thread(target=process_all).start()
    return jsonify({"status": "ok", "msg": "Processing"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

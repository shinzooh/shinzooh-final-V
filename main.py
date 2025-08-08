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
    prompt = f"""رد بالعربي فقط.
حلل {symbol} على {frame} ICT & SMC دقة 95%+: سيولة/BOS/CHoCH/FVG/OB/Premium/Discount/شموع مع المستويات والأرقام. كلاسيكي: EMA/MA/RSI/MACD (95%+, أرقام دقيقة).
اكتب التحليل الفني كامل ومرتب كنقاط.
---
ثم أكتب في قسم منفصل (بعد ---):
التوصية النهائية فقط: (شراء أو بيع) + نقطة دخول (Entry) + هدف (Take Profit) + ستوب (Stop Loss) مع السبب المختصر.
البيانات: {data_str}
"""
    xai_url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "grok-4-latest", "messages": [{"role": "user", "content": prompt}], "max_tokens": 700}
    try:
        res = requests.post(xai_url, headers=headers, json=data, timeout=30)
        res.raise_for_status()
        result = res.json()["choices"][0]["message"]["content"]
        print(f"xAI Time: {time.time() - start}s")
        print("====== xAI Analysis ======")
        print(result)
        print("==========================")
        # يقسم الرد لو فيه --- وإلا كله
        if '---' in result:
            analysis, recommendation = result.split('---', 1)
        else:
            analysis, recommendation = result, ''
        return analysis.strip(), recommendation.strip()
    except Exception as e:
        print(f"خطأ xAI: {str(e)} Time: {time.time() - start}s")
        fallback = f"⚠️ خطأ xAI: fallback - شراء {symbol} فوق الحالي، هدف +50، ستوب -30 (95%+)."
        return fallback, ""

def send_to_telegram(message, image_url=None):
    start = time.time()
    # التحقق من وجود صورة وارسالها
    if image_url and isinstance(image_url, str) and image_url.startswith('http'):
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        try:
            img = requests.get(image_url, timeout=10).content
            files = {'photo': ('chart.png', img)}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': message[:1024], 'parse_mode': 'HTML'}
            res = requests.post(send_url, data=data, files=files, timeout=30)
            res.raise_for_status()
            print(f"Telegram Photo Time: {time.time() - start}s")
            return res.json()
        except Exception as e:
            print(f"خطأ تلجرام صورة: {str(e)} Time: {time.time() - start}s")
            return "⚠️ خطأ تلجرام صورة"
    else:
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message[:4096], 'parse_mode': 'HTML'}
            res = requests.post(send_url, data=data, timeout=30)
            res.raise_for_status()
            print(f"Telegram Text Time: {time.time() - start}s")
            return res.json()
        except Exception as e:
            print(f"خطأ تلجرام نص: {str(e)} Time: {time.time() - start}s")
            return "⚠️ خطأ تلجرام نص"

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
    # payload extraction
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
    # رمز ديناميكي وفريم ديناميكي
    symbol = payload.get("SYMB") or payload.get("ticker") or "XAUUSD"
    tf = payload.get("TF") or payload.get("interval") or "1H"
    frame = f"{tf}m" if str(tf).isdigit() else tf
    data_str = json.dumps(payload, ensure_ascii=False)
    image_url = (
        payload.get("snapshot_url")
        or payload.get("image_url")
        or payload.get("chart_image_url")
    )
    # توليد عنوان واضح للرسائل
    msg_title = f"📊 <b>{symbol} {frame}</b>\n"
    # تحليل وتقسيم الرد
    analysis, recommendation = get_xai_analysis(symbol, frame, data_str)
    # أرسل التحليل مع صورة snapshot (لو فيه)
    if analysis:
        send_to_telegram(msg_title + analysis, image_url)
    # أرسل التوصية النهائية برسالة منفصلة (أوضح للمتابعة)
    if recommendation:
        send_to_telegram("🚦 <b>توصية التداول</b>\n" + msg_title + recommendation)
    print(f"Webhook Time: {time.time() - start}s")
    return jsonify({"status": "ok", "analysis": analysis, "recommendation": recommendation})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

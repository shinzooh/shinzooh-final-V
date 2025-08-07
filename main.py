import requests
from flask import Flask, request, jsonify
import json
import os  # لقراءة ENV

# إعدادات النظام
XAI_API_KEY = os.getenv("XAI_API_KEY")  # من ENV في Render
TELEGRAM_BOT_TOKEN = "7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw"
TELEGRAM_CHAT_ID = "715830182"

app = Flask(__name__)

def get_xai_analysis(symbol, frame, data_str):
    prompt = (
        f"""حلل {symbol} على فريم {frame} بناءً على ICT & SMC بدقة 95%+: 
- مناطق السيولة، BOS/CHoCH، FVG، OB، Premium/Discount، شموع قوية.
أضف تحليل كلاسيكي: EMA/MA، RSI، MACD (مستويات دقيقة 95%+).
توصية (شراء/بيع): دخول/هدف/ستوب (نجاح 95%+, انعكاس max 30 نقطة).
البيانات: {data_str}"""
    )
    xai_url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "grok-4-latest",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1200
    }
    try:
        res = requests.post(xai_url, headers=headers, json=data, timeout=60)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"خطأ في xAI API: {str(e)}")
        return f"خطأ في xAI API: {str(e)} (تفاصيل: https://x.ai/api)"

def send_to_telegram(message, image_url=None):
    if image_url:
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        try:
            img_content = requests.get(image_url).content
            files = {'photo': ('chart.png', img_content)}
            data = { 'chat_id': TELEGRAM_CHAT_ID, 'caption': message[:1024], 'parse_mode': 'HTML' }
            res = requests.post(send_url, data=data, files=files)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"خطأ في إرسال تلجرام (صورة): {str(e)}")
            return f"خطأ في إرسال تلجرام (صورة): {str(e)}"
    else:
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            data = { 'chat_id': TELEGRAM_CHAT_ID, 'text': message[:4096], 'parse_mode': 'HTML' }
            res = requests.post(send_url, data=data)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"خطأ في إرسال تلجرام (نص): {str(e)}")
            return f"خطأ في إرسال تلجرام (نص): {str(e)}"

@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.data.decode('utf-8')
    print("======= Raw Body from TradingView =======")
    print(body)
    print("=========================================")
    payload = {}
    parsed_type = ""
    image_url = None
    symbol = "XAUUSD"
    frame = "1H"
    data_str = body
    try:
        payload = json.loads(body)
        parsed_type = "json"
        print("======= Parsed Payload (JSON) =======")
        print(payload)
        print("==============================")
    except Exception:
        try:
            payload = dict(pair.split('=') for pair in body.split(',') if '=' in pair)
            parsed_type = "kv"
            print("======= Parsed Payload (key=value) =======")
            print(payload)
            print("==============================")
        except Exception as e:
            print(f"خطأ في parse payload: {str(e)}")
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
    return jsonify({"status": "ok", "analysis": analysis})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

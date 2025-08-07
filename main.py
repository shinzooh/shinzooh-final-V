import requests
from flask import Flask, request, jsonify
import json

# إعدادات النظام
XAI_API_KEY = "xai-USbuWW2tAgzXmLIIJuJ3rRn4JfeSF9rYMrhHzdqsiszUyBx5g8XSa7vtrdXGSxYL0NtYnCRShGhkr31k"
TELEGRAM_BOT_TOKEN = "7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw"
TELEGRAM_CHAT_ID = "715830182"

app = Flask(__name__)

def get_xai_analysis(symbol, frame, image_url):
    prompt = (
        f"""حلل الشارت ({symbol}) على فريم {frame} حسب منهج ICT و SMC بالكامل مع جميع العناصر: 
- مناطق السيولة (Liquidity Pools)
- BOS/CHoCH (Break of Structure/Change of Character)
- Fair Value Gap (FVG)
- Order Blocks (OB)
- Premium/Discount Zones
- شموع قوية أو انفجار سعري (Strong Candles/Price Explosions)
وأرفق تحليل كلاسيكي دقيق يشمل EMA/MA و RSI و MACD (أرقام ومستويات دقيقة بنسبة 95%+)
- أضف توصية نهائية (شراء/بيع) مع نقاط الدخول والهدف ووقف الخسارة بدقة (نجاح 95%+، انعكاس أقصى 30 نقطة)
- وضّح مناطق السكالب أو السوينغ إن وجدت
رابط الشارت: {image_url or 'غير متوفر'}
اعطني كل التفاصيل في تقرير مفصل ومرتب بدقة 95%+."""
    )
    xai_url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "grok-4",
        "messages": [
            {"role": "system", "content": "أنت خبير تحليل فني محترف ICT/SMC بدقة 95%+."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1200
    }
    try:
        res = requests.post(xai_url, headers=headers, json=data, timeout=60)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"خطأ في xAI API: {str(e)}")
        return f"خطأ في xAI API: {str(e)}"

def send_to_telegram(message, image_url=None):
    if image_url:
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        try:
            img_content = requests.get(image_url).content
            files = {'photo': ('chart.png', img_content)}
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'caption': message[:1024],
                'parse_mode': 'HTML'
            }
            res = requests.post(send_url, data=data, files=files)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"خطأ في إرسال تلجرام: {str(e)}")
            return f"خطأ في إرسال تلجرام: {str(e)}"
    else:
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message[:4096],
                'parse_mode': 'HTML'
            }
            res = requests.post(send_url, data=data)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"خطأ في إرسال تلجرام: {str(e)}")
            return f"خطأ في إرسال تلجرام: {str(e)}"

@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.data.decode('utf-8')
    print("======= Raw Body from TradingView =======")
    print(body)
    print("=========================================")
    
    try:
        data = json.loads(body) if body else {}
    except Exception as e:
        print(f"خطأ في parse payload: {str(e)}")
        data = {}
    
    print("======= Parsed Payload =======")
    print(data)
    print("==============================")
    
    symbol = data.get("ticker") or "XAUUSD"
    frame = data.get("interval") or "1H"
    image_url = data.get("image_url") or data.get("snapshot_url")
    
    analysis = get_xai_analysis(symbol, frame, image_url)
    send_to_telegram(f"{symbol} {frame}\n\n{analysis}", image_url)
    return jsonify({"status": "ok", "analysis": analysis})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

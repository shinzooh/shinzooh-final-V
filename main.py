from fastapi import FastAPI, Request
import os, datetime, asyncio, requests, telegram
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

app = FastAPI()

# إعداد البوت
bot = telegram.Bot(token=os.getenv("TELEGRAM_TOKEN"))
chat_id = os.getenv("TELEGRAM_CHAT_ID")

# إعداد مفاتيح الذكاء الاصطناعي
XAI_KEY = os.getenv("XAI_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# إعداد session مع retries
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))

# تحليل xAI (ICT/SMC دقيق جدًا)
async def get_xai_analysis(symbol, frame, data_str):
    prompt = f"""
    تحليل احترافي لرمز {symbol} على فريم {frame} باستخدام ICT & SMC (دقة 10000%): BOS، CHoCH، FVG، OB، السيولة، Premium/Discount. 
    مؤشرات: RSI، EMA، MACD بدقة أرقام واضحة. 
    أعطني التوصية النهائية (شراء/بيع)، مع نقطة الدخول، الهدف، الستوب، سبب التوصية الفني. 
    شرط: لا يتجاوز الانعكاس 30 نقطة. 
    بيانات: {data_str}
    """
    try:
        res = session.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {XAI_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "grok-4-0709",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1200
            },
            timeout=60
        )
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("❌ xAI Error:", str(e))
        return "❌ تحليل xAI غير متاح حاليًا (fallback - راقب السيولة والمؤشرات يدويًا)."

@app.post("/webhook")
async def webhook(request: Request):
    try:
        raw = await request.body()
        data = dict([item.split("=") for item in raw.decode().split(",")])
        symbol = data.get("SYMB")
        tf = data.get("TF")
        price = data.get("C", "N/A")

        # مؤشرات رقمية (مع حماية NaN)
        def safe_float(val):
            try:
                return float(val)
            except:
                return 0

        rsi = safe_float(data.get("RSI"))
        ema = safe_float(data.get("EMA"))
        macd = safe_float(data.get("MACD"))
        bull_fvg = safe_float(data.get("BULL_FVG_CE"))
        bear_fvg = safe_float(data.get("BEAR_FVG_CE"))
        csd_up = int(data.get("CSD_UP", 0))
        csd_dn = int(data.get("CSD_DN", 0))

        # تحليل الاتجاه
        direction = "شراء ✅ (BOS صاعد, CSD↑, MACD>0)" if csd_up > csd_dn and macd > 0 else \
                    "بيع ❌ (CHoCH هابط, CSD↓, MACD<0)" if csd_dn > csd_up and macd < 0 else \
                    "No trade"

        # تحليل xAI
        analysis = await get_xai_analysis(symbol, tf, raw.decode()) if direction != "No trade" else "⏳ لا توجد فرصة مؤكدة الآن."

        # رسالة تليجرام
        msg = f"""📊 تحليل {symbol} | فريم {tf}
السعر الحالي: {price}
📈 الاتجاه المتوقع: {direction}

📌 تحليل ICT & SMC + كلاسيكي:
{analysis}

🔎 RSI: {rsi}
📉 EMA: {ema}
📊 MACD: {macd}
📘 FVG صعودي: {bull_fvg}
📕 FVG هبوطي: {bear_fvg}
🟩 CSD شراء: {csd_up}
🟥 CSD بيع: {csd_dn}

🕒 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        if direction != "No trade":
            await bot.send_message(chat_id=chat_id, text=msg)
        else:
            print("🔸 No trade, skipping...")
        return {"status": "ok"}

    except Exception as e:
        print("❌ ERROR:", e)
        return {"status": "error", "detail": str(e)}

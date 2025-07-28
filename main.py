import os
import logging
from fastapi import FastAPI, Request
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Logging setup
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Get environment variables
XAI_API_KEY = os.getenv("XAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Validate environment variables
if not XAI_API_KEY or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("Missing env vars: XAI_API_KEY or TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    raise ValueError("Missing required env vars")

# Pydantic model for TradingView data
class TradingViewData(BaseModel):
    symbol: str
    frame: str
    data: str

# Root endpoint to confirm API is running
@app.get("/")
async def root():
    return {"message": "Shinzooh API جاهز", "status": "ok"}

# Webhook endpoint to process TradingView data
@app.post("/webhook")
async def webhook(request: Request, data: TradingViewData):
    try:
        logger.debug(f"Received webhook: {data}")

        # 1. تحضير البرومبت لـ xAI
        prompt = f"Analyze the following trading data for {data.symbol} on {data.frame} timeframe: {data.data}. Provide a professional technical analysis and trading recommendation."

        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "grok-4-0709",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0
        }

        # 2. استدعاء xAI API
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=60)
            response.raise_for_status()

        analysis_en = response.json()["choices"][0]["message"]["content"][:4000].strip()
        analysis_en = ''.join(c for c in analysis_en if c.isprintable())
        if not analysis_en:
            analysis_en = "No analysis available from xAI."

        # 3. ترجمة عربية تلقائيًا
        try:
            analysis_ar = GoogleTranslator(source='en', target='ar').translate(analysis_en)
        except Exception:
            analysis_ar = "تعذر الترجمة تلقائيًا."

        # 4. إعداد كل رسالة منفصلة (4000 max لكل وحدة)
        text_ar = f"🇸🇦 التحليل بالعربي:\n{analysis_ar}"
        text_en = f"🇬🇧 English Analysis:\n{analysis_en}"
        if len(text_ar) > 4000: text_ar = text_ar[:4000] + "\n\n[...truncated...]"
        if len(text_en) > 4000: text_en = text_en[:4000] + "\n\n[...truncated...]"

        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient() as client:
            await client.post(telegram_url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text_ar
            })
            await client.post(telegram_url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text_en
            })

        logger.info("Dual language messages sent to Telegram successfully")
        return {"message": "Dual language webhook received and processed", "status": "ok"}

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e}")
        return {"message": "Error processing webhook", "status": "error", "detail": str(e)}, 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"message": "Unexpected error", "status": "error", "detail": str(e)}, 500

# Optional: Add startup/shutdown events for logging
@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI startup event triggered")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI shutdown event triggered")

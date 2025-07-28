import os
import logging
from fastapi import FastAPI, Request
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

# Load environment variables
load_dotenv()

app = FastAPI()

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

XAI_API_KEY = os.getenv("XAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not XAI_API_KEY or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("Missing env vars: XAI_API_KEY or TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    raise ValueError("Missing required env vars")

class TradingViewData(BaseModel):
    symbol: str
    frame: str
    data: str

@app.get("/")
async def root():
    return {"message": "Shinzooh API جاهز", "status": "ok"}

@app.post("/webhook")
async def webhook(request: Request, data: TradingViewData):
    try:
        logger.debug(f"Received webhook: {data}")

        # Prepare prompt for xAI API
        prompt = (
            f"Analyze the following trading data for {data.symbol} on {data.frame} timeframe: {data.data}. "
            "Provide a professional technical analysis and trading recommendation."
        )

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

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers=headers, json=payload, timeout=60
            )
            response.raise_for_status()

        # Extract & clean analysis (English)
        analysis_en = response.json()["choices"][0]["message"]["content"][:4000].strip()
        analysis_en = ''.join(c for c in analysis_en if c.isprintable())
        analysis_en = ' '.join(analysis_en.split())
        if not analysis_en:
            analysis_en = "No analysis available from xAI."

        # Translate to Arabic
        try:
            analysis_ar = GoogleTranslator(source='en', target='ar').translate(analysis_en)
        except Exception:
            analysis_ar = "تعذر الترجمة تلقائيًا."

        # Prepare the dual-language Telegram message (single message)
        telegram_text = (
            f"🔸 التحليل بالعربي:\n{analysis_ar}\n\n"
            f"🔸 English Analysis:\n{analysis_en}"
        )
        if len(telegram_text) > 4000:
            telegram_text = telegram_text[:4000] + "\n\n[...truncated...]"

        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        telegram_payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": telegram_text
        }

        async with httpx.AsyncClient() as client:
            telegram_response = await client.post(telegram_url, json=telegram_payload)
            telegram_response.raise_for_status()

        logger.info("Dual language analysis sent to Telegram successfully")
        return {"message": "Dual language analysis webhook received and processed", "status": "ok"}

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e}")
        return {"message": "Error processing webhook", "status": "error", "detail": str(e)}, 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"message": "Unexpected error", "status": "error", "detail": str(e)}, 500

@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI startup event triggered")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI shutdown event triggered")

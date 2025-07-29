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
TRADEGPT_API_KEY = os.getenv("TRADEGPT_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Validate environment variables
if not XAI_API_KEY or not TRADEGPT_API_KEY or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("Missing env vars: XAI_API_KEY or TRADEGPT_API_KEY or TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    raise ValueError("Missing required env vars")

# Pydantic model for TradingView data
class TradingViewData(BaseModel):
    symbol: str
    frame: str  # Supports '5m', '15m', '1h', '4h', '1d'
    data: str

# Root endpoint to confirm API is running
@app.get("/")
async def root():
    return {"message": "Shinzooh API جاهز", "status": "ok"}

# Function to analyze with TradeGPT
def analyze_with_tradegpt(symbol, frame, data):
    try:
        payload = {
            'symbol': symbol,
            'timeframe': frame,
            'data': data,
            'apikey': TRADEGPT_API_KEY
        }
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.tradegpt.ai/analyze", json=payload, timeout=60)
            response.raise_for_status()
        return response.json().get('analysis', "No analysis from TradeGPT")
    except httpx.HTTPStatusError as e:
        logger.error(f"TradeGPT API error: {e}")
        return "TradeGPT analysis unavailable"

# Webhook endpoint to process TradingView data
@app.post("/webhook")
async def webhook(request: Request, data: TradingViewData):
    try:
        logger.debug(f"Received webhook: {data}")

        # 1. تحليل xAI
        prompt = f"Analyze the following trading data for {data.symbol} on {data.frame} timeframe (one of 5m, 15m, 1h, 4h, 1d): {data.data}. Provide a professional technical analysis and trading recommendation."
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
            response = await client.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=60)
            response.raise_for_status()
        
        analysis_xai = response.json()["choices"][0]["message"]["content"][:4000].strip()
        analysis_xai = ''.join(c for c in analysis_xai if c.isprintable())
        if not analysis_xai:
            analysis_xai = "No analysis available from xAI."

        # 2. تحليل TradeGPT
        analysis_tradegpt = await analyze_with_tradegpt(data.symbol, data.frame, data.data)

        # 3. ترجمة التحليلات للعربي
        try:
            analysis_ar_xai = GoogleTranslator(source='en', target='ar').translate(analysis_xai)
            analysis_ar_tradegpt = GoogleTranslator(source='en', target='ar').translate(analysis_tradegpt)
        except Exception:
            analysis_ar_xai = "تعذر الترجمة لـ xAI."
            analysis_ar_tradegpt = "تعذر الترجمة لـ TradeGPT."

        # 4. إعداد الرسائل (قسم لعربي وإنجليزي)
        text_ar = f"🇸🇦 التحليل لـ {data.symbol} ({data.frame}):\n{data.data}\n\nxAI: {analysis_ar_xai}\nTradeGPT: {analysis_ar_tradegpt}"
        text_en = f"🇬🇧 Analysis for {data.symbol} ({data.frame}):\n{data.data}\n\nxAI: {analysis_xai}\nTradeGPT: {analysis_tradegpt}"
        if len(text_ar) > 4000: text_ar = text_ar[:4000] + "\n\n[...truncated...]"
        if len(text_en) > 4000: text_en = text_en[:4000] + "\n\n[...truncated...]"

        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient() as client:
            await client.post(telegram_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text_ar})
            await client.post(telegram_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text_en})

        logger.info("Dual language messages with xAI and TradeGPT sent to Telegram successfully")
        return {"message": "Dual language webhook with xAI and TradeGPT received and processed", "status": "ok"}

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

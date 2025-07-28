import os
import logging
from fastapi import FastAPI, Request
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

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
        
        # Prepare prompt for xAI API
        prompt = f"Analyze the following trading data for {data.symbol} on {data.frame} timeframe: {data.data}. Provide a professional technical analysis and trading recommendation."
        
        # xAI API request headers and payload
        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "grok-4-0709",  # Use "grok-beta" if needed
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0
        }
        
        # Call xAI API
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=60)
        
        response.raise_for_status()
        analysis = response.json()["choices"][0]["message"]["content"][:1900]  # Limit to 1900 chars
        if len(response.json()["choices"][0]["message"]["content"]) > 1900:
            logger.warning("Analysis truncated due to Telegram limit")
        
        logger.debug(f"xAI analysis: {analysis}")
        
        # Prepare and send message to Telegram
        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        telegram_payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"**{data.symbol} ({data.frame}) Analysis**\n{data.data}\n\n**Recommendation:**\n{analysis}",
            "parse_mode": "Markdown"
        }
        
        async with httpx.AsyncClient() as client:
            telegram_response = await client.post(telegram_url, json=telegram_payload)
        
        telegram_response.raise_for_status()
        logger.info("Message sent to Telegram successfully")
        
        return {"message": "Webhook received and processed", "status": "ok"}
    
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

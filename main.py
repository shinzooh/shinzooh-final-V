import os
import logging
from fastapi import FastAPI, Request
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Logging setup
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Env vars
XAI_API_KEY = os.getenv("XAI_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not XAI_API_KEY or not DISCORD_WEBHOOK_URL:
    logger.error("Missing env vars: XAI_API_KEY or DISCORD_WEBHOOK_URL")
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
        prompt = f"Analyze the following trading data for {data.symbol} on {data.frame} timeframe: {data.data}. Provide a professional technical analysis and trading recommendation."
        
        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "grok-4-0709",  # or "grok-beta"
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=60)
        
        response.raise_for_status()
        analysis = response.json()["choices"][0]["message"]["content"]
        logger.debug(f"xAI analysis: {analysis}")
        
        # Send to Discord Webhook
        discord_payload = {
            "content": f"**{data.symbol} ({data.frame}) Analysis**\n{data.data}\n\n**Recommendation:**\n{analysis}"
        }
        
        async with httpx.AsyncClient() as client:
            discord_response = await client.post(DISCORD_WEBHOOK_URL, json=discord_payload)
        
        discord_response.raise_for_status()
        logger.info("Webhook sent to Discord successfully")
        
        return {"message": "Webhook received and processed", "status": "ok"}
    
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e}")
        return {"message": "Error processing webhook", "status": "error", "detail": str(e)}, 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"message": "Unexpected error", "status": "error", "detail": str(e)}, 500

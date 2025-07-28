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
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
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
        
        # 1. حضّر البرومبت xAI
        prompt = (
            f"Analyze the following trading data for {data.symbol} on {data.frame} timeframe: "
            f"{data.data}. Provide a professional technical analysis and trading recommendation with a clear BUY or SELL signal."
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
        
        # 2. استدعي xAI API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
        
        # 3. استخراج وتنظيف التحليل الإنجليزي
        analysis_en = response.json()["choices"][0]["message"]["content"][:4000].strip()
        analysis_en = ' '.join(analysis_en.split())
        analysis_en = ''.join(c for c in analysis_en if c.isprintable())
        if not analysis_en:
            analysis_en = "No analysis available from xAI."
        
        # 4. ترجمة للعربي
        try:
            analysis_ar = GoogleTranslator(source='en', target='ar').translate(analysis_en)
        except Exception:
            analysis_ar = "تعذر الترجمة تلقائيًا."
        
        # 5. حضّر رسالة تيليجرام مزدوجة (تنسيق احترافي)
        telegram_text = (
            f"💡 *توصية فنية تلقائية (Shinzooh)*\n"
            f"\n"
            f"🔸 *{data.symbol}* ({data.frame})\n"
            f"------------------------\n"
            f"📋 {data.data}\n"
            f"\n"
            f"🇸🇦 *التحليل بالعربي:*\n{analysis_ar}\n\n"
            f"🇬🇧 *English Analysis:*\n{analysis_en}"
        )
        if len(telegram_text) > 4000:
            telegram_text = telegram_text[:4000] + "\n\n[...truncated...]"
        
        # 6. فلترة: فقط إذا التحليل فيه توصية بيع/شراء قوية
        if "buy" in analysis_en.lower() or "sell" in analysis_en.lower():
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            telegram_payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": telegram_text,
                "parse_mode": "Markdown"
            }
            async with httpx.AsyncClient() as client:
                telegram_response = await client.post(telegram_url, json=telegram_payload)
                telegram_response.raise_for_status()
            logger.info("Dual-language, filtered, and formatted analysis sent to Telegram successfully")
        else:
            logger.info("No BUY/SELL signal found, message not sent.")
            return {"message": "No actionable signal (no BUY/SELL in analysis)", "status": "ok"}
        
        return {"message": "Analysis webhook received and processed", "status": "ok"}
    
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e}")
        return {
            "message": "Error processing webhook",
            "status": "error",
            "detail": str(e)
        }, 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {
            "message": "Unexpected error",
            "status": "error",
            "detail": str(e)
        }, 500

# Startup/shutdown events for logging
@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI startup event triggered")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI shutdown event triggered")

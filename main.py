import logging
import os

# إعداد اللوجينغ (تظهر كل رسالة Debug أو Error مباشرة في Railway)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.debug("🚀 Starting Shinzooh app...")
logger.debug(f"PORT: {os.getenv('PORT')}")
logger.debug(f"XAI_API_KEY: {'set' if os.getenv('XAI_API_KEY') else 'NOT set'}")
logger.debug(f"DISCORD_WEBHOOK_URL: {'set' if os.getenv('DISCORD_WEBHOOK_URL') else 'NOT set'}")

from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def home():
    logger.debug("GET / called")
    return {"message": "Shinzooh API ✅ جاهز", "status": "ok"}

@app.get("/health")
def health_check():
    logger.debug("GET /health called")
    return {"status": "healthy"}

# تقدر تضيف هنا باقي الروابط (webhook مثلاً) بعد ما تتأكد أن الخدمة اشتغلت وما فيه crash

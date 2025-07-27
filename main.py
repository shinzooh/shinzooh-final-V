import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging

app = FastAPI()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Env vars
XAI_API_KEY = os.getenv("XAI_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

async def send_discord_message(message):
    if not DISCORD_WEBHOOK_URL:
        logger.error("DISCORD_WEBHOOK_URL NOT SET")
        return False
    async with httpx.AsyncClient() as client:
        payload = {"content": message}
        try:
            resp = await client.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            logger.info("DISCORD RESP: %s", resp.text)
            return resp.status_code == 200
        except Exception as e:
            logger.error("DISCORD ERROR: %s", str(e))
            return False

async def analyze_with_xai(prompt):
    if not XAI_API_KEY:
        logger.error("XAI_API_KEY NOT SET")
        return "XAI API key missing"
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
        try:
            resp = await client.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "No analysis")
        except Exception as e:
            logger.error("XAI ERROR: %s", str(e))
            return f"XAI ERROR: {str(e)}"

@app.get("/")
async def home():
    return JSONResponse({"message": "Shinzooh API ✅ جاهز", "status": "ok"})

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        logger.info("=== [TradingView DATA] === %s", data)
        symbol = data.get('symbol', 'Unknown')
        frame = data.get('frame', 'Unknown')
        price_data = data.get('data', 'No data')

        if not all([symbol, frame, price_data]):
            raise ValueError("البيانات ناقصة: symbol, frame, data")

        prompt = f"""
        تحليل فني لرمز {symbol} على الإطار {frame} - بيانات: {price_data}
        المطلوب: توصية شراء أو بيع مع نقاط الدخول، جني الأرباح (Take Profit)، وستوب لوز (Stop Loss)
        """

        analysis = await analyze_with_xai(prompt)
        logger.info("=== [xAI Analysis] === %s", analysis)
        await send_discord_message(f"تحليل {symbol} ({frame}):\n{analysis}")

        return JSONResponse({"status": "ok", "analysis": analysis})

    except Exception as e:
        logger.error("=== [ERROR] === %s", str(e))
        await send_discord_message(f"❌ ERROR في السيرفر: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('PORT', 8080)))
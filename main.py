import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from flask import Flask, request, jsonify
import json
import os
import time
from threading import Thread

XAI_API_KEY = os.getenv("XAI_API_KEY")
TELEGRAM_BOT_TOKEN = "7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw"
TELEGRAM_CHAT_ID = "715830182"

# retry setup
session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount('https://', adapter)

app = Flask(__name__)

def get_xai_analysis(symbol, frame, data_str):
    start = time.time()
    prompt = (
        f"Analyze {symbol} on {frame} with ICT & SMC (liquidity, BOS, CHoCH, FVG, OB, Premium/Discount, candles with levels) with 95%+ accuracy. "
        "Start with a sentence like 'Current candle on {symbol} {frame} shows close at C, high at H, low at L, indicating a bullish/bearish candle with close above/below the midpoint.' "
        "Then write each SMC and Classic Indicator point as a clear bullet point with exact values from input, one per line, with a blank line after each bullet for spacing. No section headers, no markdown, no table, just clear concise bullets. "
        "---"
        "ALWAYS at the end, give the trade recommendation as bullets ONLY: Type, Entry, Take Profit, Stop Loss, Reason. No headers, no markdown, no table, only bullets. Do not skip this part. "
        f"Data: {data_str}"
    )
    xai_url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "grok-4-latest", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1200}
    try:
        res = session.post(xai_url, headers=headers, json=data, timeout=60)
        res.raise_for_status()
        result = res.json()["choices"][0]["message"]["content"]
        print(f"xAI Time: {time.time() - start}s")
        print("====== xAI Analysis ======")
        print(result)
        print("==========================")
        sections = result.split('---')
        # Main analysis with spacing
        bullets = [l.strip("•*- ") for l in sections[0].splitlines() if l.strip()]
        main_analysis = "\n\n".join(  # مسافة سطرين بين كل نقطة
            [line for line in bullets if line and not line.lower().startswith(
                ("ict & smc", "classic indicator", "trade recommendation", "type", "entry", "take profit", "stop loss", "reason")
            ) and "|" not in line and not line.startswith("-")]
        )
        # Recommendation section
        rec_bullets = []
        if len(sections) > 1:
            rec_lines = [l.strip("•*- ") for l in sections[1].splitlines() if l.strip()]
            for line in rec_lines:
                if "|" in line or line.startswith("-"):
                    continue
                if any(key in line.lower() for key in ["type", "entry", "profit", "stop", "reason"]):
                    rec_bullets.append(line)
        rec_lookup = {'type': '', 'entry': '', 'take': '', 'stop': '', 'reason': ''}
        for l in rec_bullets:
            l2 = l.lower()
            if 'type' in l2:
                rec_lookup['type'] = l.split(':', 1)[-1].strip()
            elif 'entry' in l2:
                rec_lookup['entry'] = l.split(':', 1)[-1].strip()
            elif 'profit' in l2:
                rec_lookup['take'] = l.split(':', 1)[-1].strip()
            elif 'stop' in l2:
                rec_lookup['stop'] = l.split(':', 1)[-1].strip()
            elif 'reason' in l2:
                rec_lookup['reason'] = l.split(':', 1)[-1].strip()
        if all([rec_lookup['type'], rec_lookup['entry'], rec_lookup['take'], rec_lookup['stop']]):
            rec_fmt = (f"<b>🚦 Trade Recommendation</b>\n"
                       f"Type: <b>{rec_lookup['type']}</b>\n"
                       f"Entry: <b>{rec_lookup['entry']}</b>\n"
                       f"Take Profit: <b>{rec_lookup['take']}</b>\n"
                       f"Stop Loss: <b>{rec_lookup['stop']}</b>\n"
                       f"Reason: {rec_lookup['reason']}")
        else:
            rec_fmt = None
        return main_analysis, rec_fmt
    except Exception as e:
        print(f"xAI Error: {str(e)} Time: {time.time() - start}s")
        fallback = f"⚠️ xAI Error: fallback - Buy {symbol} above current, TP +50, SL -30 (95%+)."
        return fallback, None

def send_to_telegram(message, image_url=None):
    start = time.time()
    if image_url and isinstance(image_url, str) and image_url.startswith('http'):
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        try:
            img = requests.get(image_url, timeout=10).content
            files = {'photo': ('chart.png', img)}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': message[:1024], 'parse_mode': 'HTML'}
            res = requests.post(send_url, data=data, files=files, timeout=30)
            res.raise_for_status()
            print(f"Telegram Photo Time: {time.time() - start}s")
            return res.json()
        except Exception as e:
            print(f"Telegram Photo Error: {str(e)} Time: {time.time() - start}s")
            return "⚠️ Telegram Photo Error"
    else:
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message[:4096], 'parse_mode': 'HTML'}
            res = requests.post(send_url, data=data, timeout=30)
            res.raise_for_status()
            print(f"Telegram Text Time: {time.time() - start}s")
            return res.json()
        except Exception as e:
            print(f"Telegram Text Error: {str(e)} Time: {time.time() - start}s")
            return "⚠️ Telegram Text Error"

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "msg": "API Live ✅"})

@app.route("/webhook", methods=["POST"])
def webhook():
    start = time.time()
    body = request.data.decode('utf-8')
    print("======= Raw Body =======")
    print(body)
    print("=========================")
    try:
        payload = json.loads(body)
        print("======= Parsed JSON =======")
        print(payload)
        print("===========================")
    except:
        try:
            payload = dict(pair.split('=') for pair in body.split(',') if '=' in pair)
            print("======= Parsed KV =======")
            print(payload)
            print("=========================")
        except Exception as e:
            print(f"Parse Error: {str(e)}")
            payload = {}
    symbol = payload.get("SYMB") or payload.get("ticker") or "XAUUSD"
    tf = payload.get("TF") or payload.get("interval") or "1H"
    frame = f"{tf}m" if str(tf).isdigit() else tf
    data_str = json.dumps(payload, ensure_ascii=False)
    image_url = (
        payload.get("snapshot_url") or payload.get("image_url") or payload.get("chart_image_url")
    )
    msg_title = f"📊 <b>{symbol} {frame}</b>\n"

    def process_analysis():
        main_analysis, rec_fmt = get_xai_analysis(symbol, frame, data_str)
        if main_analysis:
            # رسالة التحليل منفصلة مع صورة إذا موجودة
            send_to_telegram(msg_title + main_analysis, image_url)
        if rec_fmt:
            # رسالة التوصية منفصلة (بدون صورة إضافية، أو أضف image_url لو تبي)
            send_to_telegram(rec_fmt)
        print(f"Webhook Processing Time: {time.time() - start}s")

    Thread(target=process_analysis).start()
    print(f"Webhook Response Time: {time.time() - start}s")
    return jsonify({"status": "ok", "msg": "Received and processing"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

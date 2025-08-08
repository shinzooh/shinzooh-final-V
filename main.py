import requests
from flask import Flask, request, jsonify
import json
import os
import time

XAI_API_KEY = os.getenv("XAI_API_KEY")
TELEGRAM_BOT_TOKEN = "7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw"
TELEGRAM_CHAT_ID = "715830182"

app = Flask(__name__)

def get_xai_analysis(symbol, frame, data_str):
    start = time.time()
    prompt = (
        f"Analyze {symbol} on {frame} using ICT & SMC (liquidity, BOS, CHoCH, FVG, OB, Premium/Discount, candles with levels) with 95%+ accuracy. "
        "Each point as a bullet, use exact numbers from the input. Be concise.\n"
        "---\n"
        "Next, write Classic Indicators section (EMA/MA/RSI/MACD), each as a bullet, with exact values from the input.\n"
        "---\n"
        "Finally, give the trade recommendation in a summary table:\n"
        "Type (Buy/Sell):\nEntry:\nTake Profit:\nStop Loss:\nReason (max 1 line):\n"
        f"Data: {data_str}"
    )
    xai_url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "grok-4-latest", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1200}
    try:
        res = requests.post(xai_url, headers=headers, json=data, timeout=30)
        res.raise_for_status()
        result = res.json()["choices"][0]["message"]["content"]
        print(f"xAI Time: {time.time() - start}s")
        print("====== xAI Analysis ======")
        print(result)
        print("==========================")
        sections = result.split('---')
        ict_smc = sections[0].strip() if len(sections) > 0 else ''
        classic = sections[1].strip() if len(sections) > 1 else ''
        rec = sections[2].strip() if len(sections) > 2 else ''
        return ict_smc, classic, rec
    except Exception as e:
        print(f"xAI Error: {str(e)} Time: {time.time() - start}s")
        fallback = f"⚠️ xAI Error: fallback - Buy {symbol} above current, TP +50, SL -30 (95%+)."
        return fallback, "", ""

def format_analysis(text):
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    formatted = []
    for line in lines:
        if not line.startswith("•") and (line.startswith("- ") or line.startswith("* ")):
            formatted.append("• " + line[2:])
        elif not line.startswith("•") and not line.endswith(":"):
            formatted.append("• " + line)
        else:
            formatted.append(line)
    return "\n".join(formatted)

def format_rec(text):
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    lookup = {'type': '', 'entry': '', 'take': '', 'stop': '', 'reason': ''}
    for l in lines:
        l2 = l.lower()
        if 'type' in l2:
            lookup['type'] = l.split(':', 1)[-1].strip()
        elif 'entry' in l2:
            lookup['entry'] = l.split(':', 1)[-1].strip()
        elif 'profit' in l2:
            lookup['take'] = l.split(':', 1)[-1].strip()
        elif 'stop' in l2:
            lookup['stop'] = l.split(':', 1)[-1].strip()
        elif 'reason' in l2:
            lookup['reason'] = l.split(':', 1)[-1].strip()
    return (f"<b>🚦 Trade Recommendation</b>\n"
            f"Type: <b>{lookup['type']}</b>\n"
            f"Entry: <b>{lookup['entry']}</b>\n"
            f"Take Profit: <b>{lookup['take']}</b>\n"
            f"Stop Loss: <b>{lookup['stop']}</b>\n"
            f"Reason: {lookup['reason']}")

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
        parsed_type = "json"
        print("======= Parsed JSON =======")
        print(payload)
        print("===========================")
    except:
        try:
            payload = dict(pair.split('=') for pair in body.split(',') if '=' in pair)
            parsed_type = "kv"
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
    image_url = ( payload.get("snapshot_url") or payload.get("image_url") or payload.get("chart_image_url") )
    msg_title = f"📊 <b>{symbol} {frame}</b>\n"
    ict_smc, classic, rec = get_xai_analysis(symbol, frame, data_str)
    if ict_smc:
        ict_fmt = format_analysis(ict_smc)
        send_to_telegram(msg_title + "\n<b>ICT & SMC Analysis</b>\n" + ict_fmt, image_url)
    if classic:
        classic_fmt = format_analysis(classic)
        send_to_telegram("<b>Classic Indicators</b>\n" + classic_fmt)
    if rec:
        rec_fmt = format_rec(rec)
        send_to_telegram(rec_fmt)
    print(f"Webhook Time: {time.time() - start}s")
    return jsonify({"status": "ok", "ict_smc": ict_smc, "classic": classic, "rec": rec})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

from flask import Flask, request
import requests
import json
from datetime import datetime, timezone
import os
import logging

# إعدادات تليجرام
TELEGRAM_BOT_TOKEN = '7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw'
TELEGRAM_CHAT_ID = '715830182'

# إعدادات Discord
DISCORD_WEBHOOK_URL = ''  # غيّريها لرابط Webhook إذا أردتي

# Rate limiting
REJECT_NOTIFY_LIMIT_SEC = 300
last_reject_notify = {'ts': datetime(1970, 1, 1, tzinfo=timezone.utc)}

# حدود السيولة (الفوليوم)
VOLUME_THRESHOLDS = {
    'forex': 5000,
    'indices': 10000,
    'crypto': 2000
}

app = Flask(__name__)

# مسار الصفحة الرئيسية للفحص الصحي
@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "Shinzooh Webhook شغالة!", 200

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        logging.exception("[Telegram Error] %s", e)

def send_discord_message(text):
    if DISCORD_WEBHOOK_URL and DISCORD_WEBHOOK_URL.startswith('http'):
        try:
            data = {"content": text}
            response = requests.post(DISCORD_WEBHOOK_URL, json=data)
            response.raise_for_status()
        except Exception as e:
            logging.exception("[Discord Error] %s", e)

def notify_rejection(reason, alert_data=None):
    now = datetime.now(timezone.utc)
    last_time = last_reject_notify.get('ts', datetime(1970, 1, 1, tzinfo=timezone.utc))
    if (now - last_time).total_seconds() > REJECT_NOTIFY_LIMIT_SEC:
        msg = f"⚠️ *Alert مرفوض*: {reason}"
        if alert_data and alert_data.get('interval') and alert_data.get('time'):
            msg += f"\nالفريم: `{alert_data.get('interval')}`\nالوقت: `{alert_data.get('time')}`"
        send_telegram_message(msg)
        send_discord_message(msg)
        last_reject_notify['ts'] = now

@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    try:
        data = request.json
        print(f"[DEBUG] Received Alert: {data}")
        price = data.get('close')
        open_ = data.get('open')
        timeframe = data.get('interval')
        timestamp = data.get('time')
        chart_url = data.get('chart_image_url') or data.get('screenshot_url')
        high = data.get('high')
        low = data.get('low')
        volume = data.get('volume')
        ticker = data.get('ticker')

        # التحقق من البيانات
        if not price or not timeframe or not timestamp:
            notify_rejection("بيانات ناقصة من Alert", data)
            return json.dumps({"status": "error", "message": "بيانات ناقصة من Alert"}), 400

        # فلتر زمني
        if timeframe in ["1", "1m", "5", "5m"]:
            interval

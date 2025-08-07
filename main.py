import schedule
import time
import yfinance as yf
from datetime import datetime, timezone
from dateutil import tz
import requests
import logging
import json
import pandas as pd
import ta

logging.basicConfig(level=logging.INFO)

TELEGRAM_BOT_TOKEN = '7550573728:AAFnoaMmcnb7dAfC4B9Jz9FlopMpJPiJNxw'
TELEGRAM_CHAT_ID = '715830182'

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        logging.exception("[Telegram Error] %s", e)

kwt_tz = tz.gettz('Asia/Kuwait')

symbols = ['GC=F', 'EURUSD=X', 'BTC-USD']  # XAUUSD (Gold), EURUSD, BTCUSD
frames = {
    '5m': '5m',
    '15m': '15m',
    '1h': '60m',
    '4h': '240m',
    '1d': '1d'
}

def get_data(symbol, interval):
    ticker = yf.Ticker(symbol)
    data = ticker.history(period='1d', interval=interval)
    if data.empty:
        return None
    return data

def analyze_ict_smc(data):
    if len(data) < 2:
        return "لا بيانات كافية لـ ICT-SMC"
    last_close = data['Close'].iloc[-1]
    prev_close = data['Close'].iloc[-2]
    last_high = data['High'].iloc[-1]
    last_low = data['Low'].iloc[-1]
    prev_high = data['High'].iloc[-2]
    prev_low = data['Low'].iloc[-2]
    analysis = ""
    if last_close > prev_close and last_high > prev_high:
        analysis += f"📈 Order Block صعودي (دعم عند {last_low})\n"
    elif last_close < prev_close and last_low < prev_low:
        analysis += f"📉 Order Block هابط (مقاومة عند {last_high})\n"
    if (last_high - last_low) > (prev_high - prev_low) * 1.5:
        analysis += "⚠️ Fair Value Gap (فجوة سعرية)\n"
    return analysis or "لا إشارة ICT-SMC واضحة"

def calculate_liquidity(data, asset_type='forex'):
    threshold = VOLUME_THRESHOLDS.get(asset_type, 5000)
    volume = data['Volume'].iloc[-1]
    if volume > threshold:
        return f"🚨 دخول سيولة قوية! ({volume:.0f})"
    return "لا سيولة قوية"

def calculate_rsi(data):
    rsi = ta.momentum.RSIIndicator(data['Close']).rsi().iloc[-1]
    if rsi > 70:
        return "RSI: overbought"
    elif rsi < 30:
        return "RSI: oversold"
    return "RSI: محايد"

def calculate_ma(data):
    ma = data['Close'].mean()
    return f"MA: {ma:.2f}"

def calculate_macd(data):
    macd = ta.trend.MACD(data['Close']).macd().iloc[-1]
    if macd > 0:
        return "MACD: صعودي"
    elif macd < 0:
        return "MACD: هابط"
    return "MACD: محايد"

def get_tradingview_chart_url(symbol, interval):
    return f"https://www.tradingview.com/chart/?symbol={symbol}&interval={interval}"

def run_analysis(session):
    for symbol in symbols:
        for frame_name, interval in frames.items():
            data = get_data(symbol, interval)
            if data is None:
                continue
            analysis = f"*تحليل {symbol} في {frame_name} - جلسة {session}*\n"
            analysis += f"السعر: {data['Close'].iloc[-1]:.2f}\n"
            analysis += analyze_ict_smc(data) + "\n"
            analysis += calculate_liquidity(data) + "\n"
            analysis += calculate_rsi(data) + "\n"
            analysis += calculate_ma(data) + "\n"
            analysis += calculate_macd(data) + "\n"
            analysis += f"[صورة الشارت]({get_tradingview_chart_url(symbol, frame_name)})"
            send_telegram_message(analysis)

schedule.every().day.at("09:00").do(run_analysis, 'سوق لندن')
schedule.every().day.at("14:00").do(run_analysis, 'سوق نيويورك')
schedule.every().day.at("16:30").do(run_analysis, 'السوق الأمريكي')

while True:
    schedule.run_pending()
    time.sleep(60)
</parameter
</xai:function_call

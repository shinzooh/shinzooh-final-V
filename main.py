import os
import asyncio
import json
import logging
import time
import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# إعداد FastAPI
app = FastAPI(title="Shinzooh Trading Bot - Fixed Version", version="6.0.0")

# متغيرات البيئة
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

# إعداد جلسة requests مع إعادة المحاولة
session = requests.Session()
retry_strategy = Retry(
    total=3,
    status_forcelist=[429, 500, 502, 503, 504],
    method_whitelist=["HEAD", "GET", "OPTIONS", "POST"],
    backoff_factor=1
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# إعدادات الأمان
SAFETY_FILTERS = {
    "rsi_min": 35,
    "rsi_max": 75,
    "macd_min": -0.3,
    "max_reversal_points": 30,
    "min_risk_reward": 1.5,
    "min_csd": 1.0,
    "min_volume_ratio": 0.8
}

# تخزين مؤقت للتنبيهات
alert_cache = {}
CACHE_DURATION = 5

def now_str():
    """الحصول على الوقت الحالي"""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def _to_float_safe(s):
    """تحويل آمن للنص إلى رقم"""
    if s is None:
        return None
    s = str(s).strip()
    if s in ("", "NaN", "nan", "null", "None", "{", "}", "{{rsi}}"):
        return None
    try:
        return float(s)
    except:
        s2 = re.sub(r"[^0-9\.\-\+eE]", "", s)
        try:
            return float(s2)
        except:
            return None

def parse_alert_data(alert_text: str) -> Dict[str, Any]:
    """تحليل بيانات التنبيه"""
    try:
        data = {}
        pairs = alert_text.replace('\n', '').split(',')
        
        for pair in pairs:
            if '=' in pair:
                key, value = pair.strip().split('=', 1)
                key = key.strip()
                value = value.strip()
                
                try:
                    if value.lower() in ['nan', 'null', '', 'na']:
                        data[key] = None
                    elif value.lower() in ['true', '1']:
                        data[key] = True
                    elif value.lower() in ['false', '0']:
                        data[key] = False
                    else:
                        if '.' in value:
                            data[key] = float(value)
                        else:
                            try:
                                data[key] = int(value)
                            except ValueError:
                                data[key] = float(value)
                except ValueError:
                    data[key] = value
        
        return data
    except Exception as e:
        logger.error(f"خطأ في تحليل البيانات: {e}")
        return {}

def apply_safety_filters(data: Dict[str, Any]) -> Tuple[bool, str]:
    """تطبيق فلاتر الأمان"""
    try:
        reasons = []
        
        rsi = data.get('RSI', 50)
        if rsi and (rsi < SAFETY_FILTERS["rsi_min"]):
            reasons.append(f"RSI منخفض ({rsi:.1f})")
        elif rsi and (rsi > SAFETY_FILTERS["rsi_max"]):
            reasons.append(f"RSI مرتفع ({rsi:.1f})")
        
        macd_hist = data.get('MACD_HIST', 0)
        if macd_hist and macd_hist < SAFETY_FILTERS["macd_min"]:
            reasons.append(f"MACD ضعيف ({macd_hist:.3f})")
        
        if reasons:
            return False, " | ".join(reasons)
        else:
            return True, "جميع فلاتر الأمان مستوفاة"
            
    except Exception as e:
        return False, f"خطأ في فلاتر الأمان: {e}"

def analyze_with_openai(data: Dict[str, Any]) -> Dict[str, Any]:
    """تحليل باستخدام OpenAI"""
    try:
        if not OPENAI_API_KEY:
            return {"decision": "UNAVAILABLE", "reason": "OpenAI API غير متوفر", "confidence": 0}
        
        symbol = data.get('SYMB', 'غير محدد')
        close = data.get('C', 0)
        rsi = data.get('RSI', 50)
        ema = data.get('EMA', 0)
        macd = data.get('MACD', 0)
        
        prompt = f"""
        أنت محلل تداول خبير. حلل هذه البيانات وأعطِ قرار واضح:
        
        الرمز: {symbol}
        السعر: {close}
        RSI: {rsi}
        EMA: {ema}
        MACD: {macd}
        
        أعطِ قرار محدد: شراء أو بيع أو انتظار
        ثم اذكر السبب في جملة واحدة.
        """
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 150,
            "temperature": 0.1
        }
        
        response = session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            analysis = result['choices'][0]['message']['content']
            
            analysis_upper = analysis.upper()
            if "شراء" in analysis or "BUY" in analysis_upper:
                decision = "شراء"
                confidence = 0.8
            elif "بيع" in analysis or "SELL" in analysis_upper:
                decision = "بيع"
                confidence = 0.8
            else:
                decision = "انتظار"
                confidence = 0.5
            
            return {
                "decision": decision,
                "reason": analysis.strip(),
                "confidence": confidence
            }
        else:
            return {
                "decision": "خطأ",
                "reason": f"خطأ OpenAI API ({response.status_code})",
                "confidence": 0
            }
    
    except Exception as e:
        return {
            "decision": "خطأ",
            "reason": f"خطأ OpenAI: {str(e)[:100]}",
            "confidence": 0
        }

def analyze_with_xai(data: Dict[str, Any]) -> Dict[str, Any]:
    """تحليل باستخدام xAI"""
    try:
        if not XAI_API_KEY:
            return {"decision": "UNAVAILABLE", "reason": "xAI API غير متوفر", "confidence": 0}
        
        csd_up = data.get('CSD_UP', 0) or 0
        csd_down = data.get('CSD_DN', 0) or 0
        bos_bull = data.get('BOS_BULL', 0) or 0
        bos_bear = data.get('BOS_BEAR', 0) or 0
        
        prompt = f"""
        أنت خبير ICT/SMC. حلل هذه البيانات:
        
        CSD صاعد: {csd_up}
        CSD هابط: {csd_down}
        BOS صاعد: {bos_bull}
        BOS هابط: {bos_bear}
        
        أعطِ قرار محدد: شراء أو بيع أو انتظار
        ثم اذكر السبب حسب ICT.
        """
        
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "model": "grok-beta",
            "stream": False,
            "temperature": 0.1
        }
        
        response = session.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            analysis = result['choices'][0]['message']['content']
            
            analysis_upper = analysis.upper()
            if "شراء" in analysis or "BUY" in analysis_upper:
                decision = "شراء"
                confidence = 0.9
            elif "بيع" in analysis or "SELL" in analysis_upper:
                decision = "بيع"
                confidence = 0.9
            else:
                decision = "انتظار"
                confidence = 0.6
            
            return {
                "decision": decision,
                "reason": analysis.strip(),
                "confidence": confidence
            }
        else:
            return {
                "decision": "خطأ",
                "reason": f"خطأ xAI API ({response.status_code})",
                "confidence": 0
            }
    
    except Exception as e:
        return {
            "decision": "خطأ",
            "reason": f"خطأ xAI: {str(e)[:100]}",
            "confidence": 0
        }

def analyze_with_claude(data: Dict[str, Any]) -> Dict[str, Any]:
    """تحليل باستخدام Claude"""
    try:
        if not CLAUDE_API_KEY:
            return {"decision": "UNAVAILABLE", "reason": "Claude API غير متوفر", "confidence": 0}
        
        symbol = data.get('SYMB', 'غير محدد')
        close = data.get('C', 0)
        rsi = data.get('RSI', 50)
        premium = data.get('PREMIUM', 0) or 0
        discount = data.get('DISCOUNT', 0) or 0
        
        prompt = f"""
        أنت محلل شامل. حلل هذه البيانات:
        
        الرمز: {symbol}
        السعر: {close}
        RSI: {rsi}
        Premium Zone: {premium}
        Discount Zone: {discount}
        
        أعطِ قرار محدد: شراء أو بيع أو انتظار
        ثم اذكر السبب الشامل.
        """
        
        payload = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        response = session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Authorization": f"Bearer {CLAUDE_API_KEY}",
                "Content-Type": "application/json",
                "x-api-version": "2023-06-01"
            },
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            analysis = result['content'][0]['text']
            
            analysis_upper = analysis.upper()
            if "شراء" in analysis or "BUY" in analysis_upper:
                decision = "شراء"
                confidence = 0.85
            elif "بيع" in analysis or "SELL" in analysis_upper:
                decision = "بيع"
                confidence = 0.85
            else:
                decision = "انتظار"
                confidence = 0.4
            
            return {
                "decision": decision,
                "reason": analysis.strip(),
                "confidence": confidence
            }
        else:
            return {
                "decision": "خطأ",
                "reason": f"خطأ Claude API ({response.status_code})",
                "confidence": 0
            }
    
    except Exception as e:
        return {
            "decision": "خطأ",
            "reason": f"خطأ Claude: {str(e)[:100]}",
            "confidence": 0
        }

def calculate_trade_levels(data: Dict[str, Any], direction: str) -> Dict[str, float]:
    """حساب مستويات التداول"""
    try:
        close = data.get('C', 0)
        atr = data.get('ATR', 0) or (close * 0.001)
        
        if direction == "شراء":
            entry = close
            tp1 = close + (atr * 2)
            tp2 = close + (atr * 4)
            tp3 = close + (atr * 6)
            tp4 = close + (atr * 8)
            sl = close - (atr * 3)
        elif direction == "بيع":
            entry = close
            tp1 = close - (atr * 2)
            tp2 = close - (atr * 4)
            tp3 = close - (atr * 6)
            tp4 = close - (atr * 8)
            sl = close + (atr * 3)
        else:
            return {"entry": None, "tp1": None, "tp2": None, "tp3": None, "tp4": None, "sl": None}
        
        return {
            "entry": round(entry, 2),
            "tp1": round(tp1, 2),
            "tp2": round(tp2, 2),
            "tp3": round(tp3, 2),
            "tp4": round(tp4, 2),
            "sl": round(sl, 2)
        }
    
    except Exception as e:
        logger.error(f"خطأ في حساب المستويات: {e}")
        return {"entry": None, "tp1": None, "tp2": None, "tp3": None, "tp4": None, "sl": None}

def format_message(data: Dict[str, Any], openai_result: Dict, xai_result: Dict, claude_result: Dict, safety_passed: bool, safety_reason: str) -> str:
    """تنسيق الرسالة الشاملة"""
    
    symbol = data.get('SYMB', 'غير محدد')
    timeframe = data.get('TF', 'غير محدد')
    close_price = data.get('C', 0)
    rsi = data.get('RSI', 50)
    ema = data.get('EMA', 0)
    
    def get_decision_emoji(decision):
        if decision == "شراء":
            return "✅"
        elif decision == "بيع":
            return "🔴"
        elif decision == "انتظار":
            return "⚠️"
        elif decision == "UNAVAILABLE":
            return "🚫"
        else:
            return "❓"
    
    openai_decision = openai_result.get('decision', 'خطأ')
    xai_decision = xai_result.get('decision', 'خطأ')
    claude_decision = claude_result.get('decision', 'خطأ')
    
    # حساب الإجماع
    valid_decisions = []
    for decision in [openai_decision, xai_decision, claude_decision]:
        if decision not in ['خطأ', 'UNAVAILABLE']:
            valid_decisions.append(decision)
    
    buy_count = valid_decisions.count('شراء')
    sell_count = valid_decisions.count('بيع')
    wait_count = valid_decisions.count('انتظار')
    total_valid = len(valid_decisions)
    
    if total_valid == 0:
        consensus = "خطأ في جميع النماذج"
        final_decision = "لا صفقة"
        trade_direction = None
    elif buy_count >= 2:
        consensus = f"إجماع على الشراء ({buy_count}/{total_valid})"
        final_decision = "🟢 شراء"
        trade_direction = "شراء"
    elif sell_count >= 2:
        consensus = f"إجماع على البيع ({sell_count}/{total_valid})"
        final_decision = "🔴 بيع"
        trade_direction = "بيع"
    else:
        consensus = f"تعارض بين النماذج"
        final_decision = "لا صفقة"
        trade_direction = None
    
    # حساب مستويات التداول
    if trade_direction and safety_passed:
        levels = calculate_trade_levels(data, trade_direction)
    else:
        levels = {"entry": None, "tp1": None, "tp2": None, "tp3": None, "tp4": None, "sl": None}
    
    entry_str = f"{levels['entry']:.2f}" if levels['entry'] else "—"
    tp1_str = f"{levels['tp1']:.2f}" if levels['tp1'] else "—"
    tp2_str = f"{levels['tp2']:.2f}" if levels['tp2'] else "—"
    tp3_str = f"{levels['tp3']:.2f}" if levels['tp3'] else "—"
    tp4_str = f"{levels['tp4']:.2f}" if levels['tp4'] else "—"
    sl_str = f"{levels['sl']:.2f}" if levels['sl'] else "—"
    
    message = f"""📊 <b>{symbol} {timeframe}</b>

<b>🔍 التحليل الفني الكلاسيكي</b>

<b>السعر الحالي:</b> {close_price:.2f}
<b>RSI:</b> {rsi:.1f}
<b>EMA:</b> {ema:.2f}

<b>🤖 ملخص النماذج</b>

<b>OpenAI:</b> {get_decision_emoji(openai_decision)} <b>{openai_decision}</b>
<i>السبب:</i> {openai_result.get('reason', 'غير متوفر')[:100]}

<b>xAI:</b> {get_decision_emoji(xai_decision)} <b>{xai_decision}</b>
<i>السبب:</i> {xai_result.get('reason', 'غير متوفر')[:100]}

<b>Claude:</b> {get_decision_emoji(claude_decision)} <b>{claude_decision}</b>
<i>السبب:</i> {claude_result.get('reason', 'غير متوفر')[:100]}

<b>⚠️ تحليل الإجماع</b>

<b>{consensus}</b>

<b>🎯 التوصية النهائية</b>

<b>نوع الصفقة:</b> {final_decision}
<b>نقاط الدخول:</b> {entry_str}

<b>أهداف جني الأرباح:</b>
• TP1: {tp1_str}
• TP2: {tp2_str}
• TP3: {tp3_str}
• TP4: {tp4_str}

<b>وقف الخسارة:</b> {sl_str}

<b>⚡ شروط الأمان</b>

• RSI بين {SAFETY_FILTERS['rsi_min']}-{SAFETY_FILTERS['rsi_max']}: {'✅' if SAFETY_FILTERS['rsi_min'] <= rsi <= SAFETY_FILTERS['rsi_max'] else '❌'}
• فلاتر الأمان: {'✅ مستوفاة' if safety_passed else f'❌ {safety_reason}'}

<b>🕒 الوقت:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC
<b>📊 الرمز:</b> {symbol} ({timeframe})"""

    return message

def send_telegram_message(message: str):
    """إرسال رسالة إلى Telegram"""
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.error("معلومات Telegram غير مكتملة")
            return False
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        response = session.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            logger.info("تم إرسال الرسالة بنجاح")
            return True
        else:
            logger.error(f"فشل إرسال الرسالة: {response.status_code}")
            return False
    
    except Exception as e:
        logger.error(f"خطأ في إرسال الرسالة: {e}")
        return False

def is_duplicate_alert(alert_data: str) -> bool:
    """فحص التنبيهات المكررة"""
    try:
        current_time = datetime.utcnow().timestamp()
        alert_hash = hash(alert_data)
        
        expired_keys = [
            key for key, timestamp in alert_cache.items()
            if current_time - timestamp > CACHE_DURATION
        ]
        for key in expired_keys:
            del alert_cache[key]
        
        if alert_hash in alert_cache:
            return True
        
        alert_cache[alert_hash] = current_time
        return False
    
    except Exception as e:
        logger.error(f"خطأ في فحص التكرار: {e}")
        return False

@app.get("/")
async def root():
    """الصفحة الرئيسية"""
    return {
        "ok": True,
        "service": "Shinzooh Trading Bot - Fixed Version",
        "version": "6.0.0",
        "ai_engines": {
            "OpenAI": "✅ متاح" if OPENAI_API_KEY else "❌ غير متاح",
            "xAI": "✅ متاح" if XAI_API_KEY else "❌ غير متاح",
            "Claude": "✅ متاح" if CLAUDE_API_KEY else "❌ غير متاح"
        },
        "telegram": {
            "configured": "✅ مُعد" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "❌ غير مُعد"
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """فحص صحة النظام"""
    return {
        "status": "healthy",
        "cache_size": len(alert_cache),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/webhook")
async def webhook_handler(request: Request):
    """معالج التنبيهات الرئيسي"""
    try:
        body = await request.body()
        data_text = body.decode('utf-8')
        
        logger.info(f"تم استقبال تنبيه: {data_text[:150]}...")
        
        if is_duplicate_alert(data_text):
            logger.info("تنبيه مكرر - تم تجاهله")
            return {"status": "ignored", "reason": "duplicate_alert"}
        
        parsed_data = parse_alert_data(data_text)
        
        if not parsed_data:
            raise HTTPException(status_code=400, detail="فشل في تحليل البيانات")
        
        safety_passed, safety_reason = apply_safety_filters(parsed_data)
        
        # تحليل متوازي
        loop = asyncio.get_event_loop()
        openai_task = loop.run_in_executor(None, analyze_with_openai, parsed_data)
        xai_task = loop.run_in_executor(None, analyze_with_xai, parsed_data)
        claude_task = loop.run_in_executor(None, analyze_with_claude, parsed_data)
        
        openai_result, xai_result, claude_result = await asyncio.gather(
            openai_task, xai_task, claude_task
        )
        
        logger.info(f"نتائج التحليل - OpenAI: {openai_result.get('decision')}, xAI: {xai_result.get('decision')}, Claude: {claude_result.get('decision')}")
        
        message = format_message(
            parsed_data, openai_result, xai_result, claude_result,
            safety_passed, safety_reason
        )
        
        success = await loop.run_in_executor(None, send_telegram_message, message)
        
        if success:
            return {
                "status": "success",
                "message": "تم التحليل والإرسال بنجاح",
                "ai_results": {
                    "openai": openai_result.get('decision'),
                    "xai": xai_result.get('decision'),
                    "claude": claude_result.get('decision')
                }
            }
        else:
            raise HTTPException(status_code=500, detail="فشل في إرسال الرسالة")
    
    except Exception as e:
        logger.error(f"خطأ في معالجة التنبيه: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/test")
async def test_endpoint(request: Request):
    """نقطة اختبار"""
    try:
        test_data = await request.json()
        
        sample_alert = (
            f"SYMB={test_data.get('symbol', 'XAUUSD')},"
            f"TF={test_data.get('timeframe', '5m')},"
            f"C={test_data.get('close', 2652)},"
            f"RSI={test_data.get('rsi', 65)},"
            f"EMA={test_data.get('ema', 2649)},"
            f"MACD={test_data.get('macd', 0.15)}"
        )
        
        parsed_data = parse_alert_data(sample_alert)
        safety_passed, safety_reason = apply_safety_filters(parsed_data)
        
        # تحليل اختبار مبسط
        openai_result = {"decision": "شراء", "reason": "اختبار - RSI جيد + EMA صاعد", "confidence": 0.8}
        xai_result = {"decision": "شراء", "reason": "اختبار - إشارات ICT إيجابية", "confidence": 0.9}
        claude_result = {"decision": "انتظار", "reason": "اختبار - منطقة توازن", "confidence": 0.6}
        
        message = format_message(
            parsed_data, openai_result, xai_result, claude_result,
            safety_passed, safety_reason
        )
        
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, send_telegram_message, message)
        
        return {
            "status": "success" if success else "partial_success",
            "message": "تم إرسال رسالة اختبار",
            "telegram_sent": success
        }
    
    except Exception as e:
        logger.error(f"خطأ في الاختبار: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)


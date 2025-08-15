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
app = FastAPI(title="Shinzooh Trading Bot - Perfect Final", version="8.0.0")

# متغيرات البيئة
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

# إعداد جلسة requests مع إعادة المحاولة المصححة
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"]  # تصحيح: استخدام allowed_methods بدلاً من method_whitelist
)

session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))
session.mount("http://", HTTPAdapter(max_retries=retry_strategy))

# إعدادات الأمان المحسنة
SAFETY_FILTERS = {
    "rsi_min": 35,
    "rsi_max": 75,
    "macd_min": -0.2,
    "max_reversal_points": 30,
    "min_risk_reward": 1.5,
    "min_csd": 1.0,
    "min_volume_ratio": 0.8
}

# تخزين مؤقت للتنبيهات
alert_cache = {}
CACHE_DURATION = 5
MIN_GAP_SEC = 5
_last_send = {}

def now_str():
    """الحصول على الوقت الحالي"""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def _to_float_safe(s):
    """تحويل آمن للنص إلى رقم"""
    if s is None:
        return None
    s = str(s).strip()
    if s in ("", "NaN", "nan", "null", "None", "{", "}", "{{rsi}}", "na"):
        return None
    try:
        return float(s)
    except:
        s2 = re.sub(r"[^0-9\.\-\+eE]", "", s)
        try:
            return float(s2)
        except:
            return None

def parse_kv(raw_text: str) -> Dict[str, str]:
    """تحليل بيانات التنبيه من النص الخام"""
    try:
        data = {}
        pairs = raw_text.replace('\n', '').split(',')
        
        for pair in pairs:
            if '=' in pair:
                key, value = pair.strip().split('=', 1)
                data[key.strip()] = value.strip()
        
        return data
    except Exception as e:
        logger.error(f"خطأ في تحليل البيانات: {e}")
        return {}

def normalize_data(kv: Dict[str, str]) -> Dict[str, Any]:
    """تطبيع البيانات وتحويلها للأنواع المناسبة"""
    return {
        "SYMB": kv.get("SYMB", ""),
        "TF": kv.get("TF", ""),
        "O": _to_float_safe(kv.get("O") or kv.get("OPEN")),
        "H": _to_float_safe(kv.get("H") or kv.get("HIGH")),
        "L": _to_float_safe(kv.get("L") or kv.get("LOW")),
        "C": _to_float_safe(kv.get("C") or kv.get("CLOSE")),
        "V": _to_float_safe(kv.get("V") or kv.get("VOLUME")),
        "RSI": _to_float_safe(kv.get("RSI")),
        "EMA": _to_float_safe(kv.get("EMA") or kv.get("MA")),
        "MACD": _to_float_safe(kv.get("MACD")),
        "MACD_SIGNAL": _to_float_safe(kv.get("MACD_SIGNAL")),
        "MACD_HIST": _to_float_safe(kv.get("MACD_HIST")),
        "CSD_UP": _to_float_safe(kv.get("CSD_UP")),
        "CSD_DN": _to_float_safe(kv.get("CSD_DN")),
        "BULL_FVG_CE": _to_float_safe(kv.get("BULL_FVG_CE")),
        "BEAR_FVG_CE": _to_float_safe(kv.get("BEAR_FVG_CE")),
        "BOS_BULL": _to_float_safe(kv.get("BOS_BULL")),
        "BOS_BEAR": _to_float_safe(kv.get("BOS_BEAR")),
        "PREMIUM": _to_float_safe(kv.get("PREMIUM")),
        "DISCOUNT": _to_float_safe(kv.get("DISCOUNT")),
        "EQUILIBRIUM": _to_float_safe(kv.get("EQUILIBRIUM")),
        "ATR14": _to_float_safe(kv.get("ATR14") or kv.get("ATR")),
        "VOLUME_RATIO": _to_float_safe(kv.get("VOLUME_RATIO")),
    }

def apply_safety_filters(data: Dict[str, Any]) -> Tuple[bool, str]:
    """تطبيق فلاتر الأمان المحسنة"""
    try:
        reasons = []
        
        # فحص RSI
        rsi = data.get('RSI')
        if rsi is not None:
            if rsi < SAFETY_FILTERS["rsi_min"]:
                reasons.append(f"RSI منخفض ({rsi:.1f})")
            elif rsi > SAFETY_FILTERS["rsi_max"]:
                reasons.append(f"RSI مرتفع ({rsi:.1f})")
        
        # فحص MACD
        macd_hist = data.get('MACD_HIST') or data.get('MACD')
        if macd_hist is not None and macd_hist < SAFETY_FILTERS["macd_min"]:
            reasons.append(f"MACD ضعيف ({macd_hist:.3f})")
        
        # فحص CSD
        csd_up = data.get('CSD_UP') or 0
        csd_down = data.get('CSD_DN') or 0
        if max(csd_up, csd_down) < SAFETY_FILTERS["min_csd"]:
            reasons.append(f"CSD ضعيف (أعلى قيمة: {max(csd_up, csd_down):.2f})")
        
        if reasons:
            return False, " | ".join(reasons)
        else:
            return True, "جميع فلاتر الأمان مستوفاة"
            
    except Exception as e:
        logger.error(f"خطأ في فلاتر الأمان: {e}")
        return False, f"خطأ في فلاتر الأمان: {e}"

def build_analysis_prompt(data: Dict[str, Any]) -> str:
    """بناء prompt التحليل الشامل"""
    sym = data.get("SYMB", "غير محدد")
    tf = data.get("TF", "غير محدد")
    close = data.get("C", 0)
    rsi = data.get("RSI", 50)
    ema = data.get("EMA", 0)
    macd = data.get("MACD", 0)
    csd_up = data.get("CSD_UP", 0) or 0
    csd_down = data.get("CSD_DN", 0) or 0
    bull_fvg = data.get("BULL_FVG_CE", 0) or 0
    bear_fvg = data.get("BEAR_FVG_CE", 0) or 0
    bos_bull = data.get("BOS_BULL", 0) or 0
    bos_bear = data.get("BOS_BEAR", 0) or 0
    
    return f"""
    أنت محلل تداول خبير متخصص في التحليل الفني و ICT/SMC. حلل هذه البيانات بدقة:
    
    الرمز: {sym}
    الإطار الزمني: {tf}
    السعر الحالي: {close}
    
    التحليل الفني الكلاسيكي:
    - RSI: {rsi}
    - EMA: {ema}
    - MACD: {macd}
    
    تحليل ICT/SMC:
    - CSD صاعد: {csd_up}
    - CSD هابط: {csd_down}
    - FVG صاعدة: {bull_fvg}
    - FVG هابطة: {bear_fvg}
    - BOS صاعد: {bos_bull}
    - BOS هابط: {bos_bear}
    
    أعطِ قرار واضح ومحدد: شراء أو بيع أو انتظار
    ثم اذكر السبب في جملة واحدة مختصرة وواضحة.
    
    مثال للإجابة:
    القرار: شراء
    السبب: RSI في منطقة جيدة + CSD صاعد قوي + BOS مؤكد
    """

def ask_openai(prompt: str, timeout: int = 25) -> Tuple[bool, str]:
    """استدعاء OpenAI API"""
    try:
        if not OPENAI_API_KEY:
            return False, "OpenAI API key غير متوفر"
        
        response = session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 300
            },
            timeout=timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            return True, result["choices"][0]["message"]["content"]
        else:
            return False, f"OpenAI API خطأ: {response.status_code}"
    
    except Exception as e:
        logger.error(f"خطأ OpenAI: {e}")
        return False, f"خطأ OpenAI: {str(e)[:100]}"

def ask_xai(prompt: str, timeout: int = 25) -> Tuple[bool, str]:
    """استدعاء xAI API"""
    try:
        if not XAI_API_KEY:
            return False, "xAI API key غير متوفر"
        
        response = session.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "grok-beta",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 300,
                "stream": False
            },
            timeout=timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            return True, result["choices"][0]["message"]["content"]
        else:
            return False, f"xAI API خطأ: {response.status_code}"
    
    except Exception as e:
        logger.error(f"خطأ xAI: {e}")
        return False, f"خطأ xAI: {str(e)[:100]}"

def ask_claude(prompt: str, timeout: int = 25) -> Tuple[bool, str]:
    """استدعاء Claude API"""
    try:
        if not CLAUDE_API_KEY:
            return False, "Claude API key غير متوفر"
        
        response = session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Authorization": f"Bearer {CLAUDE_API_KEY}",
                "Content-Type": "application/json",
                "x-api-version": "2023-06-01"
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            return True, result["content"][0]["text"]
        else:
            return False, f"Claude API خطأ: {response.status_code}"
    
    except Exception as e:
        logger.error(f"خطأ Claude: {e}")
        return False, f"خطأ Claude: {str(e)[:100]}"

def extract_decision_and_reason(text: str) -> Tuple[str, str]:
    """استخراج القرار والسبب من نص التحليل"""
    if not text:
        return "خطأ", "لا يوجد نص"
    
    text_upper = text.upper()
    
    # استخراج القرار
    decision = "انتظار"  # القيمة الافتراضية
    if "شراء" in text or "BUY" in text_upper:
        decision = "شراء"
    elif "بيع" in text or "SELL" in text_upper:
        decision = "بيع"
    
    # استخراج السبب
    reason_match = re.search(r"السبب\s*:\s*([^\n\r]+)", text, re.IGNORECASE)
    if reason_match:
        reason = reason_match.group(1).strip()
    else:
        # إذا لم نجد "السبب:" نأخذ أول جملة مفيدة
        lines = text.split('\n')
        reason = "تحليل غير واضح"
        for line in lines:
            line = line.strip()
            if line and len(line) > 10 and not line.startswith("القرار"):
                reason = line[:150]
                break
    
    return decision, reason

def calculate_trade_levels(data: Dict[str, Any], direction: str) -> Dict[str, Optional[float]]:
    """حساب مستويات التداول بدقة"""
    try:
        close = data.get('C', 0)
        if not close:
            return {"entry": None, "tp1": None, "tp2": None, "tp3": None, "tp4": None, "sl": None}
        
        # حساب ATR أو استخدام قيمة افتراضية
        atr = data.get('ATR14') or (close * 0.002)  # 0.2% من السعر كـ ATR افتراضي
        
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

def format_comprehensive_message(
    data: Dict[str, Any], 
    openai_decision: str, openai_reason: str,
    xai_decision: str, xai_reason: str,
    claude_decision: str, claude_reason: str,
    safety_passed: bool, safety_reason: str
) -> str:
    """تنسيق الرسالة الشاملة النهائية"""
    
    symbol = data.get('SYMB', 'غير محدد')
    timeframe = data.get('TF', 'غير محدد')
    close_price = data.get('C', 0)
    rsi = data.get('RSI', 50)
    ema = data.get('EMA', 0)
    macd = data.get('MACD', 0)
    csd_up = data.get('CSD_UP', 0) or 0
    csd_down = data.get('CSD_DN', 0) or 0
    
    def get_decision_emoji(decision):
        if decision == "شراء":
            return "✅"
        elif decision == "بيع":
            return "🔴"
        elif decision == "انتظار":
            return "⚠️"
        else:
            return "❓"
    
    # حساب الإجماع
    valid_decisions = [d for d in [openai_decision, xai_decision, claude_decision] if d in ['شراء', 'بيع', 'انتظار']]
    
    buy_count = valid_decisions.count('شراء')
    sell_count = valid_decisions.count('بيع')
    wait_count = valid_decisions.count('انتظار')
    total_valid = len(valid_decisions)
    
    if total_valid == 0:
        consensus = "خطأ في جميع النماذج"
        final_decision = "لا صفقة"
        trade_direction = None
        consensus_detail = "جميع النماذج واجهت أخطاء تقنية"
    elif buy_count >= 2:
        consensus = f"إجماع على الشراء ({buy_count}/{total_valid})"
        final_decision = "🟢 شراء"
        trade_direction = "شراء"
        consensus_detail = f"أغلبية النماذج ({buy_count} من {total_valid}) تقترح الشراء"
    elif sell_count >= 2:
        consensus = f"إجماع على البيع ({sell_count}/{total_valid})"
        final_decision = "🔴 بيع"
        trade_direction = "بيع"
        consensus_detail = f"أغلبية النماذج ({sell_count} من {total_valid}) تقترح البيع"
    else:
        consensus = f"تعارض بين النماذج (شراء:{buy_count} | بيع:{sell_count} | انتظار:{wait_count})"
        final_decision = "لا صفقة"
        trade_direction = None
        consensus_detail = "لا يوجد إجماع - يجب موافقة نموذجين على الأقل من ثلاثة"
    
    # حساب مستويات التداول
    if trade_direction and safety_passed:
        levels = calculate_trade_levels(data, trade_direction)
    else:
        levels = {"entry": None, "tp1": None, "tp2": None, "tp3": None, "tp4": None, "sl": None}
    
    # تنسيق المستويات
    entry_str = f"{levels['entry']:.2f}" if levels['entry'] else "—"
    tp1_str = f"{levels['tp1']:.2f}" if levels['tp1'] else "—"
    tp2_str = f"{levels['tp2']:.2f}" if levels['tp2'] else "—"
    tp3_str = f"{levels['tp3']:.2f}" if levels['tp3'] else "—"
    tp4_str = f"{levels['tp4']:.2f}" if levels['tp4'] else "—"
    sl_str = f"{levels['sl']:.2f}" if levels['sl'] else "—"
    
    # بناء الرسالة النهائية
    message = f"""📊 <b>{symbol} {timeframe}</b>

<b>🔍 التحليل الفني الكلاسيكي</b>

<b>السعر الحالي:</b> {close_price:.2f}
<b>البيانات:</b> O={data.get('O', 'na')} | H={data.get('H', 'na')} | L={data.get('L', 'na')} | C={close_price}
<b>RSI:</b> {rsi:.1f} {'(ضمن المنطقة الآمنة)' if 35 <= rsi <= 75 else '(خارج المنطقة الآمنة)'}
<b>EMA:</b> {ema:.2f}
<b>MACD:</b> {macd:.3f}

<b>📚 تحليل ICT / SMC</b>

<b>CSD:</b> صاعد={csd_up:.2f} | هابط={csd_down:.2f}
<b>BOS:</b> {'صاعد مؤكد' if data.get('BOS_BULL') else 'هابط مؤكد' if data.get('BOS_BEAR') else 'غير واضح'}
<b>FVG:</b> {'فجوة صاعدة' if data.get('BULL_FVG_CE') else 'فجوة هابطة' if data.get('BEAR_FVG_CE') else 'لا توجد فجوات'}
<b>المناطق:</b> {'Premium' if data.get('PREMIUM') else 'Discount' if data.get('DISCOUNT') else 'Equilibrium'}

<b>🤖 ملخص النماذج</b>

<b>OpenAI:</b> {get_decision_emoji(openai_decision)} <b>{openai_decision}</b>
<i>السبب:</i> {openai_reason[:120]}

<b>xAI:</b> {get_decision_emoji(xai_decision)} <b>{xai_decision}</b>
<i>السبب:</i> {xai_reason[:120]}

<b>Claude:</b> {get_decision_emoji(claude_decision)} <b>{claude_decision}</b>
<i>السبب:</i> {claude_reason[:120]}

<b>⚠️ تحليل الإجماع</b>

<b>{consensus}</b>

<i>التفاصيل:</i> {consensus_detail}

<b>🎯 التوصية النهائية</b>

<b>نوع الصفقة:</b> {final_decision}
<b>نقاط الدخول:</b> {entry_str}

<b>أهداف جني الأرباح:</b>
• TP1: {tp1_str}
• TP2: {tp2_str}
• TP3: {tp3_str}
• TP4: {tp4_str}

<b>وقف الخسارة:</b> {sl_str}

<b>السبب:</b> {consensus_detail}

<b>⚡ شروط الأمان</b>

• أقصى انعكاس: ≤ {SAFETY_FILTERS['max_reversal_points']} نقطة
• نسبة العائد إلى المخاطرة: ≥ {SAFETY_FILTERS['min_risk_reward']}
• RSI بين {SAFETY_FILTERS['rsi_min']}-{SAFETY_FILTERS['rsi_max']}: {'✅' if SAFETY_FILTERS['rsi_min'] <= rsi <= SAFETY_FILTERS['rsi_max'] else '❌'}
• فلاتر الأمان: {'✅ مستوفاة' if safety_passed else f'❌ {safety_reason}'}

<b>🕒 الوقت:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC - {datetime.utcnow().strftime('%d-%m-%Y')}
<b>⏱️ الفريم:</b> {timeframe}
<b>📊 الرمز:</b> {symbol}"""

    return message

def send_telegram_message(message: str) -> bool:
    """إرسال رسالة إلى Telegram مع معالجة محسنة للأخطاء"""
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
            logger.info("✅ تم إرسال الرسالة بنجاح")
            return True
        else:
            logger.error(f"❌ فشل إرسال الرسالة: {response.status_code} - {response.text[:200]}")
            return False
    
    except Exception as e:
        logger.error(f"❌ خطأ في إرسال الرسالة: {e}")
        return False

def is_duplicate_alert(alert_data: str) -> bool:
    """فحص التنبيهات المكررة مع تنظيف الكاش"""
    try:
        current_time = datetime.utcnow().timestamp()
        alert_hash = hash(alert_data)
        
        # تنظيف الكاش من البيانات القديمة
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

def check_rate_limit(symbol: str, timeframe: str) -> bool:
    """فحص حد المعدل لتجنب الإرسال المفرط"""
    try:
        key = f"{symbol}|{timeframe}"
        current_time = time.time()
        
        if key in _last_send and (current_time - _last_send[key]) < MIN_GAP_SEC:
            return False  # لم يمر الوقت الكافي
        
        _last_send[key] = current_time
        return True  # يمكن الإرسال
    
    except Exception as e:
        logger.error(f"خطأ في فحص المعدل: {e}")
        return True  # في حالة الخطأ، نسمح بالإرسال

async def process_alert(raw_text: str):
    """معالجة التنبيه الرئيسية"""
    try:
        # تحليل البيانات
        kv_data = parse_kv(raw_text)
        normalized_data = normalize_data(kv_data)
        
        symbol = normalized_data.get('SYMB', '')
        timeframe = normalized_data.get('TF', '')
        close = normalized_data.get('C')
        
        # فحص البيانات الأساسية
        if not symbol or not timeframe or close is None:
            logger.warning("⚠️ بيانات أساسية مفقودة - تم تجاهل التنبيه")
            return
        
        # فحص حد المعدل
        if not check_rate_limit(symbol, timeframe):
            logger.info(f"⏳ تجاهل تنبيه مكرر لـ {symbol} {timeframe}")
            return
        
        logger.info(f"🔄 معالجة تنبيه لـ {symbol} {timeframe}")
        
        # تطبيق فلاتر الأمان
        safety_passed, safety_reason = apply_safety_filters(normalized_data)
        
        # بناء prompt التحليل
        analysis_prompt = build_analysis_prompt(normalized_data)
        
        # استدعاء خدمات الذكاء الاصطناعي بشكل متوازي
        logger.info("🤖 استدعاء خدمات الذكاء الاصطناعي...")
        
        loop = asyncio.get_event_loop()
        
        # تشغيل متوازي للتحليلات
        openai_task = loop.run_in_executor(None, ask_openai, analysis_prompt)
        xai_task = loop.run_in_executor(None, ask_xai, analysis_prompt)
        claude_task = loop.run_in_executor(None, ask_claude, analysis_prompt)
        
        # انتظار النتائج
        (openai_success, openai_text), (xai_success, xai_text), (claude_success, claude_text) = await asyncio.gather(
            openai_task, xai_task, claude_task
        )
        
        # استخراج القرارات والأسباب
        openai_decision, openai_reason = extract_decision_and_reason(openai_text) if openai_success else ("خطأ", openai_text)
        xai_decision, xai_reason = extract_decision_and_reason(xai_text) if xai_success else ("خطأ", xai_text)
        claude_decision, claude_reason = extract_decision_and_reason(claude_text) if claude_success else ("خطأ", claude_text)
        
        logger.info(f"📊 نتائج التحليل - OpenAI: {openai_decision}, xAI: {xai_decision}, Claude: {claude_decision}")
        
        # تنسيق الرسالة الشاملة
        message = format_comprehensive_message(
            normalized_data,
            openai_decision, openai_reason,
            xai_decision, xai_reason,
            claude_decision, claude_reason,
            safety_passed, safety_reason
        )
        
        # إرسال الرسالة
        success = await loop.run_in_executor(None, send_telegram_message, message)
        
        if success:
            logger.info(f"✅ تم معالجة وإرسال تنبيه {symbol} {timeframe} بنجاح")
        else:
            logger.error(f"❌ فشل في إرسال تنبيه {symbol} {timeframe}")
    
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة التنبيه: {e}")

@app.get("/")
async def root():
    """الصفحة الرئيسية مع معلومات شاملة"""
    return {
        "ok": True,
        "service": "Shinzooh Trading Bot - Perfect Final",
        "version": "8.0.0",
        "status": "running",
        "ai_engines": {
            "OpenAI": "✅ متاح" if OPENAI_API_KEY else "❌ غير متاح",
            "xAI": "✅ متاح" if XAI_API_KEY else "❌ غير متاح",
            "Claude": "✅ متاح" if CLAUDE_API_KEY else "❌ غير متاح"
        },
        "telegram": {
            "configured": "✅ مُعد" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "❌ غير مُعد"
        },
        "cache_info": {
            "alert_cache_size": len(alert_cache),
            "rate_limit_cache_size": len(_last_send)
        },
        "safety_filters": SAFETY_FILTERS,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """فحص صحة النظام المتقدم"""
    return {
        "status": "healthy",
        "uptime": "running",
        "cache_sizes": {
            "alerts": len(alert_cache),
            "rate_limits": len(_last_send)
        },
        "api_status": {
            "openai": "configured" if OPENAI_API_KEY else "missing",
            "xai": "configured" if XAI_API_KEY else "missing",
            "claude": "configured" if CLAUDE_API_KEY else "missing"
        },
        "telegram_status": "configured" if (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID) else "missing",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/webhook")
async def webhook_handler(request: Request):
    """معالج التنبيهات الرئيسي المحسن"""
    try:
        body = await request.body()
        data_text = body.decode('utf-8', errors='ignore')
        
        logger.info(f"📨 تم استقبال تنبيه: {data_text[:150]}...")
        
        # فحص التكرار
        if is_duplicate_alert(data_text):
            logger.info("⏭️ تنبيه مكرر - تم تجاهله")
            return {"status": "ignored", "reason": "duplicate_alert", "timestamp": datetime.utcnow().isoformat()}
        
        # معالجة التنبيه في الخلفية
        asyncio.create_task(process_alert(data_text))
        
        return {
            "status": "received",
            "message": "تم استقبال التنبيه وبدء المعالجة",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"❌ خطأ في معالج التنبيهات: {e}")
        raise HTTPException(status_code=500, detail=f"خطأ في معالجة التنبيه: {str(e)}")

@app.post("/test")
async def test_endpoint(request: Request):
    """نقطة اختبار شاملة"""
    try:
        test_data = await request.json()
        
        # بناء تنبيه اختبار
        sample_alert = (
            f"SYMB={test_data.get('symbol', 'XAUUSD')},"
            f"TF={test_data.get('timeframe', '5m')},"
            f"C={test_data.get('close', 2652)},"
            f"RSI={test_data.get('rsi', 65)},"
            f"EMA={test_data.get('ema', 2649)},"
            f"MACD={test_data.get('macd', 0.15)},"
            f"CSD_UP={test_data.get('csd_up', 1.2)},"
            f"CSD_DN={test_data.get('csd_down', 0.3)},"
            f"BOS_BULL={test_data.get('bos_bull', 1)},"
            f"PREMIUM={test_data.get('premium', 0)},"
            f"DISCOUNT={test_data.get('discount', 1)},"
            f"ATR14={test_data.get('atr', 2.5)}"
        )
        
        logger.info("🧪 بدء اختبار شامل للنظام...")
        
        # معالجة التنبيه الاختبار
        await process_alert(sample_alert)
        
        return {
            "status": "success",
            "message": "تم إجراء اختبار شامل للنظام",
            "test_data": test_data,
            "sample_alert": sample_alert,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"❌ خطأ في الاختبار: {e}")
        raise HTTPException(status_code=500, detail=f"خطأ في الاختبار: {str(e)}")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    logger.info(f"🚀 بدء تشغيل Shinzooh Trading Bot على المنفذ {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


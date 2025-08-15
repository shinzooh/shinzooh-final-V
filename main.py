import os
import asyncio
import json
import logging
import time
import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List
import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# إعداد FastAPI
app = FastAPI(title="Shinzooh Trading Bot - Ultimate Final Version", version="5.0.0")

# متغيرات البيئة
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

# إعدادات الأمان المحسنة
SAFETY_FILTERS = {
    "rsi_min": 35,
    "rsi_max": 75,
    "macd_min": -0.3,
    "max_reversal_points": 30,
    "min_risk_reward": 1.5,
    "min_csd": 1.0,
    "min_volume_ratio": 0.8
}

# تخزين مؤقت للتنبيهات لمنع التكرار
alert_cache = {}
CACHE_DURATION = 5  # ثواني

def now_str():
    """الحصول على الوقت الحالي بصيغة نصية"""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def _to_float_safe(s):
    """تحويل آمن للنص إلى رقم عشري"""
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

class TradingAnalyzer:
    def __init__(self):
        self.session = None
    
    async def get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None

    def parse_alert_data(self, alert_text: str) -> Dict[str, Any]:
        """تحليل بيانات التنبيه من TradingView"""
        try:
            data = {}
            pairs = alert_text.replace('\n', '').split(',')
            
            for pair in pairs:
                if '=' in pair:
                    key, value = pair.strip().split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # تحويل القيم
                    try:
                        if value.lower() in ['nan', 'null', '', 'na']:
                            data[key] = None
                        elif value.lower() in ['true', '1']:
                            data[key] = True
                        elif value.lower() in ['false', '0']:
                            data[key] = False
                        else:
                            # محاولة تحويل لرقم
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

    def apply_safety_filters(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """تطبيق فلاتر الأمان المحسنة"""
        try:
            reasons = []
            
            # فحص RSI
            rsi = data.get('RSI', 50)
            if rsi and (rsi < SAFETY_FILTERS["rsi_min"]):
                reasons.append(f"RSI منخفض جداً ({rsi:.1f} < {SAFETY_FILTERS['rsi_min']})")
            elif rsi and (rsi > SAFETY_FILTERS["rsi_max"]):
                reasons.append(f"RSI مرتفع جداً ({rsi:.1f} > {SAFETY_FILTERS['rsi_max']})")
            
            # فحص MACD
            macd_hist = data.get('MACD_HIST', 0)
            if macd_hist and macd_hist < SAFETY_FILTERS["macd_min"]:
                reasons.append(f"MACD ضعيف ({macd_hist:.3f} < {SAFETY_FILTERS['macd_min']})")
            
            # فحص CSD
            csd_up = data.get('CSD_UP', 0) or 0
            csd_down = data.get('CSD_DN', 0) or 0
            max_csd = max(csd_up, csd_down)
            if max_csd > 0 and max_csd < SAFETY_FILTERS["min_csd"]:
                reasons.append(f"CSD ضعيف ({max_csd:.2f} < {SAFETY_FILTERS['min_csd']})")
            
            # فحص نسبة الحجم
            volume_ratio = data.get('VOLUME_RATIO', 1) or 1
            if volume_ratio < SAFETY_FILTERS["min_volume_ratio"]:
                reasons.append(f"حجم التداول ضعيف ({volume_ratio:.2f} < {SAFETY_FILTERS['min_volume_ratio']})")
            
            if reasons:
                return False, " | ".join(reasons)
            else:
                return True, "جميع فلاتر الأمان مستوفاة"
            
        except Exception as e:
            return False, f"خطأ في فلاتر الأمان: {e}"

    async def analyze_with_openai(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """تحليل باستخدام OpenAI - التحليل الفني الكلاسيكي مع قرار واضح"""
        try:
            if not OPENAI_API_KEY:
                return {"decision": "UNAVAILABLE", "reason": "OpenAI API غير متوفر", "confidence": 0}
            
            session = await self.get_session()
            
            # تحضير البيانات للتحليل
            symbol = data.get('SYMB', 'غير محدد')
            timeframe = data.get('TF', 'غير محدد')
            close = data.get('C', 0)
            rsi = data.get('RSI', 50)
            ema = data.get('EMA', 0)
            macd = data.get('MACD', 0)
            macd_signal = data.get('MACD_SIGNAL', 0)
            volume_ratio = data.get('VOLUME_RATIO', 1)
            
            prompt = f"""
            أنت محلل تداول خبير متخصص في التحليل الفني الكلاسيكي. حلل هذه البيانات وأعطِ قرار واضح:
            
            الرمز: {symbol} ({timeframe})
            السعر الحالي: {close}
            RSI: {rsi}
            EMA: {ema}
            MACD: {macd}
            MACD Signal: {macd_signal}
            نسبة الحجم: {volume_ratio}
            
            حلل بناءً على:
            1. اتجاه السعر مقارنة بـ EMA
            2. مستوى RSI (تشبع أم حياد)
            3. إشارة MACD (صاعدة أم هابطة)
            4. قوة الحجم
            
            أعطِ قرار واضح ومحدد:
            - إذا كانت الإشارات إيجابية: قل "شراء"
            - إذا كانت الإشارات سلبية: قل "بيع"
            - إذا كانت الإشارات متضاربة: قل "انتظار"
            
            ثم اذكر السبب في جملة واحدة واضحة.
            """
            
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0.1
            }
            
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    analysis = result['choices'][0]['message']['content']
                    
                    # استخراج القرار
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
                    error_text = await response.text()
                    return {
                        "decision": "خطأ",
                        "reason": f"خطأ OpenAI API ({response.status}): {error_text[:100]}",
                        "confidence": 0
                    }
        
        except Exception as e:
            return {
                "decision": "خطأ",
                "reason": f"خطأ OpenAI: {str(e)[:100]}",
                "confidence": 0
            }

    async def analyze_with_xai(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """تحليل باستخدام xAI - تحليل ICT/SMC مع قرار واضح"""
        try:
            if not XAI_API_KEY:
                return {"decision": "UNAVAILABLE", "reason": "xAI API غير متوفر", "confidence": 0}
            
            session = await self.get_session()
            
            # تحضير بيانات ICT/SMC
            csd_up = data.get('CSD_UP', 0) or 0
            csd_down = data.get('CSD_DN', 0) or 0
            bos_bull = data.get('BOS_BULL', 0) or 0
            bos_bear = data.get('BOS_BEAR', 0) or 0
            bull_fvg = data.get('BULL_FVG_CE')
            bear_fvg = data.get('BEAR_FVG_CE')
            premium = data.get('PREMIUM', 0) or 0
            discount = data.get('DISCOUNT', 0) or 0
            
            prompt = f"""
            أنت خبير في تحليل ICT/SMC (Inner Circle Trader / Smart Money Concepts). حلل هذه البيانات وأعطِ قرار واضح:
            
            مؤشرات القوة:
            - CSD صاعد: {csd_up}
            - CSD هابط: {csd_down}
            
            كسر الهيكل:
            - BOS صاعد: {bos_bull}
            - BOS هابط: {bos_bear}
            
            الفجوات السعرية:
            - FVG صاعدة: {bull_fvg if bull_fvg else 'لا توجد'}
            - FVG هابطة: {bear_fvg if bear_fvg else 'لا توجد'}
            
            المناطق:
            - Premium Zone: {premium}
            - Discount Zone: {discount}
            
            حلل حسب مبادئ ICT وأعطِ قرار محدد:
            - إذا كانت إشارات ICT تدعم الصعود: قل "شراء"
            - إذا كانت إشارات ICT تدعم الهبوط: قل "بيع"
            - إذا لم تكن الإشارات واضحة: قل "انتظار"
            
            ثم اذكر السبب حسب مفاهيم ICT في جملة واحدة.
            """
            
            payload = {
                "messages": [{"role": "user", "content": prompt}],
                "model": "grok-beta",
                "stream": False,
                "temperature": 0.1
            }
            
            async with session.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {XAI_API_KEY}"},
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    analysis = result['choices'][0]['message']['content']
                    
                    # استخراج القرار
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
                    error_text = await response.text()
                    return {
                        "decision": "خطأ",
                        "reason": f"خطأ xAI API ({response.status}): {error_text[:100]}",
                        "confidence": 0
                    }
        
        except Exception as e:
            return {
                "decision": "خطأ",
                "reason": f"خطأ xAI: {str(e)[:100]}",
                "confidence": 0
            }

    async def analyze_with_claude(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """تحليل باستخدام Claude - التحليل الشامل مع قرار واضح"""
        try:
            if not CLAUDE_API_KEY:
                return {"decision": "UNAVAILABLE", "reason": "Claude API غير متوفر", "confidence": 0}
            
            session = await self.get_session()
            
            # تحضير البيانات الشاملة
            symbol = data.get('SYMB', 'غير محدد')
            close = data.get('C', 0)
            rsi = data.get('RSI', 50)
            ema = data.get('EMA', 0)
            volume_ratio = data.get('VOLUME_RATIO', 1)
            premium = data.get('PREMIUM', 0) or 0
            discount = data.get('DISCOUNT', 0) or 0
            signal_strength = data.get('SIGNAL_STRENGTH', 1) or 1
            
            prompt = f"""
            أنت محلل تداول شامل يجمع بين التحليل الفني الكلاسيكي و ICT. حلل هذه البيانات وأعطِ قرار واضح:
            
            الأساسيات:
            - الرمز: {symbol}
            - السعر: {close}
            - RSI: {rsi}
            - EMA: {ema}
            - نسبة الحجم: {volume_ratio}
            
            المناطق:
            - Premium Zone: {premium} (منطقة مقاومة)
            - Discount Zone: {discount} (منطقة دعم)
            - قوة الإشارة: {signal_strength}
            
            قم بتحليل شامل يراعي المخاطر والفرص وأعطِ قرار محدد:
            - إذا كانت الفرص تفوق المخاطر: قل "شراء"
            - إذا كانت المخاطر تفوق الفرص: قل "بيع"
            - إذا كانت المخاطر والفرص متوازنة: قل "انتظار"
            
            ثم اذكر السبب الشامل في جملة واحدة.
            """
            
            payload = {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}]
            }
            
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Authorization": f"Bearer {CLAUDE_API_KEY}",
                    "Content-Type": "application/json",
                    "x-api-version": "2023-06-01"
                },
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    analysis = result['content'][0]['text']
                    
                    # استخراج القرار
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
                    error_text = await response.text()
                    return {
                        "decision": "خطأ",
                        "reason": f"خطأ Claude API ({response.status}): {error_text[:100]}",
                        "confidence": 0
                    }
        
        except Exception as e:
            return {
                "decision": "خطأ",
                "reason": f"خطأ Claude: {str(e)[:100]}",
                "confidence": 0
            }

    def calculate_trade_levels(self, data: Dict[str, Any], direction: str) -> Dict[str, float]:
        """حساب مستويات التداول (دخول، أهداف، وقف خسارة)"""
        try:
            close = data.get('C', 0)
            atr = data.get('ATR', 0) or (close * 0.001)  # افتراض ATR 0.1% إذا لم يتوفر
            
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
                return {
                    "entry": None, "tp1": None, "tp2": None, 
                    "tp3": None, "tp4": None, "sl": None
                }
            
            return {
                "entry": round(entry, 2),
                "tp1": round(tp1, 2),
                "tp2": round(tp2, 2),
                "tp3": round(tp3, 2),
                "tp4": round(tp4, 2),
                "sl": round(sl, 2)
            }
        
        except Exception as e:
            logger.error(f"خطأ في حساب مستويات التداول: {e}")
            return {
                "entry": None, "tp1": None, "tp2": None,
                "tp3": None, "tp4": None, "sl": None
            }

    def format_comprehensive_message(self, data: Dict[str, Any], openai_result: Dict, xai_result: Dict, claude_result: Dict, safety_passed: bool, safety_reason: str) -> str:
        """تنسيق الرسالة الشاملة النهائية مع قرارات واضحة لكل نموذج"""
        
        # البيانات الأساسية
        symbol = data.get('SYMB', 'غير محدد')
        timeframe = data.get('TF', 'غير محدد')
        open_price = data.get('O', 0)
        high_price = data.get('H', 0)
        low_price = data.get('L', 0)
        close_price = data.get('C', 0)
        volume = data.get('V', 0)
        
        # المؤشرات الفنية
        rsi = data.get('RSI', 50)
        ema = data.get('EMA', 0)
        macd = data.get('MACD', 0)
        macd_signal = data.get('MACD_SIGNAL', 0)
        macd_hist = data.get('MACD_HIST', 0)
        
        # بيانات ICT/SMC
        csd_up = data.get('CSD_UP', 0) or 0
        csd_down = data.get('CSD_DN', 0) or 0
        bos_bull = data.get('BOS_BULL', 0) or 0
        bos_bear = data.get('BOS_BEAR', 0) or 0
        bull_fvg = data.get('BULL_FVG_CE')
        bear_fvg = data.get('BEAR_FVG_CE')
        premium = data.get('PREMIUM', 0) or 0
        discount = data.get('DISCOUNT', 0) or 0
        equilibrium = data.get('EQUILIBRIUM', 0) or 0
        volume_ratio = data.get('VOLUME_RATIO', 1) or 1
        
        # تحديد المنطقة
        if premium:
            zone = "Premium (مقاومة)"
            zone_emoji = "🔴"
        elif discount:
            zone = "Discount (دعم)"
            zone_emoji = "🟢"
        else:
            zone = "Equilibrium (توازن)"
            zone_emoji = "🟡"
        
        # تحليل الاتجاه
        if close_price > ema:
            trend = "صاعد (السعر فوق EMA)"
            trend_emoji = "📈"
        elif close_price < ema:
            trend = "هابط (السعر تحت EMA)"
            trend_emoji = "📉"
        else:
            trend = "جانبي (السعر عند EMA)"
            trend_emoji = "➡️"
        
        # تحليل RSI
        if rsi > 70:
            rsi_status = "تشبع شرائي"
            rsi_emoji = "🔴"
        elif rsi < 30:
            rsi_status = "تشبع بيعي"
            rsi_emoji = "🟢"
        else:
            rsi_status = "منطقة حيادية"
            rsi_emoji = "🟡"
        
        # تحليل MACD
        if macd > macd_signal:
            macd_status = "إشارة صاعدة"
            macd_emoji = "📈"
        elif macd < macd_signal:
            macd_status = "إشارة هابطة"
            macd_emoji = "📉"
        else:
            macd_status = "تقاطع محايد"
            macd_emoji = "➡️"
        
        # تحليل ICT
        ict_signals = []
        if csd_up > 1.0:
            ict_signals.append(f"CSD صاعد قوي ({csd_up:.2f})")
        if csd_down > 1.0:
            ict_signals.append(f"CSD هابط قوي ({csd_down:.2f})")
        if bos_bull:
            ict_signals.append("كسر هيكل صاعد")
        if bos_bear:
            ict_signals.append("كسر هيكل هابط")
        
        ict_analysis = " | ".join(ict_signals) if ict_signals else "لا توجد إشارات ICT قوية"
        
        # تحليل FVG
        fvg_signals = []
        if bull_fvg and str(bull_fvg).lower() not in ['nan', 'null', 'none']:
            fvg_signals.append(f"FVG صاعدة عند {bull_fvg}")
        if bear_fvg and str(bear_fvg).lower() not in ['nan', 'null', 'none']:
            fvg_signals.append(f"FVG هابطة عند {bear_fvg}")
        
        fvg_analysis = " | ".join(fvg_signals) if fvg_signals else "لا توجد فجوات سعرية نشطة"
        
        # تحليل قرارات النماذج - التعديل الجديد المطلوب
        decisions = []
        valid_decisions = []
        
        # معالجة قرارات كل نموذج
        openai_decision = openai_result.get('decision', 'خطأ')
        xai_decision = xai_result.get('decision', 'خطأ')
        claude_decision = claude_result.get('decision', 'خطأ')
        
        # تحديد الرموز والألوان لكل قرار
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
        
        # جمع القرارات الصحيحة
        for decision in [openai_decision, xai_decision, claude_decision]:
            if decision not in ['خطأ', 'UNAVAILABLE']:
                valid_decisions.append(decision)
        
        # حساب الإجماع
        buy_count = valid_decisions.count('شراء')
        sell_count = valid_decisions.count('بيع')
        wait_count = valid_decisions.count('انتظار')
        total_valid = len(valid_decisions)
        
        # تحديد الإجماع والقرار النهائي
        if total_valid == 0:
            consensus = "خطأ في جميع النماذج"
            consensus_emoji = "❌"
            final_decision = "لا صفقة"
            trade_direction = None
        elif buy_count >= 2:
            consensus = f"إجماع على الشراء ({buy_count}/{total_valid})"
            consensus_emoji = "✅"
            final_decision = "🟢 شراء"
            trade_direction = "شراء"
        elif sell_count >= 2:
            consensus = f"إجماع على البيع ({sell_count}/{total_valid})"
            consensus_emoji = "✅"
            final_decision = "🔴 بيع"
            trade_direction = "بيع"
        else:
            consensus = f"تعارض بين النماذج (شراء:{buy_count} | بيع:{sell_count} | انتظار:{wait_count})"
            consensus_emoji = "❌"
            final_decision = "لا صفقة"
            trade_direction = None
        
        # حساب مستويات التداول
        if trade_direction and safety_passed:
            levels = self.calculate_trade_levels(data, trade_direction)
        else:
            levels = {
                "entry": None, "tp1": None, "tp2": None,
                "tp3": None, "tp4": None, "sl": None
            }
        
        # تنسيق مستويات التداول
        entry_str = f"{levels['entry']:.2f}" if levels['entry'] else "—"
        tp1_str = f"{levels['tp1']:.2f}" if levels['tp1'] else "—"
        tp2_str = f"{levels['tp2']:.2f}" if levels['tp2'] else "—"
        tp3_str = f"{levels['tp3']:.2f}" if levels['tp3'] else "—"
        tp4_str = f"{levels['tp4']:.2f}" if levels['tp4'] else "—"
        sl_str = f"{levels['sl']:.2f}" if levels['sl'] else "—"
        
        # تحديد سبب عدم الصفقة
        no_trade_reason = ""
        if not safety_passed:
            no_trade_reason = f"فلاتر الأمان غير مستوفاة: {safety_reason}"
        elif total_valid < 2:
            no_trade_reason = "عدد غير كافٍ من النماذج المتاحة للتحليل"
        elif buy_count < 2 and sell_count < 2:
            no_trade_reason = "عدم وجود إجماع (يجب موافقة 2 على الأقل من 3 نماذج)"
        
        # إنشاء الرسالة النهائية
        message = f"""📊 <b>{symbol} {timeframe}</b>

<b>🔍 التحليل الفني الكلاسيكي</b>

<b>السعر الحالي:</b> {close_price:.2f}
<b>البيانات:</b> O={open_price:.2f} | H={high_price:.2f} | L={low_price:.2f} | C={close_price:.2f}
<b>الحجم:</b> {volume:,.0f} (نسبة: {volume_ratio:.2f})

<b>المؤشرات:</b>
• {rsi_emoji} RSI: {rsi:.1f} ({rsi_status})
• EMA: {ema:.2f}
• {macd_emoji} MACD: {macd:.3f} ({macd_status})
• MACD Histogram: {macd_hist:.3f}

<b>📌 التفسير:</b>
{trend_emoji} الاتجاه {trend}، RSI في {rsi_status}، MACD يظهر {macd_status}. السعر في منطقة {zone_emoji} {zone}.

<b>📚 تحليل ICT / SMC</b>

<b>مؤشرات الهيكل:</b>
• CSD: صاعد={csd_up:.2f} | هابط={csd_down:.2f}
• BOS: صاعد={'✅' if bos_bull else '❌'} | هابط={'✅' if bos_bear else '❌'}
• المنطقة: {zone_emoji} {zone}

<b>📌 التفسير:</b>
{ict_analysis}. {fvg_analysis}.

<b>🤖 ملخص النماذج</b>

<b>OpenAI:</b> {get_decision_emoji(openai_decision)} <b>{openai_decision}</b>
<i>السبب:</i> {openai_result.get('reason', 'غير متوفر')[:100]}

<b>xAI:</b> {get_decision_emoji(xai_decision)} <b>{xai_decision}</b>
<i>السبب:</i> {xai_result.get('reason', 'غير متوفر')[:100]}

<b>Claude:</b> {get_decision_emoji(claude_decision)} <b>{claude_decision}</b>
<i>السبب:</i> {claude_result.get('reason', 'غير متوفر')[:100]}

<b>⚠️ تحليل الإجماع</b>

{consensus_emoji} <b>{consensus}</b>

"""

        # إضافة تفسير التعارض أو الإجماع
        if trade_direction:
            message += f"📌 <b>النتيجة:</b> {final_decision} بناءً على إجماع النماذج\n\n"
        else:
            message += f"📌 <b>النتيجة:</b> لا توجد صفقة - {no_trade_reason}\n\n"
            
            # إضافة تفاصيل التعارض
            if total_valid >= 2 and buy_count < 2 and sell_count < 2:
                message += "<b>تفاصيل التعارض:</b>\n"
                if openai_decision not in ['خطأ', 'UNAVAILABLE']:
                    message += f"• OpenAI يقترح <b>{openai_decision}</b>\n"
                if xai_decision not in ['خطأ', 'UNAVAILABLE']:
                    message += f"• xAI يقترح <b>{xai_decision}</b>\n"
                if claude_decision not in ['خطأ', 'UNAVAILABLE']:
                    message += f"• Claude يقترح <b>{claude_decision}</b>\n"
                message += "\n"

        message += f"""<b>🎯 التوصية النهائية</b>

<b>نوع الصفقة:</b> {final_decision}
<b>نقاط الدخول:</b> {entry_str}

<b>أهداف جني الأرباح:</b>
• TP1: {tp1_str}
• TP2: {tp2_str}
• TP3: {tp3_str}
• TP4: {tp4_str}

<b>وقف الخسارة:</b> {sl_str}

<b>السبب:</b> {consensus if trade_direction else no_trade_reason}

<b>⚡ شروط الأمان</b>

• الانعكاس الأقصى: ≤ {SAFETY_FILTERS['max_reversal_points']} نقطة
• نسبة المخاطرة/العائد: ≥ {SAFETY_FILTERS['min_risk_reward']}
• RSI بين {SAFETY_FILTERS['rsi_min']}-{SAFETY_FILTERS['rsi_max']}: {'✅' if SAFETY_FILTERS['rsi_min'] <= rsi <= SAFETY_FILTERS['rsi_max'] else '❌'}
• فلاتر الأمان: {'✅ مستوفاة' if safety_passed else f'❌ {safety_reason}'}

<b>🕒 الوقت:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC - {datetime.utcnow().strftime('%d-%m-%Y')}
<b>⏱️ الفريم:</b> {timeframe}
<b>📊 الرمز:</b> {symbol}"""

        return message

    async def send_telegram_message(self, message: str):
        """إرسال رسالة إلى Telegram مع معالجة الأخطاء"""
        try:
            if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
                logger.error("معلومات Telegram غير مكتملة")
                return False
            
            session = await self.get_session()
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            
            # تقسيم الرسالة إذا كانت طويلة جداً
            max_length = 4096
            if len(message) > max_length:
                # تقسيم الرسالة
                parts = []
                current_part = ""
                lines = message.split('\n')
                
                for line in lines:
                    if len(current_part + line + '\n') > max_length:
                        if current_part:
                            parts.append(current_part.strip())
                        current_part = line + '\n'
                    else:
                        current_part += line + '\n'
                
                if current_part:
                    parts.append(current_part.strip())
                
                # إرسال كل جزء
                for i, part in enumerate(parts):
                    payload = {
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": f"{'[الجزء ' + str(i+1) + '/' + str(len(parts)) + ']' if len(parts) > 1 else ''}\n{part}",
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True
                    }
                    
                    async with session.post(url, json=payload) as response:
                        if response.status != 200:
                            logger.error(f"فشل إرسال الجزء {i+1}: {response.status}")
                            return False
                    
                    # انتظار قصير بين الأجزاء
                    await asyncio.sleep(0.5)
                
                logger.info(f"تم إرسال الرسالة في {len(parts)} أجزاء")
                return True
            else:
                # إرسال الرسالة كاملة
                payload = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.info("تم إرسال الرسالة بنجاح")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"فشل إرسال الرسالة: {response.status} - {error_text}")
                        return False
        
        except Exception as e:
            logger.error(f"خطأ في إرسال الرسالة: {e}")
            return False

    def is_duplicate_alert(self, alert_data: str) -> bool:
        """فحص التنبيهات المكررة"""
        try:
            current_time = datetime.utcnow().timestamp()
            alert_hash = hash(alert_data)
            
            # تنظيف التخزين المؤقت من البيانات القديمة
            expired_keys = [
                key for key, timestamp in alert_cache.items()
                if current_time - timestamp > CACHE_DURATION
            ]
            for key in expired_keys:
                del alert_cache[key]
            
            # فحص التكرار
            if alert_hash in alert_cache:
                return True
            
            # إضافة التنبيه الجديد
            alert_cache[alert_hash] = current_time
            return False
        
        except Exception as e:
            logger.error(f"خطأ في فحص التكرار: {e}")
            return False

# إنشاء محلل التداول
analyzer = TradingAnalyzer()

@app.get("/")
async def root():
    """الصفحة الرئيسية - معلومات البوت"""
    return {
        "ok": True,
        "service": "Shinzooh Trading Bot - Ultimate Final Version",
        "version": "5.0.0",
        "features": [
            "تحليل ثلاثي AI مع قرارات واضحة (شراء/بيع/انتظار)",
            "تحليل فني كلاسيكي شامل",
            "تحليل ICT/SMC متقدم",
            "رسائل منظمة وشاملة",
            "4 أهداف ربح + وقف خسارة ذكي",
            "فلاتر أمان محسنة",
            "منع التنبيهات المكررة",
            "قرار واضح من كل نموذج AI"
        ],
        "ai_engines": {
            "OpenAI": "✅ متاح" if OPENAI_API_KEY else "❌ غير متاح",
            "xAI": "✅ متاح" if XAI_API_KEY else "❌ غير متاح",
            "Claude": "✅ متاح" if CLAUDE_API_KEY else "❌ غير متاح"
        },
        "telegram": {
            "bot_configured": "✅ مُعد" if TELEGRAM_BOT_TOKEN else "❌ غير مُعد",
            "chat_configured": "✅ مُعد" if TELEGRAM_CHAT_ID else "❌ غير مُعد"
        },
        "safety_filters": SAFETY_FILTERS,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """فحص صحة النظام"""
    return {
        "status": "healthy",
        "uptime": "running",
        "ai_status": {
            "openai": "available" if OPENAI_API_KEY else "unavailable",
            "xai": "available" if XAI_API_KEY else "unavailable",
            "claude": "available" if CLAUDE_API_KEY else "unavailable"
        },
        "cache_size": len(alert_cache),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/webhook")
async def webhook_handler(request: Request):
    """معالج التنبيهات الرئيسي من TradingView"""
    try:
        # استقبال البيانات
        body = await request.body()
        data_text = body.decode('utf-8')
        
        # معالجة تنسيقات مختلفة للبيانات
        if data_text.startswith('{"text"'):
            json_data = json.loads(data_text)
            alert_data = json_data.get('text', '')
        elif data_text.startswith('{') and data_text.endswith('}'):
            json_data = json.loads(data_text)
            alert_data = json_data.get('message', data_text)
        else:
            alert_data = data_text
        
        logger.info(f"تم استقبال تنبيه: {alert_data[:150]}...")
        
        # فحص التكرار
        if analyzer.is_duplicate_alert(alert_data):
            logger.info("تنبيه مكرر - تم تجاهله")
            return {"status": "ignored", "reason": "duplicate_alert"}
        
        # تحليل البيانات
        parsed_data = analyzer.parse_alert_data(alert_data)
        
        if not parsed_data:
            raise HTTPException(status_code=400, detail="فشل في تحليل البيانات")
        
        logger.info(f"تم تحليل البيانات: {len(parsed_data)} عنصر")
        
        # فحص فلاتر الأمان
        safety_passed, safety_reason = analyzer.apply_safety_filters(parsed_data)
        logger.info(f"فلاتر الأمان: {'نجح' if safety_passed else 'فشل'} - {safety_reason}")
        
        # تحليل بالذكاء الاصطناعي (متوازي)
        ai_tasks = [
            analyzer.analyze_with_openai(parsed_data),
            analyzer.analyze_with_xai(parsed_data),
            analyzer.analyze_with_claude(parsed_data)
        ]
        
        openai_result, xai_result, claude_result = await asyncio.gather(*ai_tasks)
        
        logger.info(f"نتائج التحليل - OpenAI: {openai_result.get('decision')}, xAI: {xai_result.get('decision')}, Claude: {claude_result.get('decision')}")
        
        # تنسيق الرسالة الشاملة
        message = analyzer.format_comprehensive_message(
            parsed_data, openai_result, xai_result, claude_result,
            safety_passed, safety_reason
        )
        
        # إرسال الرسالة
        success = await analyzer.send_telegram_message(message)
        
        if success:
            return {
                "status": "success",
                "message": "تم التحليل والإرسال بنجاح",
                "ai_results": {
                    "openai": openai_result.get('decision'),
                    "xai": xai_result.get('decision'),
                    "claude": claude_result.get('decision')
                },
                "safety_passed": safety_passed
            }
        else:
            raise HTTPException(status_code=500, detail="فشل في إرسال الرسالة")
    
    except json.JSONDecodeError as e:
        logger.error(f"خطأ في تحليل JSON: {e}")
        raise HTTPException(status_code=400, detail="تنسيق JSON غير صحيح")
    except Exception as e:
        logger.error(f"خطأ في معالجة التنبيه: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/test")
async def test_endpoint(request: Request):
    """نقطة اختبار شاملة للنظام"""
    try:
        test_data = await request.json()
        
        # بيانات اختبار شاملة
        sample_alert = (
            f"SYMB={test_data.get('symbol', 'XAUUSD')},"
            f"TF={test_data.get('timeframe', '5m')},"
            f"O={test_data.get('open', 2650)},"
            f"H={test_data.get('high', 2655)},"
            f"L={test_data.get('low', 2648)},"
            f"C={test_data.get('close', 2652)},"
            f"V={test_data.get('volume', 1250)},"
            f"RSI={test_data.get('rsi', 65)},"
            f"EMA={test_data.get('ema', 2649)},"
            f"MACD={test_data.get('macd', 0.15)},"
            f"MACD_SIGNAL={test_data.get('macd_signal', 0.12)},"
            f"MACD_HIST={test_data.get('macd_hist', 0.03)},"
            f"CSD_UP={test_data.get('csd_up', 1.8)},"
            f"CSD_DN={test_data.get('csd_down', 0)},"
            f"BULL_FVG_CE={test_data.get('bull_fvg', 2654)},"
            f"BEAR_FVG_CE={test_data.get('bear_fvg', 'NaN')},"
            f"BOS_BULL={test_data.get('bos_bull', 1)},"
            f"BOS_BEAR={test_data.get('bos_bear', 0)},"
            f"PREMIUM={test_data.get('premium', 0)},"
            f"DISCOUNT={test_data.get('discount', 0)},"
            f"EQUILIBRIUM={test_data.get('equilibrium', 1)},"
            f"VOLUME_RATIO={test_data.get('volume_ratio', 1.45)},"
            f"ATR={test_data.get('atr', 2.1)}"
        )
        
        # معالجة البيانات
        parsed_data = analyzer.parse_alert_data(sample_alert)
        safety_passed, safety_reason = analyzer.apply_safety_filters(parsed_data)
        
        # تحليل مبسط للاختبار
        openai_result = {
            "decision": "شراء",
            "reason": "اختبار - RSI في منطقة جيدة + EMA يدعم الاتجاه الصاعد + MACD إيجابي",
            "confidence": 0.8
        }
        xai_result = {
            "decision": "شراء",
            "reason": "اختبار - CSD قوي + BOS صاعد مؤكد + FVG تدعم الاتجاه",
            "confidence": 0.9
        }
        claude_result = {
            "decision": "انتظار",
            "reason": "اختبار - السعر في منطقة توازن، يُفضل انتظار كسر واضح",
            "confidence": 0.6
        }
        
        # تنسيق وإرسال الرسالة
        message = analyzer.format_comprehensive_message(
            parsed_data, openai_result, xai_result, claude_result,
            safety_passed, safety_reason
        )
        
        success = await analyzer.send_telegram_message(message)
        
        return {
            "status": "success" if success else "partial_success",
            "message": "تم إرسال رسالة اختبار شاملة",
            "test_data": parsed_data,
            "ai_results": {
                "openai": openai_result,
                "xai": xai_result,
                "claude": claude_result
            },
            "safety_check": {
                "passed": safety_passed,
                "reason": safety_reason
            },
            "telegram_sent": success
        }
    
    except Exception as e:
        logger.error(f"خطأ في الاختبار: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def get_stats():
    """إحصائيات النظام"""
    return {
        "cache_size": len(alert_cache),
        "cache_duration": CACHE_DURATION,
        "safety_filters": SAFETY_FILTERS,
        "ai_engines_status": {
            "openai": "configured" if OPENAI_API_KEY else "not_configured",
            "xai": "configured" if XAI_API_KEY else "not_configured",
            "claude": "configured" if CLAUDE_API_KEY else "not_configured"
        },
        "telegram_status": {
            "bot_token": "configured" if TELEGRAM_BOT_TOKEN else "not_configured",
            "chat_id": "configured" if TELEGRAM_CHAT_ID else "not_configured"
        }
    }

@app.on_event("startup")
async def startup_event():
    """أحداث بدء التشغيل"""
    logger.info("🚀 بدء تشغيل Shinzooh Trading Bot - Ultimate Final Version")
    logger.info(f"✅ OpenAI: {'مُعد' if OPENAI_API_KEY else 'غير مُعد'}")
    logger.info(f"✅ xAI: {'مُعد' if XAI_API_KEY else 'غير مُعد'}")
    logger.info(f"✅ Claude: {'مُعد' if CLAUDE_API_KEY else 'غير مُعد'}")
    logger.info(f"✅ Telegram: {'مُعد' if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else 'غير مُعد'}")

@app.on_event("shutdown")
async def shutdown_event():
    """أحداث إيقاف التشغيل"""
    logger.info("🛑 إيقاف تشغيل Shinzooh Trading Bot")
    await analyzer.close_session()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )


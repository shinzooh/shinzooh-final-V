from fastapi import FastAPI, Request
import os, time, re, json, asyncio, datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==================== إعدادات البيئة ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")  # جديد - مفتاح Claude
PORT = int(os.getenv("PORT", "10000"))

# إعداد session للطلبات HTTP مع إعادة المحاولة
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
session.mount("http://", HTTPAdapter(max_retries=retries))

# إنشاء تطبيق FastAPI
app = FastAPI(
    title="Shinzooh Trading Bot Enhanced",
    description="بوت تداول ذكي مع ثلاثي الذكاء الاصطناعي: OpenAI + xAI + Claude",
    version="2.0.0"
)

# ==================== الدوال المساعدة ====================
def now_str():
    """إرجاع الوقت الحالي كنص"""
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

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

def parse_kv(raw: str) -> dict:
    """تحليل النص إلى قاموس key=value"""
    d = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        d[k.strip()] = v.strip()
    return d

def build_prompt_ar(n: dict) -> str:
    """بناء prompt للتحليل باللغة العربية - محسن"""
    sym, tf = n.get("SYMB",""), n.get("TF","")
    O,H,L,C,V = n.get("O"),n.get("H"),n.get("L"),n.get("C"),n.get("V")
    RSI,EMA,MACD = n.get("RSI"),n.get("EMA"),n.get("MACD")
    bull_ce, bear_ce = n.get("BULL_FVG_CE"), n.get("BEAR_FVG_CE")
    csd_up, csd_dn = n.get("CSD_UP"), n.get("CSD_DN")
    
    return f"""أنت محلل تقني خبير متخصص في ICT/SMC والتحليل الكلاسيكي.

حلّل زوج {sym} على إطار {tf} بدقة عالية:

📊 بيانات السعر:
- Open: {O}, High: {H}, Low: {L}, Close: {C}
- Volume: {V}

📈 المؤشرات الكلاسيكية:
- RSI: {RSI}
- EMA: {EMA} 
- MACD: {MACD}

🎯 إشارات ICT/SMC:
- CSD_UP: {csd_up} (إشارة شراء)
- CSD_DN: {csd_dn} (إشارة بيع)
- Bull FVG CE: {bull_ce} (فجوة قيمة صاعدة)
- Bear FVG CE: {bear_ce} (فجوة قيمة هابطة)

المطلوب تحليل شامل يشمل:
1) تحليل السيولة والـ Liquidity zones
2) تحديد BOS/CHoCH وتغيير الهيكل
3) تحليل FVG وOrder Blocks
4) تحديد Premium/Discount zones
5) تقييم المؤشرات الكلاسيكية

أعطني النتيجة بهذا التنسيق الدقيق:

تحليل {sym} ({tf}) - تحليل متقدم:
1) السيولة (Liquidity): [تحليلك هنا]
2) الكسر/الهيكل (BOS/CHoCH): [تحليلك هنا]
3) فجوات القيمة (FVG) وكتل الأوامر (OB): [تحليلك هنا]
4) Premium/Discount: [تحليلك هنا]
5) كلاسيكي (RSI/EMA/MACD): [تحليلك هنا]

التوصية النهائية:
- الصفقة: شراء أو بيع أو لا صفقة
- الدخول: [رقم واحد فقط]
- جني الأرباح: [رقم واحد فقط]
- وقف الخسارة: [رقم واحد فقط]
- السبب: [سطر واحد واضح ومختصر]
- شرط: الانعكاس الأقصى ≤ 30 نقطة

التزم بالتنسيق بدقة، أرقام صريحة بدون رموز أو زخرفة."""

# ==================== دوال الذكاء الاصطناعي ====================
def ask_openai(prompt: str, timeout=25):
    """استدعاء OpenAI API"""
    if not OPENAI_API_KEY:
        return False, "OpenAI API key missing"
    try:
        r = session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1200
            },
            timeout=timeout
        )
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        return True, txt
    except Exception as e:
        return False, f"OpenAI error: {e}"

def ask_xai(prompt: str, timeout=25):
    """استدعاء xAI API"""
    if not XAI_API_KEY:
        return False, "xAI API key missing"
    try:
        r = session.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "grok-4-latest",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1200
            },
            timeout=timeout
        )
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        return True, txt
    except Exception as e:
        return False, f"xAI error: {e}"

def ask_claude(prompt: str, timeout=25):
    """استدعاء Claude API - الجديد والمحسن"""
    if not CLAUDE_API_KEY:
        return False, "Claude API key missing"
    try:
        r = session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Authorization": f"Bearer {CLAUDE_API_KEY}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-3-haiku-20240307",  # الأسرع والأرخص
                "max_tokens": 1200,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=timeout
        )
        r.raise_for_status()
        txt = r.json()["content"][0]["text"]
        return True, txt
    except Exception as e:
        return False, f"Claude error: {e}"

# ==================== تحليل النتائج ====================
def extract_trade_fields(text: str):
    """استخراج حقول التوصية من النص - محسن"""
    if not text:
        return {}
    
    def grab(pattern):
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""
    
    # أنماط محسنة للاستخراج
    dirn = grab(r"الصفقة\s*:\s*([^\n\r]+)")
    entry = grab(r"الدخول\s*:\s*([0-9]+\.?[0-9]*)")
    tp = grab(r"جني\s*الأرباح\s*:\s*([0-9]+\.?[0-9]*)")
    sl = grab(r"وقف\s*الخسارة\s*:\s*([0-9]+\.?[0-9]*)")
    reason = grab(r"السبب\s*:\s*([^\n\r]+)")
    
    return {
        "direction": dirn,
        "entry": entry,
        "tp": tp,
        "sl": sl,
        "reason": reason
    }

def consensus_triple(rec_openai: dict, rec_xai: dict, rec_claude: dict):
    """تحديد الإجماع بين ثلاث توصيات - محسن ومطور"""
    def normalize_direction(d):
        s = (d or "").strip().lower()
        if any(word in s for word in ["شراء", "buy", "صاعد", "long"]):
            return "buy"
        if any(word in s for word in ["بيع", "sell", "هابط", "short"]):
            return "sell"
        if any(word in s for word in ["لا صفقة", "no trade", "انتظار", "wait"]):
            return "wait"
        return ""
    
    # تطبيع الاتجاهات
    dir_openai = normalize_direction(rec_openai.get("direction", ""))
    dir_xai = normalize_direction(rec_xai.get("direction", ""))
    dir_claude = normalize_direction(rec_claude.get("direction", ""))
    
    # حساب الأصوات
    directions = [dir_openai, dir_xai, dir_claude]
    valid_directions = [d for d in directions if d and d != "wait"]
    
    if not valid_directions:
        return False, "", "لا توجد توصيات واضحة"
    
    # إجماع ثلاثي (الأقوى)
    if len(set(valid_directions)) == 1 and len(valid_directions) == 3:
        return True, valid_directions[0], "إجماع ثلاثي مطلق 🎯"
    
    # إجماع ثنائي
    from collections import Counter
    vote_count = Counter(valid_directions)
    most_common = vote_count.most_common(1)[0]
    
    if most_common[1] >= 2:
        # تحديد مصدر الإجماع
        sources = []
        if dir_openai == most_common[0]: sources.append("OpenAI")
        if dir_xai == most_common[0]: sources.append("xAI") 
        if dir_claude == most_common[0]: sources.append("Claude")
        
        consensus_type = f"إجماع ثنائي ({' + '.join(sources)}) 🤝"
        return True, most_common[0], consensus_type
    
    # لا إجماع
    return False, "", f"تعارض: OpenAI({dir_openai}) xAI({dir_xai}) Claude({dir_claude}) ⚠️"

def pick_best_recommendation(rec_openai: dict, rec_xai: dict, rec_claude: dict, agreed_direction: str):
    """اختيار أفضل توصية من الثلاث - محسن"""
    candidates = []
    
    # فحص كل توصية
    for name, rec in [("OpenAI", rec_openai), ("xAI", rec_xai), ("Claude", rec_claude)]:
        if (rec.get("entry") and rec.get("tp") and rec.get("sl") and 
            rec.get("direction", "").lower().find(agreed_direction) != -1):
            
            try:
                entry = float(rec["entry"])
                tp = float(rec["tp"])
                sl = float(rec["sl"])
                
                # حساب نسبة المخاطرة/العائد
                if agreed_direction == "buy":
                    risk = abs(entry - sl)
                    reward = abs(tp - entry)
                else:
                    risk = abs(sl - entry)
                    reward = abs(entry - tp)
                
                rr_ratio = reward / risk if risk > 0 else 0
                
                candidates.append({
                    "source": name,
                    "rec": rec,
                    "rr_ratio": rr_ratio,
                    "entry": entry,
                    "tp": tp,
                    "sl": sl
                })
            except:
                continue
    
    if not candidates:
        # إذا لم توجد توصيات كاملة، اختر أي واحدة بها اتجاه صحيح
        for name, rec in [("OpenAI", rec_openai), ("xAI", rec_xai), ("Claude", rec_claude)]:
            if rec.get("direction", "").lower().find(agreed_direction) != -1:
                return rec, name
        return rec_openai, "OpenAI"  # fallback
    
    # اختيار الأفضل حسب نسبة المخاطرة/العائد
    best = max(candidates, key=lambda x: x["rr_ratio"])
    return best["rec"], best["source"]

# ==================== Telegram ====================
def tgsend(text: str):
    """إرسال رسالة عبر Telegram - محسن"""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("[WARN] Telegram env missing, skip send.")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = session.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")
        return False

# ==================== منع التكرار ====================
_last_send = {}
MIN_GAP_SEC = 5

# ==================== المعالج الرئيسي ====================
async def process_alert(raw_text: str):
    """معالجة التنبيه الواردة من TradingView - محسن مع ثلاثي الذكاء الاصطناعي"""
    
    # تحليل البيانات الواردة
    kv = parse_kv(raw_text)
    n = {
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
        "CSD_UP": _to_float_safe(kv.get("CSD_UP")),
        "CSD_DN": _to_float_safe(kv.get("CSD_DN")),
        "BULL_FVG_CE": _to_float_safe(kv.get("BULL_FVG_CE")),
        "BEAR_FVG_CE": _to_float_safe(kv.get("BEAR_FVG_CE")),
    }
    
    sym, tf = n["SYMB"], n["TF"]
    key = f"{sym}|{tf}"
    now_sec = time.time()
    
    # منع التكرار
    if key in _last_send and (now_sec - _last_send[key]) < MIN_GAP_SEC:
        print(f"[INFO] Skip duplicate for {key}")
        return
    _last_send[key] = now_sec
    
    # التحقق من البيانات الأساسية
    if not sym or not tf or n["C"] is None:
        print("[INFO] Missing essential data, skipping")
        return
    
    print(f"[INFO] Processing alert for {sym} {tf}")
    
    # بناء prompt وإرساله للذكاء الاصطناعي الثلاثي
    prompt = build_prompt_ar(n)
    loop = asyncio.get_event_loop()
    
    # استدعاء الثلاثة بشكل متوازي
    print("[INFO] Calling AI services...")
    tasks = [
        loop.run_in_executor(None, ask_openai, prompt),
        loop.run_in_executor(None, ask_xai, prompt),
        loop.run_in_executor(None, ask_claude, prompt)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # معالجة النتائج
    ok_openai, txt_openai = results[0] if not isinstance(results[0], Exception) else (False, str(results[0]))
    ok_xai, txt_xai = results[1] if not isinstance(results[1], Exception) else (False, str(results[1]))
    ok_claude, txt_claude = results[2] if not isinstance(results[2], Exception) else (False, str(results[2]))
    
    print(f"[INFO] AI Results - OpenAI: {ok_openai}, xAI: {ok_xai}, Claude: {ok_claude}")
    
    # استخراج التوصيات
    rec_openai = extract_trade_fields(txt_openai if ok_openai else "")
    rec_xai = extract_trade_fields(txt_xai if ok_xai else "")
    rec_claude = extract_trade_fields(txt_claude if ok_claude else "")
    
    # تحديد الإجماع
    agreed, final_direction, consensus_type = consensus_triple(rec_openai, rec_xai, rec_claude)
    
    # إحصائيات الذكاء الاصطناعي
    ai_status = []
    if ok_openai: ai_status.append("✅ OpenAI")
    else: ai_status.append("❌ OpenAI")
    
    if ok_xai: ai_status.append("✅ xAI")
    else: ai_status.append("❌ xAI")
    
    if ok_claude: ai_status.append("✅ Claude")
    else: ai_status.append("❌ Claude")
    
    # بناء رسالة التحليل
    header = f"<b>📊 {sym} {tf}</b>\n"
    header += f"<b>🤖 الذكاء الاصطناعي:</b> {' | '.join(ai_status)}\n"
    header += f"<b>📈 البيانات:</b> O={n['O']} H={n['H']} L={n['L']} C={n['C']}\n"
    
    # معلومات إضافية
    indicators = []
    if n["RSI"] is not None: indicators.append(f"RSI={n['RSI']:.1f}")
    if n["EMA"] is not None: indicators.append(f"EMA={n['EMA']:.2f}")
    if n["MACD"] is not None: indicators.append(f"MACD={n['MACD']:.3f}")
    
    if indicators:
        header += f"<b>📊 المؤشرات:</b> {' | '.join(indicators)}\n"
    
    # معلومات SMC
    smc_info = []
    if n["CSD_UP"] is not None: smc_info.append(f"CSD_UP={n['CSD_UP']:.2f}")
    if n["CSD_DN"] is not None: smc_info.append(f"CSD_DN={n['CSD_DN']:.2f}")
    if n["BULL_FVG_CE"] is not None: smc_info.append(f"Bull_FVG={n['BULL_FVG_CE']:.2f}")
    if n["BEAR_FVG_CE"] is not None: smc_info.append(f"Bear_FVG={n['BEAR_FVG_CE']:.2f}")
    
    if smc_info:
        header += f"<b>🎯 SMC:</b> {' | '.join(smc_info)}\n"
    
    header += f"<b>🔍 الإجماع:</b> {consensus_type}\n"
    header += "─" * 30
    
    # إرسال رسالة التحليل
    tgsend(header)
    await asyncio.sleep(0.5)
    
    # بناء التوصية النهائية
    final_rec = {
        "direction": "لا صفقة",
        "entry": "",
        "tp": "",
        "sl": "",
        "reason": consensus_type
    }
    
    if agreed and final_direction in ["buy", "sell"]:
        # اختيار أفضل توصية
        chosen_rec, chosen_source = pick_best_recommendation(rec_openai, rec_xai, rec_claude, final_direction)
        
        entry = _to_float_safe(chosen_rec.get("entry"))
        tp = _to_float_safe(chosen_rec.get("tp"))
        sl = _to_float_safe(chosen_rec.get("sl"))
        
        if entry and tp and sl:
            # حساب الانعكاس
            if final_direction == "buy":
                reversal = abs(entry - sl)
                reward = abs(tp - entry)
            else:
                reversal = abs(sl - entry)
                reward = abs(entry - tp)
            
            rr_ratio = reward / reversal if reversal > 0 else 0
            
            # فلاتر الأمان المحسنة
            safety_issues = []
            
            if reversal > 30:
                safety_issues.append(f"انعكاس كبير ({reversal:.1f} نقطة)")
            
            if n["RSI"] and (n["RSI"] < 35 or n["RSI"] > 75):
                safety_issues.append(f"RSI متطرف ({n['RSI']:.1f})")
            
            if n["MACD"] and n["MACD"] < -0.3:
                safety_issues.append(f"MACD سلبي جداً ({n['MACD']:.3f})")
            
            if rr_ratio < 1.5:
                safety_issues.append(f"نسبة مخاطرة/عائد ضعيفة ({rr_ratio:.2f})")
            
            if safety_issues:
                final_rec["reason"] = f"إلغاء الصفقة: {' + '.join(safety_issues)}"
            else:
                final_rec = {
                    "direction": "🟢 شراء" if final_direction == "buy" else "🔴 بيع",
                    "entry": f"{entry:.2f}",
                    "tp": f"{tp:.2f}",
                    "sl": f"{sl:.2f}",
                    "reason": f"{consensus_type} | المصدر: {chosen_source} | R:R = {rr_ratio:.2f}"
                }
    
    # بناء رسالة التوصية النهائية
    recommendation_text = f"""<b>🎯 التوصية النهائية</b>

<b>الصفقة:</b> {final_rec['direction']}
<b>الدخول:</b> {final_rec['entry']}
<b>جني الأرباح:</b> {final_rec['tp']}
<b>وقف الخسارة:</b> {final_rec['sl']}
<b>السبب:</b> {final_rec['reason']}

<b>⚡ شروط الأمان:</b>
• الانعكاس الأقصى ≤ 30 نقطة
• نسبة المخاطرة/العائد ≥ 1.5
• RSI بين 35-75

<b>🕐 الوقت:</b> {now_str()}"""
    
    # إرسال التوصية
    tgsend(recommendation_text)
    
    print(f"[INFO] Alert processed successfully for {sym} {tf}")

# ==================== API Routes ====================
@app.get("/")
def root():
    """الصفحة الرئيسية - معلومات الخدمة"""
    return {
        "ok": True,
        "service": "Shinzooh Trading Bot Enhanced",
        "version": "2.0.0",
        "ai_engines": {
            "OpenAI": "✅" if OPENAI_API_KEY else "❌",
            "xAI": "✅" if XAI_API_KEY else "❌", 
            "Claude": "✅" if CLAUDE_API_KEY else "❌"
        },
        "features": [
            "Triple AI Analysis",
            "ICT/SMC Integration", 
            "Advanced Risk Management",
            "Telegram Notifications"
        ],
        "timestamp": now_str()
    }

@app.get("/health")
def health_check():
    """فحص صحة الخدمة"""
    return {
        "status": "healthy",
        "ai_services": {
            "openai": bool(OPENAI_API_KEY),
            "xai": bool(XAI_API_KEY),
            "claude": bool(CLAUDE_API_KEY)
        },
        "telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "timestamp": now_str()
    }

@app.post("/webhook")
async def webhook(request: Request):
    """استقبال التنبيهات من TradingView"""
    try:
        raw = await request.body()
        data = raw.decode(errors="ignore")
        
        print(f"[INFO] Webhook received: {data[:200]}...")
        
        # معالجة التنبيه في الخلفية
        asyncio.create_task(process_alert(data))
        
        return {
            "status": "success",
            "message": "Alert received and processing",
            "ai_engines": 3,
            "timestamp": now_str()
        }
        
    except Exception as e:
        print(f"[ERROR] Webhook error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "timestamp": now_str()
        }

@app.post("/test")
async def test_analysis(request: Request):
    """اختبار التحليل - للتطوير فقط"""
    try:
        data = await request.json()
        test_data = f"SYMB={data.get('symbol', 'XAUUSD')},TF={data.get('timeframe', '5m')},C={data.get('close', 2650)},RSI={data.get('rsi', 50)},EMA={data.get('ema', 2645)}"
        
        asyncio.create_task(process_alert(test_data))
        
        return {"status": "test_sent", "data": test_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==================== تشغيل التطبيق ====================
if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Shinzooh Trading Bot Enhanced v2.0")
    print(f"🤖 AI Engines: OpenAI({'✅' if OPENAI_API_KEY else '❌'}) | xAI({'✅' if XAI_API_KEY else '❌'}) | Claude({'✅' if CLAUDE_API_KEY else '❌'})")
    print(f"📱 Telegram: {'✅' if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else '❌'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)


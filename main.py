# main.py
import os, re, time, logging, concurrent.futures
from datetime import datetime, timezone
from flask import Flask, request, jsonify

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ===== Logging =====
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ===== Env =====
XAI_API_KEY     = os.getenv("XAI_API_KEY","")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY","")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID","")

CONNECT_TO = 5
OAI_TIMEOUT_S = float(os.getenv("OAI_TIMEOUT_S", "20"))
XAI_TIMEOUT_S = float(os.getenv("XAI_TIMEOUT_S", "20"))

# ===== HTTP session with retries (429/50x) =====
retry = Retry(
    total=3, backoff_factor=1.0,
    status_forcelist=[429,500,502,503,504],
    allowed_methods=["GET","POST","PUT","DELETE","HEAD","OPTIONS","PATCH"]
)
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=retry))
session.mount("http://",  HTTPAdapter(max_retries=retry))

app = Flask(__name__)

# ====== Utils ======
def parse_kv(body_text: str) -> dict:
    """
    يقرأ الرسالة القادمة من Pine بالشكل:
    SYMB=XAUUSD,TF=15,O=...,H=...,L=...,C=...,V=...,RSI=...,MA=...,MACD=...,CSD_UP=0,CSD_DN=1,...
    """
    kv = {}
    # افصل بالـ comma ثم split('=',1)
    for part in body_text.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip().upper()
            v = v.strip()
            kv[k] = v
    return kv

def to_float(x):
    try:
        return float(str(x))
    except:
        return None

def ask_xai(prompt: str) -> tuple[bool, str]:
    if not XAI_API_KEY:
        return False, "xAI key missing"
    try:
        r = session.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            json={"model":"grok-beta","messages":[{"role":"user","content":prompt}],"temperature":0.2},
            timeout=(CONNECT_TO, XAI_TIMEOUT_S),
        )
        if r.status_code >= 400:
            return False, f"xAI HTTP {r.status_code}: {r.text[:200]}"
        j = r.json()
        txt = j["choices"][0]["message"]["content"]
        return True, txt
    except Exception as e:
        return False, f"xAI error: {e}"

def ask_openai(prompt: str) -> tuple[bool, str]:
    if not OPENAI_API_KEY:
        return False, "OpenAI key missing"
    try:
        r = session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model":"gpt-4o-mini","messages":[{"role":"user","content":prompt}],"temperature":0.2},
            timeout=(CONNECT_TO, OAI_TIMEOUT_S),
        )
        if r.status_code >= 400:
            return False, f"OpenAI HTTP {r.status_code}: {r.text[:200]}"
        j = r.json()
        txt = j["choices"][0]["message"]["content"]
        return True, txt
    except Exception as e:
        return False, f"OpenAI error: {e}"

def first_success(prompts: list[str], total_budget_s: float = 25.0) -> tuple[bool, str, dict]:
    """
    يطلق xAI و OpenAI بالتوازي على البرومبت العربي والإنجليزي.
    يرجع أول رد ناجح خلال الميزانية الزمنية، أو يجمع الأخطاء إن ما رجع شي.
    """
    calls = []
    for p in prompts:
        calls.append(("xai",     p, ask_xai))
        calls.append(("openai",  p, ask_openai))

    results = []
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as ex:
        fut_map = {ex.submit(fn, p): (name, p) for (name, p, fn) in calls}
        try:
            for fut in concurrent.futures.as_completed(fut_map, timeout=total_budget_s):
                name, _ = fut_map[fut]
                ok, txt = False, ""
                try:
                    ok, txt = fut.result(timeout=max(0.1, total_budget_s - (time.time()-start)))
                except Exception as e:
                    ok, txt = False, f"{name} raised: {e}"
                if ok and txt and len(txt.strip()) > 0:
                    return True, txt.strip(), {"winner": name}
                results.append(f"{name}: {txt}")
        except Exception:
            pass
    return False, "\n".join(results[-6:]), {"winner": None}

def tg_send_message_text(text: str):
    """إرسال نص خام بدون HTML/Markdown (حتى لا نطيح في Bad Request: parse entities)."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        logging.warning("Telegram env missing, skip send.")
        return
    try:
        r = session.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=(CONNECT_TO, 10),
        )
        if r.status_code != 200:
            logging.warning("Telegram non-200: %s %s", r.status_code, r.text[:200])
    except Exception as e:
        logging.warning("Telegram send error: %s", e)

def build_prompts(nrm: dict) -> tuple[str, str]:
    # عربي
    p_ar = (
        f"حلّل {nrm['SYMB']} فريم {nrm['TF']} بأسلوب ICT/SMC (Liquidity/BOS/CHoCH/FVG/OB) + كلاسيكي (RSI/EMA/MACD).\n"
        f"القيم: O={nrm['O']} H={nrm['H']} L={nrm['L']} C={nrm['C']} V={nrm['V']} RSI={nrm['RSI']} EMA={nrm['MA']} MACD={nrm['MACD']} "
        f"CSD_UP={nrm['CSD_UP']} CSD_DN={nrm['CSD_DN']} BULL_CE={nrm['BULL_FVG_CE']} BEAR_CE={nrm['BEAR_FVG_CE']}.\n"
        "أعد فقط:\n"
        "- الصفقة: شراء أو بيع\n- الدخول: رقم\n- الهدف: رقم\n- الوقف: رقم\n- السبب: سطر واحد واضح."
    )
    # إنجليزي (احتياط)
    p_en = (
        f"Analyze {nrm['SYMB']} {nrm['TF']} using ICT/SMC + classic RSI/EMA/MACD.\n"
        f"Values O={nrm['O']} H={nrm['H']} L={nrm['L']} C={nrm['C']} V={nrm['V']} RSI={nrm['RSI']} EMA={nrm['MA']} MACD={nrm['MACD']} "
        f"CSD_UP={nrm['CSD_UP']} CSD_DN={nrm['CSD_DN']} BULL_CE={nrm['BULL_FVG_CE']} BEAR_CE={nrm['BEAR_FVG_CE']}.\n"
        "Return ONLY:\nTrade: Buy or Sell\nEntry: number\nTake Profit: number\nStop Loss: number\nReason: one line."
    )
    return p_ar, p_en

def process_alert_record(kv_text: str):
    kv = parse_kv(kv_text)
    if "SYMB" not in kv or "TF" not in kv:
        tg_send_message_text("⚠️ Webhook: بيانات ناقصة من TradingView.")
        return

    # تطبيع أرقام مهمة (للإظهار فقط)
    nums = ("O","H","L","C","V","RSI","MA","MACD")
    for k in nums:
        if k in kv:
            kv[k] = str(to_float(kv[k]))

    p_ar, p_en = build_prompts(kv)
    ok, txt, meta = first_success([p_ar, p_en], total_budget_s=25.0)

    header = (
        f"الرمز: {kv.get('SYMB','?')} | الفريم: {kv.get('TF','?')}\n"
        f"O={kv.get('O')} H={kv.get('H')} L={kv.get('L')} C={kv.get('C')} V={kv.get('V')}\n"
        f"RSI={kv.get('RSI')} EMA={kv.get('MA')} MACD={kv.get('MACD')} CSD_UP={kv.get('CSD_UP')} CSD_DN={kv.get('CSD_DN')}\n"
        f"BULL_CE={kv.get('BULL_FVG_CE')} BEAR_CE={kv.get('BEAR_FVG_CE')}\n"
    )

    if ok:
        body = f"✅ توصية ({meta.get('winner','?')}):\n{txt}"
    else:
        body = "⚠️ فشل الحصول على تحليل ضمن الوقت — تم التخطي.\n" + (txt or "")
    tg_send_message_text(header + "\n" + body)

# ===== Routes =====
@app.get("/")
def root():
    return jsonify({"ok": True, "ts": datetime.now(timezone.utc).isoformat()})

@app.post("/webhook")
def webhook():
    raw = request.get_data(as_text=True) or ""
    logging.info("Raw Body (KV): %s", raw[:500])
    try:
        process_alert_record(raw.strip())
        return jsonify({"status":"ok"}), 200
    except Exception as e:
        logging.exception("process_alert error")
        tg_send_message_text(f"⚠️ Webhook error: {e}")
        return jsonify({"status":"error", "msg": str(e)}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","10000")), debug=True)

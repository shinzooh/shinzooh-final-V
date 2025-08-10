# -*- coding: utf-8 -*-
import os, traceback, concurrent.futures
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from flask import Flask, request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ========= Env =========
XAI_API_KEY        = os.getenv("XAI_API_KEY", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

MODEL_XAI  = os.getenv("XAI_MODEL", "grok-4-0709")
MODEL_OAI  = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
REQ_TIMEOUT = int(os.getenv("REQ_TIMEOUT", "20"))
ANALYSIS_OVERALL_TIMEOUT = int(os.getenv("ANALYSIS_OVERALL_TIMEOUT", "22"))

ALLOWED_TF = {"1D","4H","1H","15","5","15m","5m","60","240","D"}

# ========= HTTP session with retries =========
def make_session():
    s = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.5,
        status_forcelist=[429,500,502,503,504],
        allowed_methods=frozenset(["GET","POST"])
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    return s

SESSION = make_session()

# ========= App =========
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_prefix=1)

# ========= Helpers =========
def _to_float(x) -> Optional[float]:
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None

def _parse_time_any(x):
    if x is None: return None
    s = str(x)
    if s.isdigit():  # unix (s/ms)
        t = int(s)
        if t > 1_000_000_000_000:
            t //= 1000
        return datetime.fromtimestamp(t, tz=timezone.utc)
    try:
        s2 = s.replace("Z","+00:00")
        return datetime.fromisoformat(s2)
    except Exception:
        return None

def normalize_tv(payload: Dict[str,Any]) -> Dict[str,Any]:
    symb = str(payload.get("SYMB","")).strip()
    exch = str(payload.get("EXCHANGE","")).strip()
    tf   = str(payload.get("TF",""

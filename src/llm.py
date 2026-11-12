"""Shared LLM client used by every FinSight tool (designed for the free Gemini tier).

Features:
  1. Cache    - responses are stored in data/llm_cache.db, keyed by model + prompt.
                If the answer is already cached, no API call is made.
  2. Fallback - models from .env LLM_MODELS (e.g. gemini-3.8-flash,gemini-3.5-flash)
                are tried in order. On a 429 "daily limit" error the next model is
                used. If every model is exhausted, the user gets a clear message
                instead of a crash.
  3. Counting - successful API calls (the ones that use free quota) are counted per
                question and logged. A question may use at most MAX_CALLS calls.

Typical use in a tool:
    text = llm.generate(prompt)          # returns LIMIT_MESSAGE if all models are exhausted
"""
import hashlib
import logging
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CACHE_PATH = ROOT / "data" / "llm_cache.db"
DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash"]
LIMIT_MESSAGE = "Daily free limit reached, try again tomorrow."
UNAVAILABLE_MESSAGE = "The AI model is unavailable right now, please try again in a minute."
MAX_CALLS = 2  # per question
# A stuck connection fails after 60 s (and counts as a network error) instead of
# hanging for minutes. The Gemini SDK takes the timeout in milliseconds.
REQUEST_TIMEOUT_MS = 60_000

# 429 = daily limit reached. 503 (overloaded) and 404 (model not offered to this
# account) also move on to the next model.
LIMIT_CODES = {429}
SKIP_CODES = {404, 503}

log = logging.getLogger(__name__)


class DailyLimitReached(RuntimeError):
    """Every model returned 429. str(error) is the friendly LIMIT_MESSAGE."""

    def __init__(self):
        super().__init__(LIMIT_MESSAGE)


class CallBudgetExceeded(RuntimeError):
    """A question tried to use more than MAX_CALLS LLM calls."""


def models() -> list[str]:
    """Models to try, in order, from .env LLM_MODELS (comma-separated)."""
    raw = os.getenv("LLM_MODELS") or ",".join(DEFAULT_MODELS)
    return list(dict.fromkeys(m.strip() for m in raw.split(",") if m.strip()))


# ---------- call counting (per question) ----------

_calls = {"used": 0, "attempts": 0}


def reset_calls() -> None:
    """Call at the start of each question."""
    _calls["used"] = _calls["attempts"] = 0


def calls_used() -> int:
    """Successful API calls since reset_calls() (each one uses free quota)."""
    return _calls["used"]


def check_budget() -> None:
    if _calls["used"] >= MAX_CALLS:
        raise CallBudgetExceeded(f"This question already used {MAX_CALLS} LLM calls.")


def record_call(model: str, ok: bool) -> None:
    """Count one API request (ok=False for rejected ones, e.g. 429, which use no quota)."""
    _calls["attempts"] += 1
    if ok:
        _calls["used"] += 1
    log.info("LLM call to %s (%s) - %d used for this question",
             model, "ok" if ok else "rejected", _calls["used"])


# ---------- cache ----------

def _key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode("utf-8")).hexdigest()


def _db() -> sqlite3.Connection:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CACHE_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, model TEXT, value TEXT)")
    return con


def cache_get(model: str, prompt: str) -> str | None:
    con = _db()
    row = con.execute("SELECT value FROM cache WHERE key = ?", [_key(model, prompt)]).fetchone()
    con.close()
    return row[0] if row else None


def cache_set(model: str, prompt: str, value: str) -> None:
    con = _db()
    con.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", [_key(model, prompt), model, value])
    con.commit()
    con.close()


def cached_any(prompt: str) -> str | None:
    """A cached answer from ANY configured model (checked before calling the API)."""
    for model in models():
        hit = cache_get(model, prompt)
        if hit is not None:
            return hit
    return None


# ---------- errors ----------

def error_kind(error: Exception) -> str | None:
    """'limit', 'skip' (try next model) or None (a real bug: don't hide it)."""
    code = getattr(error, "code", None)
    if code in LIMIT_CODES:
        return "limit"
    if code in SKIP_CODES:
        return "skip"
    import httpx  # installed with the Gemini SDK
    if isinstance(error, (ConnectionError, TimeoutError, httpx.TransportError)):
        return "skip"  # temporary network problem
    return None


# ---------- main entry point ----------

def _call_model(model: str, prompt: str) -> str:
    """One Gemini request (temperature 0 = as repeatable as possible)."""
    from google import genai
    client = genai.Client(api_key=os.environ["LLM_API_KEY"],
                          http_options={"timeout": REQUEST_TIMEOUT_MS})
    response = client.models.generate_content(model=model, contents=prompt,
                                              config={"temperature": 0.0})
    return (response.text or "").strip()


def generate(prompt: str) -> str:
    """Answer `prompt`. Returns LIMIT_MESSAGE / UNAVAILABLE_MESSAGE instead of crashing."""
    hit = cached_any(prompt)
    if hit is not None:
        return hit  # 0 API calls
    if not os.getenv("LLM_API_KEY"):
        return "LLM_API_KEY is missing. Add it to the .env file."

    kinds = []
    for model in models():
        check_budget()
        try:
            answer = _call_model(model, prompt)
        except Exception as e:  # noqa: BLE001 - decide below whether to move on
            kind = error_kind(e)
            if kind is None:
                raise
            record_call(model, ok=False)
            log.warning("Model %s: %s, trying the next model", model, getattr(e, "code", e))
            kinds.append(kind)
            continue
        record_call(model, ok=True)
        cache_set(model, prompt, answer)
        return answer

    return LIMIT_MESSAGE if kinds and all(k == "limit" for k in kinds) else UNAVAILABLE_MESSAGE

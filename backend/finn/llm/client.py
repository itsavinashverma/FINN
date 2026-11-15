"""Thin Gemini client: structured JSON output, timeouts, retries, and a persistent response cache.

Scope boundary (by design): this client is used ONLY for unstructured text understanding
(announcement summaries). All financial arithmetic — QoQ/YoY, EBITDA, volume ratios, thresholds —
is plain Python in market/metrics.py and results/headline.py and never passes through here.

Gemini's structured-output schema is a protobuf-derived OpenAPI subset, not JSON Schema: a field
type must be a single string ("object"/"string"/...), and optional values use "nullable": true
rather than a type array. Verified 2026-11-13 against this project's API key.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from ..config import settings
from ..errors import SourceUnavailable

log = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Shared across every GeminiClient instance in the process: there is one API key and one
# per-minute quota, regardless of how many ResearchService/GeminiClient objects get constructed.
_pace_lock = threading.Lock()
_last_call_at = 0.0


def _pace(min_interval: float) -> None:
    global _last_call_at
    with _pace_lock:
        wait = _last_call_at + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


class LLMUnavailable(SourceUnavailable):
    pass


@dataclass
class LLMResult:
    data: dict
    cached: bool
    model: str


class GeminiClient:
    name = "gemini"

    def __init__(self, model: str | None = None, timeout: float | None = None, retries: int | None = None):
        self.model = model or settings.gemini_model
        self.timeout = timeout or settings.llm_timeout_s
        self.retries = settings.llm_retries if retries is None else retries

    @staticmethod
    def _cache_key(model: str, prompt_version: str, system: str, user: str) -> str:
        return hashlib.sha256(f"{model}|{prompt_version}|{system}\n{user}".encode()).hexdigest()

    def generate_json(self, conn, *, system: str, user: str, schema: dict, prompt_version: str) -> LLMResult:
        """Cache-first structured generation. Raises LLMUnavailable; never returns malformed JSON."""
        key = self._cache_key(self.model, prompt_version, system, user)
        row = conn.execute("SELECT response FROM llm_cache WHERE cache_key=?", (key,)).fetchone()
        if row:
            return LLMResult(data=json.loads(row["response"]), cached=True, model=self.model)

        if not settings.gemini_api_key:
            raise LLMUnavailable("gemini: GEMINI_API_KEY not configured", source="gemini")

        url = f"{API_BASE}/{self.model}:generateContent?key={settings.gemini_api_key}"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema, "temperature": 0.0},
        }

        last_err: Exception | None = None
        usage = {}
        parsed: dict | None = None
        for attempt in range(self.retries + 1):
            _pace(settings.llm_min_interval_s)
            try:
                r = requests.post(url, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last_err = SourceUnavailable(f"gemini: HTTP {r.status_code}", source="gemini")
                # 429 is a per-minute quota, not a momentary blip -- back off longer than for a 5xx.
                retry_after = r.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else (8.0 if r.status_code == 429 else 2.0) * (attempt + 1)
                time.sleep(delay)
                continue
            if r.status_code != 200:
                raise LLMUnavailable(f"gemini: HTTP {r.status_code}: {r.text[:200]}", source="gemini")
            payload = r.json()
            usage = payload.get("usageMetadata", {})
            try:
                text = payload["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
            except (KeyError, IndexError, ValueError) as e:
                raise LLMUnavailable(f"gemini: unexpected response shape: {e}", source="gemini") from e
            break
        if parsed is None:
            raise LLMUnavailable(f"gemini: request failed after retries: {last_err}", source="gemini") from last_err

        conn.execute(
            "INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?,?,?,?)",
            (key, self.model, prompt_version, json.dumps(parsed), usage.get("promptTokenCount"),
             usage.get("candidatesTokenCount"), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return LLMResult(data=parsed, cached=False, model=self.model)

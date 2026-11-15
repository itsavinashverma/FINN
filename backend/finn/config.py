from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Real environment variables take precedence."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(_BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("FINN_DATA_DIR", _BACKEND_DIR / "data")))
    user_agent: str = os.getenv(
        "FINN_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    )
    http_timeout_s: float = float(os.getenv("FINN_HTTP_TIMEOUT", "20"))
    http_retries: int = int(os.getenv("FINN_HTTP_RETRIES", "3"))
    # Minimum spacing between requests to the same host (politeness / anti-blocking).
    min_host_interval_s: float = float(os.getenv("FINN_MIN_HOST_INTERVAL", "1.0"))
    # Volume-average window and how much history we pull to support it.
    volume_window: int = 20
    history_period: str = "6mo"
    # Price bars are re-fetched if the stored copy is older than this.
    price_ttl: timedelta = timedelta(minutes=30)
    # NSE cash market closes 15:30 IST; Yahoo's EOD bar is treated as final after this.
    session_final_after: tuple[int, int] = (16, 0)

    gemini_api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or None)
    # Verified 2026-11-13: gemini-2.5-* model IDs 404 for this key ("no longer available to new
    # users"); the "-latest" alias tracks whichever current model the key can use.
    gemini_model: str = os.getenv("FINN_GEMINI_MODEL", "gemini-flash-lite-latest")
    llm_timeout_s: float = float(os.getenv("FINN_LLM_TIMEOUT", "25"))
    llm_retries: int = int(os.getenv("FINN_LLM_RETRIES", "2"))
    # Research can fire ~20 calls across several transcripts in a few seconds; the free tier's
    # per-minute quota (observed 2026-11-15: a burst of ~20 calls hit HTTP 429) needs pacing, not
    # just retries. 4.5s keeps a sustained run under ~13 calls/min.
    llm_min_interval_s: float = float(os.getenv("FINN_LLM_MIN_INTERVAL", "4.5"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "finn.sqlite3"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"


settings = Settings()

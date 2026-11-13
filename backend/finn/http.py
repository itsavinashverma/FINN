"""Shared HTTP client: timeouts, retries with backoff, per-host pacing and a SQLite response cache.

Every response that leaves this module carries its URL and retrieval time so callers
can preserve provenance.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import settings
from .errors import NotFound, SourceUnavailable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content: bytes
    content_type: str
    fetched_at: datetime  # UTC
    from_cache: bool

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class HttpClient:
    def __init__(self, db_path=None, *, timeout: float | None = None, retries: int | None = None):
        self.timeout = timeout or settings.http_timeout_s
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent, "Accept-Language": "en-US,en;q=0.9"})
        retry = Retry(
            total=retries if retries is not None else settings.http_retries,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()
        self._cache_path = str(db_path or settings.db_path)
        self._init_cache()

    # ---- cache -------------------------------------------------------------------------
    def _cache_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._cache_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_cache(self) -> None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with self._cache_conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS http_cache(
                       url TEXT PRIMARY KEY, status INTEGER, content_type TEXT,
                       body BLOB, fetched_at TEXT)"""
            )

    def _cache_get(self, url: str, ttl: timedelta) -> FetchResult | None:
        with self._cache_conn() as c:
            row = c.execute(
                "SELECT status, content_type, body, fetched_at FROM http_cache WHERE url=?", (url,)
            ).fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row[3])
        if datetime.now(timezone.utc) - fetched_at > ttl:
            return None
        return FetchResult(url, row[0], row[2], row[1] or "", fetched_at, True)

    def _cache_put(self, r: FetchResult) -> None:
        with self._cache_conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO http_cache VALUES (?,?,?,?,?)",
                (r.url, r.status, r.content_type, r.content, r.fetched_at.isoformat()),
            )

    # ---- fetch -------------------------------------------------------------------------
    def _pace(self, host: str) -> None:
        with self._lock:
            wait = self._last_hit.get(host, 0) + settings.min_host_interval_s - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_hit[host] = time.monotonic()

    def get(
        self,
        url: str,
        *,
        source: str,
        params: dict | None = None,
        headers: dict | None = None,
        cache_ttl: timedelta | None = None,
        not_found_statuses: tuple[int, ...] = (404,),
    ) -> FetchResult:
        """GET with retries. Raises NotFound / SourceUnavailable; never returns a failed response."""
        full_url = requests.Request("GET", url, params=params).prepare().url or url
        if cache_ttl:
            cached = self._cache_get(full_url, cache_ttl)
            if cached:
                log.debug("cache hit %s", full_url)
                return cached

        self._pace(urlparse(full_url).netloc)
        started = time.monotonic()
        try:
            resp = self.session.get(full_url, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            log.warning("%s fetch failed %s: %s", source, full_url, e)
            raise SourceUnavailable(f"{source}: network error: {e.__class__.__name__}", source=source) from e

        elapsed = time.monotonic() - started
        log.info("%s GET %s -> %s (%.1fs, %d bytes)", source, full_url[:140], resp.status_code, elapsed, len(resp.content))
        if resp.status_code in not_found_statuses:
            raise NotFound(f"{source}: not found ({resp.status_code})", source=source)
        if resp.status_code != 200:
            hint = " (blocked by bot protection?)" if resp.status_code in (401, 403) else ""
            raise SourceUnavailable(f"{source}: HTTP {resp.status_code}{hint}", source=source)

        result = FetchResult(
            url=full_url,
            status=resp.status_code,
            content=resp.content,
            content_type=resp.headers.get("Content-Type", ""),
            fetched_at=datetime.now(timezone.utc),
            from_cache=False,
        )
        if cache_ttl:
            self._cache_put(result)
        return result

    def get_json(self, url: str, **kw):
        r = self.get(url, **kw)
        try:
            return json.loads(r.content), r
        except ValueError as e:
            # Akamai blocks often return HTML with status 200.
            snippet = r.text[:80].replace("\n", " ")
            raise SourceUnavailable(f"{kw.get('source')}: expected JSON, got: {snippet!r}", source=kw.get("source")) from e

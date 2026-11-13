"""FastAPI surface for the data pipeline. Run: uvicorn finn.api:app --reload"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db, repo
from .config import IST
from .errors import FinnError, NotFound, ParseError, SourceUnavailable
from .http import HttpClient
from .log import setup_logging
from .models import Exchange
from .pipeline import Pipeline

setup_logging()
app = FastAPI(title="FINN data API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_http = HttpClient()
_market = None  # shared YahooProvider, created lazily by the first Pipeline that needs it


def get_pipeline() -> Iterator[Pipeline]:
    global _market
    conn = db.connect()
    try:
        p = Pipeline(conn, http=_http, market=_market)
        yield p
        _market = p._market or _market
    finally:
        conn.close()


@app.exception_handler(FinnError)
def finn_error(_: Request, e: FinnError):
    status = 404 if isinstance(e, NotFound) else 502 if isinstance(e, (SourceUnavailable, ParseError)) else 500
    code = type(e).__name__
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": str(e), "source": e.source, "retryable": e.retryable}})


@app.exception_handler(HTTPException)
def http_error(_: Request, e: HTTPException):
    return JSONResponse(status_code=e.status_code, content={"error": {
        "code": "NotFound" if e.status_code == 404 else "BadRequest", "message": str(e.detail),
        "source": None, "retryable": False}})


@app.get("/health")
def health(p: Pipeline = Depends(get_pipeline)):
    return {"ok": True, "sources": repo.source_status(p.conn)}


# ---------------------------------------------------------------- market
@app.get("/api/market/{symbol}")
def market(symbol: str, exchange: Exchange = Exchange.NSE, refresh: bool = False,
           bars: int = Query(60, ge=0, le=500), p: Pipeline = Depends(get_pipeline)):
    metrics, series = p.market_metrics(symbol, exchange, refresh=refresh)
    return {"metrics": metrics, "bars": series.bars[-bars:] if bars else [], "retrieved_at": series.retrieved_at}


# ---------------------------------------------------------------- announcements
class IngestRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=40)
    days: int = Field(7, ge=1, le=90)
    sources: list[str] | None = Field(None, description="subset of ['nse','bse']; default both")


@app.post("/api/announcements/ingest")
def ingest(req: IngestRequest, p: Pipeline = Depends(get_pipeline)):
    end = datetime.now(IST).date()
    start = end - timedelta(days=req.days)
    report = p.ingest_announcements([s.upper() for s in req.symbols], start, end,
                                    set(req.sources) if req.sources else None)
    return {"window": {"from": start, "to": end}, **report.__dict__}


@app.get("/api/announcements")
def announcements(
    symbols: str | None = Query(None, description="comma-separated NSE symbols"),
    hours: int | None = Query(24, ge=1, le=24 * 90),
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    category: str | None = Query(None, description="comma-separated glossary categories"),
    include_duplicates: bool = False,
    p: Pipeline = Depends(get_pipeline),
):
    now = datetime.now(timezone.utc)
    end = (end or now)
    start = start or (end - timedelta(hours=hours or 24))
    for name, value in (("from", start), ("to", end)):
        if value.tzinfo is None:
            raise HTTPException(422, f"'{name}' must include a timezone offset, e.g. 2026-11-13T09:00:00+05:30")
    items = repo.query_announcements(
        p.conn, start=start, end=end,
        symbols=[s.strip().upper() for s in symbols.split(",")] if symbols else None,
        categories=[c.strip() for c in category.split(",")] if category else None,
        include_duplicates=include_duplicates,
    )
    return {"window": {"from": start, "to": end}, "count": len(items), "items": items}


# ---------------------------------------------------------------- documents
@app.get("/api/companies/{symbol}/documents")
def documents(symbol: str, refresh: bool = False, kind: str | None = None, p: Pipeline = Depends(get_pipeline)):
    symbol = symbol.upper()
    meta = None
    have = p.conn.execute("SELECT COUNT(*) FROM document WHERE symbol=?", (symbol,)).fetchone()[0]
    if refresh or not have:
        meta = p.discover_documents(symbol)
    sql, args = "SELECT * FROM document WHERE symbol=?", [symbol]
    if kind:
        sql, args = sql + " AND kind=?", args + [kind]
    rows = [dict(r) for r in p.conn.execute(sql + " ORDER BY kind, period_sort DESC", args)]
    company = repo.get_company(p.conn, symbol)
    return {
        "symbol": symbol,
        "company": dict(company) if company else None,
        "statement_basis_of_source_page": meta["company"].page_basis if meta else None,
        "documents": rows,
    }


@app.post("/api/documents/{doc_id}/download")
def download(doc_id: int, p: Pipeline = Depends(get_pipeline)):
    try:
        row = p.download_document(doc_id)
    except KeyError:
        raise HTTPException(404, f"document {doc_id} not found")
    return dict(row)


@app.get("/api/sources")
def sources(p: Pipeline = Depends(get_pipeline)):
    return repo.source_status(p.conn)


_probe_cache: dict = {}


@app.get("/api/probe")
def probe(force: bool = False):
    """Live reachability of every upstream source from this host. Cached 10 min (it hits 5 sites)."""
    from .probe import run_probe

    cached = _probe_cache.get("result")
    if cached and not force and datetime.now(timezone.utc) - _probe_cache["at"] < timedelta(minutes=10):
        return cached
    result = run_probe()
    _probe_cache.update(result=result, at=datetime.now(timezone.utc))
    return result

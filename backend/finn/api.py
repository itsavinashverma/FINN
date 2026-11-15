"""FastAPI surface for the data pipeline. Run: uvicorn finn.api:app --reload"""
from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import alert_repo, db, repo
from .alerts import AlertRule
from .config import IST
from .errors import FinnError, NotFound, ParseError, SourceUnavailable
from .http import HttpClient
from .log import setup_logging
from .models import Category, Exchange, StatementBasis
from .pipeline import Pipeline
from .refresher import Refresher
from . import digest as digest_mod, portfolio
from .market.metrics import compute_metrics

setup_logging()
_http = HttpClient()
_shared: dict = {"market": None}  # YahooProvider, created lazily, shared by requests and the refresher
refresher = Refresher(_http, _shared)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("FINN_REFRESHER", "1") == "1":
        refresher.start()
    yield
    refresher.stop()


app = FastAPI(title="FINN API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_pipeline() -> Iterator[Pipeline]:
    conn = db.connect()
    try:
        p = Pipeline(conn, http=_http, market=_shared["market"])
        yield p
        _shared["market"] = p._market or _shared["market"]
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


@app.get("/api/results/{symbol}")
def results(symbol: str, period_end: str | None = Query(None, description="YYYY-MM-DD quarter end; default latest"),
            basis: StatementBasis = StatementBasis.CONSOLIDATED, p: Pipeline = Depends(get_pipeline)):
    from .results.service import ResultsService

    try:
        pe = date.fromisoformat(period_end) if period_end else None
    except ValueError:
        raise HTTPException(422, "period_end must be YYYY-MM-DD")
    card = ResultsService(p.http, screener=p.documents).card(symbol, pe, basis)
    repo.log_fetch(p.conn, card.source, symbol.upper(), True, f"results {card.current.fiscal_label}")
    return card


# ---------------------------------------------------------------- portfolio & digest
class PortfolioUpdate(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=30)


def _portfolio_rows(p: Pipeline) -> list[dict]:
    now = datetime.now(timezone.utc)
    out = []
    for sym in portfolio.symbols(p.conn):
        company = repo.get_company(p.conn, sym)
        series = repo.load_series(p.conn, sym, Exchange.NSE)
        m = compute_metrics(series, now) if series else None
        out.append({"symbol": sym, "name": company["name"] if company else None,
                    "metrics": m.model_dump(mode="json") if m else None})
    return out


@app.get("/api/portfolio")
def get_portfolio(p: Pipeline = Depends(get_pipeline)):
    """Holdings with the latest *stored* EOD metrics (the refresher keeps them current)."""
    return {"holdings": _portfolio_rows(p), "refresher": refresher.status}


@app.put("/api/portfolio")
def put_portfolio(body: PortfolioUpdate, p: Pipeline = Depends(get_pipeline)):
    syms = portfolio.replace(p.conn, body.symbols)
    threading.Thread(target=refresher.run_once, daemon=True).start()
    return {"symbols": syms}


@app.get("/api/digest")
def get_digest(
    hours: int = Query(24, ge=1, le=24 * 30),
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    with_results: bool = True,
    with_summaries: bool = Query(False, description="LLM one-line summaries for the notable tier (adds latency/cost)"),
    max_summaries: int = Query(8, ge=0, le=30, description="cap on LLM calls per digest request"),
    p: Pipeline = Depends(get_pipeline),
):
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(hours=hours)
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "'from'/'to' must include a timezone offset")
    syms = portfolio.symbols(p.conn)
    rows = repo.query_announcements(p.conn, start=start, end=end, symbols=syms)
    items = digest_mod.build_items(rows)
    if with_results:
        from .results.service import ResultsService

        svc = ResultsService(p.http, screener=p.documents)
        for item in items:
            if item.category == "results" and item.tier == "critical" and item.symbol:
                try:
                    item.results = svc.card(item.symbol).model_dump(mode="json")
                except FinnError as e:
                    item.results_error = str(e)
    if with_summaries:
        from .llm.client import GeminiClient
        from .llm.summarize import summarize

        client = GeminiClient()
        # Notable tier only: critical items already carry a results card or speak for themselves,
        # and routine items are collapsed, not worth the model call.
        candidates = [i for i in items if i.tier == "notable"][:max_summaries]
        for item in candidates:
            row = p.conn.execute("SELECT * FROM announcement WHERE source=? AND source_id=?",
                                 (item.lead.source, item.lead.source_id)).fetchone()
            try:
                item.summary = summarize(repo.row_to_announcement(row), client, p.conn).model_dump(mode="json")
            except FinnError as e:
                item.summary_error = str(e)
    status = {"refresher": refresher.status, "sources": repo.source_status(p.conn)}
    return digest_mod.assemble(items, {"from": start.isoformat(), "to": end.isoformat()}, status)


@app.get("/api/status")
def status(p: Pipeline = Depends(get_pipeline)):
    return {"refresher": refresher.status, "sources": repo.source_status(p.conn)}


@app.post("/api/refresh")
def refresh():
    threading.Thread(target=refresher.run_once, daemon=True).start()
    return {"started": True, "status": refresher.status}


# ---------------------------------------------------------------- alerts
class AlertRuleCreate(BaseModel):
    kind: str = Field(pattern="^(price_move|volume_spike|category)$")
    symbol: str | None = Field(None, description="NSE symbol this rule watches; omit for the whole portfolio")
    threshold: float | None = Field(None, description="percent for price_move, multiplier (x) for volume_spike")
    categories: list[str] | None = Field(None, description="glossary categories to watch, for kind='category'")
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    symbol: str | None = None
    threshold: float | None = None
    categories: list[str] | None = None
    enabled: bool | None = None


def _validate_rule_shape(kind: str, threshold: float | None, categories: list[str] | None) -> None:
    if kind in ("price_move", "volume_spike"):
        if threshold is None or threshold <= 0:
            raise HTTPException(422, f"'{kind}' rules need a positive threshold "
                                     f"({'%' if kind == 'price_move' else 'x multiplier'})")
    elif kind == "category":
        if not categories:
            raise HTTPException(422, "'category' rules need a non-empty 'categories' list")
        known = {c.value for c in Category}
        bad = set(categories) - known
        if bad:
            raise HTTPException(422, f"unknown categories: {sorted(bad)}; valid values are {sorted(known)}")


@app.get("/api/alert-rules")
def list_alert_rules(p: Pipeline = Depends(get_pipeline)):
    return {"rules": alert_repo.list_rules(p.conn)}


@app.post("/api/alert-rules")
def create_alert_rule(body: AlertRuleCreate, p: Pipeline = Depends(get_pipeline)):
    _validate_rule_shape(body.kind, body.threshold, body.categories)
    rule = alert_repo.create_rule(p.conn, AlertRule(kind=body.kind, symbol=body.symbol, threshold=body.threshold,
                                                    categories=body.categories, enabled=body.enabled))
    return rule


@app.put("/api/alert-rules/{rule_id}")
def update_alert_rule(rule_id: int, body: AlertRuleUpdate, p: Pipeline = Depends(get_pipeline)):
    existing = alert_repo.get_rule(p.conn, rule_id)
    if not existing:
        raise HTTPException(404, f"alert rule {rule_id} not found")
    fields = body.model_dump(exclude_unset=True)
    _validate_rule_shape(existing.kind, fields.get("threshold", existing.threshold),
                        fields.get("categories", existing.categories))
    return alert_repo.update_rule(p.conn, rule_id, **fields)


@app.delete("/api/alert-rules/{rule_id}")
def delete_alert_rule(rule_id: int, p: Pipeline = Depends(get_pipeline)):
    if not alert_repo.delete_rule(p.conn, rule_id):
        raise HTTPException(404, f"alert rule {rule_id} not found")
    return {"deleted": rule_id}


@app.get("/api/alerts")
def list_alerts(
    since: datetime | None = Query(None, description="ISO timestamp with timezone offset"),
    symbol: str | None = None, unread_only: bool = False,
    limit: int = Query(200, ge=1, le=1000), p: Pipeline = Depends(get_pipeline),
):
    if since and since.tzinfo is None:
        raise HTTPException(422, "'since' must include a timezone offset")
    items = alert_repo.query_alerts(p.conn, since=since, symbol=symbol, unread_only=unread_only, limit=limit)
    return {"count": len(items), "items": items}


@app.post("/api/alerts/{alert_id}/read")
def read_alert(alert_id: int, p: Pipeline = Depends(get_pipeline)):
    if not alert_repo.mark_read(p.conn, alert_id):
        raise HTTPException(404, f"alert {alert_id} not found or already read")
    return {"id": alert_id, "read": True}


@app.post("/api/alerts/evaluate")
def evaluate_alerts_now(days: int = Query(7, ge=1, le=90), p: Pipeline = Depends(get_pipeline)):
    """Evaluate all enabled rules against currently stored data (no network calls). Idempotent."""
    syms = portfolio.symbols(p.conn)
    end = datetime.now(IST).date()
    fired = p.evaluate_alerts(syms, end - timedelta(days=days), end)
    return {"fired": fired}


# ---------------------------------------------------------------- LLM summaries
@app.get("/api/announcements/{source}/{source_id}/summary")
def announcement_summary(source: str, source_id: str, p: Pipeline = Depends(get_pipeline)):
    """A one-line, fact/interpretation-separated summary of one filing's own disclosed text.
    Never used for numbers — results come from /api/results. Cached: repeat calls cost nothing."""
    from .llm.client import GeminiClient
    from .llm.summarize import summarize

    row = p.conn.execute("SELECT * FROM announcement WHERE source=? AND source_id=?",
                         (source.upper(), source_id)).fetchone()
    if not row:
        raise HTTPException(404, f"announcement {source}:{source_id} not found")
    ann = repo.row_to_announcement(row)
    summary = summarize(ann, GeminiClient(), p.conn)
    repo.log_fetch(p.conn, "gemini", f"{source}:{source_id}", True, "cached" if summary.cached else "generated")
    return summary


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

"""Live end-to-end probe of every data source for candidate companies.

Usage:  python -m scripts.probe_sources [--portfolio SYM,...] [--research SYM,...] [--days 7]

Writes data/source_report.json and prints a summary. Uses the real pipeline (and the real DB),
so a successful run also seeds the database. Nothing here is mocked.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from finn import db
from finn.config import IST, settings
from finn.errors import FinnError
from finn.log import setup_logging
from finn.models import Exchange
from finn.pipeline import Pipeline

PORTFOLIO = ("RELIANCE,HDFCBANK,ICICIBANK,BAJFINANCE,TCS,INFY,PERSISTENT,KPITTECH,ITC,ASIANPAINT,"
             "TITAN,TRENT,MARUTI,SUNPHARMA,LT,POLYCAB,DIXON,BHARTIARTL")
RESEARCH = "NESTLEIND,PIDILITIND,HAVELLS,DMART"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio", default=PORTFOLIO)
    ap.add_argument("--research", default=RESEARCH)
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    setup_logging()

    conn = db.connect()
    p = Pipeline(conn)
    report: dict = {"run_at": datetime.now(timezone.utc).isoformat(), "market": {}, "announcements": {}, "documents": {}}
    portfolio = [s.strip().upper() for s in args.portfolio.split(",") if s.strip()]

    # 1. Prices (NSE, plus BSE for one symbol to prove .BO support)
    for sym, ex in [(s, Exchange.NSE) for s in portfolio] + [(portfolio[0], Exchange.BSE)]:
        t = time.monotonic()
        try:
            m, s = p.market_metrics(sym, ex, refresh=True)
            report["market"][f"{sym}.{ex.yahoo_suffix[1:]}"] = {
                "ok": True, "bars": len(s.bars), "as_of": str(m.as_of), "close": m.close,
                "change_pct": m.change_pct, "volume_ratio": m.volume_ratio, "warnings": m.warnings,
                "secs": round(time.monotonic() - t, 1)}
        except FinnError as e:
            report["market"][f"{sym}.{ex.yahoo_suffix[1:]}"] = {"ok": False, "error": str(e)}

    # 2. Announcements, NSE + BSE, de-duplicated
    end = datetime.now(IST).date()
    r = p.ingest_announcements(portfolio, end - timedelta(days=args.days), end)
    cats = Counter(row[0] for row in conn.execute(
        "SELECT category FROM announcement WHERE duplicate_of IS NULL AND announced_at >= ?",
        ((datetime.now(IST) - timedelta(days=args.days)).isoformat(),)))
    report["announcements"] = {**r.__dict__, "categories_visible": dict(cats.most_common())}

    # 3. Documents for research candidates: discover, then download latest transcript + annual report
    for sym in [s.strip().upper() for s in args.research.split(",") if s.strip()]:
        entry: dict = {}
        try:
            found = p.discover_documents(sym)["company"]
            kinds = Counter(d.kind.value for d in found.documents)
            entry.update(ok=True, company=found.company, bse_code=found.bse_code, basis=found.page_basis,
                         counts=dict(kinds), downloads=[])
            for kind in ("transcript", "annual_report"):
                row = conn.execute("SELECT id FROM document WHERE symbol=? AND kind=? ORDER BY period_sort DESC LIMIT 1",
                                   (sym, kind)).fetchone()
                if not row:
                    entry["downloads"].append({"kind": kind, "status": "none listed"})
                    continue
                d = p.download_document(row["id"])
                entry["downloads"].append({"kind": kind, "period": d["period_label"], "status": d["status"],
                                           "bytes": d["bytes"], "host": d["host"], "error": d["error"]})
        except FinnError as e:
            entry = {"ok": False, "error": str(e)}
        report["documents"][sym] = entry

    out = settings.data_dir / "source_report.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    # ---- summary
    mk = report["market"]
    print(f"\nMARKET  {sum(v['ok'] for v in mk.values())}/{len(mk)} ok")
    for k, v in mk.items():
        print(f"  {k:16} " + (f"as_of={v['as_of']} close={v['close']:.2f} chg={v['change_pct']}% volx={v['volume_ratio']} {v['warnings'] or ''}"
                               if v["ok"] else f"FAIL {v['error']}"))
    a = report["announcements"]
    print(f"\nANNOUNCEMENTS fetched={a['fetched']} inserted={a['inserted']} updated={a['updated']} "
          f"duplicates={a['duplicates']} needs_review={a['needs_review']} errors={len(a['errors'])}")
    for e in a["errors"]:
        print("  ERROR", e)
    print("  visible by category:", a["categories_visible"])
    print("\nDOCUMENTS")
    for k, v in report["documents"].items():
        print(f"  {k:10} " + (f"{v['company']} bse={v['bse_code']} basis={v['basis']} {v['counts']}" if v["ok"] else f"FAIL {v['error']}"))
        for d in v.get("downloads", []):
            print(f"      {d}")
    print(f"\nreport: {out}")


if __name__ == "__main__":
    main()

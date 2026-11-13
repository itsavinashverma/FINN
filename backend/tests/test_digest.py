from finn.digest import assemble, build_items, score, tier


def row(i, symbol, category, title, at="2026-11-12T10:00:00+05:30", body=None, review=0):
    return {"source": "BSE", "source_id": str(i), "symbol": symbol, "company": f"{symbol} Ltd", "category": category,
            "title": title, "body": body, "exchange_category": None, "announced_at": at, "document_url": None,
            "filing_url": None, "needs_review": review}


def test_cfo_change_outranks_company_secretary_change():
    cfo, _ = score("management_change", "Resignation of Mr X as Chief Financial Officer")
    cs, _ = score("management_change", "Appointment of Ms Y as Company Secretary and Compliance Officer")
    assert tier(cfo) == "critical" and tier(cs) == "routine"


def test_rating_downgrade_vs_reaffirmation():
    down, reasons = score("credit_rating", "CRISIL downgrades long-term rating; outlook negative")
    same, _ = score("credit_rating", "Credit rating reaffirmed")
    assert down > same and any("downgrade" in r for r in reasons)


def test_parent_company_results_are_not_critical():
    s, reasons = score("results", "Reference to the Financial Results issued by Suzuki Motor Corporation")
    assert tier(s) != "critical" and any("parent" in r for r in reasons)


def test_commercial_paper_redemption_is_not_a_raise():
    s, _ = score("fund_raise", "Redemption of Commercial Paper")
    qip, _ = score("fund_raise", "Outcome of QIP 2026 - Special Committee meeting")
    assert tier(s) == "routine" and tier(qip) == "critical"


def test_reasons_explain_score():
    s, reasons = score("press_release", "Bagging of order worth Rs 500 crore")
    assert s == 50 and reasons[0].startswith("press release") and "order / contract (+15)" in reasons


def test_results_day_collapses_into_one_item_led_by_the_results():
    rows = [
        row(1, "TCS", "results", "Copy of Newspaper Publication of financial results", "2026-11-12T18:00:00+05:30"),
        row(2, "TCS", "results", "Outcome of Board Meeting - Financial Results Q2", "2026-11-12T16:00:00+05:30"),
        row(3, "TCS", "results", "Investor Presentation", "2026-11-12T16:30:00+05:30"),
        row(4, "INFY", "results", "Financial Results Q2", "2026-11-12T15:00:00+05:30"),
    ]
    items = build_items(rows)
    tcs = next(i for i in items if i.symbol == "TCS")
    assert len(items) == 2 and tcs.lead.source_id == "2" and len(tcs.related) == 2
    assert tcs.announced_at == "2026-11-12T18:00:00+05:30" and tcs.tier == "critical"


def test_non_grouped_categories_stay_separate_and_sorted():
    rows = [row(1, "ITC", "unclassified", "Loss of share certificates"),
            row(2, "ITC", "M&A", "Acquisition of 100% stake in XYZ"),
            row(3, "LT", "press_release", "Bagging of order")]
    items = build_items(rows)
    assert [i.category for i in items] == ["M&A", "press_release", "unclassified"]


def test_assemble_counts_every_filing_once():
    rows = [row(1, "TCS", "results", "Financial Results"), row(2, "TCS", "results", "Investor Presentation"),
            row(3, "ITC", "unclassified", "Trading window closure", review=1)]
    d = assemble(build_items(rows), {"from": "a", "to": "b"})
    assert d.counts == {"critical": 1, "notable": 0, "routine": 1, "filings": 3}
    assert d.routine[0].needs_review

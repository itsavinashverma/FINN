from finn.research import evidence as ev


def test_save_and_get_evidence_roundtrip(conn):
    e = ev.save_evidence(conn, symbol="tcs", document_id=None, document_name="NSE Integrated Filing: Q2 FY27",
                         source_url="https://nse/x.xml", page_number=None, text="Revenue: INR 73,188 crore")
    fetched = ev.get_evidence(conn, e.id)
    assert fetched == e
    assert fetched.symbol == "TCS"   # normalised to upper case


def test_same_inputs_produce_the_same_id_deterministically(conn):
    args = dict(symbol="TCS", document_name="doc", page_number=5, text="quote")
    assert ev.evidence_id(**args) == ev.evidence_id(**args)


def test_different_text_produces_a_different_id():
    a = ev.evidence_id("TCS", "doc", 5, "quote one")
    b = ev.evidence_id("TCS", "doc", 5, "quote two")
    assert a != b


def test_saving_the_same_evidence_twice_is_idempotent(conn):
    kw = dict(symbol="TCS", document_id=None, document_name="doc", source_url="https://x", page_number=1, text="t")
    e1 = ev.save_evidence(conn, **kw)
    e2 = ev.save_evidence(conn, **kw)
    assert e1.id == e2.id
    assert conn.execute("SELECT COUNT(*) FROM evidence WHERE id=?", (e1.id,)).fetchone()[0] == 1


def test_get_evidence_returns_none_for_unknown_id(conn):
    assert ev.get_evidence(conn, "does-not-exist") is None


def test_page_number_and_document_id_can_be_none_for_structured_filings(conn):
    e = ev.save_evidence(conn, symbol="TCS", document_id=None, document_name="Screener quarterly table",
                         source_url="https://screener.in/company/TCS/", page_number=None, text="Sales: 73188")
    assert e.document_id is None and e.page_number is None

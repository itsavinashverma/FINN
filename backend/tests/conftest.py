import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
RETRIEVED = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def retrieved_at():
    return RETRIEVED


@pytest.fixture
def conn(tmp_path, monkeypatch):
    from finn import db
    return db.connect(tmp_path / "test.sqlite3")

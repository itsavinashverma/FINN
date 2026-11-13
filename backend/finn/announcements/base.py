from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from ..models import Announcement


@dataclass(frozen=True)
class CompanyRef:
    """Identifiers for one company. NSE needs `symbol`; BSE needs `bse_code`."""

    symbol: str
    bse_code: str | None = None
    isin: str | None = None


class AnnouncementProvider(Protocol):
    name: str

    def fetch(self, company: CompanyRef, start: date, end: date) -> list[Announcement]:
        """All announcements for `company` with announcement date in [start, end] (IST)."""
        ...


_INFORMED = re.compile(
    r"^.{0,160}?\bhas (?:informed|submitted)(?: to)?(?: the Exchange)?(?:,)?\s*(?:about|regarding|that|the)?\s*",
    re.IGNORECASE,
)


def clean_title(text: str | None) -> str | None:
    """Strip NSE's boilerplate prefix: 'Tata Consultancy Services Limited has informed the Exchange about …'."""
    if not text:
        return None
    t = " ".join(text.split())
    t = _INFORMED.sub("", t, count=1).strip(" .'\"")
    return (t[:1].upper() + t[1:]) if t else None


def parse_size(text: str | None) -> int | None:
    """'330.53 KB' -> 338463. Returns None if absent/unparseable (never 0)."""
    if not text:
        return None
    m = re.match(r"^\s*([\d.]+)\s*(B|Bytes|KB|MB|GB)\s*$", str(text), re.IGNORECASE)
    if not m:
        return None
    mult = {"b": 1, "bytes": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3}[m.group(2).lower()]
    value = int(float(m.group(1)) * mult)
    return value or None

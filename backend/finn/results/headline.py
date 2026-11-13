"""Headline numbers (Revenue, EBITDA, PBT, PAT) and QoQ / YoY changes. Pure functions, no I/O.

EBITDA is not reported in filings; for companies it is derived as
    EBITDA = Profit before exceptional items & tax + Finance costs + D&A − Other income
(verified: TCS Q2 FY27 gives ₹18,815 cr = Screener's "Operating Profit"). For banks and NBFCs,
interest is the cost of doing business, so EBITDA is reported as not meaningful and the
pre-provision operating profit / net interest income are shown instead.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from ..models import StatementBasis
from .xbrl import QuarterFacts

CRORE = Decimal(10_000_000)
SUPPORTED_FORMATS = {"INDAS", "BANKING", "NBFC_INDAS"}


class Metric(BaseModel):
    key: str
    label: str
    value_cr: float | None          # ₹ crore; None when unavailable / not meaningful
    formula: str | None = None      # how it was derived, when not reported directly
    note: str | None = None         # e.g. "not meaningful for banks"


class Headline(BaseModel):
    symbol: str | None
    period_start: str
    period_end: str
    fiscal_label: str               # "Q2 FY27"
    basis: StatementBasis
    audited: bool | None
    format: str
    metrics: dict[str, Metric]      # revenue, ebitda, pbt, pat (+ extras)
    checks: list[str] = Field(default_factory=list)   # failed internal-consistency checks


class Change(BaseModel):
    pct: float | None
    note: str | None = None         # "n.m.", "loss → profit", …


def fiscal_label(period_end) -> str:
    """Indian fiscal year ends in March: quarter ending Sep-2026 -> 'Q2 FY27'."""
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(period_end.month)
    fy = period_end.year + 1 if period_end.month > 3 else period_end.year
    return f"Q{q} FY{fy % 100:02d}" if q else period_end.isoformat()


def _cr(v: Decimal | None) -> float | None:
    return None if v is None else round(float(v / CRORE), 2)


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(CRORE, abs(b) * Decimal("0.005"))


def compute_headline(f: QuarterFacts) -> Headline:
    q = f.quarter
    g = q.get
    checks: list[str] = list(f"non-INR unit: {u}" for u in f.non_inr_units)
    m: dict[str, Metric] = {}

    if f.format not in SUPPORTED_FORMATS:
        reason = f"filing format {f.format} (e.g. insurance) is not supported yet"
        for key, label in (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("pbt", "PBT"), ("pat", "PAT")):
            m[key] = Metric(key=key, label=label, value_cr=None, note=reason)
        return _headline(f, m, checks)

    if f.format == "BANKING":
        income, interest, interest_exp = g("Income"), g("InterestEarned"), g("InterestExpended")
        m["revenue"] = Metric(key="revenue", label="Total income", value_cr=_cr(income),
                              note="banks: interest earned + other income")
        m["nii"] = Metric(key="nii", label="Net interest income",
                          value_cr=_cr(interest - interest_exp) if interest is not None and interest_exp is not None else None,
                          formula="Interest earned − Interest expended")
        m["ebitda"] = Metric(key="ebitda", label="EBITDA", value_cr=None, note="not meaningful for banks")
        m["ppop"] = Metric(key="ppop", label="Operating profit (pre-provision)",
                           value_cr=_cr(g("OperatingProfitBeforeProvisionAndContingencies")))
        m["pbt"] = Metric(key="pbt", label="PBT", value_cr=_cr(g("ProfitLossFromOrdinaryActivitiesBeforeTax")))
        m["pat"] = Metric(key="pat", label="PAT", value_cr=_cr(g("ProfitLossForThePeriod")))
        if income is not None and interest is not None and g("OtherIncome") is not None \
                and not _close(income, interest + g("OtherIncome")):
            checks.append("total income ≠ interest earned + other income")
        return _headline(f, m, checks)

    # Companies (INDAS) and NBFCs (NBFC_INDAS) share the Ind-AS P&L layout.
    revenue, other, income, expenses = g("RevenueFromOperations"), g("OtherIncome"), g("Income"), g("Expenses")
    pbt, exceptional, pbeit = g("ProfitBeforeTax"), g("ExceptionalItemsBeforeTax"), g("ProfitBeforeExceptionalItemsAndTax")
    finance, dna = g("FinanceCosts"), g("DepreciationDepletionAndAmortisationExpense")
    if pbeit is None and pbt is not None and exceptional is not None:
        pbeit = pbt - exceptional

    m["revenue"] = Metric(key="revenue", label="Revenue", value_cr=_cr(revenue))
    if f.format == "NBFC_INDAS":
        m["ebitda"] = Metric(key="ebitda", label="EBITDA", value_cr=None,
                             note="not meaningful for lenders: finance cost is their cost of goods")
    else:
        parts = (pbeit, finance, dna, other)
        m["ebitda"] = Metric(
            key="ebitda", label="EBITDA",
            value_cr=_cr(pbeit + finance + dna - other) if all(p is not None for p in parts) else None,
            formula="PBT before exceptional items + Finance costs + D&A − Other income",
            note=None if all(p is not None for p in parts) else "an input was not reported in the filing",
        )
    m["pbt"] = Metric(key="pbt", label="PBT", value_cr=_cr(pbt))
    m["pat"] = Metric(key="pat", label="PAT", value_cr=_cr(g("ProfitLossForPeriod")))
    owners = g("ProfitOrLossAttributableToOwnersOfParent")
    if f.basis is StatementBasis.CONSOLIDATED and owners is not None:
        m["pat_owners"] = Metric(key="pat_owners", label="PAT to shareholders", value_cr=_cr(owners))
    if exceptional:
        m["exceptional"] = Metric(key="exceptional", label="Exceptional items", value_cr=_cr(exceptional),
                                  note="included in PBT/PAT, excluded from EBITDA")
    if other is not None:
        m["other_income"] = Metric(key="other_income", label="Other income", value_cr=_cr(other))

    # Internal consistency: catches parser bugs and mis-tagged filings rather than hiding them.
    if None not in (income, revenue, other) and not _close(income, revenue + other):
        checks.append("total income ≠ revenue + other income")
    if None not in (income, expenses, pbeit) and not _close(income - expenses, pbeit):
        checks.append("income − expenses ≠ profit before exceptional items")
    if None not in (pbeit, pbt) and exceptional is not None and not _close(pbeit + exceptional, pbt):
        checks.append("PBT ≠ pre-exceptional profit + exceptional items")
    return _headline(f, m, checks)


def _headline(f: QuarterFacts, metrics: dict[str, Metric], checks: list[str]) -> Headline:
    return Headline(symbol=f.symbol, period_start=f.period_start.isoformat(), period_end=f.period_end.isoformat(),
                    fiscal_label=fiscal_label(f.period_end), basis=f.basis, audited=f.audited, format=f.format,
                    metrics=metrics, checks=checks)


def pct_change(current: float | None, base: float | None) -> Change:
    """Percentage change with explicit handling of the cases where a % would mislead."""
    if current is None or base is None:
        return Change(pct=None, note="unavailable")
    if base == 0:
        return Change(pct=None, note="n.m.")
    if base < 0 and current >= 0:
        return Change(pct=None, note="loss → profit")
    if base > 0 and current < 0:
        return Change(pct=None, note="profit → loss")
    if base < 0 and current < 0:
        return Change(pct=None, note="loss narrowed" if current > base else "loss widened")
    return Change(pct=round((current / base - 1) * 100, 2))


def compare(current: Headline, base: Headline | None) -> dict[str, Change] | None:
    """Per-metric change. Refuses to compare different statement bases or formats."""
    if base is None:
        return None
    if base.basis != current.basis:
        raise ValueError(f"refusing to compare {current.basis} with {base.basis} figures")
    if base.format != current.format:
        raise ValueError(f"refusing to compare {current.format} with {base.format} filings")
    return {k: pct_change(v.value_cr, base.metrics[k].value_cr if k in base.metrics else None)
            for k, v in current.metrics.items()}

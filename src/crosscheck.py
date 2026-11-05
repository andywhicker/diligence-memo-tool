"""
Code-only consistency check: the same metric, for the same fiscal year, stated
with values that can't both be right.

Example it is built to catch (AVAV FY2026 10-K):
  MD&A p. 66: "SG&A expense ... was $443.0 million"
  Income statement p. 65: SG&A 443,251 (in thousands) = $443.3 million
  $443.251M does not round to $443.0M, so the two can't both be right as written.

Rules:
  - Metric names are mapped to a small set of standard line items. Anything that
    looks like a change, driver, segment, product/service split, or quarter is
    skipped, so only like-for-like figures are compared.
  - A difference is flagged only if it exceeds the rounding of the LESS precise
    figure (e.g. $443.0M is precise to +/- $0.05M).
  - Deterministic: the same document always gives the same flags.
"""

import re
from itertools import combinations

from src.fintable import _parse

# standard line item -> pattern on the finding's metric name
CANONICAL = {
    "Revenue": r"^(total |net )?(revenue|revenues|net sales|sales)$",
    "Cost of sales": r"^(total )?cost of (sales|revenue|revenues)$",
    "Gross profit": r"^gross (profit|margin)$",
    "SG&A": r"^(sg&a|selling, general,? and administrative)( expense| expenses)?$",
    "R&D": r"^(r&d|research and development)( expense| expenses)?$",
    "Operating income": r"^(income|loss|\(loss\) income|income \(loss\)) from operations$|^operating (income|loss)$",
    "Net income": r"^net (income|loss|\(loss\) income|income \(loss\))$",
    "Operating cash flow": r"^(operating cash flow|net cash (provided by|used in|\(used in\) provided by|provided by \(used in\)) operating activities)$",
    "Capex": r"^(capex|capital expenditures|purchases? of property and equipment|acquisition of property and equipment)$",
    "D&A": r"^depreciation and amortization$",
    "Funded backlog": r"^funded backlog$",
    "Unfunded backlog": r"^unfunded backlog$",
    "Effective tax rate": r"^effective (income )?tax rate$",
    "Goodwill impairment": r"^goodwill impairment( charge| loss)?$",
}
_SKIP = re.compile(r"increase|decrease|change|growth|driver|segment|\baxs\b|\bscde\b|product|service|"
                   r"legacy|acquired|pro forma|quarter|three months|six months|nine months", re.I)
_MONEY_OR_PCT = {"money", "pct"}


def _canonical(metric: str) -> str | None:
    m = metric.strip().lower()
    if not m or _SKIP.search(m):
        return None
    for name, pat in CANONICAL.items():
        if re.search(pat, m):
            return name
    return None


def _single_year(period: str) -> str | None:
    if re.search(r"three|six|nine|quarter|month", period, re.I):
        return None
    years = set(re.findall(r"(?:19|20)\d\d", period))
    return years.pop() if len(years) == 1 else None


def _precision(value_text: str, scale_to_millions: float) -> float:
    """Half a unit in the last written digit, in $ millions (or % points)."""
    m = re.search(r"\d[\d,]*(?:\.(\d+))?", value_text)
    decimals = len(m.group(1)) if m and m.group(1) else 0
    return 0.5 * (10 ** -decimals) * scale_to_millions


def _scale(value_text: str, unit: str) -> float:
    """$M per one written unit, used only for the rounding tolerance."""
    u, v = (unit or "").lower(), value_text.lower()
    if "%" in v or "%" in u:
        return 1.0
    if "billion" in v or "billion" in u:
        return 1000.0
    if "million" in v or "million" in u:
        return 1.0
    if "thousand" in u:
        return 0.001
    return 1e-6


def find_mismatches(findings: list[dict]) -> list[dict]:
    rows = []
    for f in findings:
        if not f["value"]:
            continue
        name = _canonical(f["metric"])
        year = _single_year(f["period"])
        if not name or not year:
            continue
        kind = "pct" if "%" in f["value"] or "%" in (f["unit"] or "") else "money"
        v, k = _parse(f["value"], f["unit"], kind)
        if v is None or k not in _MONEY_OR_PCT:
            continue
        if name in ("Capex", "D&A", "Goodwill impairment"):
            v = abs(v)
        tol = _precision(f["value"], _scale(f["value"], f["unit"]))
        rows.append((name, year, k, v, tol, f))

    flags, seen = [], set()
    for a, b in combinations(rows, 2):
        if (a[0], a[1], a[2]) != (b[0], b[1], b[2]) or a[5]["page"] == b[5]["page"]:
            continue
        diff = abs(a[3] - b[3])
        if diff <= max(a[4], b[4]) + 1e-9:
            continue
        key = (a[0], a[1], round(min(a[3], b[3]), 1), round(max(a[3], b[3]), 1))   # one flag per pair of values
        if key in seen:
            continue
        seen.add(key)
        # put the narrative/MD&A side first when there is one
        fa, fb = (a[5], b[5]) if a[5]["category"] == "narrative" or b[5]["category"] != "narrative" else (b[5], a[5])
        rel = diff / max(abs(a[3]), abs(b[3]), 1e-9)
        flags.append({"metric": a[0], "year": a[1], "kind": a[2], "a": fa, "b": fb, "diff": diff, "rel": rel})
    flags.sort(key=lambda x: -x["rel"])
    return flags

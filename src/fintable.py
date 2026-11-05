"""
Financial summary table.

Division of labor:
  - The MODEL only chooses which verified finding goes in each cell (judgment).
  - CODE converts units to $ millions, computes growth/margins/ratios (labeled
    "calc."), and cross-checks each cell against the same figure on other pages.

Cross-check: a 10-K reports most headline figures more than once (MD&A, the
financial statements, the segment note). Those were extracted independently,
from different chunks. If a cell's value also appears on another page with the
same fiscal year, the cell is "corroborated". This is how we catch the model
picking the wrong column or the wrong unit.
"""

import json
import re
from dataclasses import dataclass, field

from src import llm
from src.extract import load_prompt
from src.synthesize import format_findings

ROWS = ["revenue", "gross_profit", "operating_income", "ebitda_reported", "adjusted_ebitda",
        "d_and_a", "capex", "backlog_total", "largest_customer_pct"]

LABELS = {
    "revenue": "Revenue", "revenue_growth": "Revenue growth % (calc.)",
    "gross_profit": "Gross profit", "gross_margin": "Gross margin % (calc.)",
    "operating_income": "Operating income (loss)",
    "ebitda_reported": "EBITDA (as reported by company)",
    "adjusted_ebitda": "Adjusted EBITDA (as reported by company)",
    "d_and_a": "D&A", "capex": "Capex", "capex_pct": "Capex % of revenue (calc.)",
    "backlog_total": "Backlog (total)", "largest_customer_pct": "Largest customer % of revenue",
}
ORDER = ["revenue", "revenue_growth", "gross_profit", "gross_margin", "operating_income",
         "ebitda_reported", "adjusted_ebitda", "d_and_a", "capex", "capex_pct",
         "backlog_total", "largest_customer_pct"]

SCHEMA = {
    "type": "object",
    "properties": {
        "years": {"type": "array", "items": {"type": "string"}},
        "cells": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "row": {"type": "string", "enum": ROWS},
                "year": {"type": "string"},
                "finding_id": {"type": "string"},
            },
            "required": ["row", "year", "finding_id"],
            "additionalProperties": False,
        }},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["years", "cells", "notes"],
    "additionalProperties": False,
}

NUMERIC_CATEGORIES = {"financial", "balance_sheet", "backlog", "customers"}


@dataclass
class Cell:
    value: float | None = None       # $ millions, or % for percentage rows
    is_pct: bool = False
    pages: list = field(default_factory=list)
    finding_id: str = ""
    calc: bool = False
    corroborated_on: list = field(default_factory=list)
    warning: str = ""


@dataclass
class FinTable:
    years: list
    cells: dict                      # (row, year) -> Cell
    notes: list                      # raw notes with [F..] IDs (citation-checked later)
    calcs: list                      # pseudo-findings for calculated metrics (used by consistency check)
    problems: list                   # cells the code rejected, with reasons


def parse_value(value: str, unit: str) -> tuple[float | None, bool]:
    """'(311,026)' + '$ thousands' -> (-311.026, False). '85%' -> (85.0, True)."""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", value or "")
    if not m:
        return None, False
    x = float(m.group(0).replace(",", ""))
    if "(" in value or value.strip().startswith("-"):
        x = -x
    u = (unit or "").lower()
    if "%" in u or "%" in value or "percent" in u:
        return x, True
    if "thousand" in u:
        return x / 1_000, False
    if "billion" in u:
        return x * 1_000, False
    if "million" in u:
        return x, False
    if u.strip() in ("$", "usd", "dollars"):
        return x / 1_000_000, False
    return None, False                       # unknown unit: refuse to guess


def _year_digits(label: str) -> str:
    m = re.search(r"(19|20)\d\d", label)
    return m.group(0) if m else label


def build(findings: list[dict], cache_path=None, reuse: bool = False) -> FinTable:
    by_id = {f["id"]: f for f in findings}
    if reuse and cache_path and cache_path.exists():
        print("  [financial table] reused saved model output")
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        numeric = [f for f in findings if f["category"] in NUMERIC_CATEGORIES and f["value"]]
        prompt = load_prompt("financial_table.md").replace("{{FINDINGS}}", format_findings(numeric))
        raw = json.loads(llm.ask(prompt, label="financial table", schema=SCHEMA, max_tokens=32000))
        if cache_path:
            cache_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    years = raw["years"][-3:]
    cells, problems = {}, []
    for c in raw["cells"]:
        if c["year"] not in years or not c["finding_id"]:
            continue
        f = by_id.get(c["finding_id"])
        if f is None:
            problems.append(f"{LABELS[c['row']]} {c['year']}: model chose nonexistent finding {c['finding_id']}")
            continue
        value, is_pct = parse_value(f["value"], f["unit"])
        if value is None:
            problems.append(f"{LABELS[c['row']]} {c['year']}: could not read unit '{f['unit']}' "
                            f"for value '{f['value']}' ({f['id']}); left blank")
            continue
        if c["row"] in ("capex", "d_and_a"):
            value = abs(value)            # cash flow statements show outflows in parentheses
        cell = Cell(value=value, is_pct=is_pct, pages=[f["page"]], finding_id=f["id"])
        # The chosen finding's own period must mention the column's year.
        if _year_digits(c["year"]) not in f["period"]:
            cell.warning = f"period of {f['id']} is '{f['period']}', not {c['year']}"
        # Cross-check: same value, same year, on a different page.
        for g in findings:
            if g["id"] == f["id"] or g["page"] == f["page"] or not g["value"]:
                continue
            gv, gpct = parse_value(g["value"], g["unit"])
            if gv is None or gpct != is_pct:
                continue
            if c["row"] in ("capex", "d_and_a"):
                gv = abs(gv)
            if abs(gv - value) <= max(0.051, abs(value) * 0.0005) and _year_digits(c["year"]) in g["period"]:
                if g["page"] not in cell.corroborated_on:
                    cell.corroborated_on.append(g["page"])
        cells[(c["row"], c["year"])] = cell

    calcs = _add_calcs(cells, years)
    return FinTable(years, cells, raw["notes"], calcs, problems)


def _ratio(cells, num_row, den_row, year):
    a, b = cells.get((num_row, year)), cells.get((den_row, year))
    if a and b and a.value is not None and b.value not in (None, 0):
        return a.value / b.value * 100, sorted(set(a.pages + b.pages), key=lambda p: (len(p), p))
    return None, None


def _add_calcs(cells, years) -> list[dict]:
    calcs = []

    def put(row, year, value, pages, desc):
        cells[(row, year)] = Cell(value=value, is_pct=True, pages=pages, calc=True)
        calcs.append({"id": f"C-{row.upper()}-{year}", "category": "calc", "page": "calc",
                      "pages": pages, "metric": LABELS[row], "value": f"{value:.1f}", "unit": "%",
                      "period": year, "claim": f"{LABELS[row]} for {year} = {value:.1f}% ({desc})"})

    for i, y in enumerate(years):
        v, p = _ratio(cells, "gross_profit", "revenue", y)
        if v is not None:
            put("gross_margin", y, v, p, "gross profit / revenue")
        v, p = _ratio(cells, "capex", "revenue", y)
        if v is not None:
            put("capex_pct", y, v, p, "capex / revenue")
        for row in ("operating_income", "adjusted_ebitda"):
            v, p = _ratio(cells, row, "revenue", y)
            if v is not None:
                # margin calcs available to the consistency check, not shown as table rows
                calcs.append({"id": f"C-{row.upper()}_MARGIN-{y}", "category": "calc", "page": "calc",
                              "pages": p, "metric": f"{LABELS[row]} margin (calc.)", "value": f"{v:.1f}",
                              "unit": "%", "period": y,
                              "claim": f"{LABELS[row]} as % of revenue for {y} = {v:.1f}%"})
        if i > 0:
            cur, prev = cells.get(("revenue", y)), cells.get(("revenue", years[i - 1]))
            if cur and prev and prev.value:
                g = (cur.value / prev.value - 1) * 100
                put("revenue_growth", y, g, sorted(set(cur.pages + prev.pages)), f"vs. {years[i - 1]}")
    return calcs


def _fmt(cell: Cell | None) -> str:
    if cell is None or cell.value is None:
        return "Not disclosed"
    num = f"{cell.value:.1f}%" if cell.is_pct else (
        f"({abs(cell.value):,.1f})" if cell.value < 0 else f"{cell.value:,.1f}")
    pages = ", ".join(cell.pages)
    cite = f"(calc.; p{'p' if len(cell.pages) > 1 else ''}. {pages})" if cell.calc else f"(p. {pages})"
    mark = ""
    if not cell.calc:
        mark = " ✓" if cell.corroborated_on else " †"
        if cell.warning:
            mark += " ⚠"
    return f"{num} {cite}{mark}"


def render(t: FinTable) -> tuple[str, list[str]]:
    """Return (markdown table, list of check lines for under the table)."""
    lines = ["| Metric ($ in millions) | " + " | ".join(t.years) + " |",
             "|---|" + "---|" * len(t.years)]
    calc_rows = {"revenue_growth", "gross_margin", "capex_pct"}
    for row in ORDER:
        cells = [_fmt(t.cells.get((row, y))) for y in t.years]
        if row in calc_rows:
            cells = ["n/a" if c == "Not disclosed" else c for c in cells]   # calc impossible, not undisclosed
        lines.append(f"| {LABELS[row]} | " + " | ".join(cells) + " |")

    sourced = [(k, c) for k, c in t.cells.items() if not c.calc]
    corr = [c for _, c in sourced if c.corroborated_on]
    checks = [f"Cross-check: {len(corr)} of {len(sourced)} sourced cells match the same figure for the same "
              f"year on at least one other page (✓). † = found on one page only; verify manually."]
    for (row, y), c in sorted(t.cells.items()):
        if c.warning:
            checks.append(f"⚠ {LABELS[row]} {y}: {c.warning}.")
    checks += [f"⚠ {p}." for p in t.problems]
    return "\n".join(lines), checks

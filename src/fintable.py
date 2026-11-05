"""
Financial tables and PE metrics.

Division of labor:
  - The MODEL only points to inputs: for each slot and year, a finding ID and the
    exact number inside that finding (a finding can hold several numbers).
  - CODE checks the number is in the finding's quote, converts units to
    $ millions, computes every metric (labeled "calc." with its formula), and
    cross-checks each input against the same figure on other pages.

Every calculated metric is also exported as a "calc finding" with an ID like
C-FCF-FY2026, so the memo writer and the consistency check can cite it.

Outputs four tables for Section 5:
  A. Financial summary (template rows)
  B. Cash conversion & earnings quality
  C. Balance sheet & liquidity
  D. Operating metrics
"""

import json
import re
from dataclasses import dataclass, field

from src import llm
from src.extract import load_prompt
from src.synthesize import format_findings
from src.verify import normalize

# slot -> (label, kind). kind: money ($M), pct, count
SLOTS = {
    "revenue": ("Revenue", "money"),
    "gross_profit": ("Gross profit", "money"),
    "operating_income": ("Operating income (loss)", "money"),
    "ebitda_reported": ("EBITDA (as reported by company)", "money"),
    "adjusted_ebitda": ("Adjusted EBITDA (as reported by company)", "money"),
    "d_and_a": ("D&A", "money"),
    "depreciation": ("Depreciation (excl. amortization)", "money"),
    "goodwill_impairment": ("of which: goodwill impairment", "money"),
    "capex": ("Capex", "money"),
    "operating_cash_flow": ("Operating cash flow", "money"),
    "acquired_revenue": ("Revenue from businesses acquired in year", "money"),
    "cost_of_sales": ("Cost of sales", "money"),
    "ffp_revenue": ("Fixed-price revenue", "money"),
    "cost_plus_revenue": ("Cost-plus revenue", "money"),
    "tm_revenue": ("T&M revenue", "money"),
    "largest_customer_pct": ("Largest customer % of revenue", "pct"),
    "total_debt": ("Total debt (principal)", "money"),
    "cash": ("Cash and equivalents", "money"),
    "short_term_investments": ("Short-term investments", "money"),
    "revolver_available": ("Undrawn revolver availability", "money"),
    "accounts_receivable": ("Accounts receivable", "money"),
    "unbilled_receivables": ("Unbilled receivables", "money"),
    "inventory": ("Inventories", "money"),
    "funded_backlog": ("Funded backlog", "money"),
    "unfunded_backlog": ("Unfunded backlog", "money"),
    "backlog_total": ("Backlog (total)", "money"),
    "employees": ("Employees", "count"),
}
SUMMABLE = {"acquired_revenue"}
POSITIVE = {"capex", "d_and_a", "depreciation", "goodwill_impairment", "total_debt"}

# calculated rows -> (label, kind). kind: pct, money, x (multiple), days, musd ($M per head)
CALC_ROWS = {
    "revenue_growth": ("Revenue growth % (calc.)", "pct"),
    "gross_margin": ("Gross margin % (calc.)", "pct"),
    "capex_pct": ("Capex % of revenue (calc.)", "pct"),
    "op_margin": ("Operating margin % (calc.)", "pct"),
    "adj_ebitda_margin": ("Adj. EBITDA margin % (calc.)", "pct"),
    "organic_growth": ("Organic revenue growth % (calc.)", "pct"),
    "fcf": ("Free cash flow (OCF - capex) (calc.)", "money"),
    "fcf_conversion": ("FCF / Adj. EBITDA (calc.)", "pct"),
    "gaap_ebitda": ("GAAP EBITDA (op. income + D&A) (calc.)", "money"),
    "addbacks": ("Add-backs to reach Adj. EBITDA (calc.)", "money"),
    "other_addbacks_pct": ("Add-backs excl. impairment, % of Adj. EBITDA (calc.)", "pct"),
    "dso": ("DSO incl. unbilled, days (calc.)", "days"),
    "dio": ("DIO, days (calc.)", "days"),
    "cash_and_sti": ("Cash + short-term investments (calc.)", "money"),
    "net_debt": ("Net debt (calc.)", "money"),
    "gross_leverage": ("Total debt / Adj. EBITDA (calc.)", "x"),
    "net_leverage": ("Net debt / Adj. EBITDA (calc.)", "x"),
    "liquidity": ("Liquidity incl. undrawn revolver (calc.)", "money"),
    "funded_coverage": ("Funded backlog / revenue (calc.)", "x"),
    "total_backlog_coverage": ("Total backlog / revenue (calc.)", "x"),
    "capex_to_dep": ("Capex / depreciation (calc.)", "x"),
    "revenue_per_fte": ("Revenue per employee, $M (calc.)", "musd"),
    "ffp_pct": ("Fixed-price % of revenue (calc.)", "pct"),
    "cost_plus_pct": ("Cost-plus % of revenue (calc.)", "pct"),
    "tm_pct": ("T&M % of revenue (calc.)", "pct"),
}

TABLES = [
    ("Financial summary", ["revenue", "revenue_growth", "gross_profit", "gross_margin", "operating_income",
                           "ebitda_reported", "adjusted_ebitda", "d_and_a", "capex", "capex_pct",
                           "backlog_total", "largest_customer_pct"], True),
    ("Cash conversion & earnings quality", ["organic_growth", "operating_cash_flow", "fcf", "fcf_conversion",
                                            "gaap_ebitda", "addbacks", "goodwill_impairment",
                                            "other_addbacks_pct", "dso", "dio"], False),
    ("Balance sheet & liquidity (fiscal year end)", ["total_debt", "cash_and_sti", "net_debt", "gross_leverage",
                                                     "net_leverage", "liquidity"], False),
    ("Operating metrics", ["funded_coverage", "total_backlog_coverage", "capex_to_dep", "revenue_per_fte",
                           "ffp_pct", "cost_plus_pct", "tm_pct", "SEGMENTS"], False),
]

_PICK = {"type": "object", "properties": {"finding_id": {"type": "string"}, "number": {"type": "string"}},
         "required": ["finding_id", "number"], "additionalProperties": False}
SCHEMA = {
    "type": "object",
    "properties": {
        "years": {"type": "array", "items": {"type": "string"}},
        "cells": {"type": "array", "items": {
            "type": "object",
            "properties": {"slot": {"type": "string", "enum": list(SLOTS)},
                           "year": {"type": "string"},
                           "picks": {"type": "array", "items": _PICK}},
            "required": ["slot", "year", "picks"], "additionalProperties": False}},
        "segments": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "profit_label": {"type": "string"},
                           "year": {"type": "string"}, "revenue": _PICK, "profit": _PICK},
            "required": ["name", "profit_label", "year", "revenue", "profit"], "additionalProperties": False}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["years", "cells", "segments", "notes"],
    "additionalProperties": False,
}

NUMERIC_CATEGORIES = {"financial", "balance_sheet", "backlog", "customers", "business"}


@dataclass
class Cell:
    value: float
    kind: str
    pages: list
    ids: list = field(default_factory=list)
    calc: bool = False
    formula: str = ""
    corroborated_on: list = field(default_factory=list)
    warning: str = ""


@dataclass
class FinTable:
    years: list
    cells: dict          # (row, year) -> Cell
    labels: dict         # row -> label (includes segment rows)
    notes: list          # model notes with [F..] IDs (citation-checked by caller)
    calcs: list          # calc findings for the memo writer and consistency check
    problems: list       # rejected picks, with reasons
    assumptions: list    # code-generated method notes


# ---- parsing and checks ---------------------------------------------------------
def _parse(number: str, unit: str, kind: str):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", number or "")
    if not m:
        return None, None
    x = float(m.group(0).replace(",", ""))
    if "(" in number or number.strip().lstrip("$").startswith("-"):
        x = -x
    if kind == "count":
        return x, "count"
    if kind == "price":                       # dollars per share, kept as written
        return x, "price"
    u, n = (unit or "").lower(), number.lower()
    if "%" in number or ("%" in u and "$" not in u) or "percent" in u:
        return x, "pct"
    if "billion" in n:
        return x * 1_000, "money"
    if "million" in n:
        return x, "money"
    if "thousand" in u:
        return x / 1_000, "money"
    if "billion" in u:
        return x * 1_000, "money"
    if "million" in u:
        return x, "money"
    if u.strip() in ("$", "usd", "dollars"):
        return x / 1_000_000, "money"
    return None, None


def _in_finding(number: str, f: dict) -> bool:
    bare = re.sub(r"[^\d.]", "", number or "").strip(".")
    if not bare:
        return False
    quote_digits = normalize(f["quote"]).replace(",", "")
    value_bare = re.sub(r"[^\d.]", "", f["value"] or "").strip(".")
    return bare in quote_digits or bare == value_bare


def _year(label: str) -> str:
    m = re.search(r"(19|20)\d\d", label)
    return m.group(0) if m else label


def _slug(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", s.upper()).strip("_")


def _sorted_pages(pages):
    return sorted(set(pages), key=lambda p: (not p.isdigit(), int(p) if p.isdigit() else 0, p))


def fmt(value: float, kind: str) -> str:
    if kind == "pct":
        return f"{value:.1f}%"
    if kind == "x":
        return f"{value:.2f}x"
    if kind == "days":
        return f"{value:.0f}"
    if kind == "musd":
        return f"${value:.2f}"
    if kind == "count":
        return f"{value:,.0f}"
    if kind == "price":
        return f"${value:,.2f}"
    return f"({abs(value):,.1f})" if value < 0 else f"{value:,.1f}"


# ---- build ------------------------------------------------------------------
def build(findings: list[dict], cache_file=None) -> FinTable:
    by_id = {f["id"]: f for f in findings}
    numeric = [f for f in findings if f["category"] in NUMERIC_CATEGORIES and f["value"]]
    prompt = load_prompt("financial_table.md").replace("{{FINDINGS}}", format_findings(numeric))
    raw = json.loads(llm.ask(prompt, label="financial table", schema=SCHEMA, max_tokens=48000,
                             cache_file=cache_file))

    years = raw["years"][-3:]
    cells, problems, labels = {}, [], {k: v[0] for k, v in {**SLOTS, **CALC_ROWS}.items()}

    def take(picks, row, year, kind, summable=False):
        if not picks:
            return None
        if len(picks) > 1 and not summable:
            problems.append(f"{labels[row]} {year}: model gave {len(picks)} picks for a single-value slot; used the first")
            picks = picks[:1]
        total, pages, ids, warn = 0.0, [], [], ""
        for p in picks:
            f = by_id.get(p["finding_id"])
            if f is None:
                problems.append(f"{labels[row]} {year}: nonexistent finding {p['finding_id']}; left blank")
                return None
            if not _in_finding(p["number"], f):
                problems.append(f"{labels[row]} {year}: '{p['number']}' is not in finding {f['id']}; left blank")
                return None
            v, k = _parse(p["number"], f["unit"], kind)
            if v is None or k != kind:
                problems.append(f"{labels[row]} {year}: could not read '{p['number']}' (unit '{f['unit']}') "
                                f"as {kind} from {f['id']}; left blank")
                return None
            if row in POSITIVE:
                v = abs(v)
            total += v
            pages.append(f["page"])
            ids.append(f["id"])
            if _year(year) not in f["period"] and _year(year) not in f["claim"]:
                warn = f"{f['id']} is dated '{f['period']}', not {year}"
        cell = Cell(total, kind, _sorted_pages(pages), ids, warning=warn)
        if len(picks) == 1:
            _corroborate(cell, row, year, findings)
        return cell

    for c in raw["cells"]:
        if c["year"] in years:
            cell = take(c["picks"], c["slot"], c["year"], SLOTS[c["slot"]][1], c["slot"] in SUMMABLE)
            if cell:
                cells[(c["slot"], c["year"])] = cell

    segments = []
    for s in raw["segments"]:
        if s["year"] not in years:
            continue
        name = s["name"].strip()
        rk, pk = f"seg_rev:{name}", f"seg_profit:{name}"
        labels[rk], labels[pk] = f"{name} revenue", f"{name} {s['profit_label']}"
        labels[f"seg_margin:{name}"] = f"{name} {s['profit_label']} margin % (calc.)"
        for key, pick in ((rk, s["revenue"]), (pk, s["profit"])):
            if pick["finding_id"]:
                cell = take([pick], key, s["year"], "money")
                if cell:
                    cells[(key, s["year"])] = cell
        if name not in segments:
            segments.append(name)

    calcs, assumptions = _calculate(cells, years, segments, labels)
    return FinTable(years, cells, labels, raw["notes"], calcs, problems, assumptions)


def _corroborate(cell: Cell, row: str, year: str, findings: list[dict]):
    """Same value, same year, on a different page = independent confirmation."""
    for g in findings:
        if g["id"] in cell.ids or g["page"] in cell.pages or not g["value"]:
            continue
        gv, gk = _parse(g["value"], g["unit"], cell.kind)
        if gv is None or gk != cell.kind:
            continue
        if row in POSITIVE:
            gv = abs(gv)
        if abs(gv - cell.value) <= max(0.051, abs(cell.value) * 0.0005) and _year(year) in g["period"]:
            if g["page"] not in cell.corroborated_on:
                cell.corroborated_on.append(g["page"])


# ---- metrics -----------------------------------------------------------------
def _calculate(cells, years, segments, labels):
    calcs, assumptions = [], set()

    def get(row, y):
        c = cells.get((row, y))
        return c if c is not None else None

    def put(row, y, value, inputs, formula, kind=None):
        kind = kind or CALC_ROWS[row][1]
        pages = _sorted_pages([p for c in inputs for p in c.pages])
        cells[(row, y)] = Cell(value, kind, pages, calc=True, formula=formula)
        calcs.append({
            "id": f"C-{_slug(row)}-{_slug(y)}", "category": "calc", "page": "calc", "pages": pages,
            "metric": labels[row], "value": fmt(value, kind).strip("$x%()").replace(",", ""),
            "unit": {"pct": "%", "money": "$ millions", "x": "x", "days": "days", "musd": "$ millions"}[kind],
            "period": y, "quote": "",
            "claim": f"{labels[row]} for {y} = {fmt(value, kind)}; formula: {formula}",
        })

    def m(c):   # money text for formulas
        return fmt(c.value, "money")

    for i, y in enumerate(years):
        prev = years[i - 1] if i > 0 else None
        rev, gp, op = get("revenue", y), get("gross_profit", y), get("operating_income", y)
        adj, da, dep = get("adjusted_ebitda", y), get("d_and_a", y), get("depreciation", y)
        capex, ocf, imp = get("capex", y), get("operating_cash_flow", y), get("goodwill_impairment", y)
        acq, cogs = get("acquired_revenue", y), get("cost_of_sales", y)
        debt, cash, sti, rcf = get("total_debt", y), get("cash", y), get("short_term_investments", y), get("revolver_available", y)
        ar, unb, inv = get("accounts_receivable", y), get("unbilled_receivables", y), get("inventory", y)
        fb, ub, bt, emp = get("funded_backlog", y), get("unfunded_backlog", y), get("backlog_total", y), get("employees", y)
        rev_prev = get("revenue", prev) if prev else None

        if rev and rev_prev and rev_prev.value:
            put("revenue_growth", y, (rev.value / rev_prev.value - 1) * 100, [rev, rev_prev],
                f"{m(rev)} / {m(rev_prev)} - 1")
        if rev and rev.value:
            for row, c, name in (("gross_margin", gp, "gross profit"), ("capex_pct", capex, "capex"),
                                 ("op_margin", op, "operating income"), ("adj_ebitda_margin", adj, "Adj. EBITDA"),
                                 ("ffp_pct", get("ffp_revenue", y), "fixed-price revenue"),
                                 ("cost_plus_pct", get("cost_plus_revenue", y), "cost-plus revenue"),
                                 ("tm_pct", get("tm_revenue", y), "T&M revenue")):
                if c:
                    put(row, y, c.value / rev.value * 100, [c, rev], f"{name} {m(c)} / revenue {m(rev)}")
        if rev and acq and rev_prev and rev_prev.value:
            organic = rev.value - acq.value
            put("organic_growth", y, (organic / rev_prev.value - 1) * 100, [rev, acq, rev_prev],
                f"(revenue {m(rev)} - acquired revenue {m(acq)}) / prior-year revenue {m(rev_prev)} - 1")
            assumptions.add("Organic growth removes revenue contributed in the year by businesses acquired in that "
                            "year, as the company discloses it; it does not adjust the prior year.")
        if ocf and capex:
            fcf = ocf.value - capex.value
            put("fcf", y, fcf, [ocf, capex], f"OCF {m(ocf)} - capex {m(capex)}")
            if adj and adj.value > 0:
                put("fcf_conversion", y, fcf / adj.value * 100, [ocf, capex, adj],
                    f"FCF {fmt(fcf, 'money')} / Adj. EBITDA {m(adj)}")
        if op and da:
            gaap = op.value + da.value
            put("gaap_ebitda", y, gaap, [op, da], f"operating income {m(op)} + D&A {m(da)}")
            if adj:
                addbacks = adj.value - gaap
                put("addbacks", y, addbacks, [adj, op, da],
                    f"Adj. EBITDA {m(adj)} - GAAP EBITDA {fmt(gaap, 'money')}")
                if imp and adj.value > 0:
                    put("other_addbacks_pct", y, (addbacks - imp.value) / adj.value * 100, [adj, op, da, imp],
                        f"(add-backs {fmt(addbacks, 'money')} - goodwill impairment {m(imp)}) / Adj. EBITDA {m(adj)}")
                assumptions.add("Add-backs = company Adjusted EBITDA minus GAAP EBITDA (operating income + D&A). If "
                                "the company's measure is segment-level, add-backs also include costs outside "
                                "segment results (e.g. unallocated corporate).")
        if rev and rev.value and ar:
            recv = ar.value + (unb.value if unb else 0)
            put("dso", y, recv / rev.value * 365, [ar, rev] + ([unb] if unb else []),
                f"(AR {m(ar)}" + (f" + unbilled {m(unb)}" if unb else "") + f") / revenue {m(rev)} x 365")
            if not unb:
                assumptions.add(f"DSO for {y} excludes unbilled receivables (not found).")
            assumptions.add("Working-capital days use fiscal-year-end balances, not averages; balances acquired "
                            "mid-year inflate days relative to a full-year average.")
        if inv and cogs and cogs.value:
            put("dio", y, inv.value / cogs.value * 365, [inv, cogs], f"inventory {m(inv)} / cost of sales {m(cogs)} x 365")
        if cash:
            liquid = cash.value + (sti.value if sti else 0)
            liq_inputs = [cash] + ([sti] if sti else [])
            put("cash_and_sti", y, liquid, liq_inputs,
                f"cash {m(cash)}" + (f" + short-term investments {m(sti)}" if sti else ""))
            assumptions.add("Net debt treats short-term investments as cash." if sti else
                            f"No short-term investments found for {y}; net debt uses cash only.")
            if debt:
                nd = debt.value - liquid
                put("net_debt", y, nd, [debt] + liq_inputs, f"debt {m(debt)} - cash and investments {fmt(liquid, 'money')}")
                assumptions.add("Total debt is principal as disclosed (excludes leases; convertible notes at principal).")
                if adj and adj.value > 0:
                    put("gross_leverage", y, debt.value / adj.value, [debt, adj], f"debt {m(debt)} / Adj. EBITDA {m(adj)}")
                    put("net_leverage", y, nd / adj.value, [debt, adj] + liq_inputs,
                        f"net debt {fmt(nd, 'money')} / Adj. EBITDA {m(adj)}")
            if rcf:
                put("liquidity", y, liquid + rcf.value, liq_inputs + [rcf],
                    f"cash and investments {fmt(liquid, 'money')} + undrawn revolver {m(rcf)}")
        if rev and rev.value:
            if fb:
                put("funded_coverage", y, fb.value / rev.value, [fb, rev], f"funded backlog {m(fb)} / revenue {m(rev)}")
            total_bl = bt.value if bt else (fb.value + ub.value if fb and ub else None)
            if total_bl is not None:
                ins = [bt] if bt else [fb, ub]
                put("total_backlog_coverage", y, total_bl / rev.value, ins + [rev],
                    f"total backlog {fmt(total_bl, 'money')} / revenue {m(rev)}")
                if not bt:
                    assumptions.add("Total backlog = funded + unfunded as reported (the company does not report a total).")
            if emp and emp.value:
                put("revenue_per_fte", y, rev.value / emp.value, [rev, emp], f"revenue {m(rev)} / {fmt(emp.value, 'count')} employees")
        if capex and dep and dep.value:
            put("capex_to_dep", y, capex.value / dep.value, [capex, dep], f"capex {m(capex)} / depreciation {m(dep)}")
        for name in segments:
            sr, sp = get(f"seg_rev:{name}", y), get(f"seg_profit:{name}", y)
            if sr and sp and sr.value:
                put(f"seg_margin:{name}", y, sp.value / sr.value * 100, [sp, sr],
                    f"{name} profit {m(sp)} / revenue {m(sr)}", kind="pct")

    return calcs, sorted(assumptions)


# ---- render -------------------------------------------------------------------
def _cell_text(cell: Cell | None) -> str:
    if cell is None:
        return "Not disclosed"
    pages = ", ".join(cell.pages)
    if cell.calc:
        return f"{fmt(cell.value, cell.kind)} (calc.; p{'p' if len(cell.pages) > 1 else ''}. {pages})"
    mark = " ✓" if cell.corroborated_on else " †"
    if cell.warning:
        mark += " ⚠"
    return f"{fmt(cell.value, cell.kind)} (p{'p' if len(cell.pages) > 1 else ''}. {pages}){mark}"


def render(t: FinTable) -> str:
    out = []
    segments = sorted({k.split(":", 1)[1] for (k, _) in t.cells if k.startswith("seg_margin:")})
    for title, rows, keep_all in TABLES:
        rows = [r for row in rows for r in ([f"seg_margin:{s}" for s in segments] if row == "SEGMENTS" else [row])]
        body = []
        for row in rows:
            texts = [_cell_text(t.cells.get((row, y))) for y in t.years]
            is_calc = row in CALC_ROWS or row.startswith("seg_margin:")
            if is_calc:
                texts = ["n/a" if x == "Not disclosed" else x for x in texts]
            if not keep_all and all(x in ("n/a", "Not disclosed") for x in texts):
                continue
            body.append(f"| {t.labels[row]} | " + " | ".join(texts) + " |")
        if not body:
            continue
        unit = "$ in millions" if title != "Operating metrics" else "$ in millions, ratios as noted"
        out += [f"**{title}**", "", f"| Metric ({unit}) | " + " | ".join(t.years) + " |",
                "|---|" + "---|" * len(t.years), *body, ""]
    return "\n".join(out)


def checks(t: FinTable) -> list[str]:
    sourced = [c for c in t.cells.values() if not c.calc]
    corr = [c for c in sourced if c.corroborated_on]
    lines = [f"Cross-check: {len(corr)} of {len(sourced)} sourced inputs match the same figure for the same year "
             f"on at least one other page (✓). † = found on one page only; verify manually.",
             "Every (calc.) figure is computed by code from the cited inputs; formulas are listed in calcs.json."]
    lines += [f"Method: {a}" for a in t.assumptions]
    for (row, y), c in sorted(t.cells.items()):
        if c.warning:
            lines.append(f"⚠ {t.labels[row]} {y}: {c.warning}.")
    lines += [f"⚠ {p}." for p in t.problems]
    return lines

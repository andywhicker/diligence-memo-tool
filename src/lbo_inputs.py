"""
LBO inputs: everything the v2 Excel model needs, with a page cite on every number.

Two sources:
  1. The financial tables already built for the memo (src/fintable.py): revenue,
     EBITDA, D&A, capex, cash, debt, working capital, etc.
  2. A separate, small model call for LBO-only items (share count and price,
     payables, taxes, NOLs, interest, SBC, acquisition costs, revolver size).
     Kept separate so it never changes the memo's cached answers.

Same rules as the tables: the model only points to a number inside a finding;
code checks the number is in the finding's quote, converts units, and
cross-checks against other pages.

Output: output/<doc>/lbo_inputs.json, read by lbo.py (no AI in v2).
"""

import json
from datetime import date

from src import llm
from src.extract import load_prompt
from src.fintable import Cell, _corroborate, _in_finding, _parse, _sorted_pages, _year
from src.synthesize import format_findings

# slot -> (label, kind)
LBO_SLOTS = {
    "shares_outstanding": ("Common shares outstanding", "count"),
    "share_price": ("Share price", "price"),
    "accounts_payable": ("Accounts payable", "money"),
    "accrued_liabilities": ("Accrued liabilities", "money"),
    "contract_liabilities": ("Contract liabilities / customer advances", "money"),
    "cash_taxes_paid": ("Cash taxes paid", "money"),
    "effective_tax_rate": ("Effective tax rate", "pct"),
    "federal_nol": ("Federal NOL carryforwards", "money"),
    "interest_expense": ("Interest expense", "money"),
    "stock_based_comp": ("Stock-based compensation", "money"),
    "acquisition_costs": ("Acquisition-related expenses (company add-back)", "money"),
    "revolver_commitment": ("Revolver commitment", "money"),
}
POSITIVE = {"cash_taxes_paid", "interest_expense", "stock_based_comp", "acquisition_costs",
            "accounts_payable", "accrued_liabilities", "contract_liabilities"}

_PICK = {"type": "object", "properties": {"finding_id": {"type": "string"}, "number": {"type": "string"}},
         "required": ["finding_id", "number"], "additionalProperties": False}
SCHEMA = {
    "type": "object",
    "properties": {
        "years": {"type": "array", "items": {"type": "string"}},
        "cells": {"type": "array", "items": {
            "type": "object",
            "properties": {"slot": {"type": "string", "enum": list(LBO_SLOTS)},
                           "year": {"type": "string"},
                           "picks": {"type": "array", "items": _PICK}},
            "required": ["slot", "year", "picks"], "additionalProperties": False}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["years", "cells", "notes"],
    "additionalProperties": False,
}


def build(findings: list[dict], cache_file=None):
    by_id = {f["id"]: f for f in findings}
    with_values = [f for f in findings if f["value"]]
    prompt = load_prompt("lbo_inputs.md").replace("{{FINDINGS}}", format_findings(with_values))
    raw = json.loads(llm.ask(prompt, label="LBO inputs", schema=SCHEMA, max_tokens=32000, cache_file=cache_file))

    cells, problems = {}, []
    for c in raw["cells"]:
        if not c["picks"]:
            continue
        slot, year = c["slot"], c["year"]
        label, kind = LBO_SLOTS[slot]
        p = c["picks"][0]
        f = by_id.get(p["finding_id"])
        if f is None:
            problems.append(f"{label} {year}: nonexistent finding {p['finding_id']}; left blank")
            continue
        if not _in_finding(p["number"], f):
            problems.append(f"{label} {year}: '{p['number']}' is not in finding {f['id']}; left blank")
            continue
        v, k = _parse(p["number"], f["unit"], kind)
        if v is None or k != kind:
            problems.append(f"{label} {year}: could not read '{p['number']}' (unit '{f['unit']}') as {kind}; left blank")
            continue
        if slot in POSITIVE:
            v = abs(v)
        cell = Cell(v, kind, [f["page"]], [f["id"]])
        if _year(year) not in f["period"] and _year(year) not in f["claim"]:
            cell.warning = f"{f['id']} is dated '{f['period']}', not {year}"
        _corroborate(cell, slot, year, findings)
        cells[(slot, year)] = cell
    return cells, raw["notes"], problems


def _cell_json(cell: Cell, label: str, by_id: dict) -> dict:
    return {
        "label": label, "value": round(cell.value, 6), "kind": cell.kind,
        "unit": {"money": "$ millions", "pct": "%", "count": "count", "price": "$ per share"}.get(cell.kind, cell.kind),
        "pages": cell.pages, "finding_ids": cell.ids,
        "quotes": [by_id[i]["quote"] for i in cell.ids if i in by_id],
        "corroborated_on": cell.corroborated_on, "warning": cell.warning,
    }


def export(path, company: str, pdf: str, findings: list[dict], table, lbo_cells, lbo_notes, lbo_problems):
    """Write lbo_inputs.json: every sourced input with value, unit, page cites and quote."""
    by_id = {f["id"]: f for f in findings}
    inputs = {}
    for (slot, year), cell in table.cells.items():
        if cell.calc or slot.startswith("seg_"):
            continue
        inputs.setdefault(slot, {})[year] = _cell_json(cell, table.labels[slot], by_id)
    for (slot, year), cell in lbo_cells.items():
        inputs.setdefault(slot, {})[year] = _cell_json(cell, LBO_SLOTS[slot][0], by_id)
    data = {
        "company": company, "source_document": pdf, "generated": date.today().isoformat(),
        "years": table.years,
        "inputs": inputs,
        "notes": lbo_notes + table.notes,
        "problems": lbo_problems + table.problems,
        "method": table.assumptions,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data

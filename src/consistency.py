"""
Consistency check: where management's narrative and the numbers disagree.

The model proposes items. Code keeps an item only if:
  - it cites at least one narrative/statement finding AND at least one numeric
    finding or code-calculated metric (two-sided);
  - every cited ID exists;
  - every number it writes appears in the findings it cites (rounding allowed).
Dropped items are logged with the reason.
"""

import json

from src import llm
from src.citations import _matches, _number_forms, _numbers_in
from src.extract import load_prompt
from src.synthesize import format_findings

FLAGS = ["Inconsistent", "Needs explanation", "Consistent"]

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "narrative_claim": {"type": "string"},
                "narrative_ids": {"type": "array", "items": {"type": "string"}},
                "what_numbers_show": {"type": "string"},
                "number_ids": {"type": "array", "items": {"type": "string"}},
                "flag": {"type": "string", "enum": FLAGS},
                "why": {"type": "string"},
            },
            "required": ["narrative_claim", "narrative_ids", "what_numbers_show", "number_ids", "flag", "why"],
            "additionalProperties": False,
        }}
    },
    "required": ["items"],
    "additionalProperties": False,
}

NARRATIVE_CATEGORIES = {"narrative", "qoe", "guidance", "business", "risk"}
NUMBER_CATEGORIES = {"financial", "balance_sheet", "backlog", "customers"}


def _cite(ids: list[str], by_id: dict) -> str:
    pages, calc = [], False
    for i in ids:
        f = by_id[i]
        if f["category"] == "calc":
            calc = True
            pages += f["pages"]
        else:
            pages.append(f["page"])
    pages = sorted(set(pages), key=lambda p: (not p.isdigit(), int(p) if p.isdigit() else 0, p))
    prefix = "calc.; " if calc else ""
    return f"({prefix}p{'p' if len(pages) > 1 else ''}. {', '.join(pages)})"


def run(findings: list[dict], calcs: list[dict], cache_path=None, reuse: bool = False):
    by_id = {f["id"]: f for f in findings + calcs}
    if reuse and cache_path and cache_path.exists():
        print("  [consistency check] reused saved model output")
        items = json.loads(cache_path.read_text(encoding="utf-8"))["items"]
    else:
        narrative = [f for f in findings if f["category"] in NARRATIVE_CATEGORIES]
        numbers = [f for f in findings if f["category"] in NUMBER_CATEGORIES and f["value"]]
        calc_text = "\n".join(f"[{c['id']}] {c['claim']}" for c in calcs) or "(none)"
        prompt = (load_prompt("consistency_check.md")
                  .replace("{{NARRATIVE}}", format_findings(narrative))
                  .replace("{{NUMBERS}}", format_findings(numbers))
                  .replace("{{CALCS}}", calc_text))
        raw = json.loads(llm.ask(prompt, label="consistency check", schema=SCHEMA, max_tokens=32000))
        if cache_path:
            cache_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        items = raw["items"]

    rows, dropped = [], []
    for it in items:
        label = it["narrative_claim"][:100]
        all_ids = it["narrative_ids"] + it["number_ids"]
        bad = [i for i in all_ids if i not in by_id]
        if bad:
            dropped.append((label, f"cites nonexistent IDs {bad}"))
            continue
        if not it["narrative_ids"] or not it["number_ids"]:
            dropped.append((label, "not two-sided (needs a narrative cite and a number cite)"))
            continue
        forms = set().union(*(_number_forms(by_id[i]) for i in all_ids))
        text = " ".join([it["narrative_claim"], it["what_numbers_show"], it["why"]])
        unsupported = [n for n in _numbers_in(text) if not _matches(n, forms)]
        if unsupported:
            dropped.append((label, f"numbers {unsupported} not in cited findings"))
            continue
        rows.append(f"| {it['narrative_claim']} | {_cite(it['narrative_ids'], by_id)} "
                    f"| {it['what_numbers_show']} | {_cite(it['number_ids'], by_id)} "
                    f"| **{it['flag']}**: {it['why']} |")

    header = ["| Narrative claim | Cite | What the numbers show | Cite | Flag |",
              "|---|---|---|---|---|"]
    if not rows:
        return "No inconsistencies identified that passed citation checks.", dropped
    return "\n".join(header + [r.replace("\n", " ") for r in rows]), dropped

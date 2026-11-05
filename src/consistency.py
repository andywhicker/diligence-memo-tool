"""
Consistency check: where management's narrative and the numbers disagree.

Three layers, merged into one table:
  1. CODE (src/crosscheck.py): the same line item for the same year stated with
     values that can't both be right. Deterministic: same flags every run.
  2. AI pass 1: reads narrative + numbers + code calcs, proposes items.
  3. AI pass 2: told what layers 1-2 found, asked specifically for what they missed.
     (A single AI pass found different things on different runs; two passes with
     the second hunting for misses is more reliable.)

AI items are kept only if:
  - they cite at least one narrative/statement finding AND at least one numeric
    finding or code-calculated metric (two-sided);
  - every cited ID exists;
  - every number they write appears in the findings they cite (rounding allowed).
Dropped items are logged with the reason.
"""

import json

from src import llm
from src.citations import _matches, _number_forms, _numbers_in
from src.crosscheck import find_mismatches
from src.extract import load_prompt
from src.synthesize import format_calcs, format_findings

FLAGS = ["Inconsistent", "Needs explanation", "Consistent"]
MAX_ITEMS = 12

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


def _code_item(x: dict) -> dict:
    """Turn a crosscheck mismatch into a table row (already verified: both sides are verified findings)."""
    a, b = x["a"], x["b"]
    unit = "pts" if x["kind"] == "pct" else "M"
    diff = f"{x['diff']:.1f} pts" if x["kind"] == "pct" else f"${x['diff']:,.1f}M"
    return {
        "narrative_claim": a["claim"], "narrative_ids": [a["id"]],
        "what_numbers_show": b["claim"], "number_ids": [b["id"]],
        "flag": "Needs explanation",
        "why": (f"Code check: the same line item ({x['metric']}, FY{x['year']}) is stated with values that differ "
                f"by {diff} (calc.), more than rounding allows. Confirm which figure is right: a typo, a "
                f"restatement, or a different definition."),
        "source": "code",
    }


def _summary(items: list[dict]) -> str:
    if not items:
        return "(none yet)"
    return "\n".join(f"- {it['narrative_claim'][:160]} | cites {it['narrative_ids'] + it['number_ids']}"
                     for it in items)


def _overlaps(a: dict, b: dict) -> bool:
    ia, ib = set(a["narrative_ids"] + a["number_ids"]), set(b["narrative_ids"] + b["number_ids"])
    return bool(ia and ib) and len(ia & ib) >= 0.5 * min(len(ia), len(ib))


def run(findings: list[dict], calcs: list[dict], cache_file=None):
    by_id = {f["id"]: f for f in findings + calcs}
    narrative = [f for f in findings if f["category"] in NARRATIVE_CATEGORIES]
    numbers = [f for f in findings if f["category"] in NUMBER_CATEGORIES and f["value"]]

    code_items = [_code_item(x) for x in find_mismatches(findings)]
    print(f"  [consistency: code check] {len(code_items)} same-metric mismatches found")

    base = (load_prompt("consistency_check.md")
            .replace("{{NARRATIVE}}", format_findings(narrative))
            .replace("{{NUMBERS}}", format_findings(numbers))
            .replace("{{CALCS}}", format_calcs(calcs)))

    def ask(pass_no: int, already: list[dict]) -> list[dict]:
        cache = cache_file.with_name(f"{cache_file.stem}_pass{pass_no}.json") if cache_file else None
        prompt = base.replace("{{ALREADY_FOUND}}", _summary(already))
        out = json.loads(llm.ask(prompt, label=f"consistency pass {pass_no}", schema=SCHEMA,
                                 max_tokens=32000, cache_file=cache))["items"]
        for it in out:
            it["source"] = f"pass {pass_no}"
        return out

    pass1 = ask(1, code_items)
    pass2 = ask(2, code_items + pass1)

    kept, dropped = [], []
    for it in pass1 + pass2:
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
        if any(_overlaps(it, k) for k in kept):
            dropped.append((label, f"duplicate of an earlier item ({it['source']})"))
            continue
        kept.append(it)

    # A code flag is redundant if an AI item already cites both of its findings.
    code_kept = [c for c in code_items
                 if not any(set(c["narrative_ids"] + c["number_ids"]) <= set(k["narrative_ids"] + k["number_ids"])
                            for k in kept)]
    # The item limit applies to AI items only. Code flags are deterministic and both sides are
    # verified findings, so they are always kept.
    order = {"Inconsistent": 0, "Needs explanation": 1, "Consistent": 2}
    kept.sort(key=lambda it: order[it["flag"]])
    if len(kept) > MAX_ITEMS:
        dropped += [(it["narrative_claim"][:100], "over the AI item limit") for it in kept[MAX_ITEMS:]]
        kept = kept[:MAX_ITEMS]
    # Order: problems first (Inconsistent, then Needs explanation, then Consistent), AI before code within each.
    items = sorted(kept + code_kept, key=lambda it: (order[it["flag"]], it["source"] == "code"))

    counts = {s: sum(1 for it in items if it["source"] == s) for s in ("code", "pass 1", "pass 2")}
    print(f"  [consistency] kept {len(items)} items (code {counts['code']}, pass 1 {counts['pass 1']}, "
          f"pass 2 {counts['pass 2']}); dropped {len(dropped)}")

    header = ["| Narrative claim | Cite | What the numbers show | Cite | Flag |", "|---|---|---|---|---|"]
    if not items:
        return "No inconsistencies identified that passed citation checks.", dropped
    rows = [f"| {it['narrative_claim']} | {_cite(it['narrative_ids'], by_id)} "
            f"| {it['what_numbers_show']} | {_cite(it['number_ids'], by_id)} "
            f"| **{it['flag']}**: {it['why']} |".replace("\n", " ") for it in items]
    return "\n".join(header + rows), dropped

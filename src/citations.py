"""
Citation enforcement: the memo's "no citation, no claim" rule, applied by code.

Every line of the draft memo is checked. A line is DELETED (and logged) if:
  - it cites a finding ID that doesn't exist;
  - it contains a number but cites nothing;
  - it contains a number that does not appear in any finding it cites
    (allowing only rounding/unit conversion, e.g. 1,976,845 thousand -> 1,976.8 million).

Lines that pass have their IDs replaced by page cites: [F08-056][F10-003] -> (pp. 65, 81).

Exempt from needing a citation: headers, blank lines, "Not disclosed" items,
and lines with no numbers in the Questions for Management section or in the
fixed disclaimer text. (Number-free factual sentences elsewhere still need a
citation; they are deleted if they have none.)
"""

import re
from dataclasses import dataclass, field

from src.verify import _EXEMPT, _NUMBER

_ID_TOKEN = r"F\d{2}-\d{3}|C-[A-Z0-9_]+-[A-Z0-9_]+"      # findings (F08-056) and code calcs (C-FCF-FY2026)
_ID = re.compile(rf"\[({_ID_TOKEN})\]")
_ID_RUN = re.compile(rf"(?:\s*\[(?:{_ID_TOKEN})\])+")
_PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")
_LIST_PREFIX = re.compile(r"^\s*(?:[-*>]|\d+[.)])\s+")
_HEADER_NUM = re.compile(r"^#+\s*\d+\.")


@dataclass
class CitationReport:
    kept: int = 0
    deleted: list = field(default_factory=list)      # (line, reason)


def _number_forms(f: dict) -> set[str]:
    """All acceptable written forms of the numbers in one finding."""
    forms = set()
    texts = [f["value"], f["claim"]]
    for t in texts:
        for n in _NUMBER.findall(t or ""):
            bare = n.replace(",", "").rstrip(".")
            if not bare:
                continue
            forms.add(bare)
            try:
                x = float(bare)
            except ValueError:
                continue
            for dp in (0, 1, 2):                    # ordinary rounding: 2.61 -> 2.6, 1,183.0 -> 1183
                forms.add(f"{x:.{dp}f}")
            unit = (f.get("unit") or "").lower()
            # divisors converting the stated unit to other common units (<1 means multiply)
            scales = []
            if "thousand" in unit:
                scales = [1e3, 1e6, 1e-3]           # -> millions, billions, raw dollars
            elif unit.strip() in ("$", "usd", "dollars"):
                scales = [1e3, 1e6, 1e9]            # -> thousands, millions, billions
            elif "million" in unit:
                scales = [1e3, 1e-3]                # -> billions, thousands
            for s in scales:
                for dp in (0, 1, 2):
                    forms.add(f"{x / s:.{dp}f}")
    return forms


def _numbers_in(line: str) -> list[str]:
    text = _ID_RUN.sub(" ", line)
    text = _LIST_PREFIX.sub("", text)
    for pattern in _EXEMPT:
        text = pattern.sub(" ", text)
    out = []
    for n in _NUMBER.findall(text):
        bare = n.replace(",", "").rstrip(".")
        if not bare or re.fullmatch(r"(19|20)\d\d", bare):
            continue
        out.append(bare)
    return out


def _matches(num: str, forms: set[str]) -> bool:
    if num in forms:
        return True
    # tolerate trailing-zero differences: "28.0" vs "28", "1,183.0" vs "1183"
    try:
        x = float(num)
    except ValueError:
        return False
    return any(_safe_float(f) == x for f in forms)


def _safe_float(s: str):
    try:
        return float(s)
    except ValueError:
        return None


def _page_cite(ids: list[str], by_id: dict) -> str:
    pages, calc = [], False
    for i in ids:
        f = by_id[i]
        for p in (f["pages"] if f.get("category") == "calc" else [f["page"]]):
            if p not in pages:
                pages.append(p)
        calc = calc or f.get("category") == "calc"
    pages.sort(key=lambda p: (not p.isdigit(), int(p) if p.isdigit() else 0, p))
    prefix = "calc.; " if calc else ""
    return f"({prefix}p. {pages[0]})" if len(pages) == 1 else f"({prefix}pp. {', '.join(pages)})"


def normalize_id_brackets(text: str) -> str:
    """'[F14-038, F14-036]' -> '[F14-038][F14-036]' (models sometimes group IDs in one bracket)."""
    def split(m):
        ids = re.findall(_ID_TOKEN, m.group(0))
        return "".join(f"[{i}]" for i in ids)
    return re.sub(rf"\[\s*(?:{_ID_TOKEN})(?:\s*[,;]\s*(?:{_ID_TOKEN}))+\s*\]", split, text)


def enforce(draft: str, findings: list[dict]) -> tuple[str, CitationReport]:
    draft = normalize_id_brackets(draft)
    by_id = {f["id"]: f for f in findings}
    report = CitationReport()
    out_lines = []
    section = ""
    lines = draft.splitlines()
    # a table header row is the row directly above a |---|---| separator row
    header_rows = {i - 1 for i, l in enumerate(lines)
                   if l.strip().startswith("|") and set(l.strip()) <= set("|-: ")}

    parents = []    # stack of (indent, ids) for list items, used for sub-bullet inheritance

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if idx in header_rows:
            out_lines.append(line)
            continue

        # Sub-bullets with no IDs inherit the IDs of their parent bullet.
        # Their numbers are still checked against those inherited findings.
        is_list_item = bool(_LIST_PREFIX.match(line))
        indent = len(line) - len(line.lstrip())
        if is_list_item:
            while parents and parents[-1][0] >= indent:
                parents.pop()
            own_ids = _ID.findall(line)
            if not own_ids and indent > 0 and parents and parents[-1][1]:
                line = line.rstrip() + " " + "".join(f"[{i}]" for i in parents[-1][1])
                stripped = line.strip()
            parents.append((indent, _ID.findall(line)))
        elif stripped:
            parents = []
        if stripped.startswith("#"):
            section = stripped.lower()
            out_lines.append(line)
            continue
        if not stripped or _PLACEHOLDER.fullmatch(stripped) or set(stripped) <= set("|-: "):
            out_lines.append(line)
            continue

        ids = _ID.findall(line)
        nums = _numbers_in(line)
        in_questions = "questions for management" in section
        not_disclosed = "not disclosed" in stripped.lower()
        is_disclaimer = stripped.startswith(">")
        has_placeholder = bool(_PLACEHOLDER.search(stripped))

        reason = None
        bad_ids = [i for i in ids if i not in by_id]
        if bad_ids:
            reason = f"cites nonexistent finding(s) {bad_ids}"
        elif not ids:
            if nums and not has_placeholder:
                reason = f"states number(s) {nums} with no citation"
            elif not (in_questions or not_disclosed or is_disclaimer or has_placeholder or _is_label_only(stripped)):
                reason = "factual line with no citation"
        else:
            forms = set().union(*(_number_forms(by_id[i]) for i in ids))
            unsupported = [n for n in nums if not _matches(n, forms)]
            if unsupported:
                reason = f"number(s) {unsupported} not found in cited findings {ids}"

        if reason:
            report.deleted.append((stripped, reason))
            # If this bullet has sub-bullets, keep a visible marker so they don't
            # appear to belong to the previous bullet.
            nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
            if is_list_item and _LIST_PREFIX.match(nxt) and (len(nxt) - len(nxt.lstrip())) > indent:
                out_lines.append(" " * indent + "- _(uncited statement removed; see citation_log.md)_")
            continue

        if ids:
            # replace each run of adjacent IDs with one page cite
            line = _ID_RUN.sub(lambda m: " " + _page_cite(_ID.findall(m.group(0)), by_id), line)
        report.kept += 1
        out_lines.append(line)

    return _renumber("\n".join(out_lines)), report


def _renumber(text: str) -> str:
    """Re-number top-level numbered lists (1. 2. 3.) within each section after deletions."""
    out, n = [], 0
    for line in text.splitlines():
        if line.startswith("#"):
            n = 0
        m = re.match(r"^(\d+)\.\s", line)
        if m:
            n += 1
            line = f"{n}." + line[m.end() - 1:]
        out.append(line)
    return "\n".join(out)


def _is_label_only(s: str) -> bool:
    """Lines like '**Financial**' or 'Table:' that introduce content rather than state facts."""
    s = _LIST_PREFIX.sub("", s).strip()
    core = re.sub(r"\b(?:fy)?(?:19|20)\d\d\b", "", s.strip("*_: "), flags=re.I).strip()   # years are fine in labels
    for pattern in _EXEMPT:                                    # so are "(3)", "Top 10", "Item 7"
        core = pattern.sub("", core)
    looks_like_label = s.endswith(":") or s.endswith(":**") or (s.startswith("**") and s.endswith("**"))
    return looks_like_label and len(core) < 60 and not _NUMBER.search(core)

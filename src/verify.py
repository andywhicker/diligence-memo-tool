"""
Step 2: check every finding against the source. Plain Python, no AI.

A finding passes only if ALL of these hold:
  1. its page ref exists in the document;
  2. its quote appears on that page (after normalizing whitespace,
     curly quotes, dashes, and letter case, nothing else);
  3. if it has a value, that value appears inside the quote;
  4. every number in the plain-English claim also appears inside the quote
     (years like 2026 and accounting-standard refs like "ASC 606" excepted).

What this does NOT check (known limitation): for a table row like
"Revenue 1,976,775 820,627 716,720", it confirms the number is in the row,
but not that the model matched it to the right column/year, or that the
unit ("$ thousands") is right. Those are checked later by cross-referencing
the same figure across different parts of the document.

Anything that fails is rejected with a reason and kept in a log so you can
audit what the model got wrong. Rejected findings never reach the memo.
"""

import re

from src.pdf_pages import Page

_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "‑": "-", " ": " ",
})


def normalize(text: str) -> str:
    """Lowercase, standardize punctuation, collapse all whitespace to single spaces."""
    text = text.translate(_TRANSLATE).lower()
    text = re.sub(r"\s+", " ", text)
    # PDF tables often add or drop a space after "$" or before "%"
    text = re.sub(r"\$\s+", "$", text)
    text = re.sub(r"\s+%", "%", text)
    return text.strip()


def _bare_number(s: str) -> str:
    """'$ (2,596)' -> '2,596'; '32.1%' -> '32.1'. Used only to check the value is in the quote."""
    return re.sub(r"[^\d.,]", "", s).strip(".,")


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_EXEMPT = [
    # accounting-standard and document references: "ASC 606", "Item 7", "Note 12"
    re.compile(r"\b(?:asc|asu|topic|item|section|rule|note)\s+[\d\-]+", re.I),
    # dates: "April 30, 2026", "May 1" (the day number is not a financial figure)
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\b", re.I),
    # period labels: "FY2026", "FY26", "Q3"
    re.compile(r"\b(?:fy|q)\s?\d{1,4}\b", re.I),
    # descriptors, not figures: "top 10 customers", "Top-5", "(3)" item counts
    re.compile(r"\btop[\s-]?\d{1,2}\b", re.I),
    re.compile(r"\(\d\)"),
]


def _unverified_claim_numbers(claim: str, quote_norm: str) -> list[str]:
    """Numbers in the claim sentence that do not appear in the quote."""
    for pattern in _EXEMPT:
        claim = pattern.sub(" ", claim)
    quote_digits = quote_norm.replace(",", "")
    missing = []
    for n in _NUMBER.findall(claim):
        bare = n.replace(",", "").rstrip(".")
        if re.fullmatch(r"(19|20)\d\d", bare):     # years
            continue
        if bare not in quote_digits:
            missing.append(n)
    return missing


def verify(findings: list[dict], pages_by_ref: dict[str, Page]) -> tuple[list[dict], list[dict]]:
    norm_pages = {ref: normalize(p.text) for ref, p in pages_by_ref.items()}
    passed, rejected = [], []

    for f in findings:
        reason = None
        page_text = norm_pages.get(f["page"])
        quote = normalize(f["quote"])

        if page_text is None:
            reason = f"page ref '{f['page']}' does not exist"
        elif len(quote) < 8:
            reason = "quote too short to verify"
        elif quote not in page_text:
            reason = f"quote not found on page {f['page']}"
        elif f["value"].strip():
            bare = _bare_number(f["value"])
            if bare and bare not in quote:
                reason = f"value '{f['value']}' not found in quote"
        if not reason:
            missing = _unverified_claim_numbers(f["claim"], quote)
            if missing:
                reason = f"claim states {missing} but the quote does not"

        if reason:
            rejected.append({**f, "reject_reason": reason})
        else:
            passed.append(f)

    return passed, rejected

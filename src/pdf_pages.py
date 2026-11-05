"""
PDF -> list of Page objects, each carrying the page number we will cite.

Two page numbers exist for every page:
  - pdf_page:     position in the PDF file (1, 2, 3, ...). Always known.
  - printed_page: the number printed at the bottom of the page in the
                  original document (e.g. "65"). What a reader of the 10-K sees.

We cite the printed number when we can detect it reliably, otherwise the
PDF position (written "PDF 12"). Detection is checked, not trusted: if a
detected number breaks the pattern of its neighbours, we fall back to the
PDF position for that page and say so.
"""

import re
from collections import Counter
from dataclasses import dataclass

from pypdf import PdfReader

MIN_CHARS = 50          # pages with less text than this are treated as unreadable (scans, images)
_LONE_NUMBER = re.compile(r"^\d{1,3}$")


@dataclass
class Page:
    pdf_page: int
    printed_page: str | None
    text: str

    @property
    def ref(self) -> str:
        """The label used in citations: '65' or 'PDF 1'."""
        return self.printed_page if self.printed_page else f"PDF {self.pdf_page}"

    @property
    def readable(self) -> bool:
        return len(self.text.strip()) >= MIN_CHARS


@dataclass
class PageMap:
    pages: list[Page]
    cite_mode: str                # "printed" or "pdf"
    notes: list[str]              # anything the user should know about page numbering / coverage

    def by_ref(self) -> dict[str, Page]:
        return {p.ref: p for p in self.pages}


def _clean(text: str) -> str:
    lines = text.splitlines()
    # 10-K pages printed from EDGAR start with a "Table of Contents" back-link; drop it.
    if lines and lines[0].strip() == "Table of Contents":
        lines = lines[1:]
    return "\n".join(lines).strip()


def _extract(page) -> tuple[str, str | None]:
    """
    Return (page text, printed page number or None).

    The printed number is the footer: the LOWEST piece of text on the page,
    if that text is just a 1-3 digit number. We use physical position
    (y-coordinate) because pypdf often outputs the footer near the top of
    the extracted text, not at the bottom.
    """
    items = []   # (y position, text); y is measured from the bottom of the page

    def visitor(text, cm, tm, font, size):
        t = text.strip()
        if t:
            items.append((tm[5] * cm[3] + cm[5], t))

    text = page.extract_text(visitor_text=visitor) or ""
    number = None
    if items:
        lowest_y, lowest_text = min(items, key=lambda it: it[0])
        if _LONE_NUMBER.match(lowest_text):
            number = lowest_text
    return text, number


def load_pages(pdf_path: str) -> PageMap:
    reader = PdfReader(pdf_path)
    raw, detected = [], {}
    for i, p in enumerate(reader.pages, start=1):
        text, number = _extract(p)
        if number is not None:
            # remove the footer number from the text so it isn't mistaken for data
            text = re.sub(rf"(?m)^\s*{re.escape(number)}\s*$\n?", "", text, count=1)
        raw.append((i, _clean(text)))
        detected[i] = number

    # The printed number should equal (pdf position - constant offset) on most pages.
    offsets = Counter(i - int(n) for i, n in detected.items() if n)
    notes = []
    if not offsets:
        mode, offset = "pdf", None
        notes.append("No printed page numbers detected; citations use PDF page positions ('PDF 12').")
    else:
        offset, hits = offsets.most_common(1)[0]
        share = hits / len(raw)
        mode = "printed" if share >= 0.8 else "pdf"
        if mode == "pdf":
            notes.append(f"Printed page numbers only consistent on {share:.0%} of pages; "
                         "citations use PDF page positions ('PDF 12').")

    pages, fallbacks = [], []
    for i, text in raw:
        n = detected[i]
        printed = None
        if mode == "printed":
            if n is not None and i - int(n) == offset:
                printed = n
            elif n is not None or i - offset >= 1:
                fallbacks.append(i)
        pages.append(Page(pdf_page=i, printed_page=printed, text=text))

    if mode == "printed":
        notes.append(f"Citations use printed page numbers (PDF page = printed page + {offset}).")
        if fallbacks:
            notes.append(f"No reliable printed number on PDF pages {fallbacks}; those are cited as 'PDF n'.")

    unreadable = [p.pdf_page for p in pages if not p.readable]
    if unreadable:
        notes.append(f"Little or no extractable text on PDF pages {unreadable} (likely images/scans); not analyzed.")

    return PageMap(pages=pages, cite_mode=mode, notes=notes)

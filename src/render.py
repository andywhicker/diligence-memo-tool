"""
Final memo -> Word (.docx) with IC-memo styling, then Word -> PDF.

We convert our own controlled Markdown (headings, bullets, numbered lists,
tables, blockquotes, **bold**) into a styled Word document with python-docx.
The PDF is exported by Microsoft Word itself, so the PDF matches the .docx
exactly. If Word isn't available, the .docx and .md are still produced.

All visual choices (fonts, colors, sizes) are constants at the top of this
file so they are easy to change.
"""

import re
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

# ---- Style -------------------------------------------------------------------
FONT = "Calibri"
HEAD_FONT = "Calibri"
NAVY = RGBColor(0x1F, 0x38, 0x64)
NAVY_HEX = "1F3864"
SLATE = RGBColor(0x59, 0x59, 0x59)
CITE_GRAY = RGBColor(0x80, 0x80, 0x80)
BAND_HEX = "F2F4F7"
PANEL_HEX = "EEF2F8"
BORDER_HEX = "BFC7D5"
FLAG_COLORS = {"Inconsistent": RGBColor(0xC0, 0x00, 0x00),
               "Needs explanation": RGBColor(0xC5, 0x7A, 0x00),
               "Consistent": RGBColor(0x2E, 0x7D, 0x32)}
BODY_PT, TABLE_PT, SMALL_PT = 10, 8.5, 8

_CITE = re.compile(r"(\((?:calc\.;\s*)?pp?\.\s[^)]*\))")
_INLINE = re.compile(r"(\*\*[^*]+\*\*|_\([^)]*\)_|_[^_]+_)")
_NUMERIC_CELL = re.compile(r"^[\s$()\-–,.\d%]+(\s*\(.*\))?(\s*[✓†⚠ ]*)?$|^Not disclosed$")


# ---- Low-level helpers ---------------------------------------------------------
def _shade(cell, hex_color):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def _cell_margins(cell, top=50, bottom=50, left=80, right=80):
    tc_pr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for side, val in (("top", top), ("bottom", bottom), ("start", left), ("end", right)):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tc_pr.append(mar)


def _table_borders(table, color=BORDER_HEX, inside=True):
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    edges = ["top", "bottom", "insideH"] + (["left", "right", "insideV"] if inside else [])
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        if edge in edges:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:color"), color)
        else:
            el.set(qn("w:val"), "nil")
        borders.append(el)
    tbl_pr.append(borders)


def _repeat_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def _no_split(row):
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:cantSplit"))


def _bottom_rule(paragraph, color=NAVY_HEX, size=8):
    p_pr = paragraph._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    bdr.append(bottom)
    p_pr.append(bdr)


def _field(run, code):
    """Insert a Word field (e.g. PAGE, NUMPAGES) into a run."""
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = code
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def _spacing(p, before=0, after=4, line=1.08):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line


# ---- Inline text: bold, italics, muted citations ------------------------------------
def add_inline(p, text, size=BODY_PT, color=None, bold=False):
    for piece in _CITE.split(text):
        if not piece:
            continue
        if _CITE.fullmatch(piece):
            r = p.add_run(piece)
            r.font.size = Pt(size - 1.5)
            r.font.color.rgb = CITE_GRAY
            continue
        for part in _INLINE.split(piece):
            if not part:
                continue
            r = p.add_run()
            if part.startswith("**") and part.endswith("**"):
                r.text, r.bold = part[2:-2], True
            elif part.startswith("_") and part.endswith("_") and len(part) > 2:
                r.text, r.italic = part[1:-1], True
                r.font.color.rgb = SLATE
            else:
                r.text = part
                r.bold = bold or None
            r.font.size = Pt(size)
            if color is not None and r.font.color.rgb is None:
                r.font.color.rgb = color


# ---- Document setup -----------------------------------------------------------
def _setup(doc, company):
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.left_margin = sec.right_margin = Inches(1.0)   # 6.5" text width matches Word's default header/footer tab stops
    sec.top_margin, sec.bottom_margin = Inches(0.85), Inches(0.8)
    sec.header_distance = sec.footer_distance = Inches(0.4)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.font.size = Pt(BODY_PT)

    for style_name in ("List Bullet", "List Bullet 2", "List Number"):
        st = doc.styles[style_name]
        st.font.name, st.font.size = FONT, Pt(BODY_PT)

    # Header: confidentiality line + company, right-aligned, with rule
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = hp.add_run("CONFIDENTIAL  |  FIRST-PASS DILIGENCE MEMO")
    r.font.size, r.font.color.rgb, r.bold = Pt(7.5), SLATE, True
    r = hp.add_run(f"\t\t{company}")
    r.font.size, r.font.color.rgb = Pt(7.5), SLATE
    _bottom_rule(hp, color=BORDER_HEX, size=4)

    # Footer: disclaimer left, page X of Y right
    fp = sec.footer.paragraphs[0]
    r = fp.add_run("Machine-generated first pass. Verify every figure against the cited page.")
    r.font.size, r.font.color.rgb, r.italic = Pt(7), CITE_GRAY, True
    r = fp.add_run("\t\tPage ")
    r.font.size, r.font.color.rgb = Pt(7.5), SLATE
    r = fp.add_run(); r.font.size = Pt(7.5); r.font.color.rgb = SLATE; _field(r, "PAGE")
    r = fp.add_run(" of "); r.font.size = Pt(7.5); r.font.color.rgb = SLATE
    r = fp.add_run(); r.font.size = Pt(7.5); r.font.color.rgb = SLATE; _field(r, "NUMPAGES")


# ---- Blocks -----------------------------------------------------------------
def _title_block(doc, company, header_rows):
    p = doc.add_paragraph()
    _spacing(p, before=0, after=0)
    r = p.add_run("FIRST-PASS DILIGENCE MEMO")
    r.font.size, r.bold, r.font.color.rgb = Pt(9), True, SLATE
    r.font.name = HEAD_FONT

    p = doc.add_paragraph()
    _spacing(p, before=2, after=6)
    r = p.add_run(company)
    r.font.size, r.bold, r.font.color.rgb = Pt(24), True, NAVY
    r.font.name = HEAD_FONT
    _bottom_rule(p, size=12)

    # Key-facts panel: 2 columns of label/value pairs
    if header_rows:
        t = doc.add_table(rows=0, cols=2)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        _table_borders(t, color="FFFFFF", inside=False)
        for label, value in header_rows:
            row = t.add_row()
            for cell in row.cells:
                _shade(cell, PANEL_HEX)
                _cell_margins(cell, 40, 40, 120, 120)
            lp = row.cells[0].paragraphs[0]
            add_inline(lp, label, size=8.5, color=SLATE, bold=True)
            vp = row.cells[1].paragraphs[0]
            add_inline(vp, value, size=9)
            for c in row.cells:
                _spacing(c.paragraphs[0], 0, 0)
        widths = (Inches(1.6), Inches(4.9))
        for row in t.rows:
            for c, w in zip(row.cells, widths):
                c.width = w
        doc.add_paragraph().paragraph_format.space_after = Pt(2)


def _callout(doc, text):
    t = doc.add_table(rows=1, cols=1)
    _table_borders(t, color="FFFFFF", inside=False)
    cell = t.rows[0].cells[0]
    _shade(cell, "FFF8E5")
    _cell_margins(cell, 70, 70, 140, 140)
    p = cell.paragraphs[0]
    _spacing(p, 0, 0)
    add_inline(p, text, size=8.5, color=SLATE)
    for r in p.runs:
        r.italic = True
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def _heading(doc, text):
    p = doc.add_paragraph()
    _spacing(p, before=14, after=6)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text.upper() if not text[0].isdigit() else text)
    r.font.name, r.font.size, r.bold, r.font.color.rgb = HEAD_FONT, Pt(12.5), True, NAVY
    _bottom_rule(p, size=6)


def _subheading(doc, text):
    p = doc.add_paragraph()
    _spacing(p, before=8, after=3)
    p.paragraph_format.keep_with_next = True
    add_inline(p, text.strip("*"), size=10, color=NAVY, bold=True)


def _bullet(doc, text, level, small=False):
    style = "List Bullet" if level == 0 else "List Bullet 2"
    p = doc.add_paragraph(style=style)
    _spacing(p, 0, 2 if small else 3)
    add_inline(p, text, size=SMALL_PT + 0.5 if small else BODY_PT, color=SLATE if small else None)


def _numbered(doc, num, text):
    p = doc.add_paragraph()
    _spacing(p, 0, 3)
    p.paragraph_format.left_indent = Inches(0.3)
    p.paragraph_format.first_line_indent = Inches(-0.3)
    r = p.add_run(f"{num}.\t")
    r.bold, r.font.color.rgb, r.font.size = True, NAVY, Pt(BODY_PT)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(0.3))
    add_inline(p, text)


def _table(doc, rows, kind):
    header, body = rows[0], rows[1:]
    ncols = len(header)
    t = doc.add_table(rows=1, cols=ncols)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    _table_borders(t)

    usable = 6.5
    if kind == "consistency":
        widths = [1.7, 0.55, 1.85, 0.55, 1.85]
    elif kind == "financial":
        widths = [2.6] + [(usable - 2.6) / (ncols - 1)] * (ncols - 1)
    elif kind == "lbo":
        widths = [1.8, 3.8, 0.9]
    else:
        widths = [usable / ncols] * ncols
    widths = widths[:ncols] + [usable / ncols] * (ncols - len(widths))

    hdr = t.rows[0]
    _repeat_header(hdr)
    for i, text in enumerate(header):
        c = hdr.cells[i]
        _shade(c, NAVY_HEX)
        _cell_margins(c)
        p = c.paragraphs[0]
        _spacing(p, 0, 0)
        add_inline(p, text, size=TABLE_PT, color=RGBColor(0xFF, 0xFF, 0xFF), bold=True)
        if kind == "financial" and i > 0:
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    for ri, cells in enumerate(body):
        row = t.add_row()
        _no_split(row)
        is_calc = kind == "financial" and "(calc.)" in cells[0]
        for i in range(ncols):
            text = cells[i] if i < len(cells) else ""
            c = row.cells[i]
            _cell_margins(c)
            if ri % 2 == 1:
                _shade(c, BAND_HEX)
            p = c.paragraphs[0]
            _spacing(p, 0, 0)
            if kind == "consistency" and i == 4:
                m = re.match(r"\*\*(Inconsistent|Needs explanation|Consistent)\*\*:?\s*(.*)", text)
                if m:
                    r = p.add_run(m.group(1) + ". ")
                    r.bold, r.font.size, r.font.color.rgb = True, Pt(TABLE_PT), FLAG_COLORS[m.group(1)]
                    add_inline(p, m.group(2), size=TABLE_PT - 0.5)
                    continue
            if kind == "financial" and i > 0:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                add_inline(p, text, size=TABLE_PT, color=SLATE if is_calc else None)
                if is_calc:
                    for r in p.runs:
                        r.italic = True
            elif kind == "financial" and i == 0:
                add_inline(p, text, size=TABLE_PT, color=SLATE if is_calc else None,
                           bold=not is_calc)
                if is_calc:
                    for r in p.runs:
                        r.italic = True
            else:
                add_inline(p, text, size=TABLE_PT - (0.5 if kind == "consistency" else 0))

    for row in t.rows:
        for c, w in zip(row.cells, widths):
            c.width = Inches(w)
    if kind == "financial":
        # keep the whole financial table on one page
        for row in t.rows[:-1]:
            for c in row.cells:
                for p in c.paragraphs:
                    p.paragraph_format.keep_with_next = True
    gap = doc.add_paragraph()
    _spacing(gap, 0, 4)


def _split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


# ---- Main entry -----------------------------------------------------------------
def to_docx(memo_md: str, out_path: Path) -> Path:
    lines = memo_md.splitlines()
    title = next((l for l in lines if l.startswith("# ")), "# Diligence Memo")
    company = title.split(":", 1)[-1].strip() if ":" in title else title[2:].strip()

    doc = Document()
    _setup(doc, company)

    # Header table (first table before the first "##") becomes the key-facts panel
    i, header_rows = 0, []
    while i < len(lines) and not lines[i].startswith("## "):
        l = lines[i]
        if l.startswith("|") and not set(l.strip()) <= set("|-: "):
            cells = _split_row(l)
            if cells[0].lower() not in ("field",):
                header_rows.append((cells[0], cells[1] if len(cells) > 1 else ""))
        i += 1
    _title_block(doc, company, header_rows)
    for l in lines[:i]:
        if l.startswith(">"):
            _callout(doc, l.lstrip("> ").strip())

    section, small = "", False
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("## "):
            small = False
            section = s[3:].lower()
            if section.startswith("appendix"):
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            _heading(doc, s[3:])
        elif s.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not set(lines[i].strip()) <= set("|-: "):
                    block.append(_split_row(lines[i]))
                i += 1
            kind = ("financial" if "financial summary" in section else
                    "consistency" if "consistency" in section else
                    "lbo" if "lbo" in section else "plain")
            _table(doc, block, kind)
            continue
        elif re.match(r"^\s*[-*]\s", line):
            level = 1 if (len(line) - len(line.lstrip())) >= 2 else 0
            _bullet(doc, re.sub(r"^\s*[-*]\s+", "", line), level, small=small)
        elif re.match(r"^\d+\.\s", s):
            num, text = s.split(".", 1)
            _numbered(doc, num, text.strip())
        elif s.startswith(">"):
            _callout(doc, s.lstrip("> ").strip())
        elif s.startswith("**") and s.endswith("**"):
            small = s.strip("*").strip().lower() == "table notes"
            _subheading(doc, s)
        elif s and s != "---":
            p = doc.add_paragraph()
            _spacing(p, 0, 4)
            add_inline(p, s)
        i += 1

    doc.core_properties.title = f"First-Pass Diligence Memo: {company}"
    doc.core_properties.author = "diligence-memo-tool"
    doc.save(out_path)
    return out_path


def to_pdf(docx_path: Path) -> Path | None:
    """Ask Microsoft Word to export the .docx as PDF. Returns None if Word isn't available."""
    pdf_path = docx_path.with_suffix(".pdf")
    script = (
        "$ErrorActionPreference='Stop';"
        "$w = New-Object -ComObject Word.Application; $w.Visible = $false; $w.DisplayAlerts = 0;"
        "try {"
        f"  $d = $w.Documents.Open('{docx_path}', $false, $true);"
        "   $d.Fields.Update() | Out-Null;"
        f"  $d.ExportAsFixedFormat('{pdf_path}', 17);"
        "   $d.Close($false)"
        "} finally { $w.Quit() }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       check=True, timeout=180, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"  [warn] PDF export via Word failed ({e.__class__.__name__}); .docx and .md were still written.")
        return None
    return pdf_path if pdf_path.exists() else None

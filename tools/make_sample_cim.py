"""
Generate a FICTIONAL CIM for testing the private-company path (management case, EV/EBITDA entry).

Northfold Signal Systems is a made-up company. Every page says so. The document has:
  - 3 years of historicals (FY2023A-FY2025A) and a 5-year management case (FY2026E-FY2030E)
  - management EBITDA add-backs, including an aggressive pro forma one (a QoE test)
  - two planted narrative-vs-numbers inconsistencies (a consistency-check test):
      1. text says FY2025 adjusted EBITDA margin "expanded to 20.1%"; the table gives 39.8 / 201.4 = 19.8%
      2. text says backlog of "$310.0 million"; the backlog table says $295.0 million
  - page numbers alone in the footer, like a real CIM

Usage:  python tools/make_sample_cim.py docs/Northfold_CIM_FICTIONAL.pdf
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK  # noqa: E402
from docx.shared import Pt, RGBColor  # noqa: E402

from src.render import _field, to_pdf  # noqa: E402

CO = "Northfold Signal Systems, Inc."
FICT = "FICTIONAL COMPANY. TEST DOCUMENT ONLY. NOT A REAL CIM."
NAVY = RGBColor(0x1F, 0x38, 0x64)


def h(doc, text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold, r.font.size, r.font.color.rgb = True, Pt(15), NAVY


def para(doc, text):
    p = doc.add_paragraph(text)
    p.paragraph_format.space_after = Pt(6)


def bullets(doc, items):
    for t in items:
        doc.add_paragraph(t, style="List Bullet")


def table(doc, header, rows, note=None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Light Grid Accent 1"
    for i, x in enumerate(header):
        t.rows[0].cells[i].text = x
    for r in rows:
        cells = t.add_row().cells
        for i, x in enumerate(r):
            cells[i].text = x
    if note:
        p = doc.add_paragraph(note)
        p.runs[0].italic = True
        p.runs[0].font.size = Pt(8)


def page_break(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def build_docx(path: Path):
    doc = Document()
    sec = doc.sections[0]
    sec.different_first_page_header_footer = True
    hp = sec.header.paragraphs[0]
    hp.text = f"{CO} | Confidential Information Memorandum | {FICT}"
    hp.runs[0].font.size = Pt(7)
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _field(fp.add_run(), "PAGE")            # page number alone in the footer

    # cover (no page number)
    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph()
    r = p.add_run("CONFIDENTIAL INFORMATION MEMORANDUM")
    r.bold, r.font.size = True, Pt(12)
    p = doc.add_paragraph()
    r = p.add_run(f"{CO} (fictional)")
    r.bold, r.font.size, r.font.color.rgb = True, Pt(26), NAVY
    para(doc, "Electronic warfare and signals intelligence sensors for U.S. and allied defense customers")
    para(doc, "March 2026")
    p = doc.add_paragraph()
    r = p.add_run(FICT + " Northfold Signal Systems does not exist. All names, figures and events are invented "
                         "to test software.")
    r.bold, r.font.color.rgb = True, RGBColor(0xC0, 0, 0)
    page_break(doc)

    h(doc, "Notice to Recipients")
    para(doc, "This fictional Confidential Information Memorandum has been prepared solely to test document-analysis "
              "software. It describes an invented company. No investment, offer or solicitation is made or implied.")
    para(doc, "The projections in this memorandum were prepared by management of the fictional company and reflect "
              "management's estimates and assumptions. Actual results may differ materially.")
    page_break(doc)

    h(doc, "1. Executive Summary")
    para(doc, f"{CO} (\"Northfold\" or the \"Company\") designs and manufactures compact electronic warfare (EW) "
              "and signals intelligence (SIGINT) sensors for U.S. Army, U.S. Special Operations Command and allied "
              "customers. Founded in 2009 and headquartered in Huntsville, Alabama, the Company is privately owned "
              "by its founders.")
    para(doc, "Northfold generated revenue of $201.4 million and Adjusted EBITDA of $39.8 million in fiscal 2025, "
              "and Adjusted EBITDA margin expanded to 20.1% in fiscal 2025.")
    para(doc, "Investment highlights:")
    bullets(doc, ["Mission-critical, sole-source positions on two Army programs of record",
                  "Backlog of $310.0 million at December 31, 2025, providing multi-year revenue visibility",
                  "Management projects revenue of $409.0 million and Adjusted EBITDA of $96.3 million in fiscal 2030",
                  "62% of employees hold active security clearances"])
    page_break(doc)

    h(doc, "2. Company Overview")
    para(doc, "Northfold operates in two product lines: Tactical EW Sensors (61% of fiscal 2025 revenue) and "
              "Strategic SIGINT Receivers (39% of fiscal 2025 revenue).")
    para(doc, "The Company employs 410 people, of whom 254 hold active security clearances. Manufacturing takes place "
              "in a 120,000 square foot leased facility in Huntsville, Alabama.")
    para(doc, "Northfold's fiscal year ends December 31.")
    page_break(doc)

    h(doc, "3. Customers and Contracts")
    para(doc, "The U.S. Army accounted for 41% of fiscal 2025 revenue. The top five customers accounted for 78% of "
              "fiscal 2025 revenue. Northfold is the prime contractor on 58% of revenue and a subcontractor on 42%.")
    para(doc, "Firm-fixed-price contracts represented 65% of fiscal 2025 revenue, cost-plus contracts 28% and "
              "time-and-materials contracts 7%.")
    table(doc, ["Backlog ($ in millions)", "Dec. 31, 2024", "Dec. 31, 2025"],
          [["Funded backlog", "148.0", "176.0"], ["Unfunded backlog", "96.0", "119.0"],
           ["Total backlog", "244.0", "295.0"]])
    para(doc, "The Company's largest program, the Army's Tactical Spectrum Sensor, has a recompete expected in "
              "fiscal 2028.")
    page_break(doc)

    h(doc, "4. Market Overview")
    para(doc, "Management estimates the addressable market for tactical EW and SIGINT sensors at $4.2 billion in "
              "2025, growing at 7% per year. Principal competitors include larger defense primes and several "
              "venture-backed entrants.")
    page_break(doc)

    h(doc, "5. Historical Financial Performance")
    para(doc, "Summary income statement (fiscal years ended December 31; $ in millions):")
    table(doc, ["", "FY2023A", "FY2024A", "FY2025A"],
          [["Revenue", "142.6", "168.9", "201.4"], ["Cost of revenue", "(98.4)", "(115.7)", "(136.9)"],
           ["Gross profit", "44.2", "53.2", "64.5"], ["SG&A", "(26.3)", "(29.4)", "(33.6)"],
           ["Operating income", "17.9", "23.8", "30.9"], ["Depreciation and amortization", "3.6", "4.1", "4.7"],
           ["Management add-backs", "2.6", "3.6", "4.2"], ["Adjusted EBITDA", "24.1", "31.5", "39.8"]])
    para(doc, "Management add-backs in fiscal 2025 consisted of founder compensation normalization of $1.1 million, "
              "one-time legal expense of $0.6 million and pro forma cost savings of $2.5 million from a planned "
              "facility consolidation that had not occurred as of December 31, 2025.")
    para(doc, "Revenue grew 19.2% in fiscal 2025, driven by higher production volumes on the Tactical Spectrum Sensor "
              "program. Gross margin was 32.0% in fiscal 2025.")
    page_break(doc)

    h(doc, "6. Cash Flow and Balance Sheet")
    table(doc, ["$ in millions", "FY2023A", "FY2024A", "FY2025A"],
          [["Capital expenditures", "4.2", "5.0", "6.1"], ["Cash taxes paid", "0.8", "1.0", "1.2"],
           ["Net cash provided by operating activities", "14.9", "19.6", "24.3"]])
    para(doc, "The Company is taxed as an S corporation; cash taxes reflect state taxes only.")
    table(doc, ["Balance sheet at Dec. 31 ($ in millions)", "FY2024A", "FY2025A"],
          [["Cash and cash equivalents", "6.1", "8.4"], ["Accounts receivable", "26.0", "31.2"],
           ["Unbilled receivables", "10.1", "12.5"], ["Inventories", "8.7", "9.8"],
           ["Accounts payable", "9.9", "11.3"], ["Accrued liabilities", "6.8", "7.6"],
           ["Customer advances", "2.4", "3.1"], ["Term loan", "52.0", "45.0"]])
    para(doc, "The term loan of $45.0 million will be repaid at the closing of a transaction. The Company has a "
              "$25.0 million revolving credit facility, undrawn at December 31, 2025.")
    page_break(doc)

    h(doc, "7. Management Projections")
    para(doc, "Management's projections for fiscal 2026 through fiscal 2030 ($ in millions):")
    table(doc, ["", "FY2026E", "FY2027E", "FY2028E", "FY2029E", "FY2030E"],
          [["Revenue", "238.0", "279.5", "322.0", "366.0", "409.0"],
           ["Adjusted EBITDA", "50.0", "61.5", "73.2", "85.1", "96.3"],
           ["Capital expenditures", "7.1", "8.4", "9.6", "11.0", "12.3"]],
          note="Source: Company management. Projections assume the Tactical Spectrum Sensor recompete is won in FY2028.")
    para(doc, "Key projection assumptions: continued production ramp on the Tactical Spectrum Sensor program, two new "
              "allied customers beginning in fiscal 2027, and Adjusted EBITDA margin expansion to 23.5% by fiscal "
              "2030 from operating leverage.")
    page_break(doc)

    h(doc, "8. Transaction Overview")
    para(doc, "The shareholders are exploring a sale of 100% of the Company. Indications of interest are due April "
              "30, 2026. The memorandum does not state an asking price.")
    doc.save(path)


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/Northfold_CIM_FICTIONAL.pdf").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:          # Word works outside OneDrive
        docx = Path(tmp) / "Northfold_CIM_FICTIONAL.docx"
        build_docx(docx)
        pdf = to_pdf(docx)
        if not pdf:
            sys.exit("PDF export via Word failed.")
        shutil.copy2(pdf, out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

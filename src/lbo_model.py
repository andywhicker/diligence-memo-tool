"""
v2: Excel LBO model built from lbo_inputs.json. No AI in this file.

Python writes inputs and FORMULAS; Excel does all the math, so every number
recalculates when you change an assumption.

Conventions (standard for banking/PE models):
  blue text   = hardcoded input (sourced from the 10-K, or your assumption)
  black text  = formula
  green text  = formula that pulls from another tab
  yellow fill = key assumption / placeholder you should set
  $ in millions unless labeled; percentages stored as fractions (0.15 = 15.0%)

Tabs built so far: Guide, Historicals, Assumptions.
"""

from dataclasses import dataclass, field

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# ---- style ------------------------------------------------------------------
FONT = "Arial"
BLUE, BLACK, GREEN, WHITE, GRAY = "0000FF", "000000", "008000", "FFFFFF", "808080"
NAVY = "1F3864"
YELLOW = "FFF2CC"
BAND = "F2F4F7"
FMT = {
    "money": '#,##0.0;(#,##0.0);"-"',
    "pct": '0.0%;(0.0%);"-"',
    "x": '0.0"x";(0.0"x");"-"',
    "count": '#,##0;(#,##0);"-"',
    "price": '$#,##0.00;($#,##0.00);"-"',
    "days": '#,##0;(#,##0);"-"',
}
THIN = Side(style="thin", color="BFC7D5")


def font(color=BLACK, bold=False, italic=False, size=10):
    return Font(name=FONT, color=color, bold=bold, italic=italic, size=size)


def title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = font(NAVY, bold=True, size=14)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = font(GRAY, italic=True, size=9)


def header_row(ws, row, labels, start_col=1):
    for i, text in enumerate(labels):
        c = ws.cell(row=row, column=start_col + i, value=text)
        c.font = font(WHITE, bold=True)
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center" if i else "left", vertical="center")


def section(ws, row, text, ncols):
    c = ws.cell(row=row, column=1, value=text)
    c.font = font(NAVY, bold=True, size=11)
    for col in range(1, ncols + 1):
        ws.cell(row=row, column=col).border = Border(bottom=Side(style="medium", color=NAVY))


def cell(ws, ref, value, kind=None, color=BLACK, bold=False, fill=None, italic=False):
    c = ws[ref]
    c.value = value
    c.font = font(color, bold=bold, italic=italic)
    if kind:
        c.number_format = FMT[kind]
    if fill:
        c.fill = PatternFill("solid", fgColor=fill)
    return c


# ---- Historicals --------------------------------------------------------------
HIST_ROWS = [
    ("Income statement", None),
    ("revenue", "Revenue"),
    ("gross_profit", "Gross profit"),
    ("operating_income", "Operating income (loss)"),
    ("adjusted_ebitda", "Adjusted EBITDA (as reported by company)"),
    ("d_and_a", "D&A"),
    ("depreciation", "Depreciation (excl. amortization)"),
    ("stock_based_comp", "Stock-based compensation"),
    ("acquisition_costs", "Acquisition-related expenses (company add-back)"),
    ("interest_expense", "Interest expense, net"),
    ("effective_tax_rate", "Effective tax rate"),
    ("cash_taxes_paid", "Cash taxes paid"),
    ("Cash flow", None),
    ("operating_cash_flow", "Operating cash flow"),
    ("capex", "Capex"),
    ("Balance sheet (fiscal year end)", None),
    ("cash", "Cash and equivalents"),
    ("short_term_investments", "Short-term investments"),
    ("total_debt", "Total debt (principal)"),
    ("accounts_receivable", "Accounts receivable"),
    ("unbilled_receivables", "Unbilled receivables"),
    ("inventory", "Inventories"),
    ("accounts_payable", "Accounts payable"),
    ("accrued_liabilities", "Accrued liabilities"),
    ("contract_liabilities", "Customer advances"),
    ("Other", None),
    ("funded_backlog", "Funded backlog"),
    ("unfunded_backlog", "Unfunded backlog"),
    ("employees", "Employees"),
    ("Market data and point-in-time items (latest)", None),
    ("shares_outstanding", "Basic shares outstanding"),
    ("share_price", "Share price ($ per share)"),
    ("federal_nol", "Federal NOL carryforwards"),
    ("revolver_commitment", "Existing revolver commitment"),
]
POINT_IN_TIME = {"shares_outstanding", "share_price", "federal_nol", "revolver_commitment"}


@dataclass
class Model:
    """Where things live, so later tabs can reference cells by name instead of hardcoding addresses."""
    hist: dict = field(default_factory=dict)        # slot -> row on Historicals
    hist_cols: dict = field(default_factory=dict)   # year label -> column letter on Historicals
    last_hist_col: str = ""
    a: dict = field(default_factory=dict)           # assumption name -> absolute ref on Assumptions
    live: dict = field(default_factory=dict)        # driver -> row of the live (selected-scenario) line
    proj_cols: dict = field(default_factory=dict)   # projection year -> column letter on Assumptions
    proj_years: list = field(default_factory=list)
    placeholders: list = field(default_factory=list)


def _source_text(item: dict) -> str:
    pages = ", ".join(item["pages"])
    mark = " ✓" if item["corroborated_on"] else " †"
    return f"p. {pages}{mark}" + (" ⚠" if item["warning"] else "")


def _quote_comment(item: dict) -> Comment:
    lines = [f"{fid} (p. {p}): \"{q[:300]}\"" for fid, p, q in zip(item["finding_ids"], item["pages"], item["quotes"])]
    if item["corroborated_on"]:
        lines.append(f"Same figure also found on p. {', '.join(item['corroborated_on'])}.")
    if item["warning"]:
        lines.append(f"Check: {item['warning']}.")
    c = Comment("\n".join(lines), "diligence-memo-tool")
    c.width, c.height = 420, 160
    return c


def build_historicals(wb, data: dict, m: Model):
    ws = wb.create_sheet("Historicals")
    years = data["years"]
    title(ws, f"{data['company']}: historical financials ($ in millions)",
          f"Source: {data['source_document']}. Blue = figure from the filing (hover for the exact quote). "
          f"✓ = same figure found on a second page; † = one page only; ⚠ = check the period.")
    header_row(ws, 4, ["Metric"] + [f"{y}A" for y in years] + ["Source (page)"])
    cols = {y: get_column_letter(2 + i) for i, y in enumerate(years)}
    src_col = get_column_letter(2 + len(years))
    m.hist_cols, m.last_hist_col = cols, cols[years[-1]]

    row = 5
    for slot, label in HIST_ROWS:
        if label is None:
            row += 1
            section(ws, row, slot, len(years) + 2)
            row += 1
            continue
        ws.cell(row=row, column=1, value=label).font = font()
        m.hist[slot] = row
        values = data["inputs"].get(slot, {})
        sources = []
        targets = [years[-1]] if slot in POINT_IN_TIME else years
        for y in targets:
            item = values.get(y) or (next(iter(values.values())) if slot in POINT_IN_TIME and values else None)
            if not item:
                continue
            v = item["value"] / 100 if item["kind"] == "pct" else item["value"]
            c = cell(ws, f"{cols[y]}{row}", v, item["kind"], BLUE)
            c.comment = _quote_comment(item)
            sources.append(f"{y}: {_source_text(item)}")
        src = ws[f"{src_col}{row}"]
        src.value = "; ".join(sources) if sources else "Not disclosed"
        src.font = font(GRAY, size=8)
        row += 1

    # ---- derived lines: formulas only ----
    row += 1
    section(ws, row, "Derived (formulas)", len(years) + 2)
    row += 1
    r = m.hist

    def need(col, slots, expr):
        refs = ",".join(f"{col}{r[s]}" for s in slots)
        return f'=IF(COUNT({refs})<{len(slots)},"n/a",{expr})'

    derived = [
        ("rev_growth", "Revenue growth", "pct",
         lambda c, p: None if p is None else need(c, ["revenue"], f"{c}{r['revenue']}/{p}{r['revenue']}-1")
         .replace(f"COUNT({c}{r['revenue']})<1", f"COUNT({c}{r['revenue']},{p}{r['revenue']})<2")),
        ("gross_margin", "Gross margin", "pct",
         lambda c, p: need(c, ["gross_profit", "revenue"], f"{c}{r['gross_profit']}/{c}{r['revenue']}")),
        ("ebitda_margin", "Adj. EBITDA margin", "pct",
         lambda c, p: need(c, ["adjusted_ebitda", "revenue"], f"{c}{r['adjusted_ebitda']}/{c}{r['revenue']}")),
        ("dep_pct", "Depreciation % revenue", "pct",
         lambda c, p: need(c, ["depreciation", "revenue"], f"{c}{r['depreciation']}/{c}{r['revenue']}")),
        ("capex_pct", "Capex % revenue", "pct",
         lambda c, p: need(c, ["capex", "revenue"], f"{c}{r['capex']}/{c}{r['revenue']}")),
        ("nwc", "Net working capital", "money",
         lambda c, p: need(c, ["accounts_receivable", "unbilled_receivables", "inventory", "accounts_payable",
                               "accrued_liabilities", "contract_liabilities"],
                           f"{c}{r['accounts_receivable']}+{c}{r['unbilled_receivables']}+{c}{r['inventory']}"
                           f"-{c}{r['accounts_payable']}-{c}{r['accrued_liabilities']}-{c}{r['contract_liabilities']}")),
        ("nwc_pct", "NWC % revenue", "pct", None),   # filled below (needs the nwc row)
        ("fcf", "Free cash flow (OCF - capex)", "money",
         lambda c, p: need(c, ["operating_cash_flow", "capex"], f"{c}{r['operating_cash_flow']}-{c}{r['capex']}")),
    ]
    for key, label, kind, fn in derived:
        ws.cell(row=row, column=1, value=label).font = font()
        m.hist[key] = row
        for i, y in enumerate(years):
            c, p = cols[y], (cols[years[i - 1]] if i else None)
            if key == "nwc_pct":
                f = f'=IF(OR({c}{r["nwc"]}="n/a",COUNT({c}{r["revenue"]})<1),"n/a",{c}{r["nwc"]}/{c}{r["revenue"]})'
            else:
                f = fn(c, p)
            if f:
                cell(ws, f"{c}{row}", f, kind)
                ws[f"{c}{row}"].alignment = Alignment(horizontal="right")
        row += 1

    # market-based valuation at the latest date
    L = m.last_hist_col
    row += 1
    section(ws, row, "Market valuation at latest share price", len(years) + 2)
    row += 1
    market = [
        ("market_cap", "Equity market value (basic)", "money",
         f"={L}{r['shares_outstanding']}*{L}{r['share_price']}/1000000"),
        ("market_ev", "Enterprise value at market (debt - cash - ST investments)", "money",
         f"={L}{row}+{L}{r['total_debt']}-{L}{r['cash']}-N({L}{r['short_term_investments']})"),
        ("market_multiple", "EV / FY adj. EBITDA at market", "x",
         f"=IF(N({L}{r['adjusted_ebitda']})=0,\"n/a\",{L}{row + 1}/{L}{r['adjusted_ebitda']})"),
    ]
    for key, label, kind, f in market:
        ws.cell(row=row, column=1, value=label).font = font()
        m.hist[key] = row
        cell(ws, f"{L}{row}", f, kind)
        row += 1

    ws.column_dimensions["A"].width = 52
    for y in years:
        ws.column_dimensions[cols[y]].width = 13
    ws.column_dimensions[src_col].width = 46
    ws.freeze_panes = "B5"
    return ws


# ---- Assumptions ----------------------------------------------------------------
SCENARIOS = ["Base", "Upside", "Downside"]


def build_assumptions(wb, data: dict, m: Model, n_years: int = 5):
    ws = wb.create_sheet("Assumptions")
    title(ws, "Assumptions: change the blue cells; yellow = placeholder you should set",
          "Nothing on this tab comes from the filing unless the Basis column says so. "
          "The 10-K has no management projections, so the operating case is yours.")
    H = "Historicals"
    hr, L = m.hist, m.last_hist_col
    last_year = int(data["years"][-1][-4:])
    m.proj_years = [f"FY{last_year + i}" for i in range(1, n_years + 1)]
    m.proj_cols = {y: get_column_letter(3 + i) for i, y in enumerate(m.proj_years)}
    basis_col = get_column_letter(3 + n_years)

    def put(row, key, label, value, kind, basis, placeholder=True, color=BLUE):
        ws.cell(row=row, column=1, value=label).font = font()
        c = cell(ws, f"C{row}", value, kind, color, fill=YELLOW if placeholder else None)
        b = ws[f"{basis_col}{row}"]
        b.value = basis
        b.font = font(GRAY, italic=True, size=8)
        m.a[key] = f"Assumptions!$C${row}"
        if placeholder:
            m.placeholders.append(label)
        return c

    def dropdown(ref, options):
        dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=False)
        dv.error, dv.errorTitle = "Pick one of the listed options.", "Invalid choice"
        ws.add_data_validation(dv)
        dv.add(ws[ref])

    # scenario switch
    row = 4
    section(ws, row, "Scenario", 3 + n_years)
    put(5, "scenario", "Active scenario (dropdown)", "Base", None,
        "Switches every operating driver below between the Base, Upside and Downside rows.", placeholder=False)
    ws["C5"].font = font(BLUE, bold=True)
    ws["C5"].fill = PatternFill("solid", fgColor=YELLOW)
    dropdown("C5", SCENARIOS)
    ws.cell(row=6, column=1, value="Scenario number (formula)").font = font(GRAY, size=9)
    cell(ws, "C6", '=MATCH($C$5,{"Base","Upside","Downside"},0)', "count")
    m.a["scenario_idx"] = "Assumptions!$C$6"

    # transaction
    row = 8
    section(ws, row, "Transaction (closes at fiscal year end " + data["years"][-1] + ")", 3 + n_years)
    put(9, "entry_method", "Entry valuation method (dropdown)", "Premium to share price", None,
        "Public company, so a take-private: price per share = market price x (1 + premium). "
        "Or switch to an EV / EBITDA multiple.")
    dropdown("C9", ["Premium to share price", "EV / EBITDA multiple"])
    put(10, "premium", "Offer premium to share price", 0.30, "pct", "Placeholder: your call (take-private premiums are often 20-40%).")
    put(11, "entry_multiple", "Entry EV / EBITDA (if multiple method)", 22.0, "x",
        "Placeholder: your call. Market multiple today is on the Historicals tab.")
    put(12, "ebitda_basis", "EBITDA basis for valuation and leverage (dropdown)", "Company adj. EBITDA", None,
        "Company figure as reported, or diligence-adjusted (bridge tab, step 3).")
    dropdown("C12", ["Company adj. EBITDA", "Diligence-adjusted EBITDA"])
    put(13, "dilution", "Dilution from options / RSUs (% of basic shares)", 0.02, "pct",
        "Placeholder: the filing gives basic shares only; check the equity footnote.")
    put(14, "txn_fees", "Transaction fees (% of enterprise value)", 0.02, "pct", "Placeholder: your call.")
    put(15, "fin_fees", "Financing fees (% of new debt)", 0.025, "pct", "Placeholder: your call.")
    put(16, "min_cash", "Minimum cash on balance sheet ($M)", 100.0, "money", "Placeholder: your call.")
    put(17, "existing_debt", "Existing debt repaid at close ($M)", f"={H}!{L}{hr['total_debt']}", "money",
        "Linked to Historicals: convertible notes repaid at principal on a change of control (check the indenture).",
        placeholder=False, color=GREEN)

    # financing
    section(ws, 19, "New financing", 3 + n_years)
    put(20, "tlb_x", "Term loan B (x EBITDA)", 4.0, "x", "Placeholder: your call.")
    put(21, "tlb_rate", "Term loan B all-in interest rate", 0.080, "pct", "Placeholder: your call (SOFR + spread).")
    put(22, "tlb_amort", "Term loan B mandatory amortization (% of original per year)", 0.01, "pct",
        "Placeholder: 1% per year is typical for a TLB.")
    put(23, "sweep_on", "Cash sweep (dropdown)", "On", None, "On = excess cash above the minimum repays the term loan.")
    dropdown("C23", ["On", "Off"])
    put(24, "sweep_pct", "Cash sweep (% of excess cash)", 0.75, "pct", "Placeholder: your call.")
    put(25, "notes_x", "Senior notes (x EBITDA)", 1.5, "x", "Placeholder: your call.")
    put(26, "notes_rate", "Senior notes interest rate", 0.095, "pct", "Placeholder: your call.")
    put(27, "rcf_size", "New revolver commitment ($M)", f"={H}!{L}{hr['revolver_commitment']}", "money",
        "Seeded from the existing facility size (Historicals); undrawn at close.", placeholder=False, color=GREEN)
    put(28, "rcf_rate", "Revolver interest rate (if drawn)", 0.075, "pct", "Placeholder: your call.")

    # exit
    section(ws, 30, "Exit", 3 + n_years)
    put(31, "exit_year", "Exit year (dropdown)", m.proj_years[-1], None, "Hold period ends at this fiscal year end.")
    dropdown("C31", m.proj_years[2:])
    put(32, "exit_multiple", "Exit EV / EBITDA", 18.0, "x", "Placeholder: your call. Often set at or below entry.")

    # operating case
    row = 34
    section(ws, row, "Operating case by scenario", 3 + n_years)
    header_row(ws, row + 1, ["Driver", "Scenario"] + m.proj_years + ["Basis"])
    rev = f"{H}!{L}{hr['revenue']}"
    fy26 = lambda num: f"{H}!{L}{hr[num]}"   # noqa: E731 (kept for readability in basis text)
    actual = {k: data["inputs"].get(k, {}).get(data["years"][-1], {}).get("value") for k in
              ("revenue", "adjusted_ebitda", "depreciation", "capex", "accounts_receivable", "unbilled_receivables",
               "inventory", "accounts_payable", "accrued_liabilities", "contract_liabilities")}
    rv = actual["revenue"] or 1
    margin = (actual["adjusted_ebitda"] or 0) / rv
    dep = (actual["depreciation"] or 0) / rv
    capex = (actual["capex"] or 0) / rv
    nwc = sum((actual[k] or 0) for k in ("accounts_receivable", "unbilled_receivables", "inventory")) - \
          sum((actual[k] or 0) for k in ("accounts_payable", "accrued_liabilities", "contract_liabilities"))
    nwc_pct = nwc / rv
    fy = data["years"][-1]

    drivers = [
        ("growth", "Revenue growth", "pct",
         [[0.12, 0.10, 0.09, 0.08, 0.07], [0.16, 0.14, 0.12, 0.10, 0.09], [0.06, 0.05, 0.05, 0.04, 0.04]],
         "Placeholder: your call. For reference, FY2026 organic growth was ~26% (memo, calc.)."),
        ("margin", "Adj. EBITDA margin", "pct",
         [[margin, margin + .005, margin + .01, margin + .015, margin + .02],
          [margin + .005, margin + .015, margin + .025, margin + .03, margin + .035],
          [margin - .015, margin - .015, margin - .01, margin - .01, margin - .005]],
         f"Seeded from {fy} actual {margin:.1%} (Historicals); path is a placeholder."),
        ("dep_pct", "Depreciation % revenue", "pct",
         [[dep] * 5] * 3, f"Seeded from {fy} actual {dep:.1%}. Excludes intangible amortization."),
        ("capex_pct", "Capex % revenue", "pct",
         [[capex] * 5, [capex - .002] * 5, [capex + .003] * 5], f"Seeded from {fy} actual {capex:.1%}."),
        ("nwc_pct", "Net working capital % revenue", "pct",
         [[nwc_pct] * 5, [nwc_pct - .01 * i for i in range(1, 6)], [nwc_pct + .01, nwc_pct + .02] + [nwc_pct + .02] * 3],
         f"Seeded from {fy} actual {nwc_pct:.1%} (AR + unbilled + inventory - AP - accrued - advances)."),
        ("tax_rate", "Cash tax rate (% of pre-tax income)", "pct",
         [[0.21] * 5] * 3, "Placeholder: 21% federal statutory; NOLs are used separately in the model."),
    ]
    row += 2
    for key, label, kind, values, basis in drivers:
        for s, scen in enumerate(SCENARIOS):
            ws.cell(row=row, column=1, value=label if s == 0 else "").font = font(bold=s == 0)
            ws.cell(row=row, column=2, value=scen).font = font(GRAY, size=9)
            for i, y in enumerate(m.proj_years):
                cell(ws, f"{m.proj_cols[y]}{row}", round(values[s][i], 4), kind, BLUE, fill=YELLOW)
            if s == 0:
                b = ws[f"{basis_col}{row}"]
                b.value = basis
                b.font = font(GRAY, italic=True, size=8)
            row += 1
        ws.cell(row=row, column=1, value=f"{label}: live").font = font(NAVY, bold=True)
        ws.cell(row=row, column=2, value="=$C$5").font = font(NAVY, size=9)
        for y in m.proj_years:
            c = m.proj_cols[y]
            f = f"=CHOOSE($C$6,{c}{row - 3},{c}{row - 2},{c}{row - 1})"
            x = cell(ws, f"{c}{row}", f, kind, BLACK, bold=True)
            x.border = Border(top=THIN, bottom=THIN)
        m.live[key] = row
        m.placeholders.append(label)
        row += 2

    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 12
    for y in m.proj_years:
        ws.column_dimensions[m.proj_cols[y]].width = 12
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions[basis_col].width = 70
    ws.freeze_panes = "C5"
    return ws


# ---- Guide ----------------------------------------------------------------------
def build_guide(wb, data: dict, m: Model):
    ws = wb.active
    ws.title = "Guide"
    title(ws, f"{data['company']}: LBO model (first pass)",
          f"Built by lbo.py from {data['source_document']} on {data['generated']}. All math is Excel formulas.")
    rows = [
        ("How to use", None),
        ("1. Pick a scenario and set the yellow cells on the Assumptions tab.", None),
        ("2. Historical figures come from the filing; hover over any blue number on Historicals for the exact quote and page.", None),
        ("3. The 10-K has no management case: every projection driver is your assumption.", None),
        ("", None),
        ("Color legend", None),
        ("Blue text: hardcoded input (from the filing, or your assumption)", BLUE),
        ("Black text: formula", BLACK),
        ("Green text: formula linking to another tab", GREEN),
        ("Yellow fill: key assumption or placeholder to set", "fill"),
        ("", None),
        ("Status", None),
        ("Tabs in this version: Guide, Historicals, Assumptions. Sources & Uses, Model, Returns and Checks come next.", None),
    ]
    for i, (text, style) in enumerate(rows, start=4):
        c = ws.cell(row=i, column=1, value=text)
        if style is None and text and not text[0].isdigit() and text not in ("",):
            c.font = font(NAVY, bold=True, size=11) if text in ("How to use", "Color legend", "Status") else font()
        elif style == "fill":
            c.font = font()
            c.fill = PatternFill("solid", fgColor=YELLOW)
        elif style:
            c.font = font(style)
        else:
            c.font = font()
    ws.column_dimensions["A"].width = 120
    return ws


def build(data: dict, out_path) -> Model:
    wb = Workbook()
    m = Model()
    build_guide(wb, data, m)
    build_historicals(wb, data, m)
    build_assumptions(wb, data, m)
    wb.save(out_path)
    return m

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
    case: dict = None                               # management case or consensus, if any
    scenarios: list = field(default_factory=list)
    scen_rows: dict = field(default_factory=dict)


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

    # market-based valuation at the latest date (public companies only)
    L = m.last_hist_col
    if not data.get("is_public", True):
        _finish_historicals(ws, years, cols, src_col)
        return ws
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
    _finish_historicals(ws, years, cols, src_col)
    return ws


def _finish_historicals(ws, years, cols, src_col):
    ws.column_dimensions["A"].width = 52
    for y in years:
        ws.column_dimensions[cols[y]].width = 13
    ws.column_dimensions[src_col].width = 46
    ws.freeze_panes = "B5"


# ---- Cases (management case or consensus) --------------------------------------------
SCENARIOS = ["Base", "Upside", "Downside"]
# rows on the Cases tab that feed the 4th scenario on Assumptions (same column letters by year)
CASE_ROWS = {"growth": 27, "margin": 28, "capex_pct": 29}


def prepare_case(data: dict, m: Model):
    """Pick the case source: management projections (CIM) first, else a consensus file."""
    if data.get("projection_years"):
        ins = data["inputs"]
        vals = {}
        for y in data["projection_years"]:
            v = {}
            for slot, key in (("proj_revenue", "revenue"), ("proj_adj_ebitda", "ebitda"), ("proj_capex", "capex")):
                item = ins.get(slot, {}).get(y)
                if item:
                    v[key] = {"value": item["value"], "cite": _source_text(item), "comment": _quote_comment(item)}
            vals[y] = v
        m.case = {"name": "Management", "label": "Management case (from the CIM)", "values": vals,
                  "source": f"Management projections in {data['source_document']}", "test_only": False}
    elif data.get("consensus"):
        c = data["consensus"]
        vals = {}
        for y, metrics in c["by_year"].items():
            vals[y] = {k: {"value": d["value"],
                           "cite": f"{d['source']}, as of {d['as_of']}" + (f", n={d['num_analysts']}" if d["num_analysts"] else ""),
                           "comment": None} for k, d in metrics.items()}
        m.case = {"name": "Consensus", "label": "Consensus estimates", "values": vals,
                  "source": f"Consensus file {c['file']}", "test_only": c["test_only"]}
    else:
        m.case = None


def build_cases(wb, data: dict, m: Model):
    ws = wb.create_sheet("Cases")
    case = m.case
    years = m.proj_years
    cols = [m.proj_cols[y] for y in years]
    H, L, hr = "Historicals", m.last_hist_col, m.hist
    title(ws, f"{case['label']} and sponsor haircut ($ in millions)",
          "Blue = figure from the source (hover for the quote where available). The sponsor case applies your "
          "haircuts; pick it in the scenario dropdown on Assumptions.")
    section(ws, 4, "Case source", 7)
    ws["A5"], ws["C5"] = "Case", case["name"]
    ws["A6"], ws["C6"] = "Source", case["source"]
    for ref in ("A5", "A6"):
        ws[ref].font = font()
    ws["C5"].font, ws["C6"].font = font(bold=True), font(GRAY, size=9)
    if case["test_only"]:
        ws["A7"] = "TEST ONLY: these are not real consensus estimates. Replace the file before relying on this case."
        ws["A7"].font = font("C00000", bold=True)

    section(ws, 9, "Haircut controls", 7)

    def ctl(row, key, label, value, kind, note):
        ws.cell(row=row, column=1, value=label).font = font()
        cell(ws, f"C{row}", value, kind, BLUE, fill=YELLOW)
        ws.cell(row=row, column=4, value=note).font = font(GRAY, italic=True, size=8)
        m.a[key] = f"Cases!$C${row}"
        m.placeholders.append(label)

    ctl(10, "rev_haircut", "Revenue haircut", 0.0, "pct", "Placeholder: % cut to each year's revenue.")
    ctl(11, "ebitda_haircut", "EBITDA haircut", 0.10, "pct", "Placeholder: % cut to each year's EBITDA.")
    ctl(12, "haircut_phase", "Haircut phase-in (dropdown)", "Flat", None,
        "Flat = same haircut every year. Ramp = 0 in year 1 rising to the full haircut in the last year.")
    dv = DataValidation(type="list", formula1='"Flat,Ramp"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(ws["C12"])

    header_row(ws, 15, ["", f"{data['years'][-1]}A"] + [f"{y}E" for y in years])
    ws["A16"] = "Haircut weight (share of the full haircut applied)"
    ws["A16"].font = font(GRAY)
    n = len(years)
    for i, c in enumerate(cols, start=1):
        cell(ws, f"{c}16", f'=IF($C$12="Flat",1,{i}/{n})', "pct", GRAY)

    section(ws, 18, f"{case['name']} figures as provided", 2 + n)
    ws["A19"], ws["A20"], ws["A21"], ws["A22"] = "Revenue", "EBITDA", "Capex", "Source"
    for r in (19, 20, 21, 22):
        ws[f"A{r}"].font = font()
    ws["A22"].alignment = Alignment(vertical="top")
    cell(ws, "B19", f"={H}!{L}{hr['revenue']}", "money", GREEN)
    cell(ws, "B20", f"={H}!{L}{hr['adjusted_ebitda']}", "money", GREEN)
    cell(ws, "B21", f"=N({H}!{L}{hr['capex']})", "money", GREEN)
    extended = []
    for i, (y, c) in enumerate(zip(years, cols)):
        p = "B" if i == 0 else cols[i - 1]
        v = case["values"].get(y, {})
        for r, key in ((19, "revenue"), (20, "ebitda"), (21, "capex")):
            item = v.get(key)
            if item:
                x = cell(ws, f"{c}{r}", round(item["value"], 6), "money", BLUE)
                if item.get("comment"):
                    x.comment = item["comment"]
            elif key == "revenue":
                pp = "B" if i <= 1 else cols[i - 2]
                cell(ws, f"{c}{r}", f"={p}19*(1+IF({pp}19=0,0,{p}19/{pp}19-1))", "money", BLACK, fill=YELLOW)
                extended.append(y)
            elif key == "ebitda":
                cell(ws, f"{c}{r}", f"={c}19*IF({p}19=0,0,{p}20/{p}19)", "money", BLACK, fill=YELLOW)
            else:
                cell(ws, f"{c}{r}", "n/a", None, GRAY)
                ws[f"{c}{r}"].alignment = Alignment(horizontal="right")
        cites = sorted({it["cite"] for it in v.values()})
        s = ws[f"{c}22"]
        s.value = "; ".join(cites) if cites else "Extended (not in source)"
        s.font = font(GRAY, size=7)
        s.alignment = Alignment(wrap_text=True, vertical="top")
    if extended:
        ws.cell(row=23, column=1, value=f"Yellow = not in the source; extended at the prior year's growth and margin "
                                        f"({', '.join(sorted(set(extended)))}). Placeholder: your call.").font = \
            font(GRAY, italic=True, size=8)

    section(ws, 24, "Sponsor case after haircut (feeds the scenario dropdown)", 2 + n)
    labels = {25: "Revenue", 26: "EBITDA", 27: "Revenue growth", 28: "EBITDA margin", 29: "Capex % revenue",
              30: "EBITDA haircut ($)"}
    for r, t in labels.items():
        ws.cell(row=r, column=1, value=t).font = font(bold=r in (25, 26))
    cell(ws, "B25", "=B19", "money")
    cell(ws, "B26", "=B20", "money")
    base_capex_row = m.scen_rows["capex_pct"][0]
    for i, c in enumerate(cols):
        p = "B" if i == 0 else cols[i - 1]
        cell(ws, f"{c}25", f"={c}19*(1-$C$10*{c}16)", "money", bold=True)
        cell(ws, f"{c}26", f"={c}20*(1-$C$11*{c}16)", "money", bold=True)
        cell(ws, f"{c}27", f"=IF({p}25=0,0,{c}25/{p}25-1)", "pct")
        cell(ws, f"{c}28", f"=IF({c}25=0,0,{c}26/{c}25)", "pct")
        cell(ws, f"{c}29", f'=IF(ISNUMBER({c}21),IF({c}19=0,0,{c}21/{c}19),Assumptions!{c}{base_capex_row})', "pct")
        cell(ws, f"{c}30", f"={c}26-{c}20", "money")
    ws.cell(row=31, column=1, value="Capex % uses the source's capex where given, otherwise the Base case. "
                                    "Depreciation, NWC and tax follow the Base case on Assumptions.").font = \
        font(GRAY, italic=True, size=8)
    ws.column_dimensions["A"].width = 50
    for c in ["B"] + cols:
        ws.column_dimensions[c].width = 15
    ws.row_dimensions[22].height = 36
    return ws


# ---- Assumptions ----------------------------------------------------------------


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
    scens = SCENARIOS + ([m.case["name"]] if m.case else [])
    m.scenarios = scens
    put(5, "scenario", "Active scenario (dropdown)", "Base", None,
        "Switches every operating driver below between the scenario rows"
        + (f", including the {m.case['name']} case from the Cases tab." if m.case else "."), placeholder=False)
    ws["C5"].font = font(BLUE, bold=True)
    ws["C5"].fill = PatternFill("solid", fgColor=YELLOW)
    dropdown("C5", scens)
    ws.cell(row=6, column=1, value="Scenario number (formula)").font = font(GRAY, size=9)
    cell(ws, "C6", "=MATCH($C$5,{" + ",".join(f'"{s}"' for s in scens) + "},0)", "count")
    m.a["scenario_idx"] = "Assumptions!$C$6"

    # transaction
    row = 8
    public = data.get("is_public", True)
    section(ws, row, "Transaction (closes at fiscal year end " + data["years"][-1] + ")", 3 + n_years)
    put(9, "entry_method", "Entry valuation method (dropdown)",
        "Premium to share price" if public else "EV / EBITDA multiple", None,
        "Public company, so a take-private: price per share = market price x (1 + premium). "
        "Or switch to an EV / EBITDA multiple." if public else
        "Private company: no share price, so entry is set by the EV / EBITDA multiple. "
        "(The premium method does not apply.)")
    dropdown("C9", ["Premium to share price", "EV / EBITDA multiple"])
    put(10, "premium", "Offer premium to share price", 0.30, "pct", "Placeholder: your call (take-private premiums are often 20-40%).")
    put(11, "entry_multiple", "Entry EV / EBITDA (if multiple method)", 22.0, "x",
        "Placeholder: your call. Market multiple today is on the Historicals tab.")
    put(12, "ebitda_basis", "EBITDA basis for valuation and leverage (dropdown)", "Company adj. EBITDA", None,
        "Company figure as reported, or diligence-adjusted (bridge tab, step 3).")
    dropdown("C12", ["Company adj. EBITDA", "Diligence-adjusted EBITDA"])
    put(13, "dilution", "Target's existing options / RSUs, cashed out at close (% of basic shares)", 0.02, "pct",
        "Placeholder: the filing gives basic shares only; check the equity footnote. "
        "(New management options are separate: see Sponsor equity structure.)")
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

    # sponsor equity structure
    section(ws, 34, "Sponsor equity structure", 3 + n_years)
    put(35, "equity_structure", "Sponsor equity structure (dropdown)", "Strip: PIK preferred + common", None,
        "Strip = sponsor funds its equity as PIK preferred plus common in fixed proportions; "
        "All common = no preferred.", placeholder=False)
    ws["C35"].fill = PatternFill("solid", fgColor=YELLOW)
    dropdown("C35", ["Strip: PIK preferred + common", "All common"])
    put(36, "pref_pct", "PIK preferred share of sponsor equity (if strip)", 0.98, "pct",
        "Your structure: 98% preferred / 2% common.", placeholder=False)
    ws["C36"].fill = PatternFill("solid", fgColor=YELLOW)
    put(37, "common_pct", "Common share of sponsor equity (formula)",
        '=IF($C$35="All common",1,1-$C$36)', "pct", "Formula: 1 - preferred share (100% if all common).",
        placeholder=False, color=BLACK)
    put(38, "pik_rate", "Preferred PIK dividend rate (compounds annually)", 0.12, "pct",
        "Placeholder: your call. Accrues to the preferred; paid at exit ahead of common.")
    put(39, "mgmt_pool", "Management option pool (% of common equity gain)", 0.10, "pct",
        "Placeholder: your call. Options struck at the entry common value; they dilute the common only.")

    # operating case
    row = 41
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
    m.scen_rows = {}
    for key, label, kind, values, basis in drivers:
        rows = []
        for s, scen in enumerate(SCENARIOS):
            ws.cell(row=row, column=1, value=label if s == 0 else "").font = font(bold=s == 0)
            ws.cell(row=row, column=2, value=scen).font = font(GRAY, size=9)
            for i, y in enumerate(m.proj_years):
                cell(ws, f"{m.proj_cols[y]}{row}", round(values[s][i], 4), kind, BLUE, fill=YELLOW)
            if s == 0:
                b = ws[f"{basis_col}{row}"]
                b.value = basis
                b.font = font(GRAY, italic=True, size=8)
            rows.append(row)
            row += 1
        if m.case:
            # 4th scenario: growth / margin / capex from the Cases tab; other drivers follow Base
            ws.cell(row=row, column=2, value=m.case["name"]).font = font(GRAY, size=9)
            for y in m.proj_years:
                c = m.proj_cols[y]
                if key in CASE_ROWS:
                    cell(ws, f"{c}{row}", f"=Cases!{c}{CASE_ROWS[key]}", kind, GREEN)
                else:
                    cell(ws, f"{c}{row}", f"={c}{rows[0]}", kind, BLACK)
            b = ws[f"{basis_col}{row}"]
            b.value = (f"{m.case['name']} case, after haircut (Cases tab)." if key in CASE_ROWS
                       else "Follows Base (type over to set a different value for this case).")
            b.font = font(GRAY, italic=True, size=8)
            rows.append(row)
            row += 1
        ws.cell(row=row, column=1, value=f"{label}: live").font = font(NAVY, bold=True)
        ws.cell(row=row, column=2, value="=$C$5").font = font(NAVY, size=9)
        for y in m.proj_years:
            c = m.proj_cols[y]
            f = "=CHOOSE($C$6," + ",".join(f"{c}{r}" for r in rows) + ")"
            x = cell(ws, f"{c}{row}", f, kind, BLACK, bold=True)
            x.border = Border(top=THIN, bottom=THIN)
        m.live[key] = row
        m.scen_rows[key] = rows
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
        ("Tabs in this version: Guide, Historicals, Assumptions, Bridge, Sources & Uses, Model, Returns. Checks come next.", None),
        ("Sponsor equity: strip of PIK preferred and common (or all common); management options dilute the common only.", None),
        ("Model simplifications: interest on beginning-of-year balances (no circular reference); depreciation excludes "
         "acquired-intangible amortization (understates the tax shield); NOLs offset taxable income without annual limits.", None),
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


# ---- EBITDA bridge --------------------------------------------------------------
def build_bridge(wb, data: dict, m: Model):
    """Company adj. EBITDA -> diligence-adjusted EBITDA, one toggle per add-back."""
    ws = wb.create_sheet("Bridge")
    fy = data["years"][-1]
    H, L, hr = "Historicals", m.last_hist_col, m.hist
    title(ws, f"EBITDA bridge, {fy}: company figure to diligence view ($ in millions)",
          "For each company add-back, choose Keep (accept it) or Deduct (treat it as a real, recurring cost). "
          "The EBITDA basis dropdown on Assumptions decides which figure drives valuation and leverage.")
    header_row(ws, 4, ["Item", "", "Treatment", "Company add-back", "Applied"])

    def label(row, text, bold=False, color=BLACK):
        ws.cell(row=row, column=1, value=text).font = font(color, bold=bold)

    label(5, f"Adjusted EBITDA as reported by company ({fy})", bold=True)
    cell(ws, "E5", f"={H}!{L}{hr['adjusted_ebitda']}", "money", GREEN, bold=True)

    items = [
        (7, "Stock-based compensation", "stock_based_comp", "Keep",
         "Non-cash, but a real cost to equity holders; many sponsors deduct it."),
        (8, "Acquisition-related expenses", "acquisition_costs", "Deduct",
         "Recurred in FY2025 and FY2026; the memo flags it as recurring for a serial acquirer."),
    ]
    for row, text, slot, default, why in items:
        label(row, f"Less: {text}")
        c = cell(ws, f"C{row}", default, None, BLUE, fill=YELLOW)
        dv = DataValidation(type="list", formula1='"Keep,Deduct"', allow_blank=False)
        ws.add_data_validation(dv)
        dv.add(c)
        cell(ws, f"D{row}", f"=-N({H}!{L}{hr[slot]})", "money", GREEN)
        cell(ws, f"E{row}", f'=IF(C{row}="Deduct",D{row},0)', "money")
        n = ws.cell(row=row, column=6, value=why)
        n.font = font(GRAY, italic=True, size=8)
        m.placeholders.append(f"Bridge: {text}")
    label(9, "Other diligence adjustment (+ / -)")
    cell(ws, "E9", 0.0, "money", BLUE, fill=YELLOW)
    ws.cell(row=9, column=6, value="Placeholder: e.g. pro forma cost savings or QoE findings.").font = font(GRAY, italic=True, size=8)

    label(11, f"Diligence-adjusted EBITDA ({fy})", bold=True)
    x = cell(ws, "E11", "=E5+SUM(E7:E9)", "money", BLACK, bold=True)
    x.border = Border(top=THIN)
    label(12, "Adjustments as % of revenue (carried into projections)")
    cell(ws, "E12", f"=IF(N({H}!{L}{hr['revenue']})=0,0,(E11-E5)/{H}!{L}{hr['revenue']})", "pct")
    label(14, "EBITDA used for valuation and leverage (per Assumptions)", bold=True, color=NAVY)
    s = cell(ws, "E14", f'=IF({m.a["ebitda_basis"]}="Company adj. EBITDA",E5,E11)', "money", BLACK, bold=True)
    s.fill = PatternFill("solid", fgColor=BAND)
    cell(ws, "C14", f"={m.a['ebitda_basis']}", None, GREEN)
    m.a["ltm_ebitda"] = "Bridge!$E$14"
    m.a["company_ebitda"] = "Bridge!$E$5"
    m.a["adj_pct_rev"] = "Bridge!$E$12"
    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 2
    ws.column_dimensions["C"].width = 26
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 80
    return ws


# ---- Sources & Uses ----------------------------------------------------------------
SU = "'Sources & Uses'"


def build_sources_uses(wb, data: dict, m: Model):
    ws = wb.create_sheet("Sources & Uses")
    H, L, hr, a = "Historicals", m.last_hist_col, m.hist, m.a
    title(ws, f"Sources & uses at close ({data['years'][-1]} year end, $ in millions)",
          "Entry valuation follows the method chosen on Assumptions. Sponsor equity is the plug.")

    def line(row, text, f, kind="money", color=BLACK, bold=False, key=None, note=None):
        ws.cell(row=row, column=1, value=text).font = font(bold=bold)
        c = cell(ws, f"C{row}", f, kind, color, bold=bold)
        if note:
            ws.cell(row=row, column=4, value=note).font = font(GRAY, italic=True, size=8)
        if key:
            a[key] = f"{SU}!$C${row}"
        return c

    section(ws, 4, "Entry valuation", 4)
    line(5, "EBITDA used (Bridge)", f"={a['ltm_ebitda']}", color=GREEN, key="su_ebitda")
    line(6, "Current share price", f"={H}!{L}{hr['share_price']}", "price", GREEN)
    line(7, "Offer price per share", f"=C6*(1+{a['premium']}+{a['d_prem']})", "price",
         note="Includes the Returns-tab sensitivity shift (0 unless a grid is calculating)")
    line(8, "Diluted shares (millions)", f"={H}!{L}{hr['shares_outstanding']}/1000000*(1+{a['dilution']})", "money",
         note="Basic shares x (1 + dilution assumption)")
    line(9, "Existing debt", f"={a['existing_debt']}", color=GREEN)
    line(10, "Less: cash and short-term investments", f"=-({H}!{L}{hr['cash']}+N({H}!{L}{hr['short_term_investments']}))",
         color=GREEN)
    line(11, "Equity value (premium method)", "=C7*C8")
    line(12, "Enterprise value (premium method)", "=C11+C9+C10")
    line(13, "Enterprise value (multiple method)", f"={a['entry_multiple']}*C5")
    line(14, "Equity value (multiple method)", "=C13-C9-C10")
    is_prem = f'{a["entry_method"]}="Premium to share price"'
    line(16, "Enterprise value (selected method)", f"=IF({is_prem},C12,C13)", bold=True, key="entry_ev")
    line(17, "Equity purchase price (selected method)", f"=IF({is_prem},C11,C14)", bold=True, key="equity_price")
    line(18, "Implied EV / EBITDA", '=IF(C5<=0,"n/a",C16/C5)', "x", key="implied_multiple")
    line(19, "Implied premium to current share price", '=IF(C6*C8=0,"n/a",C17/(C6*C8)-1)', "pct")

    section(ws, 21, "Uses", 4)
    line(22, "Purchase of equity", "=C17")
    line(23, "Repay existing debt", "=C9")
    line(24, "Transaction fees", f"={a['txn_fees']}*C16")
    line(25, "Financing fees", f"={a['fin_fees']}*(C31+C32)")
    line(26, "Cash to balance sheet (minimum cash)", f"={a['min_cash']}", color=GREEN)
    t = line(27, "Total uses", "=SUM(C22:C26)", bold=True, key="total_uses")
    t.border = Border(top=THIN)

    section(ws, 29, "Sources", 4)
    line(30, "Existing cash and short-term investments", "=-C10")
    line(31, "Term loan B", f"=({a['tlb_x']}+{a['d_tlb']})*C5", key="tlb_amount")
    line(32, "Senior notes", f"={a['notes_x']}*C5", key="notes_amount")
    line(33, "Revolver drawn at close", 0.0, color=BLUE, key="rcf_close")
    line(34, "Sponsor equity (plug)", "=C27-SUM(C30:C33)", bold=True, key="sponsor_equity")
    t = line(35, "Total sources", "=SUM(C30:C34)", bold=True)
    t.border = Border(top=THIN)

    section(ws, 37, "Checks and stats", 4)
    line(38, "Sources minus uses (must be 0)", "=ROUND(C35-C27,6)", key="su_check")
    line(39, "Total new debt / EBITDA", '=IF(C5<=0,"n/a",(C31+C32+C33)/C5)', "x")
    line(40, "Sponsor equity % of total sources", '=IF(C35=0,"n/a",C34/C35)', "pct")
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 50
    return ws


# ---- Model: projections, taxes, free cash flow, debt schedule -------------------------
def build_projection(wb, data: dict, m: Model):
    """
    Columns: B = last actual year (closing balance sheet), C..G = projection years
    (same letters as the Assumptions tab, so the live driver for a year sits in the same column).
    Interest is charged on BEGINNING-of-year balances to avoid a circular reference.
    """
    ws = wb.create_sheet("Model")
    H, L, hr, a = "Historicals", m.last_hist_col, m.hist, m.a
    A = "Assumptions"
    years = m.proj_years
    cols = [m.proj_cols[y] for y in years]
    title(ws, "Projections, free cash flow and debt schedule ($ in millions)",
          "Black = formula. Drivers come from the live rows on Assumptions (selected scenario). "
          "Interest on beginning balances (no circularity). Depreciation excludes acquired-intangible amortization.")
    header_row(ws, 4, ["", f"{data['years'][-1]}A"] + [f"{y}E" for y in years])
    r = {}
    row = [5]
    writing = [False]   # pass 1 only assigns row numbers (formulas refer to rows further down); pass 2 writes

    def sec(text):
        row[0] += 1
        if writing[0]:
            section(ws, row[0], text, 2 + len(years))
        row[0] += 1

    def add(key, label, kind, first=None, proj=None, bold=False, color_first=GREEN, border=False, italic=False):
        n = row[0]
        r[key] = n
        if not writing[0]:
            row[0] += 1
            return n
        ws.cell(row=n, column=1, value=label).font = font(bold=bold, italic=italic)
        if first is not None:
            cell(ws, f"B{n}", first.format(r=r, n=n) if isinstance(first, str) and "{" in first else first, kind,
                 color_first if isinstance(first, str) and "!" in first else (BLUE if not isinstance(first, str) else BLACK),
                 bold=bold, italic=italic)
        if proj is not None:
            for i, c in enumerate(cols):
                p = "B" if i == 0 else cols[i - 1]
                f = proj.format(c=c, p=p, r=r, n=n)
                x = cell(ws, f"{c}{n}", f, kind, GREEN if f.count("!") and not any(
                    k in f for k in ("+", "*", "-", "/", "MIN", "MAX", "IF")) else BLACK, bold=bold, italic=italic)
                if border:
                    x.border = Border(top=THIN)
        if border and first is not None:
            ws[f"B{n}"].border = Border(top=THIN)
        row[0] += 1
        return n

    live = lambda key: f"{A}!{{c}}{m.live[key]}"   # noqa: E731

    for pass_no in (1, 2):
        writing[0] = pass_no == 2
        row[0] = 5
        _projection_rows(sec, add, live, r, H, L, hr, a)

    m.model_rows = r
    m.model_cols = {"base": "B", **{y: c for y, c in zip(years, cols)}}
    ws.column_dimensions["A"].width = 50
    for c in ["B"] + cols:
        ws.column_dimensions[c].width = 13
    ws.freeze_panes = "B5"
    return ws


def _projection_rows(sec, add, live, r, H, L, hr, a):
    sec("Income statement")
    add("rev", "Revenue", "money", f"={H}!{L}{hr['revenue']}", "={p}{n}*(1+" + live("growth") + ")", bold=True)
    add("growth", "  growth", "pct", None, "={c}{r[rev]}/{p}{r[rev]}-1", italic=True)
    add("ebitda_co", "EBITDA, company basis", "money", f"={a['company_ebitda']}",
        "={c}{r[rev]}*(" + live("margin") + f"+{a['d_margin']})")
    add("dil_adj", "Diligence adjustments (if selected)", "money", f"={a['ltm_ebitda']}-{a['company_ebitda']}",
        f'=IF({a["ebitda_basis"]}="Company adj. EBITDA",0,{{c}}{{r[rev]}}*{a["adj_pct_rev"]})')
    add("ebitda", "EBITDA (selected basis)", "money", "=B{r[ebitda_co]}+B{r[dil_adj]}",
        "={c}{r[ebitda_co]}+{c}{r[dil_adj]}", bold=True, border=True)
    add("margin", "  margin", "pct", "=IF(B{r[rev]}=0,0,B{r[ebitda]}/B{r[rev]})", "={c}{r[ebitda]}/{c}{r[rev]}", italic=True)
    add("dep", "Less: depreciation", "money", None, "=-{c}{r[rev]}*" + live("dep_pct"))
    add("ebit", "EBIT", "money", None, "={c}{r[ebitda]}+{c}{r[dep]}", border=True)
    add("int_tlb", "Less: interest, term loan B", "money", None, f"=-{{p}}{{r[tlb_end]}}*{a['tlb_rate']}")
    add("int_notes", "Less: interest, senior notes", "money", None, f"=-{{p}}{{r[notes_end]}}*{a['notes_rate']}")
    add("int_rcf", "Less: interest, revolver", "money", None, f"=-{{p}}{{r[rcf_end]}}*{a['rcf_rate']}")
    add("ebt", "Pre-tax income", "money", None, "={c}{r[ebit]}+SUM({c}{r[int_tlb]}:{c}{r[int_rcf]})", border=True)
    add("nol_use", "NOL used", "money", None, "=MIN({p}{r[nol_end]},MAX({c}{r[ebt]},0))")
    add("taxable", "Taxable income", "money", None, "=MAX({c}{r[ebt]}-{c}{r[nol_use]},0)")
    add("tax", "Less: cash taxes", "money", None, "=-{c}{r[taxable]}*" + live("tax_rate"))
    add("ni", "Net income (cash tax basis)", "money", None, "={c}{r[ebt]}+{c}{r[tax]}", bold=True, border=True)
    add("nol_end", "NOL balance, end of year", "money", f"=N({H}!{L}{hr['federal_nol']})",
        "={p}{n}-{c}{r[nol_use]}", italic=True)

    sec("Free cash flow")
    add("fcf_ebitda", "EBITDA", "money", None, "={c}{r[ebitda]}")
    add("fcf_tax", "Less: cash taxes", "money", None, "={c}{r[tax]}")
    add("capex", "Less: capex", "money", None, "=-{c}{r[rev]}*" + live("capex_pct"))
    add("nwc", "Net working capital (balance)", "money", f"={H}!{L}{hr['nwc']}", "={c}{r[rev]}*" + live("nwc_pct"),
        italic=True)
    add("d_nwc", "Less: increase in net working capital", "money", None, "=-({c}{r[nwc]}-{p}{r[nwc]})")
    add("fcf_int", "Less: cash interest", "money", None, "=SUM({c}{r[int_tlb]}:{c}{r[int_rcf]})")
    add("fcf", "Free cash flow before debt repayment", "money", None,
        "={c}{r[fcf_ebitda]}+{c}{r[fcf_tax]}+{c}{r[capex]}+{c}{r[d_nwc]}+{c}{r[fcf_int]}", bold=True, border=True)
    add("mand", "Less: mandatory term loan amortization", "money", None,
        f"=-MIN({{p}}{{r[tlb_end]}},{a['tlb_amort']}*{a['tlb_amount']})")
    add("fcf_after", "Cash flow after mandatory repayment", "money", None, "={c}{r[fcf]}+{c}{r[mand]}", border=True)

    sec("Cash and revolver")
    add("over_min", "Cash above minimum before revolver and sweep", "money", None,
        f"={{p}}{{r[cash_end]}}+{{c}}{{r[fcf_after]}}-{a['min_cash']}")
    add("rcf_repay", "Revolver repayment", "money", None, "=-IF({c}{r[over_min]}>0,MIN({p}{r[rcf_end]},{c}{r[over_min]}),0)")
    add("rcf_draw", "Revolver draw (funds any shortfall)", "money", None,
        f"=IF({{c}}{{r[over_min]}}<0,MIN(-{{c}}{{r[over_min]}},{a['rcf_size']}-{{p}}{{r[rcf_end]}}),0)")
    add("excess", "Excess cash after revolver", "money", None, "={c}{r[over_min]}+{c}{r[rcf_repay]}+{c}{r[rcf_draw]}")
    add("sweep", "Less: optional term loan repayment (cash sweep)", "money", None,
        f'=-IF({a["sweep_on"]}="On",MIN({{p}}{{r[tlb_end]}}+{{c}}{{r[mand]}},MAX({{c}}{{r[excess]}},0)*{a["sweep_pct"]}),0)')
    add("cash_end", "Cash, end of year", "money", f"={a['min_cash']}",
        f"={a['min_cash']}+{{c}}{{r[excess]}}+{{c}}{{r[sweep]}}", bold=True, border=True)

    sec("Debt schedule (end of year balances)")
    add("tlb_end", "Term loan B", "money", f"={a['tlb_amount']}", "={p}{n}+{c}{r[mand]}+{c}{r[sweep]}")
    add("notes_end", "Senior notes (bullet)", "money", f"={a['notes_amount']}", "={p}{n}")
    add("rcf_end", "Revolver", "money", f"={a['rcf_close']}", "={p}{n}+{c}{r[rcf_repay]}+{c}{r[rcf_draw]}")
    add("debt", "Total debt", "money", "=SUM(B{r[tlb_end]}:B{r[rcf_end]})", "=SUM({c}{r[tlb_end]}:{c}{r[rcf_end]})",
        bold=True, border=True)
    add("net_debt", "Net debt", "money", "=B{r[debt]}-B{r[cash_end]}", "={c}{r[debt]}-{c}{r[cash_end]}")

    sec("Credit statistics")
    add("lev", "Total debt / EBITDA", "x", '=IF(B{r[ebitda]}<=0,"n/a",B{r[debt]}/B{r[ebitda]})',
        '=IF({c}{r[ebitda]}<=0,"n/a",{c}{r[debt]}/{c}{r[ebitda]})')
    add("net_lev", "Net debt / EBITDA", "x", '=IF(B{r[ebitda]}<=0,"n/a",B{r[net_debt]}/B{r[ebitda]})',
        '=IF({c}{r[ebitda]}<=0,"n/a",{c}{r[net_debt]}/{c}{r[ebitda]})')
    add("cover", "EBITDA / cash interest", "x", None,
        '=IF({c}{r[fcf_int]}=0,"n/a",{c}{r[ebitda]}/-{c}{r[fcf_int]})')
    add("paydown", "Cumulative debt paydown % of opening debt", "pct", None,
        '=IF($B{r[debt]}=0,"n/a",1-{c}{r[debt]}/$B{r[debt]})')


# ---- Returns and sensitivities ------------------------------------------------------
SHIFT_ROWS = {"d_prem": 6, "d_exit": 7, "d_tlb": 8, "d_margin": 9}


def build_returns(wb, data: dict, m: Model):
    ws = wb.create_sheet("Returns")
    a, R = m.a, m.model_rows
    title(ws, "Returns and sensitivities",
          "Exit at the fiscal year end chosen on Assumptions. Single equity investment at close and single "
          "distribution at exit (no dividends), so IRR = MOIC^(1/years) - 1.")

    # sensitivity shifts (must stay 0; Excel data tables vary them)
    section(ws, 4, "Sensitivity shifts: leave at 0 (the grids below vary these)", 8)
    shifts = [("d_prem", "Entry premium shift (percentage points)", "pct"),
              ("d_exit", "Exit multiple shift (turns)", "x"),
              ("d_tlb", "Term loan leverage shift (turns of EBITDA)", "x"),
              ("d_margin", "EBITDA margin shift, all years (percentage points)", "pct")]
    for key, label, kind in shifts:
        rr = SHIFT_ROWS[key]
        ws.cell(row=rr, column=1, value=label).font = font(GRAY)
        cell(ws, f"C{rr}", 0, kind, BLUE)
    ws.cell(row=5, column=1, value="Keep these at 0. They exist only so the live grids can test other values.").font = \
        font(GRAY, italic=True, size=8)

    def line(row, label, f, kind="money", bold=False, color=BLACK, key=None, note=None):
        ws.cell(row=row, column=1, value=label).font = font(bold=bold)
        c = cell(ws, f"C{row}", f, kind, color, bold=bold)
        if note:
            ws.cell(row=row, column=4, value=note).font = font(GRAY, italic=True, size=8)
        if key:
            a[key] = f"Returns!$C${row}"
        return c

    proj = m.proj_years
    first, last = m.proj_cols[proj[0]], m.proj_cols[proj[-1]]
    rng = lambda key: f"Model!${first}${R[key]}:${last}${R[key]}"   # noqa: E731

    section(ws, 11, "Exit", 8)
    line(12, "Exit year", f"={a['exit_year']}", None, color=GREEN)
    line(13, "Years held", f"=MATCH(C12&\"E\",Model!${first}$4:${last}$4,0)", "count")
    line(14, "Exit-year EBITDA (selected basis)", f"=INDEX({rng('ebitda')},C13)")
    line(15, "Exit EV / EBITDA", f"={a['exit_multiple']}+{a['d_exit']}", "x")
    line(16, "Exit enterprise value", "=C14*C15", bold=True)
    line(17, "Less: debt at exit", f"=-INDEX({rng('debt')},C13)")
    line(18, "Plus: cash at exit", f"=INDEX({rng('cash_end')},C13)")
    line(19, "Exit equity value", "=SUM(C16:C18)", bold=True)
    ws["C19"].border = Border(top=THIN)

    section(ws, 21, "Equity waterfall at exit", 8)
    strip = f'{a["equity_structure"]}="All common"'
    line(22, "Sponsor equity invested at close", f"={a['sponsor_equity']}", color=GREEN, key="sponsor_in")
    line(23, "  of which PIK preferred", f"=IF({strip},0,C22*{a['pref_pct']})",
         note="Per the equity structure on Assumptions")
    line(24, "  of which common", "=C22-C23")
    line(25, "Preferred accreted value at exit (invested x (1 + PIK)^years)", f"=C23*(1+{a['pik_rate']})^C13")
    line(26, "Exit equity value", "=C19")
    line(27, "To PIK preferred (paid first)", "=MIN(MAX(C26,0),C25)")
    line(28, "Common equity value (after preferred)", "=MAX(C26,0)-C27")
    line(29, "Less: management options", f"=-{a['mgmt_pool']}*MAX(0,C28-C24)",
         note="Pool % of the gain on common above its entry value; comes out of the common only")
    line(30, "To sponsor common", "=C28+C29")
    line(31, "Total proceeds to sponsor", "=C27+C30", bold=True)
    ws["C31"].border = Border(top=THIN)

    section(ws, 33, "Returns", 8)
    irr = lambda out, inv: (f'=IF({inv}<=0,"n/a",IF({out}<=0,-1,({out}/{inv})^(1/C13)-1))')   # noqa: E731
    line(34, "Sponsor MOIC", '=IF(C22<=0,"n/a",C31/C22)', "x", bold=True, key="moic")
    line(35, "Sponsor IRR", irr("C31", "C22"), "pct", bold=True, key="irr")
    line(36, "PIK preferred MOIC / IRR", '=IF(C23<=0,"n/a",C27/C23)', "x")
    cell(ws, "D36", irr("C27", "C23"), "pct")
    line(37, "Common MOIC / IRR (sponsor's common, after management)", '=IF(C24<=0,"n/a",C30/C24)', "x")
    cell(ws, "D37", irr("C30", "C24"), "pct")
    line(38, "Management options value at exit", "=-C29")
    for ref in ("C34", "C35"):
        ws[ref].fill = PatternFill("solid", fgColor=BAND)

    section(ws, 40, "Value creation (sources of the equity gain)", 8)
    line(41, "Entry EV / EBITDA (implied)", f"={a['implied_multiple']}", "x", color=GREEN)
    line(42, "EBITDA growth (at entry multiple)", f"=(C14-{a['su_ebitda']})*C41")
    line(43, "Multiple expansion / (contraction)", "=(C15-C41)*C14")
    line(44, "Net debt paydown", "=(Model!$B${0}-Model!$B${1})-(-C17-C18)".format(R["debt"], R["cash_end"]))
    line(45, "Fees and other leakage", "=C46-SUM(C42:C44)", note="Transaction and financing fees, and the equity "
                                                                 "cushion paid above entry EV.")
    line(46, "Total equity gain / (loss), before management options", "=C26-C22", bold=True)
    ws["C46"].border = Border(top=THIN)
    line(47, "Less: management options", "=C29")
    line(48, "Sponsor gain / (loss)", "=C31-C22", bold=True)

    # sensitivity grids (filled in by Excel data tables after the file is built)
    m.data_tables = []

    def grid(top, heading, row_label, col_label, row_shift_key, col_shift_key, row_vals, col_vals,
             row_kind, col_kind, row_base, col_base):
        section(ws, top, heading, 8)
        ws.cell(row=top + 1, column=1, value=f"Rows: {row_label}. Columns: {col_label}. "
                                             f"Labels show the absolute value; the grid substitutes the shift.").font = \
            font(GRAY, italic=True, size=8)
        hdr, corner = top + 3, f"B{top + 3}"
        # absolute-value labels (formulas) above the column headers and left of the row headers
        for j, v in enumerate(col_vals):
            col = get_column_letter(3 + j)
            cell(ws, f"{col}{top + 2}", f"={col_base}+{col}{hdr}", col_kind, BLACK, bold=True)
            cell(ws, f"{col}{hdr}", v, col_kind, BLUE, italic=True)
        for i, v in enumerate(row_vals):
            rr = hdr + 1 + i
            cell(ws, f"A{rr}", f"={row_base}+B{rr}", row_kind, BLACK, bold=True)
            ws[f"A{rr}"].alignment = Alignment(horizontal="right")
            cell(ws, f"B{rr}", v, row_kind, BLUE, italic=True)
        c = cell(ws, corner, f"={a['irr']}", "pct", GRAY, italic=True)
        c.number_format = ';;;'   # hidden: Excel needs the output formula here
        for i in range(len(row_vals)):
            for j in range(len(col_vals)):
                x = ws.cell(row=hdr + 1 + i, column=3 + j)
                x.number_format = FMT["pct"]
                x.font = font()
                if i == len(row_vals) // 2 and j == len(col_vals) // 2:
                    x.fill = PatternFill("solid", fgColor=YELLOW)
        last_col = get_column_letter(2 + len(col_vals))
        m.data_tables.append({"sheet": "Returns", "range": f"{corner}:{last_col}{hdr + len(row_vals)}",
                              "row_input": f"C{SHIFT_ROWS[col_shift_key]}",
                              "col_input": f"C{SHIFT_ROWS[row_shift_key]}"})

    grid(51, "Sponsor IRR: entry premium (rows) x exit multiple (columns)", "offer premium to share price",
         "exit EV / EBITDA", "d_prem", "d_exit", [-0.10, -0.05, 0, 0.05, 0.10], [-4, -2, 0, 2, 4],
         "pct", "x", a["premium"], a["exit_multiple"])
    grid(62, "Sponsor IRR: term loan leverage (rows) x EBITDA margin shift (columns)", "term loan B, turns of EBITDA",
         "EBITDA margin change vs. the scenario, all years", "d_tlb", "d_margin", [-1, -0.5, 0, 0.5, 1],
         [-0.02, -0.01, 0, 0.01, 0.02], "x", "pct", a["tlb_x"], "0")
    ws.cell(row=63, column=1).value += " Column labels show the margin change itself."

    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 10
    for col in "CDEFG":
        ws.column_dimensions[col].width = 12
    return ws


def build(data: dict, out_path) -> Model:
    wb = Workbook()
    m = Model()
    # sensitivity shift cells live on the Returns tab; other tabs reference them by address
    m.a.update({k: f"Returns!$C${r}" for k, r in SHIFT_ROWS.items()})
    prepare_case(data, m)
    build_guide(wb, data, m)
    build_historicals(wb, data, m)
    build_assumptions(wb, data, m)
    if m.case:
        build_cases(wb, data, m)
    build_bridge(wb, data, m)
    build_sources_uses(wb, data, m)
    build_projection(wb, data, m)
    build_returns(wb, data, m)
    wb.save(out_path)
    return m

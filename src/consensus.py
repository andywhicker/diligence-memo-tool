"""
Consensus estimates for a public company, read from a simple CSV you fill in.

Why a file: consensus isn't in the 10-K, and there is no free source that is both
reliable and citable. Fill the file from Capital IQ, FactSet, or WRDS (I/B/E/S);
an automated pull can later write the same file.

File format (one row per fiscal year and metric, $ in millions):

    fiscal_year,metric,value_musd,source,as_of,num_analysts
    FY2027,revenue,2250.0,Capital IQ consensus (mean),2026-11-05,9
    FY2027,ebitda,330.0,Capital IQ consensus (mean),2026-11-05,8

metric: revenue | ebitda | capex   (revenue and ebitda required; capex optional)
Lines starting with # are ignored.
"""

import csv
from pathlib import Path

METRICS = {"revenue", "ebitda", "capex"}
COLUMNS = ["fiscal_year", "metric", "value_musd", "source", "as_of", "num_analysts"]

TEMPLATE = """# Consensus estimates for {company}. $ in millions. One row per fiscal year and metric.
# metric: revenue | ebitda | capex (capex optional). Use the company's fiscal-year labels, e.g. FY2027.
# Fill from Capital IQ, FactSet or WRDS (I/B/E/S). Record the source and the as-of date on every row.
# Leave a value blank if there is no estimate. A comment line containing "TEST ONLY" marks the file as test data.
fiscal_year,metric,value_musd,source,as_of,num_analysts
"""


def write_template(path: Path, company: str, years: list[str]) -> None:
    rows = "".join(f"{y},{m},,,,\n" for y in years for m in ("revenue", "ebitda", "capex"))
    path.write_text(TEMPLATE.format(company=company) + rows, encoding="utf-8")


def read(path: Path) -> dict:
    """Return {'by_year': {FY: {metric: {...}}}, 'test_only': bool, 'problems': [...]}"""
    # utf-8-sig: Excel's "CSV UTF-8" and Windows tools add an invisible byte-order mark at the start
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    test_only = any("TEST ONLY" in l.upper() for l in lines if l.startswith("#"))
    body = [l for l in lines if l.strip() and not l.lstrip().startswith("#")]
    out, problems = {}, []
    for i, row in enumerate(csv.DictReader(body), start=1):
        missing = [c for c in COLUMNS if c not in row]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")
        metric = (row["metric"] or "").strip().lower()
        if metric not in METRICS:
            problems.append(f"row {i}: unknown metric '{row['metric']}'")
            continue
        raw = (row["value_musd"] or "").replace(",", "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            problems.append(f"row {i}: value '{row['value_musd']}' is not a number")
            continue
        if not row["source"].strip() or not row["as_of"].strip():
            problems.append(f"row {i}: source and as_of date are required")
            continue
        out.setdefault(row["fiscal_year"].strip(), {})[metric] = {
            "value": value, "source": row["source"].strip(), "as_of": row["as_of"].strip(),
            "num_analysts": row["num_analysts"].strip()}
    for y, metrics in out.items():
        for need in ("revenue", "ebitda"):
            if need not in metrics:
                problems.append(f"{y}: no {need} estimate")
    return {"by_year": dict(sorted(out.items())), "test_only": test_only, "problems": problems,
            "file": path.name}

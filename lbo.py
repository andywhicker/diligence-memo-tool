"""
v2: build the Excel LBO model from a v1 run.

Usage:
  python lbo.py output/<doc>/lbo_inputs.json

Writes output/<Company>_LBO_<date>.xlsx, then opens it in Microsoft Excel (in the
background) to recalculate and check every formula. No AI calls; costs nothing.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import config
from src import consensus, excel_com, lbo_model


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Excel LBO from lbo_inputs.json (written by diligence.py).")
    ap.add_argument("inputs", help="path to output/<doc>/lbo_inputs.json")
    ap.add_argument("--consensus", metavar="CSV", help="consensus estimates file (public companies)")
    ap.add_argument("--consensus-template", metavar="CSV",
                    help="write a blank consensus file to fill in, then exit")
    ap.add_argument("--no-excel", action="store_true", help="skip the Excel recalculation check")
    args = ap.parse_args()

    data = json.loads(Path(args.inputs).read_text(encoding="utf-8"))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", data["company"]).strip("_")

    last = int(data["years"][-1][-4:])
    if args.consensus_template:
        consensus.write_template(Path(args.consensus_template), data["company"],
                                 [f"FY{last + i}" for i in range(1, 6)])
        print(f"Wrote {args.consensus_template}. Fill it from Capital IQ, FactSet or WRDS, then run with --consensus.")
        return
    if args.consensus:
        data["consensus"] = consensus.read(Path(args.consensus))
        c = data["consensus"]
        print(f"Consensus: {len(c['by_year'])} years from {c['file']}"
              + (" [TEST ONLY: not real consensus]" if c["test_only"] else ""))
        for p in c["problems"]:
            print(f"  [warn] {p}")
    out = config.OUTPUT_DIR / f"{slug}_LBO_{date.today().isoformat()}.xlsx"

    m = lbo_model.build(data, out)
    print(f"Built: {out}")
    print(f"  {len(m.placeholders)} assumptions are placeholders for you to set (yellow cells).")

    if args.no_excel:
        return
    print("Recalculating in Excel, adding the sensitivity grids, and checking every formula...")
    # Excel "data tables" (What-If Analysis) can't be written by Python; ask Excel to create them.
    ops = [f"$ws=$wb.Worksheets.Item('{t['sheet']}'); "
           f"$null=$ws.Range('{t['range']}').Table($ws.Range('{t['row_input']}'), $ws.Range('{t['col_input']}'))"
           for t in m.data_tables]
    result = excel_com.check(out, ops=ops)
    print(f"  {result['formulas']} formulas, {len(result['errors'])} showing errors")
    for e in result["errors"][:20]:
        print(f"    {e}")
    if result["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

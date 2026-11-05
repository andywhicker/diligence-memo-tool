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
from src import excel_com, lbo_model


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Excel LBO from lbo_inputs.json (written by diligence.py).")
    ap.add_argument("inputs", help="path to output/<doc>/lbo_inputs.json")
    ap.add_argument("--no-excel", action="store_true", help="skip the Excel recalculation check")
    args = ap.parse_args()

    data = json.loads(Path(args.inputs).read_text(encoding="utf-8"))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", data["company"]).strip("_")
    out = config.OUTPUT_DIR / f"{slug}_LBO_{date.today().isoformat()}.xlsx"

    m = lbo_model.build(data, out)
    print(f"Built: {out}")
    print(f"  {len(m.placeholders)} assumptions are placeholders for you to set (yellow cells).")

    if args.no_excel:
        return
    print("Recalculating in Excel and checking every formula...")
    result = excel_com.check(out)
    print(f"  {result['formulas']} formulas, {len(result['errors'])} showing errors")
    for e in result["errors"][:20]:
        print(f"    {e}")
    if result["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

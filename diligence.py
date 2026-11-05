"""
Diligence memo generator.

Usage:
  python diligence.py --check              # test that the API key and model work (costs < $0.01)
  python diligence.py docs/<file>.pdf      # full run (built in later steps)
"""

import argparse
import sys

import config
from src import llm


def check() -> None:
    print(f"Model: {config.MODEL} | effort: {config.EFFORT}")
    answer = llm.ask("Reply with exactly: OK", label="setup check", max_tokens=2000)
    print(f"Model replied: {answer.strip()!r}")
    print(llm.tracker.summary())


def main() -> None:
    parser = argparse.ArgumentParser(description="First-pass diligence memo from a 10-K or CIM PDF.")
    parser.add_argument("pdf", nargs="?", help="path to the source PDF, e.g. docs/AVAV_10-K_FY2026_clean.pdf")
    parser.add_argument("--check", action="store_true", help="test the API connection and exit")
    args = parser.parse_args()

    if args.check:
        check()
        return
    if not args.pdf:
        parser.print_help()
        sys.exit(1)
    sys.exit("Full pipeline not built yet (steps 2-7).")


if __name__ == "__main__":
    main()

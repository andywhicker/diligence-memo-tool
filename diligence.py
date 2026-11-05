"""
Diligence memo generator.

Usage:
  python diligence.py --check                    # test that the API key and model work (costs < $0.01)
  python diligence.py docs/<file>.pdf --dry-run  # read + chunk the PDF only; no API calls, no cost
  python diligence.py docs/<file>.pdf            # full run (built in later steps)
"""

import argparse
import sys

import config
from src import llm
from src.chunker import make_chunks
from src.pdf_pages import load_pages


def dry_run(pdf: str) -> None:
    page_map = load_pages(pdf)
    pages = page_map.pages
    print(f"PDF: {pdf}")
    print(f"Pages: {len(pages)} | citation mode: {page_map.cite_mode}")
    for note in page_map.notes:
        print(f"  - {note}")
    print("\nSample page refs (PDF position -> cited as):")
    for p in pages[:3] + pages[-2:]:
        print(f"  PDF {p.pdf_page:>3} -> (p. {p.ref})")

    chunks = make_chunks(pages)
    total = sum(c.approx_tokens for c in chunks)
    print(f"\nChunks: {len(chunks)} ({config.PAGES_PER_CHUNK} pages each, {config.PAGE_OVERLAP}-page overlap)")
    for c in chunks:
        print(f"  chunk {c.index:>2}: pp. {c.refs[0]:>6} - {c.refs[-1]:<6} ~{c.approx_tokens:,} tokens")
    print(f"Total text sent across all chunks: ~{total:,} tokens (includes overlap)")


def check() -> None:
    print(f"Model: {config.MODEL} | effort: {config.EFFORT}")
    answer = llm.ask("Reply with exactly: OK", label="setup check", max_tokens=2000)
    print(f"Model replied: {answer.strip()!r}")
    print(llm.tracker.summary())


def main() -> None:
    parser = argparse.ArgumentParser(description="First-pass diligence memo from a 10-K or CIM PDF.")
    parser.add_argument("pdf", nargs="?", help="path to the source PDF, e.g. docs/AVAV_10-K_FY2026_clean.pdf")
    parser.add_argument("--check", action="store_true", help="test the API connection and exit")
    parser.add_argument("--dry-run", action="store_true", help="read and chunk the PDF only; no API calls")
    args = parser.parse_args()

    if args.check:
        check()
        return
    if not args.pdf:
        parser.print_help()
        sys.exit(1)
    if args.dry_run:
        dry_run(args.pdf)
        return
    sys.exit("Full pipeline not built yet (steps 2-7).")


if __name__ == "__main__":
    main()

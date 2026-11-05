"""
Diligence memo generator.

Usage:
  python diligence.py --check                    # test that the API key and model work (costs < $0.01)
  python diligence.py docs/<file>.pdf --dry-run  # read + chunk the PDF only; no API calls, no cost
  python diligence.py docs/<file>.pdf            # full run (built in later steps)
"""

import argparse
import json
import sys
import time
from pathlib import Path

import config
from src import llm
from src.chunker import make_chunks
from src.extract import extract_chunk
from src.pdf_pages import load_pages
from src.pipeline import run_map
from src.verify import verify


def run_one_chunk(pdf: str, n: int) -> None:
    page_map = load_pages(pdf)
    chunks = make_chunks(page_map.pages)
    if not 1 <= n <= len(chunks):
        sys.exit(f"Chunk must be between 1 and {len(chunks)}.")
    chunk = chunks[n - 1]
    print(f"Chunk {n}: pages {chunk.refs[0]}-{chunk.refs[-1]} (~{chunk.approx_tokens:,} tokens)")

    findings = extract_chunk(chunk)
    passed, rejected = verify(findings, page_map.by_ref())

    out_dir = config.OUTPUT_DIR / Path(pdf).stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"chunk_{n:02d}.json"
    out_file.write_text(json.dumps({"passed": passed, "rejected": rejected}, indent=2), encoding="utf-8")

    print(f"\nFindings: {len(findings)} extracted | {len(passed)} verified | {len(rejected)} rejected")
    by_cat = {}
    for f in passed:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    print("Verified by category: " + ", ".join(f"{k} {v}" for k, v in sorted(by_cat.items())))
    if rejected:
        print("\nRejected:")
        for f in rejected:
            print(f"  {f['id']} (p. {f['page']}): {f['reject_reason']} | {f['claim'][:90]}")
    print(f"\nSaved: {out_file}")
    print(llm.tracker.summary())


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
    parser.add_argument("--chunk", type=int, metavar="N", help="extract + verify chunk N only (for testing)")
    parser.add_argument("--fresh", action="store_true", help="ignore saved chunk results and re-extract everything")
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
    if args.chunk:
        run_one_chunk(args.pdf, args.chunk)
        return
    full_run(args.pdf, fresh=args.fresh)


def full_run(pdf: str, fresh: bool) -> None:
    started = time.time()
    print(f"Model: {config.MODEL} | effort: {config.EFFORT}")
    m = run_map(pdf, fresh=fresh)

    from collections import Counter
    cats = Counter(f["category"] for f in m.findings)
    reasons = Counter(r["reject_reason"].split(" '")[0].split(" [")[0] for r in m.rejected)
    print(f"\nVerified findings: {len(m.findings)} "
          f"(rejected {len(m.rejected)}, overlap duplicates removed {m.duplicates_removed})")
    print("By category: " + ", ".join(f"{k} {v}" for k, v in sorted(cats.items())))
    if reasons:
        print("Rejection reasons: " + ", ".join(f"{k}: {v}" for k, v in reasons.most_common()))
    print(f"Saved: {m.out_dir / 'findings.json'} and rejected.json")

    print("\nMemo synthesis not built yet (step 5).")
    print(f"\n{llm.tracker.summary()} | time: {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()

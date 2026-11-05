"""
Diligence memo generator.

Usage:
  python diligence.py --check                    # test that the API key and model work (costs < $0.01)
  python diligence.py docs/<file>.pdf --dry-run  # read + chunk the PDF only; no API calls, no cost
  python diligence.py docs/<file>.pdf            # full run (built in later steps)
"""

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import config
from src import llm
from src.chunker import make_chunks
from src import consistency, fintable, render
from src.citations import enforce
from src.synthesize import write_draft
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
    parser.add_argument("--fresh", action="store_true",
                        help="ignore saved chunk results and re-extract everything (later steps re-run "
                             "automatically whenever their inputs or prompts change)")
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

    cache = m.out_dir / "cache"   # model answers, reused automatically when their inputs are unchanged

    # ---- Financial tables + PE metrics: model picks inputs, code checks and calculates ----
    print("\nBuilding financial tables and metrics...")
    table = fintable.build(m.findings, cache_file=cache / "financial_table.json")
    (m.out_dir / "calcs.json").write_text(json.dumps(table.calcs, indent=2), encoding="utf-8")
    sources = m.findings + table.calcs        # everything the memo may cite

    # ---- Memo: written from verified findings + calcs, then every line citation-checked ----
    print("Writing memo...")
    draft = write_draft(m.findings, table.calcs, cache_file=cache / "memo_draft.json")
    (m.out_dir / "draft_raw.md").write_text(draft, encoding="utf-8")
    memo, report = enforce(draft, sources)

    notes_md, notes_report = enforce("\n".join(f"- {n}" for n in table.notes), sources)
    report.deleted += [(l, f"[table note] {r}") for l, r in notes_report.deleted]
    fin_block = "\n".join([fintable.render(table), "**Table notes**", "",
                           *[f"- {c}" for c in fintable.checks(table)],
                           *([notes_md] if notes_md.strip() else []), "", "**Commentary**"])

    print("Running consistency check...")
    consistency_md, dropped = consistency.run(m.findings, table.calcs, cache_file=cache / "consistency.json")
    report.deleted += [(l, f"[consistency item] {r}") for l, r in dropped]

    pages = m.page_map.pages
    readable = sum(1 for p in pages if p.readable)
    coverage = list(m.page_map.notes) + [
        f"{readable} of {len(pages)} PDF pages had extractable text and were analyzed.",
        f"{len(m.findings)} findings verified against the source; {len(m.rejected)} rejected "
        f"(quote or number not found on the cited page). See rejected.json.",
        f"{len(report.deleted)} memo lines deleted by the citation check (no valid citation or "
        f"unsupported number). See citation_log.md.",
    ]
    memo = (memo.replace("{{RUN_DATE}}", date.today().isoformat())
                .replace("{{PAGES_PROCESSED}}", f"{readable} of {len(pages)} PDF pages")
                .replace("{{COVERAGE_NOTES}}", "\n".join(f"- {c}" for c in coverage))
                .replace("{{FINANCIAL_TABLE}}", fin_block)
                .replace("{{CONSISTENCY_CHECK}}", consistency_md))

    memo_path = m.out_dir / "memo.md"
    memo_path.write_text(memo, encoding="utf-8")
    log_lines = [f"# Citation log\n\nKept {report.kept} lines; deleted {len(report.deleted)}.\n"]
    log_lines += [f"- **{reason}**\n  > {line}" for line, reason in report.deleted]
    (m.out_dir / "citation_log.md").write_text("\n".join(log_lines), encoding="utf-8")

    print(f"Citation check: kept {report.kept} lines, deleted {len(report.deleted)}")

    # ---- Step 7: deliverables (Markdown + Word + PDF) at the top of output/ ----
    title = next((l for l in memo.splitlines() if l.startswith("# ")), "# Memo")
    company = title.split(":", 1)[-1].strip() if ":" in title else Path(pdf).stem
    base = config.OUTPUT_DIR / f"{re.sub(r'[^A-Za-z0-9]+', '_', company).strip('_')}_Diligence_Memo_{date.today().isoformat()}"
    base.with_suffix(".md").write_text(memo, encoding="utf-8")
    docx_path = render.to_docx(memo, base.with_suffix(".docx"))
    pdf_path = render.to_pdf(docx_path)
    print("\nDeliverables:")
    for p in (base.with_suffix(".md"), docx_path, pdf_path):
        if p:
            print(f"  {p}")
    print(f"Working files (findings, logs, drafts): {m.out_dir}")
    print(f"\n{llm.tracker.summary()} | time: {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()

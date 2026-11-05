"""
Runs the "map" half of the pipeline over the whole document:

  PDF -> pages -> chunks -> extract findings per chunk -> verify -> de-duplicate

Each chunk's raw findings are saved to output/<doc>/chunks/chunk_NN.json
together with a fingerprint of (prompt text, model, effort). On the next run,
a chunk is re-sent to the API only if that fingerprint changed, so iterating
on later steps doesn't re-pay for extraction.
"""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import config
from src.chunker import Chunk, make_chunks
from src.extract import extract_chunk, load_prompt
from src.pdf_pages import PageMap, load_pages
from src.verify import normalize, verify

PARALLEL_CALLS = 4


@dataclass
class MapResult:
    page_map: PageMap
    chunks: list[Chunk]
    findings: list[dict]        # verified, de-duplicated
    rejected: list[dict]
    duplicates_removed: int
    out_dir: Path


NARRATIVE_ID_OFFSET = 50     # narrative-pass findings get IDs F51-..., F52-...


def _fingerprint(prompt_name: str = "extract_findings.md") -> str:
    key = load_prompt(prompt_name) + config.MODEL + config.EFFORT
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _extract_cached(chunk: Chunk, cache_dir: Path, fp: str, fresh: bool, prefix: str = "chunk",
                    prompt_name: str = "extract_findings.md", id_offset: int = 0) -> list[dict]:
    path = cache_dir / f"{prefix}_{chunk.index:02d}.json"
    label = "extract chunk" if prefix == "chunk" else "MD&A narrative chunk"
    if path.exists() and not fresh:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("fingerprint") == fp and saved.get("pages") == chunk.refs:
            print(f"  [{label} {chunk.index}] reused saved result")
            return saved["findings"]
    findings = extract_chunk(chunk, prompt_name=prompt_name, id_offset=id_offset, label=label)
    path.write_text(json.dumps({"fingerprint": fp, "pages": chunk.refs, "findings": findings}, indent=2),
                    encoding="utf-8")
    return findings


_MDNA_START = re.compile(r"item\s*7\.?\s*management.{0,3}s\s+discussion", re.I)
_MDNA_END = re.compile(r"item\s*7a\.?\s*quantitative", re.I)


def mdna_pages(pages):
    """
    The MD&A section of a 10-K: from the 'Item 7. Management's Discussion' heading to
    'Item 7A'. The table of contents lists both headings on one page, so skip any page that has both.
    Returns all readable pages if no MD&A heading is found (e.g. a CIM).
    """
    readable = [p for p in pages if p.readable]
    start = next((i for i, p in enumerate(readable)
                  if _MDNA_START.search(p.text) and not _MDNA_END.search(p.text)), None)
    if start is None:
        return readable, "no MD&A heading found; narrative pass covers the whole document"
    end = next((i for i in range(start + 1, len(readable)) if _MDNA_END.search(readable[i].text)),
               min(start + 25, len(readable) - 1))
    sel = readable[start:end + 1]
    return sel, f"narrative pass covers MD&A, pp. {sel[0].ref}-{sel[-1].ref}"


def _dedupe(findings: list[dict]) -> tuple[list[dict], int]:
    """Overlap pages get extracted twice; keep the first copy of identical facts."""
    seen, out = set(), []
    for f in findings:
        key = (f["page"], normalize(f["quote"]), f["value"].strip(), f["metric"].strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out, len(findings) - len(out)


def run_map(pdf: str, fresh: bool = False) -> MapResult:
    page_map = load_pages(pdf)
    chunks = make_chunks(page_map.pages)
    out_dir = config.OUTPUT_DIR / Path(pdf).stem
    cache_dir = out_dir / "chunks"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fp = _fingerprint()

    print(f"Extracting findings from {len(chunks)} chunks ({PARALLEL_CALLS} at a time)...")
    with ThreadPoolExecutor(max_workers=PARALLEL_CALLS) as pool:
        results = list(pool.map(lambda c: _extract_cached(c, cache_dir, fp, fresh), chunks))
    all_findings = [f for chunk_findings in results for f in chunk_findings]

    # Focused second pass: every figure and explanation management states in MD&A.
    # Feeds the consistency check (narrative vs. statements).
    sel, note = mdna_pages(page_map.pages)
    page_map.notes.append(f"MD&A {note}.")
    print(f"Narrative pass: {note}")
    narr_chunks = make_chunks(sel)
    nfp = _fingerprint("extract_narrative.md")
    with ThreadPoolExecutor(max_workers=PARALLEL_CALLS) as pool:
        narr = list(pool.map(lambda c: _extract_cached(c, cache_dir, nfp, fresh, prefix="narrative",
                                                       prompt_name="extract_narrative.md",
                                                       id_offset=NARRATIVE_ID_OFFSET), narr_chunks))
    all_findings += [f for chunk_findings in narr for f in chunk_findings]

    passed, rejected = verify(all_findings, page_map.by_ref())
    findings, dupes = _dedupe(passed)

    (out_dir / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    (out_dir / "rejected.json").write_text(json.dumps(rejected, indent=2), encoding="utf-8")
    return MapResult(page_map, chunks, findings, rejected, dupes, out_dir)

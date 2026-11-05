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


def _fingerprint() -> str:
    key = load_prompt("extract_findings.md") + config.MODEL + config.EFFORT
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _extract_cached(chunk: Chunk, cache_dir: Path, fp: str, fresh: bool) -> list[dict]:
    path = cache_dir / f"chunk_{chunk.index:02d}.json"
    if path.exists() and not fresh:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("fingerprint") == fp:
            print(f"  [extract chunk {chunk.index}] reused saved result")
            return saved["findings"]
    findings = extract_chunk(chunk)
    path.write_text(json.dumps({"fingerprint": fp, "pages": chunk.refs, "findings": findings}, indent=2),
                    encoding="utf-8")
    return findings


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

    passed, rejected = verify(all_findings, page_map.by_ref())
    findings, dupes = _dedupe(passed)

    (out_dir / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    (out_dir / "rejected.json").write_text(json.dumps(rejected, indent=2), encoding="utf-8")
    return MapResult(page_map, chunks, findings, rejected, dupes, out_dir)

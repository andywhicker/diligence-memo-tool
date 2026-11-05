"""
Step 1 of the pipeline ("map"): one chunk of pages -> a list of findings.

A finding is one fact with its page and an exact supporting quote.
The prompt lives in prompts/extract_findings.md; this file only fills in
the blanks, calls the model, and assigns each finding an ID like F08-012
(chunk 8, finding 12).
"""

import json

import config
from src import llm
from src.chunker import Chunk

CATEGORIES = ["business", "market", "customers", "backlog", "financial",
              "balance_sheet", "qoe", "narrative", "risk", "guidance"]

# The exact JSON shape the model must return. The API enforces it.
FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": CATEGORIES},
                    "claim": {"type": "string"},
                    "metric": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "period": {"type": "string"},
                    "page": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["category", "claim", "metric", "value", "unit", "period", "page", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


def load_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text(encoding="utf-8")


def extract_chunk(chunk: Chunk, prompt_name: str = "extract_findings.md", id_offset: int = 0,
                  label: str = "extract chunk") -> list[dict]:
    """
    id_offset keeps IDs unique across passes: the main pass uses chunk numbers 1-50
    (F08-012), the MD&A narrative pass uses 51+ (F51-004).
    """
    prompt = (load_prompt(prompt_name)
              .replace("{{PAGE_REFS}}", f"{chunk.refs[0]} to {chunk.refs[-1]}")
              .replace("{{CHUNK_TEXT}}", chunk.text))
    # 64k output cap: number-dense pages (e.g. MD&A results tables) can need >32k with reasoning
    raw = llm.ask(prompt, label=f"{label} {chunk.index}", schema=FINDINGS_SCHEMA, max_tokens=64000)
    findings = json.loads(raw)["findings"]
    for n, f in enumerate(findings, start=1):
        f["id"] = f"F{chunk.index + id_offset:02d}-{n:03d}"
        f["chunk"] = chunk.index + id_offset
    return findings

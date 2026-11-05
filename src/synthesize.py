"""
The "reduce" half: verified findings + memo template -> draft memo (Markdown).

The model sees only the verified findings, never the raw document, and cites
finding IDs like [F08-056]. src/citations.py then checks every line.
"""

import re

import config
from src import llm
from src.extract import load_prompt


def format_findings(findings: list[dict]) -> str:
    lines = []
    for f in findings:
        value = f"{f['value']} {f['unit']}".strip() if f["value"] else "-"
        lines.append(f"[{f['id']}] {f['category']} | p. {f['page']} | {f['metric'] or '-'} | "
                     f"{value} | {f['period']} | {f['claim']}")
    return "\n".join(lines)


def _template_without_rules() -> str:
    """The template's HTML comment holds rules we restate in the prompt; drop it to avoid duplication."""
    text = config.TEMPLATE_PATH.read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def write_draft(findings: list[dict]) -> str:
    prompt = (load_prompt("write_memo.md")
              .replace("{{TEMPLATE}}", _template_without_rules())
              .replace("{{FINDINGS}}", format_findings(findings)))
    return llm.ask(prompt, label="write memo", max_tokens=64000)

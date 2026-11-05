"""
All settings you might want to change live here.
Nothing else in the code should hard-code a model name, price, or chunk size.
"""

from pathlib import Path

# ---- Model ------------------------------------------------------------------
# Change this one line to switch models (e.g. "claude-sonnet-5-5" to cut cost ~50%).
MODEL = "claude-opus-5-5"

# How hard the model thinks before answering: "low" | "medium" | "high" | "xhigh" | "max".
# Higher = more accurate on hard extraction, but more output tokens (= more cost).
EFFORT = "high"

# If the model declines a request on safety grounds (rare; can happen with
# defense/export-control text), let Anthropic automatically retry it on another
# model. Every run logs which model actually answered, so this stays auditable.
USE_REFUSAL_FALLBACK = True

# ---- Prices (USD per 1M tokens) --------------------------------------------
# Source: Anthropic model pricing as of 2026-10. Check before relying on cost figures.
# cache_write = 1.25x input (5-minute cache); cache_read as published.
PRICES = {
    "claude-opus-5-5":   {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20},
    "claude-haiku-5-5":  {"input": 0.10, "output": 0.50,  "cache_write": 0.125, "cache_read": 0.01},
}

# ---- Chunking ---------------------------------------------------------------
PAGES_PER_CHUNK = 10   # ~10k tokens per chunk for a typical 10-K page density
PAGE_OVERLAP = 1       # repeat 1 page between chunks so tables split across a page break aren't lost

# ---- Paths ------------------------------------------------------------------
ROOT = Path(__file__).parent
PROMPTS_DIR = ROOT / "prompts"
OUTPUT_DIR = ROOT / "output"
TEMPLATE_PATH = ROOT / "memo_template.md"

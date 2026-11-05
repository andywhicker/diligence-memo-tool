"""
The only file that talks to the Anthropic API.

Every call goes through `ask()`, which:
  1. sends the prompt to the model set in config.MODEL
  2. records tokens used and which model actually answered
  3. returns the model's text

`UsageTracker` adds up tokens and cost across the whole run so we can print
a cost summary at the end.
"""

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import config

load_dotenv(config.ROOT / ".env")  # puts ANTHROPIC_API_KEY from .env into the environment


@dataclass
class CallRecord:
    label: str            # what this call was for, e.g. "extract chunk 3"
    model: str            # model that actually answered (differs from config.MODEL only if a fallback ran)
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    cost_usd: float


@dataclass
class UsageTracker:
    calls: list = field(default_factory=list)

    def add(self, label: str, response) -> CallRecord:
        u = response.usage
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        price = config.PRICES.get(response.model)
        if price is None:
            print(f"  [warn] no price on file for {response.model}; cost shown as $0", file=sys.stderr)
            cost = 0.0
        else:
            cost = (
                u.input_tokens * price["input"]
                + u.output_tokens * price["output"]
                + cache_write * price["cache_write"]
                + cache_read * price["cache_read"]
            ) / 1_000_000
        rec = CallRecord(label, response.model, u.input_tokens, u.output_tokens, cache_write, cache_read, cost)
        self.calls.append(rec)
        return rec

    def summary(self) -> str:
        tot_in = sum(c.input_tokens + c.cache_write_tokens + c.cache_read_tokens for c in self.calls)
        tot_out = sum(c.output_tokens for c in self.calls)
        tot_cost = sum(c.cost_usd for c in self.calls)
        models = sorted({c.model for c in self.calls})
        return (
            f"API calls: {len(self.calls)} | input tokens: {tot_in:,} | output tokens: {tot_out:,} | "
            f"est. cost: ${tot_cost:.2f} | model(s): {', '.join(models)}"
        )


tracker = UsageTracker()
_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit(
                "No API key found. Open the .env file in this folder and paste your key after\n"
                "ANTHROPIC_API_KEY=   (create one at console.anthropic.com > API Keys)."
            )
        _client = anthropic.Anthropic()
    return _client


def ask(prompt: str, *, label: str, system: str | None = None, max_tokens: int = 32000,
        schema: dict | None = None, cache_file: Path | None = None) -> str:
    """
    Send one prompt, return the model's text answer, and log usage.

    If `schema` (a JSON Schema) is given, the API guarantees the answer is
    valid JSON matching that shape.

    If `cache_file` is given, the answer is saved there with a fingerprint of
    (model, effort, prompt, schema). The next identical call returns the saved
    answer for free; change anything in the prompt or its inputs and it re-runs.
    """
    key = hashlib.sha256(json.dumps([config.MODEL, config.EFFORT, system, prompt, schema],
                                    sort_keys=True).encode()).hexdigest()
    if cache_file and cache_file.exists():
        saved = json.loads(cache_file.read_text(encoding="utf-8"))
        if saved.get("key") == key:
            print(f"  [{label}] reused saved answer (inputs unchanged, $0)")
            return saved["text"]

    client = _get_client()

    output_config = {"effort": config.EFFORT}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}

    params = dict(
        model=config.MODEL,
        max_tokens=max_tokens,
        output_config=output_config,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        params["system"] = system
    if config.USE_REFUSAL_FALLBACK:
        params["betas"] = ["server-side-fallback-2026-07-01"]
        params["fallbacks"] = "default"

    # Streaming keeps long requests from timing out; we just wait for the final message.
    with client.beta.messages.stream(**params) as stream:
        response = stream.get_final_message()

    rec = tracker.add(label, response)
    note = f" (served by fallback model {rec.model})" if rec.model != config.MODEL else ""
    print(f"  [{label}] in={rec.input_tokens + rec.cache_write_tokens + rec.cache_read_tokens:,} "
          f"out={rec.output_tokens:,} ${rec.cost_usd:.3f}{note}")

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model declined the request for '{label}'. Details: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"Answer for '{label}' was cut off at max_tokens={max_tokens}. Raise the limit.")

    text = "".join(b.text for b in response.content if b.type == "text")
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"key": key, "label": label, "text": text}), encoding="utf-8")
    return text

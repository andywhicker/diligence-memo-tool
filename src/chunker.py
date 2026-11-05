"""
Pages -> overlapping chunks small enough for one model call each.

Each page inside a chunk is wrapped in a tag:

    <page ref="65">
    ...page text...
    </page>

The model is told to cite only these ref values, and the verifier later
checks every quote against the page it claims to come from.
"""

from dataclasses import dataclass

import config
from src.pdf_pages import Page


@dataclass
class Chunk:
    index: int              # 1-based
    pages: list[Page]

    @property
    def refs(self) -> list[str]:
        return [p.ref for p in self.pages]

    @property
    def text(self) -> str:
        return "\n\n".join(f'<page ref="{p.ref}">\n{p.text}\n</page>' for p in self.pages)

    @property
    def approx_tokens(self) -> int:
        return len(self.text) // 4      # rough rule of thumb: ~4 characters per token


def make_chunks(pages: list[Page],
                size: int = config.PAGES_PER_CHUNK,
                overlap: int = config.PAGE_OVERLAP) -> list[Chunk]:
    readable = [p for p in pages if p.readable]
    if size <= overlap:
        raise ValueError("PAGES_PER_CHUNK must be larger than PAGE_OVERLAP")
    chunks, start, step = [], 0, size - overlap
    while start < len(readable):
        chunks.append(Chunk(index=len(chunks) + 1, pages=readable[start:start + size]))
        if start + size >= len(readable):
            break
        start += step
    return chunks

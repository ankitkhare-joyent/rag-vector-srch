"""Load markdown runbooks and split them into chunks.

Chunking strategy (docs/02 explains the trade-offs):
  * Structure first: split on markdown headings, so a chunk never straddles two topics.
  * Size second: a section longer than `max_tokens` is split on paragraph boundaries, with a small
    overlap so a sentence that depends on the previous paragraph still has its context.
  * Never split inside a fenced code block or a table: half a command or half a table is useless.
  * Every chunk carries a *contextual header* ("RB-002 EBS data volume running out of space > Immediate
    mitigation"). It is embedded and indexed together with the text, which is the cheapest big win in
    retrieval quality: "Steps" on its own means nothing, "RB-002 ... > Steps" does.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass
class Document:
    doc_id: str
    title: str
    doc_type: str
    team: str
    services: list[str]
    updated: date | None
    source_path: str
    body: str
    sha256: str


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    ordinal: int
    section: str
    content: str
    header: str            # contextual header prepended for embedding and keyword search
    token_estimate: int = field(default=0)

    @property
    def embed_text(self) -> str:
        return f"{self.header}\n\n{self.content}"


def estimate_tokens(text: str) -> int:
    """~1.3 WordPiece tokens per English word. Good enough for sizing; the embedder truncates at 512."""
    return int(len(text.split()) * 1.3) + 1


def _parse_front_matter(raw: str) -> tuple[dict, str]:
    """Tiny parser for the flat `key: value` / `key: [a, b]` front matter our runbooks use."""
    m = FRONT_MATTER.match(raw)
    if not m:
        raise ValueError("missing front matter")
    meta: dict = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        value = value.strip().strip('"')
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, raw[m.end():]


def load_document(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_front_matter(raw)
    updated = date.fromisoformat(meta["updated"]) if meta.get("updated") else None
    return Document(
        doc_id=meta["id"], title=meta["title"], doc_type=meta["doc_type"], team=meta["team"],
        services=meta.get("services", []), updated=updated, source_path=path.name, body=body,
        sha256=hashlib.sha256(raw.encode()).hexdigest(),
    )


def load_corpus(directory: Path) -> list[Document]:
    return [load_document(p) for p in sorted(directory.glob("*.md"))]


def _blocks(text: str) -> list[str]:
    """Paragraph-level blocks, keeping fenced code and tables whole."""
    blocks, current, in_fence = [], [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        is_table = line.lstrip().startswith("|")
        if not line.strip() and not in_fence:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        # a table row directly after a non-table paragraph starts a new block
        if current and not in_fence and is_table and not current[-1].lstrip().startswith("|"):
            blocks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _sections(body: str) -> list[tuple[str, str]]:
    """(section heading, text) pairs. Text before the first ## heading is the 'Overview'."""
    sections, heading, lines = [], "Overview", []
    for line in body.splitlines():
        if line.startswith("# "):            # the document title; already in the header
            continue
        if line.startswith("## "):
            if any(s.strip() for s in lines):
                sections.append((heading, "\n".join(lines).strip()))
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    if any(s.strip() for s in lines):
        sections.append((heading, "\n".join(lines).strip()))
    return sections


def chunk_document(doc: Document, max_tokens: int = 300, overlap_tokens: int = 40) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, text in _sections(doc.body):
        header = f"{doc.doc_id} {doc.title} > {section}"
        pieces: list[list[str]] = [[]]
        size = 0
        for block in _blocks(text):
            t = estimate_tokens(block)
            if pieces[-1] and size + t > max_tokens:
                # start a new piece, carrying over trailing blocks of the previous one as overlap
                carry, carried = [], 0
                for prev in reversed(pieces[-1]):
                    pt = estimate_tokens(prev)
                    if carried + pt > overlap_tokens:
                        break
                    carry.insert(0, prev)
                    carried += pt
                pieces.append(carry)
                size = carried
            pieces[-1].append(block)
            size += t
        for blocks in pieces:
            content = "\n\n".join(blocks).strip()
            if not content:
                continue
            n = len(chunks)
            chunks.append(Chunk(chunk_id=f"{doc.doc_id}#{n}", doc_id=doc.doc_id, ordinal=n, section=section,
                                content=content, header=header, token_estimate=estimate_tokens(content)))
    return chunks

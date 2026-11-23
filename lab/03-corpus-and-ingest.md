# Lab 03 · Corpus, chunking and ingest

One sitting, about 30 minutes. Background: [docs/02](../docs/02-chunking-and-ingestion.md). Code:
[rag/corpus.py](../rag/corpus.py), [rag/ingest.py](../rag/ingest.py), [corpus/runbooks/](../corpus/runbooks).

Everything the system can answer comes from 26 markdown files. This lab follows one of them into the database.
After it you can explain:

- what the front matter is for, and how a document becomes chunks
- what the contextual header is and why it's embedded with the text
- what "incremental" and "atomic per document" mean for this ingest job
- what a single bad file does to an ingest run

## Before you start

```bash
source lab/env.sh
ls corpus/runbooks | head
head -9 corpus/runbooks/rb-002-ebs-volume-full.md
```

The ingest container mounts `corpus/` from your laptop, so you can edit a runbook and re-run `mise run ingest`
without rebuilding anything.

## 1. From documents to chunks, without the stack

The chunker is plain Python; run it on your laptop.

**Predict (P1):** 26 documents, split on `##` headings. Roughly how many chunks? What's the median chunk size in
tokens, given that our runbook sections are short?

```bash
uv run python - <<'EOF'
from pathlib import Path
from collections import Counter
from rag.corpus import load_corpus, chunk_document
docs = load_corpus(Path("corpus/runbooks"))
chunks = [c for d in docs for c in chunk_document(d)]
print(len(docs), "docs,", len(chunks), "chunks,", dict(Counter(d.doc_type for d in docs)))
sizes = sorted(c.token_estimate for c in chunks)
print("tokens min/median/max:", sizes[0], sizes[len(sizes) // 2], sizes[-1])
EOF
```

**Predict (P2):** what does RB-002 turn into, and what exactly gets embedded for one chunk?

```bash
uv run python - <<'EOF'
from pathlib import Path
from rag.corpus import load_document, chunk_document
d = load_document(Path("corpus/runbooks/rb-002-ebs-volume-full.md"))
for c in chunk_document(d):
    print(c.chunk_id, c.token_estimate, "|", c.header)
print("----\n" + chunk_document(d)[1].embed_text[:300])
EOF
```

**Predict (P3):** if you shrink `max_tokens` from 300 to 60, how many chunks does RB-002 become?

```bash
uv run python -c "
from pathlib import Path; from rag.corpus import load_document, chunk_document
print(len(chunk_document(load_document(Path('corpus/runbooks/rb-002-ebs-volume-full.md')), max_tokens=60, overlap_tokens=20)))"
```

## 2. The same chunks in Postgres

```bash
psql_su "select d.doc_id, d.doc_type, d.services, count(*) chunks from rag.documents d join rag.chunks c using (doc_id)
         group by 1, 2, 3 order by 4 desc limit 5"
psql_su "select chunk_id, section, left(header, 60) header, embedding_model from rag.chunks where doc_id = 'RB-002' order by ordinal"
docker compose logs ingest | grep -E 'loaded|done|revoked'
```

## 3. Change one runbook

**Predict (P4):** you add an "Escalation" section to RB-002 and re-run ingest. How many documents are re-embedded,
and how many chunks does the index have afterwards?

```bash
cp corpus/runbooks/rb-002-ebs-volume-full.md /tmp/rb002.bak
printf '\n## Escalation\n\nIf the volume is already at the 64 TiB gp3 maximum, page the storage on-call and move data to a second volume.\n' \
  >> corpus/runbooks/rb-002-ebs-volume-full.md
mise run ingest 2>&1 | grep -E 'ingested|done'
psql_su "select chunk_id, section from rag.chunks where doc_id = 'RB-002' order by ordinal"
search "the gp3 volume is at its maximum size, what now?" hybrid true 3
```

Each changed document is replaced in its own transaction (`DELETE` cascades to its chunks, then `INSERT`s), so a
search running at the same moment sees either the old RB-002 or the new one, never half of it.

## Break it, then fix it

**Break: a file with no front matter.** Someone drops a quick note into the corpus folder.

**Predict (P5):** does ingest skip the bad file and load the rest, or stop?

```bash
cat > corpus/runbooks/zz-broken.md <<'EOF'
# A runbook someone forgot to give front matter

Restart the thing.
EOF
mise run ingest 2>&1 | grep -E 'Error|done' | tail -2
```

**Fix:** remove the file, restore RB-002, and re-run. Watch the index go back to 118 chunks.

```bash
rm corpus/runbooks/zz-broken.md
cp /tmp/rb002.bak corpus/runbooks/rb-002-ebs-volume-full.md
mise run ingest 2>&1 | grep -E 'ingested|done'
```

## Check your predictions

**P1.** `26 docs, 118 chunks, {'runbook': 15, 'guide': 5, 'policy': 4, 'postmortem': 2}`, and
`tokens min/median/max: 12 59 211`. Most sections are a few short paragraphs, so they come out well under the
300-token budget. That's on purpose here (sections are the unit an engineer looks for), but it's small for a model
with a 1M-token context; lesson 02 discusses going bigger.

**P2.**

```
RB-002#0 59 | RB-002 EBS data volume running out of space > Overview
RB-002#1 194 | RB-002 EBS data volume running out of space > Immediate mitigation (under 15 minutes)
RB-002#2 60 | RB-002 EBS data volume running out of space > Root cause follow-up
RB-002#3 49 | RB-002 EBS data volume running out of space > Volume type
----
RB-002 EBS data volume running out of space > Immediate mitigation (under 15 minutes)

1. Confirm which mount is full: `df -h` and `du -xh --max-depth=1 /data | sort -h`.
…
```

One chunk per section. The embedded text starts with the contextual header (document ID, title, section), then the
section text. A chunk that says only "1. Confirm which mount is full" would be hard to find; with the header it
matches "EBS", "volume", "RB-002" and "running out of space" too.

**P3.** Still 4. The chunker never splits inside a block, and the whole "Immediate mitigation" section is one
numbered list with a code block in it (no blank lines between items), so it is one 194-token block. A block bigger
than the budget stays whole: splitting a command list in half would be worse than an oversized chunk.

**P4.** One document re-embedded:

```
… INFO rag.ingest ingested RB-002        5 chunks  EBS data volume running out of space
… INFO rag.ingest done: 1 changed, 25 unchanged, 0 removed, 5 chunks embedded in 1.6s; 119 chunks in the index
```

The other 25 files have the same SHA-256 as last time and are skipped. RB-002 now has `RB-002#4 | Escalation`, and
the search puts it first (`dense=2 lex=4 rerank=-0.337`). A runbook edit is searchable a couple of seconds after you
save it.

**P5.** It stops: `ValueError: missing front matter`, and nothing is written in that run, because the job parses every
file before it touches the database. This is fail-fast: a broken corpus is loud instead of
silently missing a document. The alternative, skip and report, keeps the rest flowing but needs an alert someone
reads. For a corpus edited by hand, fail-fast plus a CI check on pull requests is the usual choice. After the fix:
`ingested RB-002 4 chunks` and `done: 1 changed, 25 unchanged, 0 removed … 118 chunks in the index`.

## What to remember

- Chunks follow the document's structure; blocks (lists, code, tables) are never split.
- The contextual header is embedded with every chunk. It's the cheapest retrieval improvement there is.
- Ingest is incremental (content hash), atomic per document, and fail-fast on a malformed file.

Next: [Lab 04 · Vectors in Postgres](04-vectors-in-postgres.md).

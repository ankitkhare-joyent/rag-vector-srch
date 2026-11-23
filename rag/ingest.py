"""Ingest the runbook corpus: parse -> chunk -> embed -> upsert into Postgres. Idempotent.

    docker compose run --rm ingest              # normal run: only changed documents are re-embedded
    docker compose run --rm ingest --full       # re-embed everything (e.g. after changing the model)

Runs with a *rag-writer* dynamic Postgres user from OpenBao, valid for 15 minutes; the API only ever
gets read-only users. Each document is replaced in its own transaction, so a reader never sees a
half-ingested document.
"""
import argparse
import logging
import time

from rag.bao import BaoClient, DbCredentialProvider
from rag.corpus import chunk_document, load_corpus
from rag.db import make_pool
from rag.models import embed_passages
from rag.settings import get_settings

log = logging.getLogger("rag.ingest")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true", help="re-embed every document, even unchanged ones")
    args = p.parse_args()

    s = get_settings()
    bao = BaoClient(s)
    pool = make_pool(s, DbCredentialProvider(bao, s.bao_db_role), max_size=2)
    docs = load_corpus(s.corpus_dir)
    log.info("loaded %d documents from %s", len(docs), s.corpus_dir)

    with pool.connection() as conn:
        existing = dict(conn.execute("SELECT doc_id, content_sha256 FROM documents").fetchall())
        stale_model = {r[0] for r in conn.execute(
            "SELECT DISTINCT doc_id FROM chunks WHERE embedding_model <> %s", (s.embed_model,))}

    changed = [d for d in docs if args.full or existing.get(d.doc_id) != d.sha256 or d.doc_id in stale_model]
    removed = set(existing) - {d.doc_id for d in docs}
    t0, n_chunks = time.perf_counter(), 0
    for doc in changed:
        chunks = chunk_document(doc, s.chunk_max_tokens, s.chunk_overlap_tokens)
        vectors = embed_passages([c.embed_text for c in chunks])
        with pool.connection() as conn, conn.transaction():
            conn.execute("DELETE FROM documents WHERE doc_id = %s", (doc.doc_id,))   # cascades to chunks
            conn.execute(
                "INSERT INTO documents (doc_id, title, doc_type, team, services, updated, source_path, body, "
                "content_sha256) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (doc.doc_id, doc.title, doc.doc_type, doc.team, doc.services, doc.updated, doc.source_path,
                 doc.body, doc.sha256))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (chunk_id, doc_id, ordinal, section, header, content, embedding, "
                    "embedding_model) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    [(c.chunk_id, c.doc_id, c.ordinal, c.section, c.header, c.content, v, s.embed_model)
                     for c, v in zip(chunks, vectors)])
        n_chunks += len(chunks)
        log.info("ingested %-12s %2d chunks  %s", doc.doc_id, len(chunks), doc.title)

    if removed:
        with pool.connection() as conn:
            conn.execute("DELETE FROM documents WHERE doc_id = ANY(%s)", (list(removed),))
        log.info("removed %d documents no longer in the corpus: %s", len(removed), sorted(removed))

    with pool.connection() as conn:
        total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    log.info("done: %d changed, %d unchanged, %d removed, %d chunks embedded in %.1fs; %d chunks in the index",
             len(changed), len(docs) - len(changed), len(removed), n_chunks, time.perf_counter() - t0, total)
    pool.close()
    bao.revoke_self()          # drops our rag-writer Postgres user now, not in 15 minutes


if __name__ == "__main__":
    main()

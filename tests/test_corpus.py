from pathlib import Path

from rag.corpus import _blocks, chunk_document, load_corpus

CORPUS = Path(__file__).parent.parent / "corpus" / "runbooks"


def test_every_document_parses_with_unique_ids():
    docs = load_corpus(CORPUS)
    assert len(docs) >= 20
    assert len({d.doc_id for d in docs}) == len(docs)
    assert all(d.doc_type in {"runbook", "policy", "guide", "postmortem"} for d in docs)


def test_chunks_have_context_headers_and_stay_under_budget():
    for doc in load_corpus(CORPUS):
        chunks = chunk_document(doc, max_tokens=300)
        assert chunks, doc.doc_id
        for c in chunks:
            assert c.header.startswith(f"{doc.doc_id} {doc.title} > ")
            assert c.token_estimate <= 400, (c.chunk_id, c.token_estimate)


def test_code_fences_and_tables_are_never_split():
    text = "Intro para.\n\n```\nline 1\n\nline 2\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nOutro."
    blocks = _blocks(text)
    assert "```\nline 1\n\nline 2\n```" in blocks
    assert "| a | b |\n|---|---|\n| 1 | 2 |" in blocks


def test_long_sections_split_with_overlap():
    from rag.corpus import Document
    body = "## Big\n\n" + "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
    doc = Document("T-001", "Test", "guide", "x", [], None, "t.md", body, "sha")
    chunks = chunk_document(doc, max_tokens=200, overlap_tokens=90)
    assert len(chunks) > 1
    # the last paragraph of one chunk is repeated at the start of the next
    first_last_para = chunks[0].content.split("\n\n")[-1]
    assert chunks[1].content.startswith(first_last_para)

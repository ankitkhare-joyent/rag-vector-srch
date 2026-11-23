-- Runs once, as the Postgres superuser, when the data volume is first created
-- (via sql/00-init.sh in docker-entrypoint-initdb.d). Production equivalent: a migration tool
-- (Flyway, Alembic, sqitch) running as the schema owner.
--
-- Role design ("roles are groups, users are ephemeral"):
--   rag_owner   NOLOGIN  owns the schema and tables; nobody logs in as it
--   rag_reader  NOLOGIN  SELECT only                  -> granted to dynamic users for the API
--   rag_writer  NOLOGIN  reader + INSERT/UPDATE/DELETE -> granted to dynamic users for ingest
--   bao_admin   LOGIN    OpenBao's own account: may create/drop users and grant them the two groups.
--                        OpenBao rotates its password right after setup, so afterwards no human knows it.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE ROLE rag_owner NOLOGIN;
CREATE ROLE rag_reader NOLOGIN;
CREATE ROLE rag_writer NOLOGIN IN ROLE rag_reader;
CREATE ROLE bao_admin LOGIN CREATEROLE PASSWORD :'bao_admin_password';
-- Postgres 16+: a CREATEROLE user can only grant roles it holds WITH ADMIN OPTION.
GRANT rag_reader, rag_writer TO bao_admin WITH ADMIN OPTION;
-- lets OpenBao's revocation statement end sessions of the user it is about to drop
GRANT pg_signal_backend TO bao_admin;

CREATE SCHEMA rag AUTHORIZATION rag_owner;

-- Text search config for identifiers: no stemming (so `L-1216C47A`, `HttpTokens` and `i4i` survive
-- intact) but English stopwords removed (so "how", "the", "my" do not match every chunk).
CREATE TEXT SEARCH DICTIONARY rag.simple_nostop (TEMPLATE = pg_catalog.simple, STOPWORDS = english);
CREATE TEXT SEARCH CONFIGURATION rag.ident (COPY = pg_catalog.simple);
ALTER TEXT SEARCH CONFIGURATION rag.ident
    ALTER MAPPING FOR asciiword, word, numword, asciihword, hword, numhword, hword_part,
                      hword_asciipart, hword_numpart WITH rag.simple_nostop;
ALTER SCHEMA rag OWNER TO rag_owner;
SET ROLE rag_owner;

CREATE TABLE rag.documents (
    doc_id        text PRIMARY KEY,
    title         text NOT NULL,
    doc_type      text NOT NULL,             -- runbook | policy | guide | postmortem
    team          text NOT NULL,
    services      text[] NOT NULL DEFAULT '{}',
    updated       date,
    source_path   text NOT NULL,
    body          text NOT NULL,             -- the full document, for "read the whole runbook" tools
    content_sha256 text NOT NULL,            -- ingest skips unchanged documents
    ingested_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rag.chunks (
    chunk_id        text PRIMARY KEY,        -- "<doc_id>#<ordinal>"
    doc_id          text NOT NULL REFERENCES rag.documents ON DELETE CASCADE,
    ordinal         int  NOT NULL,
    section         text NOT NULL,
    header          text NOT NULL,           -- contextual header: "RB-002 <title> > <section>"
    content         text NOT NULL,
    embedding       vector(384) NOT NULL,    -- dimension is fixed by the embedding model
    embedding_model text NOT NULL,           -- so a model change is detectable and re-embeddable
    -- Lexical side of hybrid search. Header words weigh more (A) than body words (B).
    -- 'english' stems (volumes -> volum) so word forms match; rag.ident keeps exact identifiers.
    tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', header), 'A') ||
        setweight(to_tsvector('english', content), 'B') ||
        setweight(to_tsvector('rag.ident', header || ' ' || content), 'C')
    ) STORED
);

-- Approximate nearest neighbour index. Cosine distance (<=>) because the embedder's vectors are
-- normalised; m = graph degree, ef_construction = build-time search breadth. Both are pgvector defaults.
CREATE INDEX chunks_embedding_hnsw ON rag.chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX chunks_tsv_gin ON rag.chunks USING gin (tsv);
CREATE INDEX chunks_doc_id ON rag.chunks (doc_id);
CREATE INDEX documents_services ON rag.documents USING gin (services);

RESET ROLE;
GRANT USAGE ON SCHEMA rag TO rag_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA rag TO rag_reader;
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA rag TO rag_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_owner IN SCHEMA rag GRANT SELECT ON TABLES TO rag_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_owner IN SCHEMA rag GRANT INSERT, UPDATE, DELETE ON TABLES TO rag_writer;

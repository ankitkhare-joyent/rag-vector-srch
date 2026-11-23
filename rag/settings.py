"""All configuration in one place, read from RAG_* environment variables.

Nothing secret lives here. Secrets (database passwords, the Anthropic key) are fetched from
OpenBao at runtime by rag.bao; this file only says *where* OpenBao is and *which* identity to use.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", extra="ignore")

    # --- OpenBao: where it is and how this process proves who it is (AppRole) ---
    bao_addr: str = "http://openbao:8200"
    bao_approle_dir: Path = Path("/run/secrets/bao")   # holds role_id + secret_id, mounted read-only
    bao_kv_mount: str = "secret"
    bao_db_mount: str = "database"
    bao_db_role: str = "rag-reader"                      # the ingest job overrides this with rag-writer

    # --- Postgres (no user/password here: those are dynamic, from OpenBao) ---
    pg_host: str = "postgres"
    pg_port: int = 5432
    pg_database: str = "rag"

    # --- Models (ONNX via fastembed, baked into the image at build time) ---
    models_dir: Path = Path.home() / ".cache" / "runbook-rag-models"   # images set RAG_MODELS_DIR=/models
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    rerank_model: str = "jinaai/jina-reranker-v1-turbo-en"   # chosen with eval/rerankers.py

    # --- Retrieval knobs ---
    candidates: int = 30          # how many rows each retriever returns before fusion / rerank
    rrf_k: int = 60               # reciprocal rank fusion constant (60 is the value from the original paper)
    hnsw_ef_search: int = 100     # HNSW search breadth: higher = better recall, slower

    # --- Chunking ---
    chunk_max_tokens: int = 300
    chunk_overlap_tokens: int = 40

    # --- Generation ---
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"
    agent_max_steps: int = 6

    corpus_dir: Path = Path("/app/corpus/runbooks")


@lru_cache
def get_settings() -> Settings:
    return Settings()

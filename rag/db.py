"""Postgres connection pool whose credentials come from OpenBao and rotate on their own."""
import logging

from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from rag.bao import DbCredentialProvider
from rag.settings import Settings

log = logging.getLogger("rag.db")


def make_pool(settings: Settings, creds: DbCredentialProvider, *, min_size: int = 1, max_size: int = 8) -> ConnectionPool:
    def connect_kwargs() -> dict:
        c = creds.current()                 # called by the pool for every new physical connection
        return {"user": c.username, "password": c.password}

    def configure(conn) -> None:
        register_vector(conn)               # adapt numpy arrays <-> the pgvector `vector` type
        conn.execute("SET search_path = rag, public")
        conn.commit()

    # Recycle connections at half the lease, so none is still open when OpenBao revokes its user.
    max_lifetime = max(60.0, creds.lease_seconds() / 2)
    pool = ConnectionPool(
        conninfo=f"host={settings.pg_host} port={settings.pg_port} dbname={settings.pg_database} "
                 f"application_name=rag",
        kwargs=connect_kwargs, configure=configure,
        min_size=min_size, max_size=max_size, max_lifetime=max_lifetime, open=False,
        check=ConnectionPool.check_connection,   # drop connections the server killed (e.g. a revoked user)
    )
    pool.open(wait=True, timeout=30)
    log.info("db pool open, connections recycled every %.0fs", max_lifetime)
    return pool

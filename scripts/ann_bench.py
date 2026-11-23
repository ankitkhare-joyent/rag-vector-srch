"""See approximate nearest neighbour search trade-offs for yourself, inside pgvector.

    uv run python scripts/ann_bench.py            # 20k vectors, ~1-2 minutes; needs the postgres service up
    uv run python scripts/ann_bench.py --rows 100000

Our real corpus has ~120 chunks, so Postgres just scans them all (exact search, a few ms). Vector
indexes only matter at scale, so this script makes a synthetic table of clustered 384-dim vectors
(the same shape as our embeddings) and measures:

  1. exact k-NN (sequential scan)            -> ground truth and the baseline latency
  2. HNSW at several ef_search values        -> recall vs latency, the core ANN trade-off
  3. HNSW on halfvec (16-bit floats)         -> half the index size, nearly the same recall
  4. binary quantisation + re-ranking        -> 32x smaller index, then exact re-scoring of a shortlist

Connects as the Postgres superuser (LOCAL only, scratch schema `bench`, dropped at the end).
"""
import argparse
import os
import statistics
import time

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

DSN = os.environ.get("BENCH_DSN", "postgresql://postgres:postgres-local-superuser@localhost:47432/rag")
DIM, K, N_QUERIES = 384, 10, 50


def make_data(rows: int, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Clustered unit vectors with low intrinsic dimension, like real text embeddings.

    Real embeddings use 384 numbers but live near a much lower-dimensional surface (topics, styles), which
    is what makes ANN graphs work well. Uniform random 384-dim noise would make every point roughly
    equidistant and every index look bad. So: 48 topic clusters in a 24-dim latent space, projected to 384.
    """
    rng = np.random.default_rng(seed)
    latent_dim = 24
    centers = rng.normal(size=(48, latent_dim)) * 2.0
    latent = centers[rng.integers(0, 48, rows)] + rng.normal(size=(rows, latent_dim))
    projection = rng.normal(size=(latent_dim, DIM))
    data = latent @ projection + rng.normal(scale=0.5, size=(rows, DIM))
    data /= np.linalg.norm(data, axis=1, keepdims=True)
    q_latent = latent[rng.choice(rows, N_QUERIES, replace=False)] + rng.normal(scale=0.5, size=(N_QUERIES, latent_dim))
    queries = q_latent @ projection
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    return data.astype(np.float32), queries.astype(np.float32)


def run(cur, sql: str, queries, setup: list[str] = ()) -> tuple[list[list[int]], float]:
    results, times = [], []
    for q in queries:
        for s in setup:
            cur.execute(s)
        t = time.perf_counter()
        cur.execute(sql, {"q": q})
        results.append([r[0] for r in cur.fetchall()])
        times.append((time.perf_counter() - t) * 1000)
    return results, statistics.median(times)


def recall(got: list[list[int]], truth: list[list[int]]) -> float:
    return statistics.mean(len(set(g) & set(t)) / K for g, t in zip(got, truth))


def size_mb(cur, rel: str) -> float:
    cur.execute("SELECT pg_relation_size(%s::regclass)", (rel,))
    return cur.fetchone()[0] / 1e6


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=20_000)
    p.add_argument("--keep", action="store_true", help="keep the bench schema for your own experiments")
    args = p.parse_args()
    data, queries = make_data(args.rows)

    with psycopg.connect(DSN, autocommit=True) as conn:
        register_vector(conn)
        cur = conn.cursor()
        cur.execute("DROP SCHEMA IF EXISTS bench CASCADE; CREATE SCHEMA bench; SET search_path = bench, public")
        cur.execute(f"CREATE TABLE items (id int PRIMARY KEY, v vector({DIM}))")
        t = time.perf_counter()
        with cur.copy("COPY items (id, v) FROM STDIN WITH (FORMAT BINARY)") as copy:
            copy.set_types(["int4", "vector"])
            for i, v in enumerate(data):
                copy.write_row((i, v))
        print(f"loaded {args.rows:,} x {DIM}-dim vectors in {time.perf_counter() - t:.1f}s, "
              f"table {size_mb(cur, 'items'):.0f} MB")
        cur.execute("ANALYZE items; SET maintenance_work_mem = '256MB'; SET max_parallel_maintenance_workers = 0")  # parallel builds need more /dev/shm than Docker's 64 MB default

        knn = f"SELECT id FROM items ORDER BY v <=> %(q)s LIMIT {K}"
        truth, exact_ms = run(cur, knn, queries, ["SET enable_indexscan = off"])
        cur.execute("RESET enable_indexscan")
        print(f"\n{'method':<44}{'recall@10':>10}{'p50 ms':>9}{'index MB':>10}")
        print(f"{'exact (sequential scan)':<44}{1.0:>10.3f}{exact_ms:>9.1f}{'-':>10}")

        t = time.perf_counter()
        cur.execute("CREATE INDEX items_hnsw ON items USING hnsw (v vector_cosine_ops) WITH (m = 16, ef_construction = 64)")
        build = time.perf_counter() - t
        mb = size_mb(cur, "items_hnsw")
        for ef in (10, 20, 40, 100, 200):
            got, ms = run(cur, knn, queries, [f"SET hnsw.ef_search = {ef}"])
            print(f"{f'HNSW m=16, ef_search={ef}':<44}{recall(got, truth):>10.3f}{ms:>9.1f}{mb:>10.0f}")
        print(f"   (HNSW build took {build:.1f}s)")
        cur.execute("DROP INDEX items_hnsw")

        cur.execute(f"CREATE INDEX items_half ON items USING hnsw ((v::halfvec({DIM})) halfvec_cosine_ops)")
        half_sql = f"SELECT id FROM items ORDER BY v::halfvec({DIM}) <=> %(q)s::halfvec({DIM}) LIMIT {K}"
        got, ms = run(cur, half_sql, queries, ["SET hnsw.ef_search = 40"])
        print(f"{'HNSW on halfvec (16-bit), ef_search=40':<44}{recall(got, truth):>10.3f}{ms:>9.1f}"
              f"{size_mb(cur, 'items_half'):>10.0f}")
        cur.execute("DROP INDEX items_half")

        cur.execute(f"CREATE INDEX items_bin ON items USING hnsw ((binary_quantize(v)::bit({DIM})) bit_hamming_ops)")
        bin_sql = f"""
            SELECT id FROM (
                SELECT id, v FROM items
                ORDER BY binary_quantize(v)::bit({DIM}) <~> binary_quantize(%(q)s)
                LIMIT 100
            ) shortlist ORDER BY v <=> %(q)s LIMIT {K}"""
        got, ms = run(cur, bin_sql, queries, ["SET hnsw.ef_search = 100"])
        print(f"{'binary quantised HNSW + exact re-rank of 100':<44}{recall(got, truth):>10.3f}{ms:>9.1f}"
              f"{size_mb(cur, 'items_bin'):>10.0f}")

        if not args.keep:
            cur.execute("DROP SCHEMA bench CASCADE")


if __name__ == "__main__":
    main()

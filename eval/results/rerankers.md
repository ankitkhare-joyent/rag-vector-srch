# Reranker comparison (hybrid top 20 candidates, reranked on the host CPU)

| model | recall@5 | hit@1 | mrr@10 | ndcg@10 | ms_per_query |
|---|---|---|---|---|---|
| (no reranker: hybrid RRF order) | 0.958 | 0.844 | 0.909 | 0.927 | 0 |
| Xenova/ms-marco-MiniLM-L-6-v2 | 0.958 | 0.875 | 0.921 | 0.934 | 1239 |
| Xenova/ms-marco-MiniLM-L-12-v2 | 0.958 | 0.875 | 0.92 | 0.927 | 2526 |
| jinaai/jina-reranker-v1-turbo-en | 0.99 | 0.938 | 0.959 | 0.957 | 1517 |
| BAAI/bge-reranker-base | 0.99 | 0.906 | 0.953 | 0.957 | 9810 |
| jinaai/jina-reranker-v2-base-multilingual | 0.979 | 0.938 | 0.969 | 0.97 | 15148 |

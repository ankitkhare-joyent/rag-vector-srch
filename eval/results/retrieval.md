# Retrieval eval (32 answerable questions, document-level relevance)

| config | recall@5 | hit@1 | mrr@10 | ndcg@10 | cat:lexical | cat:semantic | cat:multi | p50_ms | p95_ms |
|---|---|---|---|---|---|---|---|---|---|
| dense | 0.958 | 0.875 | 0.927 | 0.934 | 1.0 | 0.944 | 0.917 | 24 | 45 |
| lexical | 0.88 | 0.719 | 0.807 | 0.814 | 1.0 | 0.833 | 0.792 | 8 | 13 |
| hybrid | 0.958 | 0.844 | 0.906 | 0.913 | 1.0 | 0.944 | 0.917 | 38 | 72 |
| dense + rerank | 0.958 | 0.938 | 0.958 | 0.952 | 1.0 | 0.944 | 0.917 | 4766 | 6780 |
| hybrid + rerank | 0.969 | 0.938 | 0.958 | 0.956 | 1.0 | 0.944 | 1.0 | 4157 | 5070 |

`cat:*` columns are recall@5 per question category. Latency is server-side, including embedding and reranking, on the local Docker VM.

## Top-1 misses per config

**dense** (4)

- q03 top1=['RB-011'] want=['POL-SEC-004']
- q07 top1=['GUIDE-024'] want=['PM-2026-05']
- q14 top1=['RB-004'] want=['GUIDE-010']
- q15 top1=['PM-2026-03'] want=['RB-013']

**lexical** (9)

- q01 top1=['RB-001'] want=['RB-020']
- q03 top1=['RB-011'] want=['POL-SEC-004']
- q14 top1=['RB-018'] want=['GUIDE-010']
- q15 top1=['RB-008'] want=['RB-013']
- q16 top1=['RB-021'] want=['RB-012']
- q17 top1=['RB-021'] want=['GUIDE-009']
- q18 top1=['RB-014'] want=['RB-011']
- q20 top1=['RB-002'] want=['RB-025']
- q22 top1=['RB-017'] want=['PM-2026-03']

**hybrid** (5)

- q03 top1=['RB-011'] want=['POL-SEC-004']
- q14 top1=['RB-023'] want=['GUIDE-010']
- q15 top1=['RB-017'] want=['RB-013']
- q17 top1=['RB-014'] want=['GUIDE-009']
- q20 top1=['RB-002'] want=['RB-025']

**dense + rerank** (2)

- q14 top1=['RB-004'] want=['GUIDE-010']
- q19 top1=['RB-004'] want=['GUIDE-024']

**hybrid + rerank** (2)

- q14 top1=['RB-004'] want=['GUIDE-010']
- q19 top1=['RB-004'] want=['GUIDE-024']

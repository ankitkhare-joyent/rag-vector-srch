#!/usr/bin/env bash
# Bring the stack up, wait until the API is ready, run the evals and the ANN benchmark, then stop the
# stack (volumes are kept). Polite to a shared, memory-limited Docker VM.
#
#   scripts/verify.sh                  retrieval eval + ANN bench (free)
#   scripts/verify.sh --answers        also the Claude answer evals (costs API tokens)
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d --wait api mcp
curl -sf localhost:47100/readyz && echo

uv run python -m eval.retrieval
uv run python scripts/ann_bench.py | tee eval/results/ann_bench.txt
if [[ "${1:-}" == "--answers" ]]; then
  uv run python -m eval.answers --mode pipeline
  uv run python -m eval.answers --mode agentic
fi

docker compose stop

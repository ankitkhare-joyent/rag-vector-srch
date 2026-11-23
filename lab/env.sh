# Source this at the start of every lab sitting (bash or zsh), from the repo root:
#
#   source lab/env.sh
#
# It sets variables and defines shell functions. Nothing prints a secret value unless you ask for one, and the
# functions that return one (role_token, bao_field) are meant for $( ... ) only.

export BAO_ADDR="http://localhost:47200"          # this stack's OpenBao (UI at $BAO_ADDR/ui)
export API="http://localhost:47100"               # RAG API (Swagger UI at $API/docs)
export MCP_URL="http://localhost:47101/mcp"       # MCP server

# The bootstrap keeps OpenBao's init output in the bao-init volume, not on your disk. vol_cat reads a file from the
# bootstrap volumes with a throwaway container:  vol_cat init/init.json | jq 'keys'
vol_cat() {
  docker run --rm -v runbook-rag_bao-init:/b/init:ro -v runbook-rag_bao-approle:/b/approle:ro \
    --entrypoint cat runbook-rag/api:dev "/b/$1"
}
# The root token. A local-only shortcut so you can look at everything: in production nobody keeps one (docs/07).
export BAO_TOKEN="$(vol_cat init/init.json 2>/dev/null | jq -r '.root_token // empty')"
[ -n "$BAO_TOKEN" ] || echo "lab/env.sh: no root token yet; run 'mise run up' first" >&2

# OpenBao ---------------------------------------------------------------------------------------------------
# T=$(role_token rag-api)               -> log in with that service's AppRole (rag-api | rag-ingest)
role_token() {
  curl -s "$BAO_ADDR/v1/auth/approle/login" \
    -d "{\"role_id\":\"$(vol_cat "approle/$1/role_id")\",\"secret_id\":\"$(vol_cat "approle/$1/secret_id")\"}" \
    | jq -r '.auth.client_token // empty'
}
# bao_keys rag/anthropic                -> a KV secret's field names and version, never the values
bao_keys() {
  curl -s -H "X-Vault-Token: ${TOKEN:-$BAO_TOKEN}" "$BAO_ADDR/v1/secret/data/$1" \
    | jq -c 'if .errors then {errors} else {fields: (.data.data | keys), version: .data.metadata.version} end'
}
# K=$(bao_field rag/anthropic api_key)  -> one value, for use inside $( ... )
bao_field() {
  curl -s -H "X-Vault-Token: ${TOKEN:-$BAO_TOKEN}" "$BAO_ADDR/v1/secret/data/$1" | jq -r --arg f "$2" '.data.data[$f] // empty'
}

# RAG API ---------------------------------------------------------------------------------------------------
# search "question" [dense|lexical|hybrid] [rerank true|false] [k]   -> one line per hit, best first
search() {
  curl -s "$API/search" -H 'content-type: application/json' \
    -d "$(jq -n --arg q "$1" --arg m "${2:-hybrid}" --argjson r "${3:-true}" --argjson k "${4:-5}" \
          '{query: $q, mode: $m, rerank: $r, k: $k}')" \
  | jq -r '(.hits[] | "\(.chunk_id)\t dense=\(.dense_rank // "-")\t lex=\(.lexical_rank // "-")\t rerank=\(.rerank_score // "-" | tostring | .[0:6])\t \(.section)"), "timings_ms: \(.timings_ms | tostring)"'
}
# ask "question" [pipeline|agentic]     -> the answer, then its citations, tool calls and token usage
ask() {
  curl -s "$API/ask" -H 'content-type: application/json' \
    -d "$(jq -n --arg q "$1" --arg m "${2:-pipeline}" '{question: $q, mode: $m}')" \
  | jq -r '.answer, "", (.citations[] | "[\(.number)] \(.doc_id): \(.cited_text[0:90] | gsub("\n"; " "))…"),
           "", "tool calls: \([.tool_calls[] | "\(.tool) \(.input | tostring)"])",
           "usage: \(.usage | {input_tokens, output_tokens} | tostring)  latency_ms: \(.latency_ms)  stop: \(.stop_reason)"'
}

# Postgres --------------------------------------------------------------------------------------------------
# psql_su "select count(*) from rag.chunks"   -> psql as the superuser (break-glass; the apps never use it)
psql_su() { docker compose exec -T postgres psql -U postgres -d rag -P pager=off -c "$1"; }
# pg_as USER PASSWORD "SQL"             -> psql over the container network, so the password is really checked
pg_as() { docker compose exec -T -e PGPASSWORD="$2" postgres psql -h postgres -U "$1" -d rag -P pager=off -c "$3" 2>&1; }

# Policy for the RAG API. OpenBao is deny-by-default: anything not listed here is refused.

# Read the Anthropic key. KV v2 paths have a /data/ segment; reading metadata or old versions is not granted.
path "secret/data/rag/anthropic" {
  capabilities = ["read"]
}

# Get short-lived, read-only Postgres credentials (a new Postgres role per request).
path "database/creds/rag-reader" {
  capabilities = ["read"]
}

# Renew our own leases. (Token renew-self and lookup-self come from the built-in "default" policy.)
path "sys/leases/renew" {
  capabilities = ["update"]
}

# Check whether our database lease is still alive (it may have been revoked by an operator).
path "sys/leases/lookup" {
  capabilities = ["update"]
}

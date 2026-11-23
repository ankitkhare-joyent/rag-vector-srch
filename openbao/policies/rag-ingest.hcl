# Policy for the ingest job: write access to the vector tables, nothing else. No LLM key.
path "database/creds/rag-writer" {
  capabilities = ["read"]
}

path "sys/leases/renew" {
  capabilities = ["update"]
}

# Check whether our database lease is still alive (it may have been revoked by an operator).
path "sys/leases/lookup" {
  capabilities = ["update"]
}

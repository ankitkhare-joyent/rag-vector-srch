# OpenBao server configuration (production-shaped, single node).
# Differences from production are marked LOCAL.

ui            = true
api_addr      = "http://openbao:8200"
cluster_addr  = "http://openbao:8201"
disable_mlock = true   # raft storage uses mmap; mlock is not recommended with integrated storage

# Integrated storage (Raft): OpenBao keeps its encrypted data itself, no Consul/etcd needed.
# Production: 3 or 5 nodes with retry_join, spread across AZs.
storage "raft" {
  path    = "/openbao/file"
  node_id = "bao-1"
}

# LOCAL: plain HTTP on a private Docker network, published to 127.0.0.1 only.
# Production: TLS everywhere (tls_cert_file / tls_key_file), ideally mTLS for clients.
listener "tcp" {
  address         = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_disable     = true
}

# Auto-unseal. Everything in storage is encrypted with a data key, and that key is encrypted by the
# *seal*. With a Shamir seal, humans must type key shares after every restart. With auto-unseal, a key
# held somewhere else (a cloud KMS, an HSM, or here a key file) unwraps it on boot.
# LOCAL: the static seal reads a 32-byte key from a separate volume, created on first start.
# Production: seal "awskms" { kms_key_id = "..." } (or gcpckms, azurekeyvault, pkcs11, transit).
seal "static" {
  current_key_id = "local-2026-10"
  current_key    = "file:///openbao/seal/unseal.key"
}

# Audit device declared in config (OpenBao does not allow creating audit devices through the API by
# default, so a stolen root token cannot quietly turn auditing off). Every request and response is
# logged with secret values HMAC'd, never in plain text.
audit "file" "stdout" {
  options {
    file_path = "stdout"     # special value: the server's stdout, so `docker compose logs openbao` shows it
    log_raw   = "false"
  }
}

telemetry {
  disable_hostname          = true
  prometheus_retention_time = "1h"
}

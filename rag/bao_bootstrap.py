"""Configure OpenBao for the RAG stack. Idempotent: safe to run on every `docker compose up`.

What it sets up (docs/07 walks through each with the equivalent `bao` CLI command):

    1. init         first run only: initialise OpenBao, keep the root token + recovery key (LOCAL only)
    2. engines      kv-v2 at secret/, database at database/, approle auth at auth/approle/
    3. secret       secret/rag/anthropic  <- ANTHROPIC_API_KEY from .env, if set
    4. database     connection to Postgres as bao_admin, then rotate bao_admin's password so only
                    OpenBao knows it; roles rag-reader (1h) and rag-writer (15m)
    5. policies     rag-api, rag-ingest (from openbao/policies/*.hcl)
    6. approles     rag-api and rag-ingest; writes role_id + a fresh secret_id per service to
                    /bootstrap/approle/<service>/, which compose mounts read-only into that service only

The root token is used here and nowhere else. Production: an operator (or Terraform/OpenTofu with the
Vault provider, which works with OpenBao) applies this configuration, the root token is revoked after
initial setup, and workloads authenticate with platform identity (Kubernetes, AWS IAM, OIDC) instead of
a secret_id file.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx

log = logging.getLogger("bao-bootstrap")

BAO_ADDR = os.environ.get("BAO_ADDR", "http://openbao:8200")
INIT_FILE = Path(os.environ.get("BAO_INIT_FILE", "/bootstrap/init/init.json"))
APPROLE_DIR = Path(os.environ.get("BAO_APPROLE_DIR", "/bootstrap/approle"))
POLICY_DIR = Path(os.environ.get("BAO_POLICY_DIR", "/app/openbao/policies"))
PG_URL = "postgresql://{{username}}:{{password}}@postgres:5432/rag?sslmode=disable"

# Dynamic Postgres users. {{name}}, {{password}} and {{expiration}} are filled in by OpenBao.
# VALID UNTIL makes Postgres itself refuse logins after the lease, even if OpenBao were down.
CREATE_SQL = {
    "rag-reader": ["CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}' "
                   "IN ROLE rag_reader;"],
    "rag-writer": ["CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}' "
                   "IN ROLE rag_writer;"],
}
# On lease expiry or revoke: end the user's sessions, then drop it.
REVOKE_SQL = [
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = '{{name}}';",
    "DROP ROLE IF EXISTS \"{{name}}\";",
]
ROLE_TTLS = {"rag-reader": ("1h", "24h"), "rag-writer": ("15m", "1h")}

APPROLES = {
    # service      policies          token ttl / max ttl
    "rag-api":    (["rag-api"],     "1h", "24h"),
    "rag-ingest": (["rag-ingest"],  "20m", "1h"),
}


class Bao:
    def __init__(self, token: str | None = None):
        self.http = httpx.Client(base_url=BAO_ADDR, timeout=15)
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None, ok=(200, 204)) -> dict:
        r = self.http.request(method, f"/v1/{path}", json=body,
                              headers={"X-Vault-Token": self.token} if self.token else {})
        if r.status_code not in ok:
            sys.exit(f"{method} {path} -> HTTP {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else {}


def wait_for_server(bao: Bao) -> dict:
    for _ in range(60):
        try:
            # 200 active, 429 standby, 501 not initialised, 503 sealed: all mean "the server is up"
            r = bao.http.get("/v1/sys/health")
            if r.status_code in (200, 429, 501, 503):
                return r.json()
        except httpx.TransportError:
            pass
        time.sleep(1)
    sys.exit(f"OpenBao not reachable at {BAO_ADDR}")


def initialise(bao: Bao) -> str:
    health = wait_for_server(bao)
    if not health["initialized"]:
        # With auto-unseal there are no unseal keys, only *recovery* keys (needed for a few operator tasks
        # such as generating a new root token).
        out = bao.call("PUT", "sys/init", {"recovery_shares": 1, "recovery_threshold": 1})
        INIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        INIT_FILE.write_text(json.dumps(out, indent=2))
        INIT_FILE.chmod(0o600)
        log.info("initialised OpenBao; root token and recovery key saved to %s (LOCAL ONLY)", INIT_FILE)
    for _ in range(30):
        if not bao.call("GET", "sys/seal-status")["sealed"]:
            break
        time.sleep(1)
    else:
        sys.exit("OpenBao is still sealed; check the seal stanza in openbao/config.hcl")
    # Unsealed is not yet ready: right after init the node is still becoming the active Raft leader and
    # answers 500 "internal error". /sys/health returns 200 only on an active, unsealed node.
    for _ in range(60):
        if bao.http.get("/v1/sys/health").status_code == 200:
            break
        time.sleep(1)
    return json.loads(INIT_FILE.read_text())["root_token"]


def enable_engines(bao: Bao) -> None:
    mounts = bao.call("GET", "sys/mounts")["data"]
    if "secret/" not in mounts:
        bao.call("POST", "sys/mounts/secret", {"type": "kv", "options": {"version": "2"}})
        log.info("enabled kv-v2 at secret/")
    if "database/" not in mounts:
        bao.call("POST", "sys/mounts/database", {"type": "database"})
        log.info("enabled database secrets engine at database/")
    if "approle/" not in bao.call("GET", "sys/auth")["data"]:
        bao.call("POST", "sys/auth/approle", {"type": "approle"})
        log.info("enabled approle auth at auth/approle/")


def store_anthropic_key(bao: Bao) -> None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        log.warning("ANTHROPIC_API_KEY not set in .env: /ask will return 503 until you add it and re-run")
        return
    current = bao.call("GET", "secret/data/rag/anthropic", ok=(200, 404))
    if current.get("data", {}).get("data", {}).get("api_key") == key:
        log.info("secret/rag/anthropic already up to date (version %s)", current["data"]["metadata"]["version"])
        return
    # check-and-set: cas=0 creates only if absent, cas=N updates only if version N is current
    version = current.get("data", {}).get("metadata", {}).get("version", 0)
    out = bao.call("POST", "secret/data/rag/anthropic", {"options": {"cas": version}, "data": {"api_key": key}})
    log.info("wrote secret/rag/anthropic version %s", out["data"]["version"])


def configure_database(bao: Bao) -> None:
    existing = bao.call("GET", "database/config/rag-pg", ok=(200, 404))
    if not existing.get("data"):
        bao.call("POST", "database/config/rag-pg", {
            "plugin_name": "postgresql-database-plugin",
            "connection_url": PG_URL,
            "username": "bao_admin",
            "password": os.environ["BAO_ADMIN_INITIAL_PASSWORD"],
            "password_authentication": "scram-sha-256",
            "allowed_roles": list(CREATE_SQL),
            "verify_connection": True,
        })
        # From here on only OpenBao knows bao_admin's password; the value in compose.yaml is useless.
        bao.call("POST", "database/rotate-root/rag-pg")
        log.info("configured database/config/rag-pg and rotated bao_admin's password")
    for role, statements in CREATE_SQL.items():
        ttl, max_ttl = ROLE_TTLS[role]
        bao.call("POST", f"database/roles/{role}", {
            "db_name": "rag-pg", "creation_statements": statements, "revocation_statements": REVOKE_SQL,
            "default_ttl": ttl, "max_ttl": max_ttl,
        })
    log.info("database roles: %s", ", ".join(f"{r} (ttl {t[0]})" for r, t in ROLE_TTLS.items()))


def write_policies(bao: Bao) -> None:
    for f in sorted(POLICY_DIR.glob("*.hcl")):
        bao.call("PUT", f"sys/policies/acl/{f.stem}", {"policy": f.read_text()})
    log.info("policies: %s", ", ".join(f.stem for f in sorted(POLICY_DIR.glob("*.hcl"))))


def configure_approles(bao: Bao) -> None:
    for name, (policies, ttl, max_ttl) in APPROLES.items():
        bao.call("POST", f"auth/approle/role/{name}", {
            "token_policies": policies, "token_ttl": ttl, "token_max_ttl": max_ttl,
            "secret_id_ttl": "720h",          # a leaked secret_id stops working after 30 days
            "token_type": "service",
        })
        role_id = bao.call("GET", f"auth/approle/role/{name}/role-id")["data"]["role_id"]
        secret_id = bao.call("POST", f"auth/approle/role/{name}/secret-id",
                             {"metadata": json.dumps({"issued_by": "bao-bootstrap"})})["data"]["secret_id"]
        d = APPROLE_DIR / name
        d.mkdir(parents=True, exist_ok=True)
        for fname, value in (("role_id", role_id), ("secret_id", secret_id)):
            p = d / fname
            p.unlink(missing_ok=True)   # previous run left it read-only
            p.write_text(value)
            p.chmod(0o444)        # read-only; the volume is mounted read-only into exactly one service
    log.info("approles: %s (fresh secret_id written for each)", ", ".join(APPROLES))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    bao = Bao()
    bao.token = initialise(bao)
    enable_engines(bao)
    write_policies(bao)
    store_anthropic_key(bao)
    configure_database(bao)
    configure_approles(bao)
    log.info("OpenBao is configured")


if __name__ == "__main__":
    main()

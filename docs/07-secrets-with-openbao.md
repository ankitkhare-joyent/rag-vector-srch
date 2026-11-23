# 07. Secrets with OpenBao

A RAG service holds two kinds of secret: credentials for its vector database, and an API key for the
model provider. The usual way to handle them is an environment variable set from a file, which means the
same long-lived password sits in a dozen places (laptops, CI, container specs, shell history) and is
rarely rotated because rotating it means touching all of them. A secrets manager fixes that, and this
lesson shows how OpenBao does it in this stack.

## Why OpenBao and not HashiCorp Vault

It is the same story as OpenTofu and Terraform, which you already know.

* In August 2023 HashiCorp moved its products, Vault and Terraform included, from the open source Mozilla
  Public License 2.0 to the Business Source License 1.1. Vault 1.14 was the last MPL release; 1.15
  (September 2023) and later are BUSL. IBM completed its acquisition of HashiCorp in 2025.
* The BUSL lets you use Vault internally, but forbids offering anything that competes with HashiCorp, and
  the terms are HashiCorp's to interpret and change. Many companies' legal teams treat that as a risk;
  some Linux distributions and cloud vendors stopped shipping Vault.
* **OpenBao** forked Vault's last MPL code (1.14) in late 2023 under the Linux Foundation, shipped 2.0 in
  July 2024, and moved to the OpenSSF (the Linux Foundation's security foundation) in June 2025. It stays
  MPL 2.0 with open governance, so no single company can relicense it.
* It is API-compatible for everything this course uses: the same HTTP paths, the same `X-Vault-Token`
  header, the same policy language, and the Vault Terraform/OpenTofu provider and most client libraries
  (hvac, the Vault Agent pattern) work against it. The CLI is called `bao` instead of `vault`.
* It has diverged usefully since: **namespaces** (multi-tenancy, a paid Vault Enterprise feature) are in
  OpenBao since 2.3; audit devices are declared in the server config and cannot be created through the
  API by default, so a stolen admin token cannot quietly switch auditing off; a **static seal** for
  auto-unseal without a cloud KMS; KMS plugins in 2.6.

When to still pick Vault: you already run Vault Enterprise and need features OpenBao lacks (for example
performance replication across regions, or HashiCorp support contracts), or you want HCP Vault as a
managed service. For new self-managed deployments OpenBao is the default open source choice, and AWS
Secrets Manager / GCP Secret Manager remain reasonable if you only need static secrets in one cloud.

## How OpenBao works, in five ideas

### 1. Everything is encrypted, and the server starts *sealed*

OpenBao stores all data encrypted with an internal data key. That key is itself encrypted by the **seal**.
When the server starts it cannot read its own storage until it is **unsealed**:

* **Shamir seal** (the default): the master key is split into, say, 5 key shares held by 5 people; any 3
  must type theirs in after every restart. Secure, operationally painful.
* **Auto-unseal**: the master key is encrypted by an external key the server can call on boot: AWS KMS,
  GCP KMS, Azure Key Vault, an HSM, or another OpenBao's transit engine. Restarts need no humans. With
  auto-unseal, initialisation produces *recovery keys* instead of unseal keys.

This stack uses the **static seal**: a 32-byte key in a separate Docker volume (`bao-seal`) stands in
for a cloud KMS key. See [`openbao/config.hcl`](../openbao/config.hcl). Never put that key next to the data in production; the
whole point is that stealing the disk is not enough.

Storage is **Raft** (integrated storage): OpenBao replicates its own data between 3 or 5 nodes, no
Consul or etcd needed. We run one node.

### 2. Clients authenticate and get a *token*; policies decide what a token may do

Nothing talks to OpenBao without a token. You get one from an **auth method** that checks some identity
you already have:

| Auth method | Who uses it |
|---|---|
| `kubernetes` | Pods: OpenBao verifies the pod's service account token with the Kubernetes API |
| `aws` (IAM) | EC2 instances, Lambda, ECS tasks: OpenBao verifies a signed AWS STS request |
| `jwt` / `oidc` | CI (GitHub Actions OIDC tokens), humans via SSO |
| `approle` | Machines with no platform identity: a `role_id` (like a username) plus a `secret_id` (like a password) |
| `userpass`, `token` | Testing |

Every token carries **policies**. Policies are deny-by-default path rules, for example
[`openbao/policies/rag-api.hcl`](../openbao/policies/rag-api.hcl):

```hcl
path "secret/data/rag/anthropic" { capabilities = ["read"] }
path "database/creds/rag-reader" { capabilities = ["read"] }
```

The API container can read the Anthropic key and get read-only database users. It cannot write
anything, cannot get writer credentials, and cannot read any other secret. The ingest job has the
opposite: writer credentials and no LLM key (`rag-ingest.hcl`).

Tokens have a TTL. Our API token lives 1 hour and can be renewed up to 24 hours; then the app logs in
again ([`rag/bao.py`](../rag/bao.py), `BaoClient.token()`).

We use **AppRole** because Docker Compose has no workload identity. The bootstrap writes each service's
`role_id` and `secret_id` into a volume, and compose mounts only that service's subfolder, read-only
(`volume.subpath` in [`compose.yaml`](../compose.yaml)). On Kubernetes or EKS you would use the `kubernetes` auth method
instead and there would be no secret file at all: the platform identity *is* the credential.

### 3. Secrets engines: static (KV) and dynamic

* **KV v2** stores static secrets with versioning: `secret/rag/anthropic` holds the Anthropic key.
  Note the API path has an extra `/data/` segment (`secret/data/rag/anthropic`); policies use that path.
  Writes use check-and-set (`cas`) so two writers cannot silently overwrite each other.
* **Database engine** creates *dynamic* credentials. When the API asks for `database/creds/rag-reader`,
  OpenBao connects to Postgres as its own admin user and runs:

  ```sql
  CREATE ROLE "v-approle-rag-read-AbC123-1791100628" WITH LOGIN PASSWORD '<random>'
      VALID UNTIL '<now + 1h>' IN ROLE rag_reader;
  ```

  The app gets a brand-new username and password valid for one hour. When the lease ends (or is revoked),
  OpenBao terminates that user's sessions and drops the role. Nobody else ever had this password, it is
  in no file, and if it leaks it dies on its own within the hour.

The engine's own admin account (`bao_admin`) starts with a password from [`compose.yaml`](../compose.yaml), and the
bootstrap immediately calls `database/rotate-root/rag-pg`: OpenBao changes the password to a random one
only it knows. The value in [`compose.yaml`](../compose.yaml) is now useless.

Other engines worth knowing: **PKI** (issue short-lived TLS certificates), **transit** (encryption as a
service: the app sends plaintext, gets ciphertext, never sees the key), **AWS** (dynamic IAM credentials),
**SSH** (signed SSH certificates).

### 4. Leases: everything dynamic expires

Every dynamic secret and every token comes with a **lease**: a TTL, renewable up to a max TTL. Clients
renew or fetch fresh credentials before expiry. Expiry is the safety net: a forgotten credential cleans
itself up.

How the app handles it ([`rag/bao.py`](../rag/bao.py) and [`rag/db.py`](../rag/db.py)):

```
DbCredentialProvider.current()     fetch new creds when 2/3 of the lease has passed, or when
                                   sys/leases/lookup says the lease was revoked
psycopg_pool kwargs=callable       every NEW connection asks the provider for current creds
pool check=check_connection        a connection the server killed is discarded, not handed out
pool max_lifetime = lease / 2      every connection is recycled long before its user is dropped
ingest: revoke-self at exit        revoking the job's token drops its writer user immediately
```

[Lab 02](../lab/02-dynamic-db-credentials.md) revokes the API's credentials and stops OpenBao while you watch.

So credentials rotate continuously with no restarts and no shared password. You can watch it:
`GET /readyz` returns the current dynamic database user, and the Postgres log shows OpenBao creating and
dropping users.

### 5. Audit everything

Every request and response goes to the **audit device** (`audit "file"` in `config.hcl`, here written to
the container's stdout). Secret values are HMAC'd, not logged in plain text, but you can still prove
"this token read this secret at this time". `docker compose logs openbao | grep rag/anthropic` shows each
read of the Anthropic key.

## Walkthrough: what `bao-bootstrap` does

[`rag/bao_bootstrap.py`](../rag/bao_bootstrap.py) uses the HTTP API directly so every call is visible. The equivalent CLI, which you
can run yourself inside the container (`docker compose exec openbao sh`, then `export BAO_ADDR=http://127.0.0.1:8200 BAO_TOKEN=<root token>`):

```bash
bao operator init -recovery-shares=1 -recovery-threshold=1      # once; auto-unseal does the rest
bao secrets enable -path=secret kv-v2
bao secrets enable database
bao auth enable approle
bao policy write rag-api /path/to/rag-api.hcl
bao kv put -cas=0 secret/rag/anthropic api_key=...              # cas=0: create only if absent

bao write database/config/rag-pg plugin_name=postgresql-database-plugin \
    connection_url='postgresql://{{username}}:{{password}}@postgres:5432/rag' \
    username=bao_admin password=bao-admin-initial allowed_roles=rag-reader,rag-writer
bao write -f database/rotate-root/rag-pg
bao write database/roles/rag-reader db_name=rag-pg default_ttl=1h max_ttl=24h \
    creation_statements=@create-reader.sql revocation_statements=@revoke.sql

bao write auth/approle/role/rag-api token_policies=rag-api token_ttl=1h token_max_ttl=24h secret_id_ttl=720h
bao read  auth/approle/role/rag-api/role-id
bao write -f auth/approle/role/rag-api/secret-id
```

And what the API does at runtime:

```bash
bao write auth/approle/login role_id=... secret_id=...     # -> token with policy rag-api
bao kv get secret/rag/anthropic                             # -> the key
bao read database/creds/rag-reader                          # -> fresh Postgres user, 1h lease
```

## Try it

```bash
# the root token (LOCAL ONLY: in production you revoke it after setup)
docker compose run --rm --entrypoint cat bao-bootstrap /bootstrap/init/init.json

# UI: http://localhost:47200/ui, sign in with the root token, look at Secrets and Access
# Who is connected to Postgres right now? Every app user is a temporary OpenBao user:
docker compose exec postgres psql -U postgres -d rag -c "select usename, application_name from pg_stat_activity where datname='rag'"

# Revoke all reader credentials at once (incident response): the API reconnects with new ones
docker compose exec -e BAO_TOKEN=<root> openbao bao lease revoke -prefix database/creds/rag-reader
```

## Production differences

| Here (local) | Production |
|---|---|
| Static seal key in a Docker volume | Cloud KMS or HSM auto-unseal |
| One node, HTTP | 3 or 5 Raft nodes across AZs, TLS everywhere |
| Root token kept in a volume | Root token revoked after setup; `bao operator generate-root` with recovery keys in an emergency |
| AppRole `secret_id` file per service | Kubernetes / AWS IAM / OIDC auth: no secret to deliver |
| Config applied by a Python script | Terraform or OpenTofu with the Vault provider (works with OpenBao), reviewed in Git |
| App calls the API itself | Same, or OpenBao Agent / the CSI driver / External Secrets Operator rendering secrets for apps that can't |
| Anthropic key in KV, rotated by hand | Same, plus a rotation runbook; or Workload Identity Federation to the Claude API so there is no key at all |

---

← [06-agentic-retrieval-and-mcp](06-agentic-retrieval-and-mcp.md) · [Index](../README.md) · [08-production-checklist](08-production-checklist.md) →

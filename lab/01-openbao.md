# Lab 01 · OpenBao: auto-unseal, policies and the audit log

One sitting, about 30 minutes. Background: [docs/07](../docs/07-secrets-with-openbao.md). Code:
[openbao/config.hcl](../openbao/config.hcl), [openbao/policies/](../openbao/policies),
[rag/bao_bootstrap.py](../rag/bao_bootstrap.py).

OpenBao comes first because everything else boots from it: the ingest job's and the API's database logins, and the
API's Anthropic key. After this lab you can explain:

- what "sealed" means, and why this stack never needs a human to unseal it
- what the bootstrap created, and how to find out what a token may do without reading code
- that a policy change applies to tokens that already exist
- what the audit log records about a secret it never writes down

Answers to every **Predict** are at the bottom. Write your guess down before you run the command.

## Before you start

```bash
cd ~/workstuff/argocd-terraform-opentofu/rag-vector-srch
source lab/env.sh
bao version          # OpenBao v2.5.4, same as the server
```

`lab/env.sh` sets `BAO_ADDR` to this stack's OpenBao (port 47200) and `BAO_TOKEN` to the root token, read from the
`bao-init` Docker volume. That's a local shortcut so you can look at everything; in production nobody keeps one.

## 1. Is it open, and who opened it?

**Predict (P1):** most OpenBao setups use Shamir key shares that someone types in after every
restart. This one has a `seal "static"` block in `config.hcl`. What will `seal-status` say about the seal type, and
how many unseal keys will `init.json` hold?

```bash
curl -s $BAO_ADDR/v1/sys/health | jq -c '{initialized, sealed, version}'
curl -s $BAO_ADDR/v1/sys/seal-status | jq -c '{type, recovery_seal, t, n, storage_type}'
vol_cat init/init.json | jq -c '{fields: keys, unseal_keys: (.keys | length), recovery_keys: (.recovery_keys | length)}'
```

These two endpoints need no token: health checks and load balancers call them.

## 2. What did the bootstrap build?

**Predict (P2):** name the secrets engines, auth methods and audit devices before you look. (Hint:
[docs/07](../docs/07-secrets-with-openbao.md) has the five ideas.)

```bash
bao token lookup -format=json | jq -c '.data | {display_name, policies, ttl, expire_time}'
bao secrets list
bao auth list
bao audit list -detailed
```

## 3. Least privilege, seen from outside

Each service logs in with its own AppRole. Log in as both and ask what they may do.

**Predict (P3):** which of the two can read the Anthropic key? Which can get reader credentials, and which writer
credentials?

```bash
for r in rag-api rag-ingest; do
  T=$(role_token $r)
  printf '%-11s KV: ' $r; TOKEN=$T bao_keys rag/anthropic
  printf '            reader: %s  writer: %s\n' \
    "$(BAO_TOKEN=$T bao token capabilities database/creds/rag-reader)" \
    "$(BAO_TOKEN=$T bao token capabilities database/creds/rag-writer)"
done
T=$(role_token rag-api)
BAO_TOKEN=$T bao token lookup -format=json | jq -c '.data | {display_name, policies, ttl, meta, renewable}'
bao read -format=json auth/approle/role/rag-api | jq -c '.data | {token_policies, token_ttl, token_max_ttl, secret_id_ttl}'
```

`bao token capabilities` answers "what can this token do on that path" without you reading a single policy file.

## 4. The audit log

Every request and response is logged to OpenBao's stdout (`audit "file"` in `config.hcl`, `file_path = "stdout"`).

**Predict (P4):** you just read `secret/rag/anthropic` as `rag-api`. Will the audit log contain the key?

```bash
docker compose logs --no-log-prefix openbao | grep '^{' | jq -c 'select(.type=="response" and
  .request.path=="secret/data/rag/anthropic") | {time, who: .auth.display_name, policies: .auth.policies,
  api_key: .response.data.data.api_key}' | tail -1
docker compose logs --no-log-prefix openbao | grep '^{' | jq -r 'select(.type=="request") | .request.path' \
  | sort | uniq -c | sort -rn | head -6
```

## Break it, then fix it

**Break 1: restart OpenBao.** With Shamir, a restart means OpenBao is sealed until people type in their shares, and
nothing can log in until then.

**Predict (P5):** what will `/sys/health` say 3 seconds after a restart here, and does the API notice?

```bash
docker compose restart openbao && sleep 3
curl -s $BAO_ADDR/v1/sys/health | jq -c '{sealed}'
docker compose logs --no-log-prefix --since 30s openbao | grep -v '^{' | grep -E 'sealed|unsealed|stored unseal'
curl -s $API/readyz | jq -c .
```

**Break 2: take a permission away from a token that is already logged in.** Policies are not copied into the token;
the token only carries their names.

**Predict (P6):** you overwrite the `rag-api` policy so it no longer mentions the Anthropic key. A token issued
*before* the change still has 59 minutes left. Can it still read the key?

```bash
T=$(role_token rag-api)
bao policy read rag-api | grep -v '^#' | grep -v '^$'
bao policy write rag-api - <<'EOF'
path "database/creds/rag-reader" { capabilities = ["read"] }
EOF
printf 'same token, new policy: '; TOKEN=$T bao_keys rag/anthropic
```

**Fix:** the bootstrap is idempotent and rewrites every policy from `openbao/policies/*.hcl`.

```bash
mise run bootstrap
printf 'after bootstrap: '; TOKEN=$T bao_keys rag/anthropic
```

## Check your predictions

**P1.** `{"initialized":true,"sealed":false,"version":"2.5.4"}` and
`{"type":"static","recovery_seal":true,"t":1,"n":1,"storage_type":"raft"}`. `init.json` has `unseal_keys: 0` and
`recovery_keys: 1`. With auto-unseal there are no unseal keys at all: the root key is encrypted by the static key
(here a file in the `bao-seal` volume; in production an AWS KMS key or an HSM), and OpenBao decrypts it on boot by
itself. `t`/`n` now describe the *recovery* key, which you need only for a few operator tasks such as
`bao operator generate-root`.

**P2.** The root token: `policies: ["root"]`, `ttl: 0`, `expire_time: null`, it never expires. Secrets engines:
`secret/` (kv), `database/`, plus the built-ins `cubbyhole/`, `identity/`, `sys/`. Auth methods: `approle/` plus the
built-in `token/`. One audit device, `stdout/`, type `file`, options `log_raw=false file_path=stdout`. It was
declared in `config.hcl`, not created over the API: OpenBao refuses API-created audit devices by default, so a stolen
root token can't quietly switch auditing off.

**P3.**

```
rag-api     KV: {"fields":["api_key"],"version":1}
            reader: read  writer: deny
rag-ingest  KV: {"errors":["1 error occurred:\n\t* permission denied\n\n"]}
            reader: deny  writer: read
```

The API can read the key and get read-only users; the ingest job can only get writer users. The API's token:
`policies: ["default","rag-api"]`, `ttl: 3599`, `meta: {"issued_by":"bao-bootstrap","role_name":"rag-api"}`,
`renewable: true`. The role: `token_ttl 3600`, `token_max_ttl 86400` (renewable to 24 h, then log in again),
`secret_id_ttl 2592000` (a leaked secret_id stops working after 30 days).

**P4.** No. The value is HMAC'd:

```
{"time":"…","who":"approle","policies":["default","rag-api"],"api_key":"hmac-sha256:1b536009ce99…"}
```

The same value always gives the same HMAC, so you can tell that two requests read the same key, or check a suspected
leaked key with `bao write sys/audit-hash/stdout input=…`, without the log holding it. On a fresh stack the busiest
paths are `auth/approle/login`, `secret/data/rag/anthropic`, `sys/capabilities-self`, `sys/mounts` and
`sys/leases/lookup` (that last one is the API checking its database lease; Lab 02).

**P5.** `{"sealed":false}`. The log shows the restart and the unseal half a second apart:

```
…18:10:41.245Z [INFO]  core: vault is sealed
…18:10:41.789Z [INFO]  core: stored unseal keys supported, attempting fetch
…18:10:41.791Z [INFO]  core: vault is unsealed
```

(OpenBao kept Vault's log strings.) The API doesn't notice at all: `/readyz` is ready, with the same database user,
because the API holds a token and a pooled connection, and neither needs OpenBao until it expires or breaks.

**P6.** No: `{"errors":["1 error occurred:\n\t* permission denied\n\n"]}`. A token carries policy *names*; OpenBao
evaluates the policy text on every request. So tightening a policy takes effect immediately for every token, which
is what you want during an incident. After `mise run bootstrap` the same token reads the key again
(`{"fields":["api_key"],"version":1}`). The bootstrap also minted fresh secret_ids; the old ones stay valid until
their 30-day TTL, which is one reason production uses platform identity (Kubernetes, AWS IAM) instead of AppRole files.

## What to remember

- Auto-unseal moves the "who can open OpenBao" problem to whoever controls the KMS key. Restarts need no humans.
- `bao token capabilities` and `bao token lookup` tell you what a token may do, from the outside.
- Policies are evaluated per request: a change applies to every live token at once.
- The audit log proves who read what, without containing the secret.

Next: [Lab 02 · Dynamic Postgres users](02-dynamic-db-credentials.md).

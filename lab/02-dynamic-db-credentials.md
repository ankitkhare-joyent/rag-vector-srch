# Lab 02 · Dynamic Postgres users: one-hour logins, revocation and rotation

One sitting, about 35 minutes. Background: [docs/07](../docs/07-secrets-with-openbao.md) (ideas 3 and 4). Code:
[rag/bao.py](../rag/bao.py) (`DbCredentialProvider`), [rag/db.py](../rag/db.py),
[rag/bao_bootstrap.py](../rag/bao_bootstrap.py) (`CREATE_SQL`, `REVOKE_SQL`), [sql/001_schema.sql](../sql/001_schema.sql).

No service in this stack has a database password in its configuration. Each one asks OpenBao, and OpenBao creates
a brand-new Postgres user for it. After this lab you can explain:

- what OpenBao actually runs in Postgres, and what `VALID UNTIL` adds
- why the reader user can't delete anything, and who owns the tables
- what "rotate root" means for OpenBao's own admin account
- what the API does when an operator revokes its credentials, and what happens when OpenBao is down

## Before you start

```bash
source lab/env.sh
curl -s $API/readyz | jq -c .
```

## 1. Who is logged in to Postgres right now?

**Predict (P1):** the stack has been up for a few minutes. The ingest job ran once and exited; the API is running.
How many `v-…` users exist, and which of the group roles can log in?

```bash
psql_su "select rolname, rolcanlogin, rolvaliduntil from pg_roles
         where rolname like 'v-%' or rolname like 'rag_%' or rolname = 'bao_admin' order by 1"
psql_su "select usename, application_name, client_addr from pg_stat_activity where datname = 'rag' and usename <> 'postgres'"
```

## 2. Ask for a user yourself

Do what the API does at startup: log in as `rag-api` and read `database/creds/rag-reader`.

**Predict (P2):** what lease duration will you get, and what is the new user a member of?

```bash
T=$(role_token rag-api)
C=$(curl -s -H "X-Vault-Token: $T" $BAO_ADDR/v1/database/creds/rag-reader)
jq -c '{lease_id, lease_duration, renewable, username: .data.username}' <<<"$C"
U=$(jq -r .data.username <<<"$C"); P=$(jq -r .data.password <<<"$C"); L=$(jq -r .lease_id <<<"$C")
psql_su "select rolname, rolvaliduntil,
         (select string_agg(b.rolname, ',') from pg_auth_members m join pg_roles b on b.oid = m.roleid
          where m.member = r.oid) as member_of
         from pg_roles r where rolname = '$U'"
```

**Predict (P3):** you log in as that user over the network. Can it count chunks? Can it delete one?

```bash
pg_as "$U" "$P" "select current_user, count(*) from rag.chunks"
pg_as "$U" "$P" "delete from rag.chunks where doc_id = 'RB-001'"
```

**Predict (P4):** OpenBao logs in to Postgres as `bao_admin` to create these users. `compose.yaml` sets its
password to `bao-admin-initial`. Can you log in with that?

```bash
pg_as bao_admin bao-admin-initial "select 1"
```

## 3. Revoke one lease

**Predict (P5):** you revoke the lease you were given. What happens to the Postgres user?

```bash
bao lease revoke "$L"
pg_as "$U" "$P" "select 1"
psql_su "select count(*) from pg_roles where rolname = '$U'"
```

## Break it, then fix it

**Break 1: revoke every reader lease while the API is using one.** This is the incident-response move: "we think
the reader password leaked, kill them all".

**Predict (P6):** right after the revoke, the API's pooled connection is gone and its user is dropped. Will the next
three `/readyz` calls fail?

```bash
curl -s $API/readyz | jq -c .
bao lease revoke -prefix database/creds/rag-reader
psql_su "select count(*) as reader_users from pg_roles where rolname like 'v-approle-rag-read%'"
for i in 1 2 3; do curl -s -o /dev/null -w "readyz %{http_code}\n" $API/readyz; done
curl -s $API/readyz | jq -c .
docker compose logs --no-log-prefix --since 1m api | grep -E 'rag\.(bao|db)'
```

Read `DbCredentialProvider.current()` in [rag/bao.py](../rag/bao.py) and the `check=` argument in
[rag/db.py](../rag/db.py) to see why.

**Break 2: OpenBao goes away.** Stop OpenBao, then kill the API's database connections so it needs a new one.

**Predict (P7):** with OpenBao stopped, does `/readyz` work (a) before the kill, (b) after it?

```bash
docker compose stop openbao
curl -s -o /dev/null -w "(a) readyz %{http_code}\n" $API/readyz
psql_su "select count(pg_terminate_backend(pid)) as killed from pg_stat_activity where usename like 'v-approle-rag-read%'"
curl -s -w "\n(b) readyz %{http_code}\n" $API/readyz | tail -2       # takes 30 s
docker compose logs --no-log-prefix --since 1m api | grep -E 'psycopg.pool|PoolTimeout' | cut -c1-150 | tail -2
```

**Fix:** start OpenBao. It auto-unseals (Lab 01) and the API recovers by itself.

```bash
docker compose start openbao && sleep 4
curl -s -w "\nreadyz %{http_code}\n" $API/readyz | tail -2
```

## Check your predictions

**P1.** On a fresh stack, exactly one `v-…` user: the API's reader, valid until one hour after it was created.

```
 bao_admin                                          | t | 
 rag_owner                                          | f | 
 rag_reader                                         | f | 
 rag_writer                                         | f | 
 v-approle-rag-read-2PpXmjqvy6u1N9dqhfQS-1792952591 | t | 2026-10-25 19:23:11+00
```

The ingest job's writer user is gone: when the job finishes it revokes its own OpenBao token
(`bao.revoke_self()` in [rag/ingest.py](../rag/ingest.py)), and revoking a token revokes every lease it created.
Without that, the writer user would hang around until its 15-minute lease ran out. `rag_owner`, `rag_reader` and
`rag_writer` are group roles (`rolcanlogin = f`): nobody logs in as them; they only hold privileges. The one
connection in `pg_stat_activity` is the API (`application_name = rag`).

**P2.** `lease_duration: 3600`, `renewable: true`, a username like `v-approle-rag-read-xFBi0dF15gru3OuZQjLk-1792951882`
(auth method, role, random part, Unix time), `rolvaliduntil` one hour out, `member_of: rag_reader`. OpenBao ran the
`CREATE ROLE … WITH LOGIN PASSWORD '…' VALID UNTIL '…' IN ROLE rag_reader` statement from the bootstrap. `VALID
UNTIL` is a second lock: Postgres itself refuses that password after the hour, even if OpenBao were down and never
ran the revocation.

**P3.** Count: yes, `118`. Delete: `ERROR:  permission denied for table chunks`. The tables belong to `rag_owner`,
`rag_reader` has `SELECT` only, and the dynamic user only inherits `rag_reader`.

**P4.** No: `FATAL:  password authentication failed for user "bao_admin"`. Right after configuring the connection,
the bootstrap called `database/rotate-root/rag-pg`, and OpenBao changed `bao_admin`'s password to a random one only
it knows. The value in `compose.yaml` is now useless, and no human can log in as the account that can create users.

**P5.** `All revocation operations queued successfully!`, then `FATAL: password authentication failed` for that
user, and `count = 0`: OpenBao ran the revocation statements (end the user's sessions, `DROP ROLE`).

**P6.** No failure: three `readyz 200`, and the user has changed:

```
readyz 200
readyz 200
readyz 200
{"status":"ready","db_user":"v-approle-rag-read-ID8HSaFfH7x0Xxah6oEB-1792951901","chunks":118}
… WARNING rag.bao lease NJXbWBZ8ymqpp5QaPjhzIG2r is no longer valid (HTTP 400); fetching new credentials
… INFO rag.bao got dynamic Postgres user v-approle-rag-read-ID8HSaFfH7x0Xxah6oEB-1792951901 (lease 3600s)
```

Two pieces make this work. The pool runs `check_connection` before handing out a connection, so the killed
connection is discarded instead of failing a request. And the pool asks `DbCredentialProvider.current()` for
credentials every time it opens a *new* connection; that method calls `sys/leases/lookup` and fetches new credentials
when the lease is gone. Without that lookup, the app would keep presenting the revoked user's password until two
thirds of the lease had passed: up to 40 minutes of outage after a routine security action. (That's the version this
repo shipped first; the lab found it.)

**P7.** (a) `200`: the pooled connection is still open and needs nothing from OpenBao. (b) `500` after 30 seconds:

```
… WARNING psycopg.pool error connecting in 'pool-1': [Errno -2] Name or service not known
psycopg_pool.PoolTimeout: couldn't get a connection after 30.00 sec
```

The new connection needed a lease check (and credentials), OpenBao's hostname didn't resolve, and the pool gave up
after its 30-second timeout. Once OpenBao is back, `/readyz` is `200` again with no restart. So OpenBao is on the
critical path for *new* connections, not for running queries. Production answers: run OpenBao with 3 or 5 nodes,
keep the pool's minimum size above zero, and alert on OpenBao health rather than on application errors.

## What to remember

- A dynamic credential is a real database user that exists for one lease. Nobody else ever knew its password.
- `VALID UNTIL` makes Postgres enforce the expiry too. Group roles hold the privileges; users only inherit them.
- Rotate-root means even the account that creates users has a password no human knows.
- Revocation is safe only if the app re-checks its lease when it reconnects. Test it before you need it.

Next: [Lab 03 · Corpus, chunking and ingest](03-corpus-and-ingest.md).

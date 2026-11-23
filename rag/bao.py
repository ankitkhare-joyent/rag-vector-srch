"""A small OpenBao client: AppRole login, token renewal, KV v2 reads, dynamic database credentials.

Written against the HTTP API with httpx (rather than hvac) so every call is visible: this is the
whole contract between an application and OpenBao. The same calls work against HashiCorp Vault.

Lifecycle of one process:
    1. read role_id + secret_id from files      (delivered by the platform, never baked into images)
    2. POST auth/approle/login                   -> a short-lived *token* with the rag-api policy
    3. use the token to read secrets              -> KV value, or dynamic DB credentials with a *lease*
    4. renew the token and leases before they expire; log in again if renewal is refused
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import httpx

from rag.settings import Settings

log = logging.getLogger("rag.bao")


class BaoError(RuntimeError):
    pass


@dataclass
class DbCreds:
    username: str
    password: str
    lease_id: str
    issued_at: float       # time.monotonic() when issued
    ttl: float             # seconds until OpenBao revokes this Postgres role

    def age_fraction(self) -> float:
        return (time.monotonic() - self.issued_at) / self.ttl


class BaoClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._http = httpx.Client(base_url=settings.bao_addr, timeout=10)
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_renewable = False

    # ------------------------------------------------------------------ auth
    def _login(self) -> None:
        d = self.s.bao_approle_dir
        try:
            role_id = (d / "role_id").read_text().strip()
            secret_id = (d / "secret_id").read_text().strip()
        except FileNotFoundError as e:
            raise BaoError(f"AppRole credentials missing in {d}; did bao-bootstrap run?") from e
        r = self._http.post("/v1/auth/approle/login", json={"role_id": role_id, "secret_id": secret_id})
        self._raise_for(r, "AppRole login")
        auth = r.json()["auth"]
        self._token = auth["client_token"]
        self._token_expires_at = time.monotonic() + auth["lease_duration"]
        self._token_renewable = auth["renewable"]
        log.info("logged in to OpenBao with AppRole, policies=%s ttl=%ss", auth["token_policies"],
                 auth["lease_duration"])

    def token(self) -> str:
        """A valid token, renewing it at two thirds of its TTL and logging in again when needed."""
        with self._lock:
            remaining = self._token_expires_at - time.monotonic()
            if self._token and remaining > 60:
                return self._token
            if self._token and self._token_renewable and remaining > 5:
                r = self._http.post("/v1/auth/token/renew-self", headers={"X-Vault-Token": self._token})
                if r.status_code == 200:
                    auth = r.json()["auth"]
                    self._token_expires_at = time.monotonic() + auth["lease_duration"]
                    # A token cannot outlive its max TTL: when renewal returns a short TTL, log in again.
                    if auth["lease_duration"] > 60:
                        return self._token
            self._login()
            return self._token  # type: ignore[return-value]

    def _get(self, path: str) -> dict:
        r = self._http.get(f"/v1/{path}", headers={"X-Vault-Token": self.token()})
        self._raise_for(r, f"GET {path}")
        return r.json()

    @staticmethod
    def _raise_for(r: httpx.Response, what: str) -> None:
        if r.status_code >= 400:
            # OpenBao error bodies are {"errors": [...]} and never contain secret values.
            raise BaoError(f"{what} failed: HTTP {r.status_code} {r.text[:300]}")

    # ------------------------------------------------------------------ secrets engines
    def kv_get(self, path: str) -> dict:
        """Read the latest version of a KV v2 secret. Note the /data/ segment KV v2 inserts in the path."""
        return self._get(f"{self.s.bao_kv_mount}/data/{path}")["data"]["data"]

    def revoke_self(self) -> None:
        """Revoke our token, and with it every lease it created (here: our dynamic Postgres user).
        For short jobs: the user disappears when the job ends instead of when its lease runs out."""
        if self._token:
            self._http.post("/v1/auth/token/revoke-self", headers={"X-Vault-Token": self._token})
            log.info("revoked our OpenBao token and its leases")
            self._token = None

    def lease_alive(self, lease_id: str) -> bool:
        """sys/leases/lookup answers 400 for a lease that was revoked or has expired."""
        r = self._http.put("/v1/sys/leases/lookup", json={"lease_id": lease_id},
                           headers={"X-Vault-Token": self.token()})
        if r.status_code != 200:
            log.warning("lease %s is no longer valid (HTTP %s); fetching new credentials",
                        lease_id.rsplit("/", 1)[-1], r.status_code)
        return r.status_code == 200

    def db_creds(self, role: str) -> DbCreds:
        """Ask the database secrets engine to CREATE a brand-new Postgres role for us, valid for one lease."""
        body = self._get(f"{self.s.bao_db_mount}/creds/{role}")
        log.info("got dynamic Postgres user %s (lease %ss)", body["data"]["username"], body["lease_duration"])
        return DbCreds(body["data"]["username"], body["data"]["password"], body["lease_id"],
                       time.monotonic(), float(body["lease_duration"]))


class DbCredentialProvider:
    """Hands out current dynamic DB credentials; fetches a fresh pair when the lease is two thirds used.

    psycopg_pool calls this every time it opens a new connection (see rag.db), and the pool recycles
    connections well before a lease ends, so rotation needs no restarts and no shared password.
    """

    def __init__(self, bao: BaoClient, role: str):
        self.bao, self.role = bao, role
        self._creds: DbCreds | None = None
        self._lock = threading.Lock()

    def current(self) -> DbCreds:
        """Called for every NEW physical connection (rare: the pool reuses connections), so it can afford
        to ask OpenBao whether the lease is still alive. Without that check, an operator revoking the
        lease (incident response) would leave the app retrying a dropped Postgres user until 2/3 TTL."""
        with self._lock:
            c = self._creds
            if c is None or c.age_fraction() > 2 / 3 or not self.bao.lease_alive(c.lease_id):
                self._creds = self.bao.db_creds(self.role)
            return self._creds

    def lease_seconds(self) -> float:
        return self.current().ttl

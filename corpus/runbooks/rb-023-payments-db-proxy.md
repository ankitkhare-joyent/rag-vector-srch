---
id: RB-023
title: payments-db-proxy failover
doc_type: runbook
team: payments
services: [payments-db-proxy]
updated: 2026-09-02
---
# payments-db-proxy failover

`payments-db-proxy` is a set of PgBouncer instances (`r6i.large`, 8 per region) in front of the payments PostgreSQL cluster. Clients connect through a Network Load Balancer on port 6432. The proxies are standalone (not in an Auto Scaling group) because each has a fixed private IP registered with the payment processor's allow-list.

## Symptoms

- `checkout-api` errors `server closed the connection unexpectedly` or connection timeouts.
- NLB target health shows one or more proxies unhealthy.

## Steps

1. Check NLB target health and which proxy is failing.
2. If a single proxy failed its EC2 status checks, the CloudWatch recovery alarm (RB-001) recovers it on new hardware with the same private IP. Wait 10 minutes before intervening.
3. If PgBouncer itself is stuck (instance healthy, process not), connect via SSM (RB-008) and run `systemctl restart pgbouncer`. Connections on that proxy drop; clients retry.
4. If all proxies fail at once, the problem is the database or the network, not the proxies. Page the payments database owner and check the Aurora cluster status.

## Do not

- Do not terminate a proxy: its private IP is on the payment processor allow-list and changing it requires a 5-day change process with the processor.
- Do not raise `max_client_conn` above 5,000 without checking the database's `max_connections`.

## Credentials

Proxies fetch database credentials at boot from the secrets manager; they are rotated every 30 days. A proxy that failed to fetch credentials logs `auth failed` for every client; restarting PgBouncer re-reads them.

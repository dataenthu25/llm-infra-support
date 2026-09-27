---
title: "Postmortem: Slow Postgres failover on orders-db"
type: postmortem
team: data
tags: postgres, failover, patroni, high-availability
---

# Postmortem: Slow Postgres failover on orders-db (2025-04-22)

## Summary

The primary of `orders-db` lost its storage volume due to a cloud provider hardware fault.
Patroni promoted a replica, but applications kept connecting to the old primary's IP for
18 minutes because of DNS caching in PgBouncer. Order creation was unavailable during that time.

**Severity:** SEV1
**Duration:** 14:03 - 14:24 UTC (writes unavailable 14:04 - 14:22)

## Impact

- ~9,400 orders failed to be placed; about 60% of customers retried successfully later.
- Read-only pages worked throughout because they use replicas.

## Timeline (UTC)

- **14:03** EBS volume on `orders-db-1` (primary) becomes unresponsive; I/O hangs.
- **14:04** Application errors: `connection timed out` from PgBouncer.
- **14:04:40** Patroni leader key expires (TTL 30s); `orders-db-2` promoted to primary.
- **14:05** Patroni updates the `orders-db-primary` DNS record to point to `orders-db-2`.
- **14:06** Data on-call paged by `PostgresPrimaryDown`.
- **14:11** On-call sees the new primary is healthy but receives no traffic.
- **14:17** Found that PgBouncer still resolves the old IP.
- **14:21** PgBouncer instances restarted in sequence.
- **14:22** Writes succeed. Error rate drops to zero.
- **14:24** Incident resolved; old primary fenced and removed from the cluster.

## Root cause

PgBouncer resolves the database host name when it opens a server connection and caches the
result for `dns_max_ttl` seconds. Ours was set to 3600 (one hour), inherited from an old config.
Existing server connections to the dead primary hung instead of failing because TCP keepalive
settings were at kernel defaults (2 hours before the first probe). PgBouncer kept trying the
cached, dead address.

## Contributing factors

- Failover was tested quarterly, but only with a clean `patronictl switchover`. During a
  switchover the old primary closes connections, so PgBouncer reconnects immediately. A hard
  failure behaves differently and was never tested.
- There was no alert for "primary is healthy but receiving zero transactions".

## What went well

- Patroni failover itself took 40 seconds and lost no committed transactions (synchronous
  replication to one standby).
- The runbook for restarting PgBouncer was accurate.

## Action items

| Action                                                                  | Owner | Status |
|-------------------------------------------------------------------------|-------|--------|
| Set PgBouncer `dns_max_ttl = 5` and `server_login_retry = 1`            | data  | Done   |
| Set `tcp_keepalive` in PgBouncer (idle 30s, interval 10s, count 3)      | data  | Done   |
| Add hard-failure game day (kill instance, detach volume) each quarter   | data  | Open   |
| Alert when primary TPS is 0 for 2 minutes during business hours         | data  | Done   |
| Evaluate moving PgBouncer to point at Patroni's REST endpoint via HAProxy | data | Open |

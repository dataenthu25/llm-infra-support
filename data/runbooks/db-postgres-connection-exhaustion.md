---
title: Postgres connection exhaustion
type: runbook
team: data
tags: postgres, connections, pgbouncer
---

# Postgres connection exhaustion

## Overview

Applications fail with `FATAL: sorry, too many clients already` or
`remaining connection slots are reserved for non-replication superuser connections`.
Postgres uses one process per connection, so `max_connections` is deliberately low (400 on
`orders-db`). All application traffic should go through PgBouncer in transaction pooling mode.

**Alert:** `PostgresConnectionsHigh` at 85% of `max_connections`.

## Triage

```sql
SELECT count(*) AS total,
       count(*) FILTER (WHERE state = 'active') AS active,
       count(*) FILTER (WHERE state = 'idle') AS idle,
       count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx
FROM pg_stat_activity;

-- who is holding connections
SELECT usename, application_name, client_addr, count(*)
FROM pg_stat_activity
GROUP BY 1, 2, 3
ORDER BY 4 DESC
LIMIT 15;
```

## Diagnosis

### Many `idle in transaction` sessions

An application opened a transaction and never committed, often because of an exception path that
skips rollback or a slow external call made inside a transaction. These sessions also hold locks
and block vacuum.

### A service bypasses PgBouncer

If you see hundreds of connections from pod IPs with the service's name as `application_name`
rather than from PgBouncer hosts, the service is connecting directly. Check its `DATABASE_URL`.

### Connection storm after a deploy or scale-up

Each new pod opens its own pool (for example 20 connections x 60 pods = 1200). Check whether the
HPA just scaled the service.

## Mitigation

1. Terminate idle-in-transaction sessions older than 5 minutes:

   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle in transaction'
     AND now() - state_change > interval '5 minutes';
   ```

2. Scale down or pause the offending service if one clearly dominates.
3. Do **not** raise `max_connections` during an incident. It requires a restart and more
   connections usually make the database slower, not faster.

## Prevention

- Set `idle_in_transaction_session_timeout = '60s'` for application roles.
- Size application pools from the PgBouncer budget, not per pod.

---
title: Investigating slow Postgres queries
type: runbook
team: data
tags: postgres, performance, explain, indexes
---

# Investigating slow Postgres queries

## Overview

Use this runbook when a service reports rising database latency, or when
`PostgresSlowQueries` fires (mean execution time for a query fingerprint above 500ms).

## Find the expensive queries

`pg_stat_statements` is enabled on all production databases.

```sql
SELECT left(query, 100) AS query,
       calls,
       round(mean_exec_time::numeric, 1) AS mean_ms,
       round(total_exec_time::numeric / 1000, 0) AS total_s,
       rows
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 15;
```

Sort by `total_exec_time` to find what costs the database the most overall, and by
`mean_exec_time` to find what hurts individual requests.

## Check for lock waits

Slow is not always expensive. A cheap query waiting on a lock looks slow too.

```sql
SELECT a.pid, a.wait_event_type, a.wait_event,
       pg_blocking_pids(a.pid) AS blocked_by,
       now() - a.query_start AS waiting_for,
       left(a.query, 80)
FROM pg_stat_activity a
WHERE cardinality(pg_blocking_pids(a.pid)) > 0;
```

## Read the query plan

Run `EXPLAIN (ANALYZE, BUFFERS)` on a **replica** with representative parameters. `ANALYZE`
executes the query, so never run it for writes on the primary.

What to look for:

- `Seq Scan` on a large table with a selective `WHERE` clause: an index is missing.
- Estimated rows far from actual rows (for example `rows=10` vs `actual rows=250000`): table
  statistics are stale. Run `ANALYZE <table>;`.
- `Sort Method: external merge Disk`: the sort spilled to disk; `work_mem` is too small for
  this query, or the query sorts more rows than it needs.
- `Nested Loop` with a huge number of loops: often caused by the bad row estimate above.

## Fixes

- Add the missing index with `CREATE INDEX CONCURRENTLY` so writes are not blocked. It takes
  longer and cannot run inside a transaction block.
- Rewrite `OFFSET` pagination to keyset pagination for deep pages.
- For an urgent regression after a deploy, roll back the application change first and tune later.

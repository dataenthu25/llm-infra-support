---
title: Postgres replication lag
type: runbook
team: data
tags: postgres, replication, replica, wal
---

# Postgres replication lag

## Overview

Read replicas apply WAL (write-ahead log) streamed from the primary. When they fall behind,
reads from replicas return stale data. If a replica is far enough behind, the primary may have
to retain a lot of WAL, which can fill its disk.

**Alert:** `PostgresReplicationLagHigh` fires when lag exceeds 30 seconds for 5 minutes.
**Severity:** SEV3. SEV2 if the primary's WAL volume is above 80% full.

## Triage

On the **primary**:

```sql
SELECT client_addr, application_name, state,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS replay_lag_bytes,
       write_lag, flush_lag, replay_lag
FROM pg_stat_replication;
```

On the **replica**:

```sql
SELECT now() - pg_last_xact_replay_timestamp() AS replay_delay;
```

Note: `replay_delay` looks large on an idle primary even when the replica is fully caught up,
because no new transactions arrive. Always check the byte lag as well.

## Diagnosis

### Which stage is slow?

- `write_lag` high: the network between primary and replica is the bottleneck.
- `flush_lag` high, `write_lag` low: the replica's disk is slow to fsync.
- `replay_lag` high, others low: the replica receives WAL fine but cannot **apply** it fast
  enough. This is the most common case.

### Replay is blocked by queries on the replica

Long-running queries on a hot standby can conflict with replay (for example a vacuum on the
primary removing rows the replica query still needs). With `max_standby_streaming_delay` set to
a large value, replay waits for the query.

```sql
-- on the replica: longest running queries
SELECT pid, now() - query_start AS runtime, state, left(query, 80)
FROM pg_stat_activity
WHERE state <> 'idle'
ORDER BY runtime DESC
LIMIT 10;
```

### Heavy write burst on the primary

Bulk loads, large `UPDATE` batches and index builds generate WAL faster than a single replay
process can apply. Check WAL generation rate in the "Postgres / WAL" dashboard.

## Mitigation

- Cancel the blocking analytics query on the replica: `SELECT pg_cancel_backend(<pid>);`
- Pause or throttle the batch job on the primary (coordinate with its owner).
- Route latency-sensitive reads to the primary temporarily by setting the service flag
  `READ_FROM_REPLICA=false`. Check that the primary has CPU headroom first.
- If the replica is hopelessly behind and WAL on the primary is filling up, drop the replica's
  replication slot and rebuild the replica. Get approval from the data on-call lead before
  dropping a slot.

## Related

- `db-postgres-disk-full.md` for when retained WAL fills the primary disk.
- `postmortem-2025-04-22-postgres-failover.md`

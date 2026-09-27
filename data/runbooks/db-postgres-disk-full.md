---
title: Postgres disk almost full
type: runbook
team: data
tags: postgres, disk, wal, vacuum
---

# Postgres disk almost full

## Overview

If the data volume fills up, Postgres cannot write WAL and will PANIC and shut down. Recovery
then requires adding space before it can start. Treat anything above 90% as urgent.

**Alert:** `PostgresDiskUsageHigh` at 80% (warning) and 90% (page).

## Triage

Find what is using the space:

```bash
df -h /var/lib/postgresql
du -sh /var/lib/postgresql/17/main/pg_wal
du -sh /var/lib/postgresql/17/main/base
```

## Diagnosis

### WAL is piling up

If `pg_wal` is large, something is preventing WAL from being recycled:

```sql
-- inactive or lagging replication slots hold WAL forever
SELECT slot_name, active, wal_status,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained
FROM pg_replication_slots
ORDER BY pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) DESC;

-- WAL archiving failures
SELECT archived_count, failed_count, last_failed_wal, last_failed_time
FROM pg_stat_archiver;
```

An abandoned slot from a decommissioned replica or a CDC connector (Debezium) is the most common
cause.

### Table and index bloat

If `base` is large, look at the biggest relations and their dead tuples:

```sql
SELECT relname,
       pg_size_pretty(pg_total_relation_size(relid)) AS total,
       n_dead_tup, last_autovacuum
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 10;
```

Large `n_dead_tup` with an old `last_autovacuum` means vacuum cannot keep up or is blocked by a
long-running transaction.

## Mitigation

- **Abandoned slot:** confirm with the owner, then `SELECT pg_drop_replication_slot('<name>');`
- **Archiving failing:** fix the archive destination (credentials, bucket permissions). WAL is
  released once archiving catches up.
- **Buy time:** grow the volume. On our cloud provider, EBS volumes can be resized online:
  modify the volume, then run `resize2fs` or `xfs_growfs`. Volumes can only be modified once
  every 6 hours, so grow generously.
- Never delete files from `pg_wal` by hand. It corrupts the database.

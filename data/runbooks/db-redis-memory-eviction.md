---
title: Redis memory full and key eviction
type: runbook
team: data
tags: redis, cache, memory, eviction
---

# Redis memory full and key eviction

## Overview

Our Redis clusters are used as caches with `maxmemory-policy allkeys-lru`. When memory reaches
`maxmemory`, Redis evicts keys. Some eviction is normal. A sudden eviction spike means the cache
hit rate drops and load shifts to the databases behind it.

The `sessions` cluster is the exception: it uses `noeviction` because losing a session logs the
user out. When it is full, writes fail with `OOM command not allowed when used memory > 'maxmemory'`.

**Alert:** `RedisMemoryHigh` (90% of maxmemory), `RedisEvictionsSpike`.

## Diagnosis

```bash
redis-cli -h <host> INFO memory | grep -E 'used_memory_human|maxmemory_human|mem_fragmentation_ratio'
redis-cli -h <host> INFO stats | grep -E 'evicted_keys|keyspace_hits|keyspace_misses'
```

### Large keys

```bash
# samples the keyspace; safe to run in production, but do it on a replica if possible
redis-cli -h <host> --bigkeys
redis-cli -h <host> MEMORY USAGE <key>
```

A single hash or list growing without bound (for example a per-user activity feed with no trim)
is a common culprit.

### Keys without TTL

```bash
redis-cli -h <host> INFO keyspace   # compare 'keys' with 'expires'
```

If most keys have no expiry, a recent code change probably forgot to set a TTL.

### High fragmentation

A `mem_fragmentation_ratio` above 1.5 means the OS allocated much more memory than Redis uses.
Enable `activedefrag yes` on Redis 4+ rather than restarting.

## Mitigation

- For the `sessions` cluster, scale up the node type (online resize in the managed service) or
  delete expired session keys that were written without TTL.
- For caches, identify and fix the key pattern; delete bulk keys with `SCAN` + `UNLINK`, never
  `KEYS *`, which blocks the server.
- Watch the database dashboards while the cache refills. A cold cache can overload Postgres.

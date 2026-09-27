---
title: "Postmortem: Schema migration locked the payments table"
type: postmortem
team: data
tags: postgres, migrations, locks, ddl
---

# Postmortem: Schema migration locked the payments table (2025-08-09)

## Summary

A migration adding a column with a volatile default to the `payments` table waited for an
`ACCESS EXCLUSIVE` lock behind a long-running analytics query. While it waited, every other
query on `payments` queued behind the migration. Payment processing stopped for 12 minutes.

**Severity:** SEV1
**Duration:** 10:31 - 10:43 UTC

## Impact

- All payment captures and refunds failed or timed out for 12 minutes.
- ~3,100 checkout attempts failed. Retries by the payment worker recovered 2,400 of them.

## Timeline (UTC)

- **09:50** A data analyst starts a heavy report query on `payments` via the primary (read-only
  role, but connected to the primary instead of the analytics replica).
- **10:31** Deploy pipeline runs migration `0142_add_payments_risk_score`:
  `ALTER TABLE payments ADD COLUMN risk_score numeric DEFAULT random();`
- **10:31** Migration requests `ACCESS EXCLUSIVE`; waits for the analyst's `ACCESS SHARE` lock.
- **10:31** New `SELECT`/`INSERT` statements on `payments` queue behind the waiting migration.
- **10:33** `PaymentsErrorRateHigh` pages payments on-call; data on-call joined at 10:36.
- **10:40** Lock chain identified with `pg_blocking_pids`.
- **10:42** Analyst query cancelled; migration runs, but must rewrite the table (volatile default).
- **10:43** Table rewrite finishes (small table, 4 GB); traffic recovers.

## Root cause

Postgres grants locks in queue order. A pending `ACCESS EXCLUSIVE` request blocks every later
lock request on the table, even plain reads, until it is granted. The migration had no
`lock_timeout`, so it waited indefinitely and turned one slow query into a full outage.

The volatile default (`random()`) also forced a full table rewrite. A constant default would
have been a metadata-only change since Postgres 11.

## Contributing factors

- The analytics role could connect to the primary.
- The migration linter only checked for `CREATE INDEX` without `CONCURRENTLY`; it did not check
  for missing `lock_timeout` or volatile defaults.

## Action items

| Action                                                                     | Owner    | Status |
|----------------------------------------------------------------------------|----------|--------|
| All migrations run with `SET lock_timeout = '3s'` and retry with back-off  | data     | Done   |
| Linter rule: reject `ADD COLUMN ... DEFAULT <volatile function>`           | data     | Done   |
| Revoke `CONNECT` on primaries for the analytics role                       | data     | Done   |
| Set `statement_timeout = '5min'` for human read-only roles on primaries   | data     | Done   |
| Document safe migration patterns in the engineering handbook              | data     | Open   |

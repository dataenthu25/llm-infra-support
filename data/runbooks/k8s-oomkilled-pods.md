---
title: Pods OOMKilled
type: runbook
team: platform
tags: kubernetes, memory, oom, limits
---

# Pods OOMKilled

## Overview

A container is `OOMKilled` when it exceeds its memory **limit**. The Linux kernel's cgroup OOM
killer sends SIGKILL and the container exits with code 137. This is different from a node-level
OOM, where the kernel kills processes because the whole node ran out of memory.

**Alert:** `KubeContainerOOMKilled` or rising restart counts with reason `OOMKilled`.

## Diagnosis

### Confirm it is really OOM

```bash
kubectl get pod <pod> -n <namespace> \
  -o jsonpath='{range .status.containerStatuses[*]}{.name}{"\t"}{.lastState.terminated.reason}{"\n"}{end}'
```

### Compare usage with requests and limits

```bash
kubectl top pod <pod> -n <namespace> --containers
kubectl get pod <pod> -n <namespace> -o jsonpath='{.spec.containers[*].resources}'
```

In Grafana, open the "Workload / Memory" dashboard and look at
`container_memory_working_set_bytes` for the last 7 days. That metric is what the OOM killer
effectively compares against the limit.

### Is it a leak or a spike?

- **Steady climb until the kill, then repeat:** likely a memory leak. Take a heap profile before
  the next restart (for JVM: `jcmd <pid> GC.heap_dump`; for Go: `/debug/pprof/heap`).
- **Flat, then sudden jump:** a specific request or batch job loads too much data into memory.
  Correlate the timestamp with request logs.
- **Grew right after a deploy:** compare with the previous version; a dependency upgrade or a new
  cache can change the baseline.

### JVM and runtime specifics

The JVM sizes its heap from the container limit only if `-XX:MaxRAMPercentage` is set. A heap
of 75% of the limit plus metaspace, thread stacks and direct buffers can still exceed the limit.
Node.js needs `--max-old-space-size`. Python has no heap cap, so watch for unbounded caches.

## Mitigation

- Short term: raise the memory limit by 25-50% and roll out. Make sure the node pool has room:
  requests are what the scheduler reserves.
- If a leak is confirmed, schedule a rolling restart every few hours as a stopgap while the fix is
  developed. Document it in the incident ticket so it does not become permanent.
- Keep request and limit for memory equal for latency-critical services. That puts them in the
  Guaranteed QoS class, which makes them the last to be evicted under node pressure.

## Prevention

Every Deployment must set memory requests and limits. The admission policy `require-resources`
in the platform policy repo enforces this for new namespaces.

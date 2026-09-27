---
title: Kubernetes node NotReady
type: runbook
team: platform
tags: kubernetes, nodes, kubelet
---

# Kubernetes node NotReady

## Overview

A node goes `NotReady` when the control plane stops receiving kubelet heartbeats (node lease
updates) for longer than `node-monitor-grace-period` (40s by default). After roughly 5 minutes,
pods on the node are marked for eviction and rescheduled elsewhere, if there is capacity.

**Alert:** `KubeNodeNotReady`
**Severity:** SEV3 for a single node. SEV2 if more than 20% of a node pool is NotReady.

## Triage

```bash
kubectl get nodes -o wide | grep -v ' Ready'
kubectl describe node <node> | sed -n '/Conditions/,/Addresses/p'
```

Look at the conditions:

- `MemoryPressure`, `DiskPressure` or `PIDPressure` set to `True` means kubelet is alive but the
  node is starved.
- `Ready` set to `Unknown` with message `Kubelet stopped posting node status` means kubelet is
  down, the node is frozen, or it lost network connectivity to the API server.

If several nodes in the same availability zone go NotReady at once, suspect a zonal network or
cloud provider event first. Check the provider status page before touching individual nodes.

## Diagnosis

### Kubelet is down or unhealthy

SSH or use the cloud serial console:

```bash
systemctl status kubelet
journalctl -u kubelet --since "30 min ago" | tail -100
# container runtime health
systemctl status containerd
crictl ps | head
```

Frequent causes: the container runtime is hung, certificates for kubelet expired, or the node ran
out of disk under `/var/lib/containerd`.

### Disk pressure

```bash
df -h /var/lib/containerd /var/log
crictl images | wc -l
# remove unused images (kubelet image GC should do this, but can fall behind)
crictl rmi --prune
```

### Memory pressure

Check for a pod without memory limits consuming the node. `kubectl top pods -A --sort-by=memory`
from another machine, or `ps aux --sort=-rss | head` on the node.

## Mitigation

1. Cordon the node so nothing new is scheduled there:
   `kubectl cordon <node>`
2. Drain workloads (respects PodDisruptionBudgets):
   `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=5m`
3. If the node does not recover within 15 minutes, terminate the instance. The node group's
   autoscaler replaces it. Do not try to nurse a broken node back to health in production.
4. Uncordon only if you fixed the underlying cause and kubelet is healthy for 10 minutes.

## Escalation

#platform-oncall owns node pools. For zonal events, open a support case with the cloud provider
and link it in the incident channel.

---
title: Pod stuck in CrashLoopBackOff
type: runbook
team: platform
tags: kubernetes, pods, crashloop
---

# Pod stuck in CrashLoopBackOff

## Overview

`CrashLoopBackOff` means the container starts, exits, and kubelet keeps restarting it with an
exponential back-off (10s, 20s, 40s ... capped at 5 minutes). The pod is not the problem; the
process inside it is exiting. Your job is to find out *why* the process exits.

**Alert:** `KubePodCrashLooping` (fires after 15 minutes of restarts)
**Severity:** SEV3 unless the affected Deployment has zero ready replicas, then SEV2.

## Triage

1. Confirm which pods are affected and how many restarts they have:

   ```bash
   kubectl get pods -n <namespace> -o wide | grep -v Running
   kubectl get deploy <name> -n <namespace>   # are ANY replicas ready?
   ```

2. If all replicas are crash looping and the service is customer facing, page the owning team
   and consider rolling back immediately (see Mitigation) before digging further.

## Diagnosis

### Read the logs of the previous container

The current container may have just started and has no useful output. Always check `--previous`:

```bash
# logs from the container that crashed, not the one that is starting now
kubectl logs <pod> -n <namespace> --previous
# multi-container pods need -c
kubectl logs <pod> -n <namespace> -c <container> --previous
```

### Check the exit code and reason

```bash
kubectl describe pod <pod> -n <namespace> | sed -n '/Last State/,/Ready/p'
```

| Exit code | Reason         | Usual cause                                              |
|-----------|----------------|----------------------------------------------------------|
| 1         | Error          | Application error: bad config, missing env var, panic    |
| 137       | OOMKilled      | Memory limit exceeded (see `k8s-oomkilled-pods.md`)      |
| 137       | Error          | Killed by SIGKILL after failing liveness probe           |
| 139       | Error          | Segfault, often a native library mismatch                |
| 143       | Error          | SIGTERM: something asked it to stop (probe, preStop)     |

### Common causes

- **Missing Secret or ConfigMap key.** Logs usually show `KeyError` or `env var X not set`.
  Check `kubectl get events -n <namespace>` for `CreateContainerConfigError`.
- **Liveness probe too aggressive.** App needs 40s to warm up but `initialDelaySeconds` is 10.
  Events show `Liveness probe failed` right before each restart. Prefer a `startupProbe`.
- **Dependency unavailable at boot.** App exits if the database is unreachable instead of retrying.
- **Bad image.** A new tag was deployed with a broken entrypoint. Compare the image tag with the
  last known good ReplicaSet: `kubectl rollout history deploy/<name> -n <namespace>`.

## Mitigation

- Roll back if a recent deploy caused it:

  ```bash
  kubectl rollout undo deploy/<name> -n <namespace>
  kubectl rollout status deploy/<name> -n <namespace>
  ```

- If the probe is the culprit, patch the probe temporarily and open a PR with the real fix.
- If a Secret is missing, restore it from the secrets manager; do not hand-create it with
  `kubectl create secret` in production.

## Escalation

Escalate to the owning service team via their on-call rotation. Escalate to #platform-oncall only
if the issue looks node or cluster related (many unrelated pods crashing on the same node).

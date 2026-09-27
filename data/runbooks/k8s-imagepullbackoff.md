---
title: Pods stuck in ImagePullBackOff
type: runbook
team: platform
tags: kubernetes, images, registry
---

# Pods stuck in ImagePullBackOff

## Overview

`ErrImagePull` followed by `ImagePullBackOff` means kubelet cannot pull the container image.
New pods never start, so a rollout stalls. Existing pods keep running, so the impact is usually
limited to deploys and scale-ups, until nodes are replaced.

## Diagnosis

```bash
kubectl describe pod <pod> -n <namespace> | sed -n '/Events/,$p'
```

Read the exact error message. It almost always tells you which of these it is:

### `manifest unknown` or `not found`

The tag does not exist. Usually a CI pipeline failed to push, or someone typed the tag by hand.
Check the registry directly:

```bash
crane ls registry.internal.example.com/team/service | tail
```

### `unauthorized` or `403 Forbidden`

The node or the pod's `imagePullSecrets` cannot authenticate. Check:

- The Secret referenced in `imagePullSecrets` exists in the **same namespace** as the pod.
- The registry token has not expired. Tokens for the internal registry rotate every 12 hours
  through the `registry-creds` CronJob in `kube-system`. If that job is failing, every namespace
  loses pull access at the same time.

### `toomanyrequests`

Rate limited by a public registry (Docker Hub). All production images must be pulled from the
internal mirror. Fix the image reference rather than adding credentials.

### `i/o timeout` or `dial tcp`

Network path from nodes to the registry is broken. Check NAT gateway health and the registry's
own status. See `net-dns-resolution-failures.md` if the error mentions `no such host`.

## Mitigation

- For a bad tag, fix the manifest and redeploy, or roll back: `kubectl rollout undo`.
- For expired credentials, re-run the CronJob manually:
  `kubectl create job --from=cronjob/registry-creds registry-creds-manual -n kube-system`
- Pods retry automatically with back-off; deleting them speeds up recovery once the cause is fixed.

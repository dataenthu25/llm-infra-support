---
title: HorizontalPodAutoscaler not scaling
type: runbook
team: platform
tags: kubernetes, autoscaling, hpa, metrics-server
---

# HorizontalPodAutoscaler not scaling

## Overview

The HPA is supposed to add replicas when CPU (or a custom metric) is above target, but the
replica count stays flat while latency climbs. Or the reverse: it scales down too aggressively
and flaps.

## Diagnosis

### Read the HPA status

```bash
kubectl get hpa -n <namespace>
kubectl describe hpa <name> -n <namespace>
```

If the `TARGETS` column shows `<unknown>/70%`, the HPA cannot read metrics. Look at the
conditions in `describe`:

- `AbleToScale False` - the target Deployment cannot be found or scaled.
- `ScalingActive False` with `FailedGetResourceMetric` - metrics are missing.
- `ScalingLimited True` - already at `maxReplicas`. This is the most common "not scaling" cause.

### Metrics are missing

```bash
kubectl get apiservice v1beta1.metrics.k8s.io
kubectl top pods -n <namespace>
kubectl logs -n kube-system deploy/metrics-server
```

For CPU-based scaling, every container in the pod must have a CPU **request**. The HPA computes
utilization as usage divided by request. A sidecar without a request breaks the whole calculation.

For custom metrics (for example queue depth through prometheus-adapter), check the adapter:

```bash
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | jq '.resources[].name' | head
```

### The HPA scales but pods stay Pending

That is a cluster capacity problem, not an HPA problem. Check the cluster-autoscaler logs and the
node group's max size.

## Mitigation

- Manual override during an incident: `kubectl scale deploy/<name> --replicas=<n>`. The HPA will
  take control again on its next sync, so also raise `minReplicas` on the HPA if the load will last.
- Raise `maxReplicas` if the service is capped and nodes have headroom.
- To stop flapping, set `behavior.scaleDown.stabilizationWindowSeconds` to 300 or more.

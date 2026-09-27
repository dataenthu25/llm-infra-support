---
title: "Postmortem: CoreDNS overload caused cluster-wide timeouts"
type: postmortem
team: platform
tags: kubernetes, dns, coredns, ndots
---

# Postmortem: CoreDNS overload caused cluster-wide timeouts (2025-03-14)

## Summary

For 47 minutes, services in the `prod-eu-1` cluster saw intermittent DNS resolution timeouts.
Outbound calls to external APIs failed at up to 18%, and checkout conversion dropped by 11%.
CoreDNS pods were CPU throttled after a traffic surge, amplified by the default `ndots:5`
search behaviour.

**Severity:** SEV2
**Duration:** 09:12 - 09:59 UTC
**Incident commander:** platform on-call

## Impact

- `checkout-api`: p99 latency rose from 350ms to 5.2s; 6% of payment attempts failed.
- `notifications-worker`: 40k emails delayed by up to 35 minutes.
- No data loss.

## Timeline (UTC)

- **09:05** Marketing campaign goes live; traffic up 3x over 10 minutes.
- **09:12** First `EAI_AGAIN` errors in `checkout-api` logs.
- **09:18** `KubeDNSErrorsHigh` fires. On-call acknowledges.
- **09:26** On-call sees CoreDNS pods at their 200m CPU limit with heavy throttling.
- **09:31** CoreDNS scaled from 2 to 6 replicas by hand. Error rate drops by half.
- **09:44** CoreDNS CPU limit removed and replicas raised to 10.
- **09:59** Error rate back to baseline. Incident resolved.

## Root cause

Pods use the Kubernetes default `ndots:5`. Any name with fewer than five dots, like
`api.stripe.com`, is first tried against every search domain
(`<ns>.svc.cluster.local`, `svc.cluster.local`, `cluster.local`, and the VPC domain) before
the absolute name. Every external lookup therefore produced up to 5 queries (x2 for A and
AAAA). When traffic tripled, CoreDNS query volume grew roughly 30x for external names.

CoreDNS ran only 2 replicas with a 200m CPU limit, a setting from cluster bootstrap that was
never revisited. It was CPU throttled and dropped queries.

## Contributing factors

- No NodeLocal DNSCache, so every lookup crossed the network to a CoreDNS pod.
- The CoreDNS autoscaler (`cluster-proportional-autoscaler`) scales by node count, not by load.
  Node count had not changed yet, so it did not react.
- Application HTTP clients did not reuse connections, so they resolved DNS on every request.

## What went well

- The alert fired within 6 minutes and pointed straight at DNS.
- Manual scaling of CoreDNS was fast and safe.

## What went wrong

- CoreDNS dashboards were not linked from the alert, which cost about 8 minutes.
- The campaign launch was not shared with the platform team ahead of time.

## Action items

| Action                                                              | Owner      | Status |
|---------------------------------------------------------------------|------------|--------|
| Deploy NodeLocal DNSCache to all production clusters                | platform   | Done   |
| Remove CoreDNS CPU limit; set requests from observed p95 usage      | platform   | Done   |
| Set `dnsConfig.options ndots: 2` in the service Helm chart default | platform   | Done   |
| Add CoreDNS dashboard link to `KubeDNSErrorsHigh`                   | platform   | Done   |
| Enable HTTP keep-alive in checkout-api's payment client             | payments   | Open   |
| Add campaign launches to the shared change calendar                 | marketing  | Open   |

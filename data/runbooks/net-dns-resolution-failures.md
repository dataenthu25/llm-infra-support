---
title: DNS resolution failures
type: runbook
team: network
tags: networking, dns, route53, resolver
---

# DNS resolution failures

## Overview

Services log `no such host`, `NXDOMAIN`, `SERVFAIL` or `EAI_AGAIN`. DNS failures look like
everything is broken at once, because almost every connection starts with a lookup.

First decide the scope: one pod, one cluster, one VPC, or everyone (including external users).

## Triage

From an affected pod or host:

```bash
# which resolver is being used
cat /etc/resolv.conf
# ask the configured resolver
dig api.partner.com
# ask a public resolver to compare
dig @1.1.1.1 api.partner.com
# for internal names
dig orders-db-primary.db.internal.example.com
```

Interpret the result:

- **Public resolver works, ours fails:** the problem is in our resolution path (CoreDNS,
  NodeLocal DNSCache, VPC resolver, or forwarding rules).
- **Both fail with NXDOMAIN:** the record really does not exist. Check recent changes in the
  DNS repository (records are managed with Terraform).
- **Both fail with SERVFAIL:** the authoritative servers for that zone are broken, or DNSSEC
  validation fails.
- **Timeout:** packets are not reaching the resolver. Check security groups and NACLs for
  UDP/TCP 53.

## Diagnosis

### Inside Kubernetes

See `postmortem-2025-03-14-coredns-overload.md`. Check CoreDNS error rate and CPU, and whether
NodeLocal DNSCache pods are running on the affected nodes:

```bash
kubectl -n kube-system get pods -l k8s-app=node-local-dns -o wide
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50
```

### VPC resolver limits

The cloud VPC resolver allows a fixed number of packets per second per network interface
(1024 on our provider). High-volume services that bypass caching can hit it; drops show up as
`linklocal_allowance_exceeded` in the instance's ENA driver stats (`ethtool -S eth0`).

### Private zone and forwarding rules

Internal zones (`*.internal.example.com`) are private hosted zones associated with specific
VPCs. A new VPC that was not associated with the zone gets NXDOMAIN for every internal name.

## Mitigation

- Revert the most recent DNS change if it lines up with the start of errors.
- Scale CoreDNS or restart NodeLocal DNSCache pods on affected nodes.
- For VPC resolver limits, enable local caching on the affected hosts.
- Lower TTLs *before* planned changes, not during an incident; lowering them now only helps
  after the old TTL expires.

---
title: Packet loss and high network latency between services
type: runbook
team: network
tags: networking, latency, packet-loss, mtr
---

# Packet loss and high network latency between services

## Overview

Symptoms: rising p99 latency across many services, TCP retransmits, intermittent timeouts,
while CPU and application metrics look normal. The network is a shared path, so compare several
source and destination pairs before drawing conclusions.

## Triage

1. Is it one availability zone? Filter latency dashboards by `zone`. Cross-AZ-only problems
   point at the provider's inter-AZ links.
2. Is it one destination? External APIs, one database, or everything?
3. Did anything change? Security group, route table, NAT gateway, or a large traffic shift.

## Diagnosis

### Measure loss along the path

```bash
# 100 probes, report mode; loss that appears at one hop and continues to the end is real
mtr -rwzc 100 <destination>
# TCP-based, useful when ICMP is rate limited
mtr -rwzc 100 --tcp --port 443 <destination>
```

Loss at an intermediate hop that does **not** continue to the final hop is usually just that
router de-prioritizing ICMP replies. Ignore it.

### TCP retransmits on hosts

```bash
nstat -az | grep -E 'TcpRetransSegs|TcpExtTCPTimeouts'
ss -ti dst <ip> | grep -E 'rtt|retrans'
```

A retransmit rate above ~1% of segments sent is worth investigating.

### Instance network limits

Cloud instances have bandwidth and packets-per-second allowances. When exceeded, packets are
silently dropped. On our provider check:

```bash
ethtool -S eth0 | grep -E 'allowance_exceeded'
```

`bw_out_allowance_exceeded` or `pps_allowance_exceeded` increasing means the instance type is
too small for its traffic, not that the network is broken.

### NAT gateway saturation

Outbound traffic to the internet goes through NAT gateways. Check `ErrorPortAllocation` and
`PacketsDropCount` in CloudWatch. Port allocation errors happen when many connections go to the
same destination IP and port.

## Mitigation

- Shift traffic away from an unhealthy AZ by draining its targets at the load balancer.
- Move a saturated workload to a larger instance type, or spread it across more nodes.
- For NAT port exhaustion, enable connection reuse in clients, or add NAT gateways/IPs.

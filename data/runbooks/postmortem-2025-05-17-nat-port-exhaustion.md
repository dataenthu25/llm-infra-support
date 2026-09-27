---
title: "Postmortem: NAT gateway port exhaustion broke payment provider calls"
type: postmortem
team: network
tags: networking, nat, snat, connections
---

# Postmortem: NAT gateway port exhaustion broke payment provider calls (2025-05-17)

## Summary

A new release of `payments-gateway` disabled HTTP connection pooling by mistake. Each payment
request opened a new TLS connection to the payment provider's single API IP. The NAT gateway in
`eu-west-1a` ran out of source ports for that destination, and 23% of outbound calls failed
for 34 minutes.

**Severity:** SEV2
**Duration:** 16:48 - 17:22 UTC

## Impact

- 23% of card payment authorizations failed in the affected window; customers saw
  "payment could not be processed".
- Other outbound traffic from the same NAT gateway (webhooks, email provider) also saw errors.

## Timeline (UTC)

- **16:30** `payments-gateway` v4.18.0 deployed.
- **16:48** `ErrorPortAllocation` on NAT gateway `nat-1a` starts rising. No alert on this metric.
- **16:55** Payments error rate alert fires. Payments on-call suspects the provider and checks
  their status page (green).
- **17:05** Network on-call engaged. Notices errors only from pods in zone `1a`.
- **17:09** NAT gateway metrics show 55,000 concurrent connections to one destination.
- **17:14** Correlated with the payments deploy; connections per request jumped from ~0.05 to 1.
- **17:18** v4.18.0 rolled back.
- **17:22** Port allocation errors stop. Resolved.

## Root cause

A NAT gateway can hold about 55,000 simultaneous connections to each unique destination
(IP, port, protocol). v4.18.0 upgraded the HTTP client library and the new version changed the
constructor so the shared connection pool was created per request. Every request opened a fresh
connection that then sat in `TIME_WAIT`, consuming a NAT port for up to 350 seconds.

Zone `1a` failed first because it ran the most pods after a previous rebalancing.

## Contributing factors

- No alert on NAT gateway `ErrorPortAllocation`.
- The load test for the release hit a mock provider inside the VPC, so it never went through NAT.

## Action items

| Action                                                                   | Owner    | Status |
|--------------------------------------------------------------------------|----------|--------|
| Alert on NAT `ErrorPortAllocation` > 0 for 2 minutes                     | network  | Done   |
| Add a second EIP to each NAT gateway (doubles ports per destination)     | network  | Done   |
| Add metric `http_client_new_connections_total` to the service template  | platform | Open   |
| Load tests for external integrations must route through NAT              | payments | Open   |
| Unit test that the payments HTTP client is a singleton                   | payments | Done   |

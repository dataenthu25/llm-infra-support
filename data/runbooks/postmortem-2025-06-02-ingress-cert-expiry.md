---
title: "Postmortem: Expired TLS certificate on public ingress"
type: postmortem
team: platform
tags: kubernetes, tls, cert-manager, ingress
---

# Postmortem: Expired TLS certificate on public ingress (2025-06-02)

## Summary

The TLS certificate for `api.example.com` expired at 00:00 UTC. For 1 hour 22 minutes all
clients that validate certificates (every mobile app and most API integrators) failed to
connect. cert-manager had been failing to renew the certificate for 25 days, silently.

**Severity:** SEV1
**Duration:** 00:00 - 01:22 UTC

## Impact

- 100% of mobile app API calls failed for 82 minutes.
- 212 partner integrations received TLS errors; 14 partners opened support tickets.
- The web frontend was unaffected because it is served from a different CDN certificate.

## Timeline (UTC)

- **May 8** Renewal attempts start failing with `ACME HTTP-01 challenge: 404`.
- **Jun 2 00:00** Certificate expires.
- **00:04** Synthetic checks fail; `ProbeFailure` alert pages platform on-call.
- **00:19** On-call confirms the certificate expired with `openssl s_client`.
- **00:41** Root cause found: the ACME challenge path was blocked by a new ingress rule.
- **00:58** Blocking rule fixed; cert-manager retries but hits the Let's Encrypt failed
  validation rate limit.
- **01:10** Decision to switch to DNS-01 validation for this certificate.
- **01:22** New certificate issued and loaded by the ingress controller. Resolved.

## Root cause

On May 8, a change to the ingress added a catch-all rule that returned 404 for any path not
matching `/v1/*` or `/v2/*`, to reduce scanner noise. The rule took priority over the temporary
ingress that cert-manager creates for `/.well-known/acme-challenge/*`. Every HTTP-01 challenge
failed from that day on.

## Contributing factors

- cert-manager did emit `Certificate not ready` events, but nobody alerted on them.
- Our certificate expiry alert fired at **7 days** remaining, but it routed to an email list
  that was archived during a team reorg.
- HTTP-01 depends on the public ingress path working, which couples certificate renewal to
  application routing changes.

## Lessons learned

Certificate renewal is a background process that fails quietly. We need alerts on the
*renewal process* (cert-manager readiness), not just on the *expiry date*, and those alerts
must go to a pager.

## Action items

| Action                                                                 | Owner    | Status |
|------------------------------------------------------------------------|----------|--------|
| Alert on `certmanager_certificate_ready_status{condition="False"}` > 1h | platform | Done   |
| Page (not email) at 14 days to expiry for all public certificates      | platform | Done   |
| Move all public certificates to DNS-01 validation                      | platform | Done   |
| Add ACME path exclusion to the ingress chart's catch-all template      | platform | Done   |
| Audit all alert routes that point to email lists                       | sre      | Open   |

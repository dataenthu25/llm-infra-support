---
title: "Postmortem: MTU mismatch on site-to-site VPN caused hanging transfers"
type: postmortem
team: network
tags: networking, mtu, vpn, pmtud
---

# Postmortem: MTU mismatch on site-to-site VPN caused hanging transfers (2025-07-30)

## Summary

After a VPN appliance firmware upgrade in the warehouse data center, large responses between the
warehouse management system (WMS) and our cloud `inventory-api` hung, while small requests worked.
Stock updates were delayed for 3 hours 10 minutes. The cause was an MTU mismatch combined with
blocked ICMP, which broke Path MTU Discovery.

**Severity:** SEV2
**Duration:** 06:05 - 09:15 UTC

## Impact

- Inventory sync from the warehouse was delayed; ~1,800 orders were accepted for items that were
  actually out of stock and had to be cancelled.
- Health checks stayed green the entire time because they use small payloads.

## Timeline (UTC)

- **05:30** Planned firmware upgrade of the warehouse VPN appliance (change CHG-2291).
- **06:05** First `inventory-api` timeouts on `POST /v1/stock/batch`. Health checks pass.
- **06:40** Warehouse team reports "sync stuck" in the shared channel.
- **07:15** Network on-call engaged. `ping` works, TCP connect works, HTTPS for small bodies works.
- **08:20** `tcpdump` shows large segments retransmitted repeatedly with no ACK.
- **08:35** `ping -M do -s 1400` fails, `-s 1300` succeeds: path MTU is below 1400.
- **08:50** Found that the new firmware sets tunnel MTU to 1400 and does not send ICMP
  "fragmentation needed" messages back to the sender.
- **09:05** TCP MSS clamping set to 1360 on the appliance.
- **09:15** Backlog of stock updates processed. Resolved.

## Root cause

The firmware changed the IPsec tunnel MTU from 1438 to 1400. Packets larger than that with the
Don't Fragment bit set must be dropped, and the appliance is supposed to send an ICMP
"Fragmentation Needed" message so the sender lowers its packet size (Path MTU Discovery). The new
firmware had ICMP generation disabled by default. The cloud side kept sending 1438-byte packets
that silently disappeared. Small requests fit in one packet and were unaffected, which is why
the problem looked random.

## Contributing factors

- The change plan had no post-change test with large payloads.
- Health checks and synthetic probes only test small requests.
- It took over an hour to engage network on-call because the symptom looked like an application bug.

## Lessons learned

When "small works, large hangs", suspect MTU first. The quick test is
`ping -M do -s <size> <host>` (Linux) with decreasing sizes until it succeeds.

## Action items

| Action                                                                    | Owner   | Status |
|---------------------------------------------------------------------------|---------|--------|
| Configure TCP MSS clamping on all VPN tunnels as a standard               | network | Done   |
| Add large-payload (64 KB) synthetic check across each VPN                 | network | Done   |
| Add MTU verification step to the VPN change template                      | network | Done   |
| Add "small works, large hangs" to the network triage guide                | network | Open   |

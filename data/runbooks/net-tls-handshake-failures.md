---
title: TLS handshake failures
type: runbook
team: network
tags: networking, tls, certificates, openssl
---

# TLS handshake failures

## Overview

Clients report errors like `certificate has expired`, `unable to get local issuer certificate`,
`hostname mismatch`, or `handshake failure`. The fix depends entirely on which of these it is,
so start by reproducing the handshake yourself.

## Diagnosis

### Inspect what the server presents

```bash
openssl s_client -connect api.example.com:443 -servername api.example.com -showcerts </dev/null
# just the dates and names of the leaf certificate
openssl s_client -connect api.example.com:443 -servername api.example.com </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

Always pass `-servername`. Without SNI, the server may return its default certificate and you
will chase the wrong problem.

### Match the symptom

- **Expired certificate:** check `notAfter`. See `postmortem-2025-06-02-ingress-cert-expiry.md`.
- **Unable to get local issuer certificate:** the server is not sending the intermediate
  certificate. `-showcerts` shows only the leaf. Browsers often hide this (they cache
  intermediates) while curl, Java and Go clients fail.
- **Hostname mismatch:** the requested name is not in the Subject Alternative Names. Wildcards
  only cover one level: `*.example.com` does not match `a.b.example.com`.
- **Handshake failure / no shared cipher:** protocol or cipher mismatch. Old clients may only
  support TLS 1.0/1.1, which our load balancer policy disables. Test with
  `openssl s_client -tls1_2` and `-tls1_3`.

### Mutual TLS between services

For internal mTLS (service mesh), check that the client certificate is valid and issued by the
mesh CA:

```bash
istioctl proxy-config secret <pod> -n <namespace>
```

Certificate rotation issues often appear exactly 24 hours after a mesh CA change.

## Mitigation

- Replace the certificate (or re-trigger cert-manager: `cmctl renew <cert> -n <namespace>`).
- Fix the chain by configuring the full chain file (`fullchain.pem`), not just `cert.pem`.
- If a key partner uses an old TLS version, create a separate listener with a legacy policy
  for their dedicated host name rather than weakening the main endpoint.

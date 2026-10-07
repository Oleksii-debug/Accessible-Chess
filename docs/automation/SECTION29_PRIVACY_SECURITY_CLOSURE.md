# Section 29 — Privacy and security foundation

Status: terminal closure candidate for the canonical Section Plan.

Canonical scope:
- 29.1 data minimization, consent, retention and deletion for students/children;
- 29.2 threat model for server, Classroom, Web, Agent, Media and uploaded files;
- 29.3 secret/token handling, log redaction and permission boundaries;
- 29.4 abuse/moderation/rate-limit policy contracts;
- 29.5 these controls are a hard prerequisite for networked production Sections 30+.

## Existing authorities reused

This Section does not replace existing product owners. The current shipping ancestry already contains Education/Classroom deletion/privacy boundaries, short-lived Classroom join credentials with server-side revalidation, provider-neutral media safe defaults, durable chat/file retention and redaction, secure deletion, scanner/object-store gates, restart recovery, presentation privacy, and typed Agent/Media/Classroom boundaries.

The new `acs.network_security` module is the single cross-network policy gate over those owners. It contains no chess rules, GameTree, classroom roster, account store, media provider, malware scanner or network server implementation.

## Threat model

| Surface | Primary threats | Mandatory controls |
| --- | --- | --- |
| Server | unauthorized mutation, replay, resource exhaustion | authenticated principal, explicit permissions, bounded DTOs, rate limits |
| Classroom | cross-room access, abuse, child-data overcollection | room authorization, moderation, consent, retention/deletion |
| Web | browser identity spoofing, injection, cross-workspace access | trusted middleware identity, strict data contracts, workspace authorization |
| Agent | tool overreach, secret exfiltration, prompt-controlled authority | typed tools, least privilege, log redaction |
| Media | stale credentials, unexpected publishing, recording without consent | short-lived server credentials, safe publish defaults, explicit recording consent |
| Uploaded files | path traversal, malware, quota abuse | opaque-byte handling, safe names, malware/content scan, quota/rate limit |

## Privacy invariants

Ordinary analytics must never carry raw PGN/FEN libraries, book text, chat, uploaded file bytes, audio/video or clipboard content. Aggregate usage counters are a separate data class. Minor/child network processing fails closed unless explicit subject/guardian and organization policy evidence is present. Sensitive data requires a bounded retention rule with deletion and export hooks.

## Secrets and logs

Credentials remain owned by their issuing/authentication layers. Section 29 provides structured log redaction for authorization headers, cookies, credentials, passwords, API keys, join/access/refresh tokens and known raw-content fields. Unknown object values are not serialized into logs by default.

## Abuse, moderation and rate limits

Moderation is role-bounded to configured teacher/co-teacher/admin roles. Every production network operation must match an explicit rate-limit rule; counter implementation is an injected deployment port and fails closed when unavailable.

## Hard dependency for Section 30+

`ProductionSecurityPolicy.gate()` emits a deterministic `SecurityGate` bound to the complete policy digest. Server/application boundaries must call `verify_gate()` during composition. A stale, absent or mismatched gate is rejected before requests are accepted.

## Qualification

Dedicated Section-29 CI compiles the policy/tests on Ubuntu and Windows, proves all six threat surfaces, permissions, minor consent/retention, raw-content analytics prohibition, file scanning, moderation/rate limits, log redaction, and re-runs current Classroom/Media/privacy owners. It statically proves the policy module imports no chess/domain authority.

Physical NVDA/hardware/manual deployment evidence is final whole-product acceptance, not an intermediate Section-29 blocker under Simplified Section Closure Protocol v3.

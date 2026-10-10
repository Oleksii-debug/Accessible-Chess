# Section 35 — Entitlements, subscriptions, billing and organization plans

Canonical plan scope: 35.1–35.5.

## Authority and reuse

- Canonical entitlement authority remains `acs/entitlements.py`.
- Section 35 converges the hardened entitlement policy from PR #813 / exact source `524d286ad5370f847f7ea731c9d0c88829843409`, which itself preserves the cache-TTL/server-time hardening from PR #806.
- No payment vendor, card field, payment credential, provider endpoint or provider-specific product identifier is embedded in product domain code.

## Acceptance map

### 35.1 Neutral entitlement / FeatureGate authority

`FeatureGate`, `EntitlementSnapshot`, `RemotePolicy` and stable `FeatureId` values remain the single provider-neutral entitlement authority. Refresh TTL, server-time floor, bounded grace, expiry, revocation and update-required states fail closed for protected capabilities.

### 35.2 Plan models

`subscription_plans.py` defines stable models for:

- free;
- basic;
- pro;
- teacher;
- organization;
- social-license.

Plan definitions contain capability IDs and allowed billing cadences, not prices or a payment-vendor API. Organization and sponsored/social-license semantics are explicit. `SubscriptionBillingProvider` is a provider-neutral server port for checkout, management and cancellation.

### 35.3 Trial / grace / expired / revoked / update-required

The canonical entitlement state machine and FeatureGate cover trial, paid/organization active states, grace, expired, revoked and update-required. Cache refresh boundaries and local-clock rollback protection are enforced.

### 35.4 Accessible registration / plan / payment / confirmation / manage / cancel UX

`AccessibleChessSubscriptionAsgi` and the semantic HTML/JavaScript subscription client provide:

- public registration entry action;
- native radio/label/fieldset plan selection;
- native select for cadence;
- server-created checkout navigation;
- explicit refresh/confirmation action;
- management navigation;
- two-step cancellation confirmation without a pointer-only or modal-only interaction;
- polite status and assertive error live regions;
- same-origin credential behavior and no popup checkout requirement.

Payment credentials are never collected by this client. The server callback returns only a validated relative or HTTPS navigation target.

### 35.5 Accessibility and user-data safety under subscription state

Accessibility is intentionally absent from the entitlement feature catalog. Keyboard/screen-reader/semantic access is not a paid capability. User-owned local `data.export` and `data.recovery` remain allowed even when entitlement is unavailable, expired, revoked or update-required.

## Closure boundary

Section 35 does not own OAuth/OIDC cryptographic trust, secret storage, payment-processor implementation, pricing, tax/VAT calculation or organization procurement workflow. Those are infrastructure/deployment concerns behind the provider-neutral ports and do not alter the Section-35 product contract.

Manual owner/NVDA evidence remains final whole-product acceptance under Simplified Section Closure Protocol v3.


## Post-merge qualification receipt

Integrated Product authority: `2b8bcd1285511a4732e49be9fe37627ca85bb8ce`.

Post-merge readback preserved eight of nine candidate blobs byte-identically. The ninth path, `tests/test_section35_subscription_closure.py`, differs only by two syntax repairs to Python string quoting in assertions for `tabindex="-1" role="button"` and `credentials: "same-origin"`; the acceptance assertions themselves are unchanged. This qualification branch starts from the integrated Product so the Section-35 gate evaluates the corrected shipping authority rather than the historical PR head.

The exact reused entitlement authority remains supported by completed successful Entitlement Policy Contract run `36265233672`. No known executed Section-35 product RED exists on the integrated authority.

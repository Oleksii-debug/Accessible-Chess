# Security Wave 2 — R15–R27 Product Integration

Status: **STARTED — Phase A (R15–R18 product-facing vertical) implemented on a branch based on shipping with Security Wave 1 already merged.**

This record is intentionally public and contains only the product integration contract. Backend secrets, issuer/signing authority, device-anchor internals, token contents, private repository mapping, and protection configuration do not belong here.

## Integrated in Phase A

### R15 — dedicated pilot boundary
- The desktop UI cannot supply or override a backend endpoint.
- Online authorization endpoints are produced only by the private runtime.
- The public boundary accepts only credential-free HTTPS authorization URLs with no fragment.
- Environment/tenant separation remains private backend policy.

### R16 — native-app login architecture
- Login opens in the **system browser**, never in the embedded Accessible Chess WebView.
- The public product receives only an opaque flow identifier and expiry.
- PKCE/state/nonce/callback processing remains inside the private runtime.
- No permanent desktop client secret is accepted by the public contract.

### R17 — account registration and verification
- Registration uses the same system-browser boundary as login.
- The public product does not collect a password.
- Verification/account-state rules remain server/private-runtime authority.

### R18 — session/token boundary
- Polling takes only an opaque flow identifier.
- The public API has no account-id, device-id, refresh-token, access-token, password or client-secret input.
- A completed browser flow does not itself unlock premium features. The locked shell re-runs the private startup entitlement decision and closes only if that decision is authorized.

## Accessibility
- Login and registration controls are native keyboard-focusable HTML buttons.
- They remain disabled until the private runtime reports online API v2 support.
- Status changes use the existing polite live region.
- Manual signed-entitlement activation remains available as the Wave-1 fallback.

## Compatibility
- Wave-1 runtime API v1 remains accepted for R00–R14 startup.
- Online Wave-2 operations require private runtime API v2+.
- This allows gradual deployment without weakening the already merged offline protection layer.

## Not yet claimed
This branch does **not** claim R15–R27 fully integrated. The next ordered product integration work is:

1. R19 device enrollment binding;
2. R20 authenticated online lease issuance;
3. R21 renewal;
4. R22 revocation;
5. R23 admin control-plane product/backend boundary (no end-user admin secret exposure);
6. R24 telemetry consent/notice;
7. R25 risk/quarantine response;
8. R26 accessible periodic-renewal UX;
9. R27 recovery/device transfer.

Only after those are wired, qualified, and post-merge verified may the full R15–R27 bundle be called integrated.

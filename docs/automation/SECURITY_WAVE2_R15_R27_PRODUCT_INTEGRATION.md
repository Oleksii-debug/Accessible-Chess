# Security Wave 2 — R15–R27 Product Integration

Status: **IMPLEMENTED — QUALIFICATION PENDING**.

This document records only the public Accessible Chess integration contract. Backend secrets, issuer/signing authority, device anchors, account/session tokens, revocation identifiers, private repository mapping, and protection configuration remain outside the public product repository.

## Runtime compatibility

- API v1: merged Wave 1 R00–R14 offline protection.
- API v2: R15–R18 browser/account/session handoff.
- API v3: R19–R27 entitlement lifecycle, consent/privacy, live renewal monitoring and recovery/device transfer.
- API v1 remains backward-compatible with Wave 1.
- A packaged runtime that claims v3 but cannot satisfy the v3 lifecycle fails closed.

## R15 — dedicated pilot/backend boundary

- The public desktop cannot supply or override the backend authorization endpoint.
- Authorization URLs come only from the private runtime.
- The public boundary accepts only credential-free HTTPS URLs without URL fragments.
- Production/staging/tenant separation remains backend/private-runtime policy.

## R16 — native-app login architecture

- Login opens in the system browser, never the embedded Accessible Chess WebView.
- Public code receives only an opaque flow identifier and bounded expiry.
- PKCE/state/nonce/callback handling stays private.
- No permanent desktop client secret is accepted.

## R17 — account registration/verification

- Registration uses the same system-browser boundary.
- Accessible Chess does not collect an account password.
- Verification/invite/account-state logic remains server/private authority.

## R18 — session/token boundary

- Polling takes only an opaque flow identifier.
- Public product methods do not accept account ID, device ID, access token, refresh token, password, authorization code, PKCE verifier or client secret.
- Browser completion alone never unlocks premium content.

## R19 — device enrollment

- Device enrollment is owned inside the private v3 lifecycle operation.
- WebView/public Python supplies no device identifier or platform anchor.
- The product receives only a bounded lifecycle state.

## R20 — online lease issuer

- Lease issuance/signing is private/server authority.
- Public product supplies no account/device/build identity and receives no signing material.
- Successful lifecycle synchronization is followed by a new private startup decision before unlock.

## R21 — lease renewal

- Renewal is performed by the private lifecycle.
- Public product receives only safe state, retry interval and bounded lease-remaining information.
- No local perpetual-authorization switch exists.

## R22 — revocation

- revoked is a fail-closed lifecycle state.
- A v3 revocation result blocks before engine/database/user-data composition during startup.
- A revocation discovered while the product is open closes the premium window and returns to the protected shell.
- Public product cannot choose revocation subjects or call revoke/restore.

## R23 — admin control plane

- There is deliberately **no end-user admin-control API** in Accessible Chess.
- MFA/passkey admin roles, revoke/restore and admin audit stay on the private backend/control plane.
- Public integration tests prohibit admin/revocation mutator methods.

## R24 — security telemetry privacy contract

- UI can read only the bounded security notice and consent state.
- UI can set/revoke consent only for the exact notice version.
- Public product cannot submit arbitrary telemetry events, raw file paths, anomaly codes or identities.
- consent_required is a fail-closed lifecycle state and directs the user to the accessible privacy notice.

## R25 — risk/quarantine

- quarantined is fail closed.
- Product accepts only bounded actions such as re-auth/repair.
- One public UI signal cannot manufacture trust or override risk state.

## R26 — periodic renewal UX

- An authorized v3 startup session is retained host-side, never exported to WebView.
- Before premium composition, the v3 lifecycle is synchronized once.
- While the product window is open, a daemon monitor periodically re-synchronizes.
- renewal_due and network_grace publish bounded accessible aria-live warnings.
- reauth_required, revoked, quarantined, recovery_required, device_limit, consent blocking, or authority failure closes the premium window.
- After clean shutdown, the host opens the protected shell and can rebuild the product only after authority becomes valid again.

## R27 — recovery/device transfer

- Recovery and transfer use system-browser opaque flows.
- WebView supplies no old/new device ID, account ID or transfer quota.
- Private runtime owns proof, ownership, quota, cooldown, revoke/restore and re-enrollment.
- Completion still passes through the R19–R22 lifecycle before premium unlock.

## Accessibility

- Login, registration, recovery, device transfer and consent controls are keyboard-focusable HTML buttons.
- Online controls begin disabled and are enabled only after runtime capability detection.
- Locked-shell status uses the existing polite live region.
- Live renewal/grace warnings are injected into the product document with role=status and bounded aria-live politeness.
- Manual signed-entitlement activation remains available as Wave-1 fallback.

## Compile/package invariant

The production launcher contains the Nuitka directive --include-package=accessible_chess_protection_runtime.

The private runtime is not published in this repository. Production compilation must supply that private package in the build environment. Missing/invalid runtime is not an unlocked fallback: the protected startup boundary fails closed.

## Qualification gate

The dedicated Wave-2 gate compiles the public boundary and the real shipping host, parses the locked-shell JavaScript, runs Wave-1 + Wave-2 regressions on Windows and Ubuntu, and checks that secret/identity injection surfaces are absent.

Full R15–R27 product integration may be called integrated only after the exact candidate is qualified, merged into current shipping, and post-merge read back.

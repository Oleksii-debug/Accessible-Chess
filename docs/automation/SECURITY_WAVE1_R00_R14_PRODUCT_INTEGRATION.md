# Security Wave 1 — R00-R14 product integration

Status: implementation candidate on the current shipping lineage.

## Public/private boundary

The public Accessible Chess repository owns only the product-facing protection
contract, accessible locked-shell presentation, startup ordering and package
inclusion requirement. Protection implementation, production trust configuration,
issuer private material, device-anchor implementation and build-verifier internals
remain outside the public source tree.

## Shipping invariant

For an assembled/frozen release:

1. the private protection adapter must be present in the compiled Windows package;
2. protection authorization runs before user-data upgrade, Stockfish, ACSDB,
   Books/Training or other premium application services are composed;
3. missing, malformed or locked protection state fails closed;
4. a locked user is shown an accessibility-first activation shell instead of the
   premium product;
5. the shell may create the manual activation request and import a signed
   entitlement only through the private adapter;
6. a successful authorization retry proceeds through the unchanged final-product
   composition path;
7. expiry/invalid state never deletes or corrupts user data.

Source/development execution without an assembled release manifest is intentionally
not treated as a commercial packaged release, so repository tests and diagnostics
do not require production credentials.

## Wave-1 scope mapped to R00-R14

- R00-R01: trust and publication boundaries remain policy authorities.
- R02-R06: production artifact/build/provenance/signed-manifest qualification enters
  through the private artifact verifier.
- R07: durable installation identity.
- R08-R10: canonical signed entitlement and local verification/manual activation.
- R11: device binding.
- R12: finite offline lease.
- R13: rollback/clock resistance.
- R14: locked-shell/safe-expiry policy.

No online registration, account sessions, renewal, revocation or recovery service
is claimed here; those belong to the next security wave.

## Qualification rule

Repository integration is not the same as a finished production-distribution
claim. A production Windows candidate additionally requires externally provisioned
production trust configuration/issuer authority and exact packaged-candidate
qualification. Those credentials are never committed to this public repository.

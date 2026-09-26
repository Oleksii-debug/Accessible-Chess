# Accessible Chess — commercial entitlement policy

This document is implementation policy, not a payment-provider specification.

## Product invariants

- Accessibility, keyboard/NVDA operation, semantic text copy, data export and data recovery are never premium capabilities.
- The free local product remains useful: local chess, basic PGN and basic engine access are part of the free floor.
- Product code consumes provider-neutral capability IDs from `acs/entitlements.py`.
- Billing, account transport, signatures and token storage stay behind infrastructure adapters.
- Expiry or subscription cancellation never deletes user-owned local data.
- The current beta remains permissive until an explicit commercial transition is approved.

## Capability groups

Always-available safety capabilities:
- `accessibility.core`
- `data.export`
- `data.recovery`

Free local floor:
- `chess.local`
- `pgn.basic`
- `engine.basic`

Professional:
- advanced analysis
- advanced library/search
- large databases
- full books/training
- ChessBase import
- advanced automation

Coach:
- local Teacher mode
- local Classroom
- assignments
- student progress
- lesson authoring

Organization/network:
- sync
- remote lessons/classrooms
- organization administration/seats
- hosted content

## Commercialization gate

Do not activate paid enforcement until all of the following are separately approved:
1. exact Windows/NVDA human acceptance;
2. safe update/rollback and user-data recovery;
3. accessible account flow;
4. secure token storage;
5. provider-neutral server entitlement policy;
6. privacy/terms/refund process;
7. signed release distribution and dependency/license notices;
8. pilot pricing validation with real users and coaches.

## Failure behavior

Paid-feature denial must be concise and accessible. It must not hide explanations, erase data, break export/recovery, or fall back to inaccessible UI. Network or entitlement-service failure must fail closed only for protected commercial capabilities, not for always-available safety capabilities.

## Architecture boundary

`FeatureGate` is a pure policy evaluator. It does not make network calls, delete data, know payment-provider APIs, or implement chess rules. Payment providers translate external plans into provider-neutral entitlement snapshots at the infrastructure boundary.

# Section 33 — Online Game, multiplayer, spectator and social play

Canonical plan scope: 33.1–33.5.

## Reused authorities

- PR #854 exact source `2f8062bd948a33501be1bac54ee4aa01ed9dba28`: server-authoritative challenge/game/reconnect/rematch/draw/resign and canonical clock/lifecycle composition.
- PR #859 exact source `b92bdec6a099535234157f18451704e2f16a7fa6`: privacy-bounded public player directory, presence and friends/social contracts.
- Section 32 is terminally closed and remains the durable moderated communication/file authority; Section 33 does not create another chat authority.

## Acceptance map

- **33.1 Presence/challenge/accept-decline/rematch:** multiplayer coordination + player directory.
- **33.2 Authoritative synchronized game/clocks/reconnect/draw/resign:** `MultiplayerGameSnapshot`, monotonic trackers and typed intents compose existing `TimeControl` / `ClockSnapshot` / `LifecycleSnapshot`; no chess legality is duplicated.
- **33.3 Spectator/demonstration:** `SpectatorGameView` is an immutable, read-only projection of the server-authoritative game snapshot and exposes no mutation operation.
- **33.4 Friends/social discovery:** player-directory/friend contracts are explicitly identity/account-layer data and contain no position/clock authority.
- **33.5 Optional accessible voice/chat:** optional in the plan; no duplicate implementation is introduced. Existing moderated communication authority may be composed by later Web/cross-product integration.

## Closure boundaries

No Board, GameTree, chess legality, account-authentication, billing or second clock/lifecycle authority is introduced. All online mutations are typed intents against expected authoritative revisions/sequences. Social data cannot publish chess truth.

Manual owner/NVDA evidence belongs to final whole-product acceptance under Simplified Section Closure Protocol v3.

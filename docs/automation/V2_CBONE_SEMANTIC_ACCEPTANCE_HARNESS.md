# Accessible Chess V2 — CBONE semantic acceptance harness

Date: 2026-08-31
Role: ONE-TIME-DEVELOPER-14 / CBONE
Parent owner: PR #358 exact `c6852b6ee5a6158bf0785ef35e4f4bca5fb58d82`

## Verdict before Product work

CBONE remains `BLOCKED`.

The current evidence is sufficient to recognize `.cbone` as a ChessBase whole-database single-file topology, but it is not sufficient to claim semantic read support. The project must not infer that CBONE is a CBH payload, a 2CBH payload, or a container compatible with the existing libcbh/uncbv paths.

The prerequisite chain required for support promotion was not found in this round:

1. no authentic exact `.cbone` bytes with explicit lawful automated-use / CI reuse evidence were qualified;
2. no documented and pinned semantic CBONE reader was qualified;
3. consequently no exact reader license + reproducible semantic backend path was established;
4. no independent PGN/GameTree oracle tied to the exact CBONE bytes was established.

Official ChessBase documentation proves the single-file database identity and open/save use, but does not publish the internal payload semantics. Historical Scidb discussion is negative evidence only: it records that a developer had only recently discovered CBONE and did not know its format. It is not treated as proof that no reader can ever exist.

## Live ownership

PR #358 is still open/draft and remains the exact CBONE real-backend/corpus owner. Later D04/A3 checkpoints retain #358 as the CBONE owner and continue to report `CBONE=BLOCKED`; no successor real semantic decoder/corpus owner was found.

This successor therefore does not edit:

- `acs/chessbase_decoder.py`;
- `acs/chessbase_library_import.py`;
- existing CBH/CBV/CBF/2CBH/CBZ paths;
- capability/support state;
- Stage1 or Windows release files.

## Engineering blocker closed

Before this change, a future CBONE implementation had recognition/integrity primitives and the generic Library/GameTree infrastructure, but there was no CBONE-specific machine acceptance seam that could prove a decoder against independent exact-byte evidence without first wiring it into Product runtime.

`acs/cbone_acceptance.py` adds that fail-closed seam. It is acceptance infrastructure, not a decoder and not an importer registration.

A future decoder candidate must supply an immutable manifest that pins:

- backend name;
- exact 40-hex backend commit;
- SPDX license identifier and HTTPS license evidence;
- exact source SHA-256;
- HTTPS source-rights evidence plus explicit automated-use permission;
- exact independent PGN oracle SHA-256 and provenance evidence;
- exact expected game count.

The candidate function receives the exact fingerprinted `.cbone` path and must return only canonical `PgnGame` values. The harness then:

1. fingerprints the source before execution;
2. requires source SHA-256 to match the manifest;
3. verifies the oracle text SHA-256 and bounded size;
4. executes the injected decoder candidate without assuming CBH/2CBH/container semantics;
5. fingerprints the source after execution and rejects all decoder output if bytes changed;
6. rejects non-canonical output and non-contiguous source indexes;
7. replays every decoded game through canonical `validate_game_legality()`;
8. parses and independently validates every oracle game through the same canonical legality path;
9. compares exact ordered canonical `record_digest` identities;
10. serializes decoded games through the canonical PGN serializer, reopens them, revalidates legality, and requires exact semantic record identity after reopen.

The returned report intentionally has no `supported` or `safe_to_import` property.

## What this does not prove

Synthetic tests prove only the harness contract. They do not prove any byte of CBONE semantics and cannot change capability state.

A real acceptance run still requires all four external prerequisites above. After that, Product activation additionally requires the existing atomic Library publication, Search/Open, source provenance, cancellation/resource controls and applicable Windows runtime gates. Passing this harness is necessary evidence, not sufficient support authorization.

## Capability truth

`CBONE=BLOCKED`

`support_promotion_allowed=false`

`runtime_importer_registered=false`

`fake_decoder_added=false`

`NVDA_VERIFIED=NO`

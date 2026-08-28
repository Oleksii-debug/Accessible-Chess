# Version 2 CBZ crash-residue recovery

ROLE=V2-CHESSBASE-FORMATS
UTC=2026-08-28
PARENT_PR=330
PARENT_SHA=3affc9e40e7416a7d680c537b271dd8718f8fce3
SWARM_LANE_KEY=ACCESSIBLE-CHESS-V2-CBZ-CRASH-RESIDUE-RECOVERY-20260828

## Scope

This package closes one security/lifecycle blocker left by the bounded CBZ
executor: a hard process termination can leave private decrypted staging under
the output parent. It does not promote ChessBase CBZ support and does not add
a generic temporary-directory cleaner.

`CBZ=BLOCKED`.

The only Product path changed is `acs/cbz_extractor.py`. Stage 1, the canonical
chess core, GameTree, Library/ACSDB, the existing CBV extractor, Windows/NVDA
UI, backend packaging and capability authority remain outside this package.

## Ownership and deletion authority

Each newly created CBZ private workspace contains a small versioned marker.
The marker stores only:

- schema version;
- fixed purpose identifier;
- exact generated workspace directory name;
- owner process ID;
- creation timestamp.

It contains no password, source path, output path, backend path, PGN data or
other private user content.

Recovery requires an explicit trusted parent directory from the caller. It
never chooses or scans the system temporary directory by itself. A directory
is eligible for automatic deletion only when all of these checks succeed:

1. its name uses the dedicated CBZ private-workspace prefix;
2. it is a real directory rather than a symlink/reparse/non-directory object;
3. its marker is a bounded regular file with exact schema and no duplicate or
   extra JSON keys;
4. the marker is bound to the exact candidate directory name;
5. its creation time is older than the configured minimum;
6. its owner PID is positively observed as not running;
7. the full candidate can be measured without unsafe filesystem objects and
   without exceeding entry/byte bounds;
8. marker identity, dead-owner state and resource/safety scan are revalidated
   immediately before deletion.

Any uncertainty preserves the directory. PID reuse can therefore retain stale
material, but cannot authorize deleting an active workspace.

## Resource and privacy bounds

Defaults are intentionally conservative:

- minimum age: 3600 seconds;
- recovery-root scan: at most 4096 entries;
- one workspace: at most 8192 filesystem entries;
- one workspace: at most 16 GiB;
- marker: at most 4096 bytes.

The root scan bound is evaluated before any candidate is deleted, so an
overcrowded recovery root fails closed without partial cleanup. Per-workspace
entry/byte overflow, symlink/reparse/nonregular content, malformed markers and
active/fresh owners are preserved rather than recursively followed.

The public recovery result is aggregate counts only. It does not contain
private filesystem paths.

## Legacy residue boundary

Workspaces created before this marker contract are deliberately not deleted
automatically. Their name alone is not sufficient evidence of ownership.
Cleaning such historical residue requires separate explicit operational
handling; this package does not guess.

## Verification contract

`tests/test_v2_cbz_crash_recovery.py` covers:

- stale marker-qualified dead-owner cleanup;
- fresh and active workspace preservation;
- owner-state recheck immediately before deletion;
- unmarked and duplicate-key marker refusal;
- marker/workspace-name binding;
- symlink fail-closed behavior where the platform permits test creation;
- per-workspace resource bounds;
- root scan atomicity before deletion;
- path-free recovery reporting;
- machine-readable no-overclaim contract.

The dedicated Actions workflow executes that contract on Ubuntu 22.04 and
Windows Server 2025, re-runs inherited secure-CBZ tests, runs the exact pinned
`antoyo/uncbv@3c18e8a7c6a30c21f945a1ab5462521c306dca57` CBZ fixture path, and runs
the full repository unittest and pytest regressions.

## Remaining blockers

This recovery API is not yet wired into the Windows trusted host, and no
automatic startup cleanup is claimed. That integration belongs to the Windows
host/composition owner and must use this bounded API rather than invent a
second cleaner.

CBZ semantic support remains independently blocked by the absence of a
lawfully reusable real ChessBase-generated CBZ plus automatable password and an
independent PGN/GameTree/metadata oracle demonstrating the complete canonical
import/export/reopen journey.

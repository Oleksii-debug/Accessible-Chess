# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1421
REVISION: 1
SOURCE_RUN: 20260823-1421
EFFECTIVE: next worker/DEV5 invocation after 2026-08-23T11:21:29Z cutoff.

1. Accepted Stage1 Product authority is now exactly `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`. Prior `80720e8...` is historical comparison only and must not be packaged.
2. AUDIT_MASTER acceptance is recorded on PR #167 comment `5385692188`; DEV5 controlled promotion is complete. Promotion gate PR #172 / run `32635759733` is terminal GREEN on Ubuntu and Windows.
3. No developer may create another Stockfish resolver privacy implementation or another Stage1 promotion line unless a new exact accepted-source defect is independently proven.
4. Exactly one candidate WIP is authorized: DEV5 PR #175 / head `17697b8181781c3a35f12ba522c25852d268eefc` / run `32636245736`. At cutoff it is IN_PROGRESS. Do not launch, cancel, rerun, retarget or duplicate it merely to chase GREEN.
5. While V5 is active, all lanes must remain SAFE OVERLAP with respect to Stage1 Product, release harness, packaging and candidate artifact.
6. DEV1: UI/NVDA source evidence is already sufficient. PR #169 stays closed duplicate. PR #173 is supporting evidence only; no new Product/UI package for the same Stage1 repair.
7. DEV2: canonical-core evidence on `1e9d23b...` already exists. PR #174 targets an older intermediate head and is non-authoritative for current Stage1. Separate PR #171 (`acs/history.py`) is terminal GREEN P1 work but must remain out of the active candidate source until V5 decision.
8. DEV3: PR #168 stays closed superseded. PR #176 is unique and useful real Stockfish 18 Windows evidence, terminal GREEN; do not repeat that smoke unless Product/runtime source changes.
9. DEV4: repair validation is complete; no more parallel resolver/privacy repair PRs without a new independent defect on accepted `1e9d23b...`.
10. DEV5: while V5 runs, coordination/readback only on touching release surfaces. First action on continuation is always live run/job readback for `32636245736`.
11. DEV-A: PR #170 remains separate Full Product Teacher/Classroom lane work and is not Stage1 candidate input. Do not merge or duplicate it during the release freeze.
12. DEV-B remains historical/stale for the current P0 unless a newer explicit handoff assigns touching ownership. DEV-C remains coordination/read-only for this P0.
13. PR #160/V4 and all artifacts from old `80720e8...` are invalid/obsolete. Do not repair, relabel or surface them.
14. Historical packaged Move Edit SetValue/Ctrl+A/Ctrl+C classification is superseded only by V5 exact strict evidence. Preserve native keyboard/clipboard acceptance and element identity; never convert a precondition/observability failure into an inferred Product Ctrl+A/Ctrl+C defect.
15. If V5 terminal GREEN: verify exact accepted source/frozen identity, all machine gates, candidate ZIP reopen/hash/manifest identity and artifact metadata. Only after exact artifact verification may `FRESH_WINDOWS_CANDIDATE=YES`.
16. If V5 terminal RED: classify exact first failing gate before any repair; no test weakening, no speculative Product change, no automatic second candidate chain.
17. Persistent Full Product exact-GREEN authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` until Stage1 release freeze/human candidate decision completes.
18. Old rejected ZIP, PR #54 and frozen refs remain untouched. No force-push, skip, xfail, assertion weakening or duplicate implementation.
19. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` at this cutoff.

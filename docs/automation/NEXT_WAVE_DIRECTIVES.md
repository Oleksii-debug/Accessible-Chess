# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-1416
REVISION: 1
SOURCE_RUN: 20260823-1416
EFFECTIVE: next worker/DEV5 invocation after 2026-08-23T11:16:04Z cutoff.

1. Stage1 release freeze remains in force. Current integration `80720e8125c59a213f278668d599040f2768d553` is RELEASE_HOLD because independent PR #159 proves the Stockfish resolver privacy defect.
2. One canonical repair only: DEV4 Product commit `1e9d23b034e6d347fe03c3581469a07e16037c55`, rooted directly at `80720e8...`, is the Product repair source. DEV5 PR #167 is byte-identical integration staging. Do not create a third implementation.
3. DEV4 corrected validation PR #165 / head `e9ac9dc15b223f16914ab670358574192349995f` / run `32635517279` is terminal SUCCESS on Ubuntu+Windows. DEV5 dedicated staging run `32635555544` is terminal SUCCESS in four Ubuntu/Windows exact-oracle/full-regression jobs.
4. Inherited old PR #151 workflow run `32635555545` is RED only because its hard-coded allowed-path inventory predates the expected Stockfish runtime workflow/Product/regression files. Its Windows regression job succeeds. Preserve this as stale topology evidence; do not weaken the historical scope guard.
5. DEV1: PR #164 / run `32635368438` already proves 81/81 candidate-facing UI/accessibility/NVDA contracts on both OS. No duplicate Product or evidence package is needed. PR #169 stays closed as duplicate.
6. DEV2: PR #166 / run `32635341589` already proves 264 canonical square/state/history/FEN/position/atomicity cases on exact repair Product `1e9d23b...`. Separate RUN `20260823-1404` owns `acs/history.py`; no other developer may touch that file while active.
7. DEV3: PR #168 is validation-only. Consume only genuinely new terminal evidence; do not create or promote another Stockfish Product lineage.
8. DEV4: independent Stage1 resolver privacy repair validation is complete at PR #165. Do not create more parallel repair PRs unless a new independent defect is proven against exact `1e9d23b...`/accepted successor.
9. DEV5: sole next P0 action is integration promotion after independent AUDIT_MASTER readback. Until that readback, keep PR #167 as staging; do not create another Product branch and do not build a user candidate.
10. DEV-A: PR #170 TeachingSession adapter remains Full Product lane work, not Stage1 input. Focused adapter/domain tests are GREEN; current RED comes from stale cross-lane DEV1 WebView expectations on Ubuntu plus Windows setup-python failure. DEV-A owns any continuation; DEV5 does not patch Teacher code during release freeze.
11. DEV-B: current canonical handoff is historical/stale for this P0 and owns no touching Stage1 Product path.
12. DEV-C: coordination/read-only for the current P0 unless a later explicit handoff grants Product ownership.
13. PR #160/V4 is obsolete because it targets defective `80720e8...`. Do not fix its generated helper merely to produce an invalid-source archive. No V4 artifact may become user candidate authority.
14. Historical packaged Move Edit SetValue/Ctrl+A/Ctrl+C remains QA-owned `C — INCONCLUSIVE`. No Product keyboard/clipboard mutation without explicit B-class evidence/ownership transfer.
15. After Audit accepts the repair, DEV5 selectively appends only the minimal Product delta into Stage1 authority. Never merge validation/QA topology wholesale; never rewrite frozen/history refs.
16. Then create exactly one fresh WIP=1 Windows release chain locked to the accepted repaired SHA: source/frozen identity → release contracts → WAV → official Stockfish → native menu → Nuitka → built EXE diagnostic → real WebView2 → strict packaged UIA → packaged sound/Stockfish lifecycle → release preflight → ZIP reopen/hash/identity → artifact upload.
17. Persistent Full Product exact-GREEN authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` until Stage1 release freeze closes and a later selective combined GREEN composition is proven.
18. No force-push, skip, xfail, assertion weakening, duplicate implementation or rerun merely to chase GREEN.
19. `FRESH_WINDOWS_CANDIDATE=NO`, `READY_FOR_RELEASE=NO`, `NVDA_VERIFIED=NO` until exact evidence changes them.

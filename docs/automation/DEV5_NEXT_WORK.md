# DEV5_NEXT_WORK

SOURCE_RUN: 20260823-1421
MODE: V5_WIP1_OBSERVE_THEN_CLASSIFY

1. Accepted Stage1 authority is `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`. Live compare must remain identical before any release conclusion.
2. AUDIT_MASTER accepted exact repair/staging head `a06c81e424c599f996662e8898c2b1cbf8ee9dbd` in PR #167 comment `5385692188`; controlled promotion has already materialized as the one-commit/one-Product-file Stage1 fast-forward to `1e9d23b...`.
3. Promotion gate PR #172 / run `32635759733` is exact GREEN Ubuntu+Windows. Do not create another promotion gate unless new Product mutation occurs.
4. PR #175 / head `17697b8181781c3a35f12ba522c25852d268eefc` / run `32636245736` is the sole fresh Windows candidate WIP=1. Do not launch, rerun, cancel, edit or duplicate the chain merely to obtain green.
5. First action on every continuation while V5 is active: read the latest attempt/job steps for run `32636245736`. Do not rely on stale PR text.
6. If V5 is terminal GREEN, independently verify every release-critical step: exact source + frozen identity; regressions/privacy; retained QA topology; bounded SetValue helper identity/semantics; WAV; official Stockfish; native menu; Nuitka standalone; built EXE diagnostic; real WebView2; strict UIA classification; packaged sound/Stockfish lifecycle and orphan cleanup; release preflight; ZIP reopen/hash/manifest identity; artifact upload. Fetch artifact metadata and verify exact accepted Product SHA before setting `FRESH_WINDOWS_CANDIDATE=YES`.
7. Only if the complete chain and artifact identity are GREEN, and the only remaining gate is Oleksii's personal NVDA check, user-facing response must begin exactly `Тепер тестуєте ви через NVDA.` Until then never use that phrase.
8. If V5 is RED, classify the FIRST real failing gate as Product / QA-harness / environment / inconclusive before any code change. Preserve Ctrl+A/Ctrl+C native acceptance; do not infer a later clipboard defect from a precondition failure.
9. Do not fix/reuse PR #160/V4. Its source `80720e8...` is obsolete/defective and its artifact line is forbidden.
10. Do not create more Stockfish privacy implementations or duplicate evidence. DEV3 #168 is closed superseded; DEV1 #169 is closed duplicate. PR #176 is unique real Stockfish 18 evidence and already GREEN.
11. DEV1 #173 is supporting evidence only; no Product change is authorized. DEV2 #174 targets an older intermediate repair head and is not current Stage1 authority.
12. DEV2 PR #171 is a separate narrow P1 `acs/history.py` fail-closed repair with terminal GREEN CI; keep it out of the active Stage1 candidate source until V5 release decision, then consider selective post-candidate intake.
13. DEV-A PR #170 remains Full Product Teacher/Classroom lane work; do not mix it into Stage1 candidate source or duplicate it in DEV5.
14. Persistent Full Product authority remains `dd9ebf9414103c805892856fe6a04706fa69039f` through the release freeze.
15. Old rejected ZIP, PR #54 and frozen refs remain untouched.
16. No force-push, skip, xfail, assertion weakening, duplicate Product implementation or CI manipulation merely to chase GREEN.

At cutoff: V5 run `32636245736` is IN_PROGRESS; no candidate ZIP exists yet.
FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO

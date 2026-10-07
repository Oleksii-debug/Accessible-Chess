# Section 32 closure audit — Remote Classroom

Canonical plan revision: `AHj4eMRgmsXXWqlCWeR_5F-46Ih3m_cfXBnu0AmnMUpGQPqYY1C4kuw6vk_it1ujhxcUx6rkI7tx6mcmEDrW7XxWNQQ2k4X3Ko91JiCnng`.

Owner-directed out-of-order closure target: **SECTION 32 — Remote Classroom: sync, audio, chat, files, video і lesson recording**.

## Fixed acceptance map

- **32.1 Durable synchronized board/GameTree/pointer/annotations/active student/answers.**
  Existing shipping authorities are retained: `remote_session.py`, `teaching_session.py`,
  `teaching_reverse_channel.py`, `teaching_visual_board.py`, durable Education records,
  pairing and prepared-position deployment. No second chess authority is introduced.
- **32.2 Audio/video provider behind neutral compliant ports; safe default permissions.**
  Existing `classroom_realtime_media.py` remains the policy/controller authority. This
  candidate reuses the already-developed join/media transaction, provider-execution,
  binder and WebView transaction boundaries plus the pinned server-only LiveKit join
  token issuer. Provider credentials remain server-side and are never persisted here.
- **32.3 Accessible chat/moderation and file transfer with durable recovery.**
  Reuses the canonical collaboration SQLite, chat RPC/HTTP/server, file RPC/server/HTTP,
  and accessible collaboration projection from the prior Classroom lineages. File bytes
  remain opaque behind storage/scanner ports; retries, sequence/revision conflicts and
  quotas fail closed.
- **32.4 Reconnect/idempotency/group lessons/individual boards.**
  Existing remote event log, media reconnect, durable operation receipts, Classroom
  groups, lesson sessions, pairing and prepared-position deployment remain canonical.
  Reused collaboration/media components preserve operation/revision identities.
- **32.5 Lesson recording/history only through explicit privacy/consent/storage policy.**
  `classroom_lesson_recording.py` is a provider-neutral history/authority boundary.
  Provider start is not called unless every participant grants consent to the exact
  digest-bound policy. Policy explicitly fixes storage region, retention period and
  permitted data classes. Stop/delete are idempotent; the ledger stores only metadata
  and provider references, never media bytes or credentials.

## Safety and ownership boundaries

This Section does not own chess legality, GameTree serialization, account authentication,
cloud deployment, multiplayer/social play, or final release packaging. It does not set
`HUMAN_TESTED` or `NVDA_VERIFIED`; those remain final whole-product acceptance under
Simplified Section Closure Protocol v3.

## Qualification

The dedicated `Section 32 Remote Classroom` workflow runs the exact candidate on Ubuntu
and Windows. It compiles the complete `acs` package and executes synchronized classroom,
teaching, durable education, recording, collaboration/file and provider-neutral media
transaction suites. A known failing check is a blocker. Hosted-runner non-execution may
only be treated according to Simplified Section Closure Protocol v3.

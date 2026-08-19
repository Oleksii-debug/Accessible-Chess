# Accessible Chess shared contract schemas

These JSON Schema 2020-12 files describe the language-neutral v1 boundary for
future Windows, Web, Mobile, Teacher, and Classroom adapters.

- `interaction-message-v1.schema.json` is a discriminated union. `family` and
  `version` are mandatory; additional fields are rejected.
- `presentation-state-v1.schema.json` contains presentation/session data only.
  It does not contain Position, FEN, legality, or move history.
- Golden examples live in `tests/fixtures/interaction_contracts/v1` and are
  round-tripped through the production Python serializers in automated tests.

The schemas do not enable Stage 2 behavior and are not wired into the frozen
Stage 1 release. A breaking change requires a new schema version and an explicit
migration path; do not silently reinterpret a v1 payload.

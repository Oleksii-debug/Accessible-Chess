# Accessible Chess shared contract schemas

These JSON Schema 2020-12 files describe the language-neutral v1 boundary for
future Windows, Web, Mobile, Teacher, and Classroom adapters.

- `interaction-message-v1.schema.json` is a discriminated union. `family` and
  `version` are mandatory; additional fields are rejected.
- `presentation-state-v1.schema.json` contains presentation/session data only.
  It does not contain Position, FEN, legality, or move history.
- Positive and negative conformance examples live in
  `tests/fixtures/interaction_contracts/v1`. Positive examples round-trip
  through the production Python serializers. Negative examples must be
  rejected by both JSON Schema and the production readers, including scalar
  type mismatches that a permissive language might otherwise coerce.

The schemas do not enable Stage 2 behavior and are not wired into the frozen
Stage 1 release. A breaking change requires a new schema version and an explicit
migration path; do not silently reinterpret a v1 payload.

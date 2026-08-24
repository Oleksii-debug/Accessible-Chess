# WordDeck R4c — Accessibility / Release / Security matrix

This matrix is the Developer03 Foundation acceptance contract. Source self-tests, Windows UIA and human NVDA are separate evidence classes.

| Area | Machine source/self-test | Exact Windows UIA | Human NVDA |
|---|---|---|---|
| Recall English Up/Down next/true-previous | required | required | required |
| Ukrainian translation native arrows | required | required | required |
| Dictionary/Scope/Deck native arrows + focus retention | required | required, repeated cycles | required |
| Menu arrows stay menu-local | policy/source | required | required |
| Spelling selectors and answer native keys | required | required | required |
| Sentence selectors and answer native keys | required | required | required |
| Shortcut context isolation / unsafe keys | required | interaction smoke | required |
| F1 reflects live Recall/Spelling/Sentence bindings | required where deterministic | required | required |
| Shortcut capture Enter/Escape | source/settings logic | required | required |
| Alt+F4 standard close, not rebindable | required | required | required |
| Full profile export/import cancel paths | user-data tests | required | required |
| Reset cancel / no mutation | user-data tests | required | required |
| State migration/backup/recovery/fail-closed import | required | dialog smoke | targeted human confirmation |
| No private state/secrets/personal paths | required scan | n/a | n/a |
| No-admin/offline contract | required scan/runtime | launch-form artifact | user environment final check |
| Spaces + Cyrillic portable path | required exact artifact test | exact published EXE | optional final user check |
| Self-contained publish / published EXE self-test | required | same exact EXE | same candidate only |
| SentencePack production disclosure/provenance | required | safe empty/import shell | readable disclosure/status |
| Physical NVDA PASS | never inferred | never inferred | human-only |

## Fail-closed rules
- UIA skipped is not PASS.
- An older green head does not prove a newer exact head.
- A script existing in source is not execution evidence.
- Synthetic SentencePack fixtures must never be called production data.
- Missing production SentencePack must be graceful and textually explained.
- Accepted V0.1 must not be overwritten by a Foundation candidate.
- A failed critical gate cannot publish a green exact-tip acceptance status.

## Integration guidance
Prefer reusing current canonical learning/state behavior. Developer03 worker changes should be acceptance infrastructure, docs or narrowly proven accessibility repairs. Never whole-branch merge a stale worker over newer canonical shared files. If a real UIA failure proves a product defect, fix it narrowly on the isolated worker and tell Developer01 exactly what behavior/file needs selective integration.

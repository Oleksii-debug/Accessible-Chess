# DEV4 ChessBase Capability Matrix

Evidence snapshot for the current Full Product QA lane. This matrix separates safe family recognition/provenance from actual proprietary decoding. A recognized suffix is never treated as decoder support.

| Extension | Current state | Evidence-backed capability | Explicitly not proven |
|---|---|---|---|
| `.cbh` | PARTIAL | Primary-source recognition; classic same-stem companion discovery; bounded SHA-256 integrity/manifest evidence for existing files; read-only source intent | No verified CBH/CBG game decoder; no lossless game/variation/annotation import |
| `.cbg` | BLOCKED | Recognized as game/move/variation component; can be discovered as a CBH companion and fingerprinted | Standalone import and proprietary move/variation decoding are not verified |
| `.cbp` | BLOCKED | Recognized as player index/component; can be discovered/fingerprinted as companion evidence | Player-record decoding/encoding semantics are not verified |
| `.cbt` | BLOCKED | Recognized as tournament index/component; can be discovered/fingerprinted as companion evidence | Tournament/event-record decoding semantics are not verified |
| `.cbv` | PARTIAL | Recognized as a primary archive/container and can be fingerprinted as immutable evidence | Archive extraction/container semantics and contained database decoding are not verified |
| `.cbf` | PARTIAL | Recognized as a primary legacy database source and can be fingerprinted | Legacy database record/game decoding is not verified |
| `.2cbh` | PARTIAL | Recognized as a primary single-file database source and can be fingerprinted | Record/game decoding and compatibility claims are not verified |
| `.cbone` | PARTIAL | Recognized as a primary single-file database source and can be fingerprinted | Record/game decoding and compatibility claims are not verified |

## Security/evidence caveats

1. Current family recognition is filename/layout evidence only. `decoder_available` remains false in the adapter and `safe_to_import` therefore remains false.
2. Current QA PR #67 locks a PROVEN_PRODUCT_DEFECT: filesystem symlink/reparse indirection is followed by shared provenance/integrity/manifest paths instead of failing closed.
3. Current QA PR #67 also locks a PROVEN_PRODUCT_DEFECT for unbounded full-text PGN reads. This is a generic import resource boundary and is not evidence of ChessBase decoder behavior.
4. Current report/provenance DTOs expose absolute local paths in `ChessBaseSourceProbe.as_report_fields()`, `ChessBaseIntegritySnapshot.as_report_fields()` and `ChessBaseBundleManifest.as_dict()`. The DEV4 QA path-privacy gate requires serialized report/persisted metadata to avoid leaking workstation/build paths.
5. Hashing is chunked, but bounded hashing alone is not proprietary decoding support.
6. Unknown or unsupported format/version semantics must remain BLOCKED/UNSUPPORTED rather than being heuristically decoded.

## Promotion rule

An entry can move from BLOCKED/PARTIAL toward SUPPORTED only after an evidence-backed decoder slice exists, canonical legality/state validation passes, original source remains immutable, corruption/truncation/resource limits are fail-closed, provenance is complete without private-path leakage, and round-trip/loss claims are demonstrated rather than inferred.

# Section 0 convergence candidate

Status: **CANDIDATE — exact-head CI required before DONE**

This is the durable Section 0 convergence receipt. It does not replace the canonical chess core and it does not promote blocked/unsupported format families.

## Current ancestry

- pre-Section-0 application/GameTree apex: `5854b528fbd3632cfa69553a70973123eaf14b54`
- authority-boundary lineage #2329: `c61fbc8f1381ddec05109532f907595c2a7c9aaf`
- current fail-closed ImportReport lineage #2330: `633244a659b7998acddd34bef79b5e511d2990a3`
- current capability-matrix lineage #2328: `6f8ae8547dfe7c0f15ed124bc0f44a6c660c0056`
- current convergence receipt: `905df1412bda89774d265df0f6bd0ba38ec6d91f`
  - first parent: #2330 `633244a659b7998acddd34bef79b5e511d2990a3`
  - second parent: prior convergence `2a5b410635bf6df4d97983f30cc745568f83c212`
  - third parent: #2328 `6f8ae8547dfe7c0f15ed124bc0f44a6c660c0056`
- original two-parent lineage receipt retained in ancestry: `0bc9dd57d41f047e0c259af3dcf8b2791cac23d3`

No owner branch was force-pushed or rewritten. The final tree intentionally retires the now-stale component capability workflow; one exact convergence workflow below owns qualification for the composed contract.

## Section 0 acceptance mapping

- **0.1 — one Position / Move / SAN / FEN / GameTree / Game / provenance authority.** `docs/FORMAT_AUTHORITY_BOUNDARIES.md` binds the existing canonical modules; format adapters do not become a second chess-rules authority.
- **0.2 — application publication boundaries.** Format ingestion/publication is constrained to the existing application/chess authorities and provenance contracts.
- **0.3 — capability matrix.** `acs.format_capabilities.FORMAT_CAPABILITIES` is the typed read/edit/write/round-trip authority with `SUPPORTED/PARTIAL/UNSUPPORTED/BLOCKED` states. Current owner corrections are preserved: Markdown read remains `PARTIAL` pending a lawful real corpus; DOCX and PDF/OCR remain `UNSUPPORTED`. 2CBV and 2CBZ remain explicitly `BLOCKED`, not inferred from recognition evidence.
- **0.4 — lineage convergence.** #2329/#2330 and #2328 are all ancestors of the current receipt. The convergence branch is the single composed Section 0 candidate rather than another competing format implementation.
- **0.5 — malformed/partial reporting.** Shared `ImportReport`, `ImportedRecord`, `SourceFingerprint` and `ImportRegistry` fail closed on active/malformed provenance shapes and retain explicit FULL/PARTIAL/DAMAGED/WARNING evidence.

## Explicit external/no-overclaim state

Full semantic CBF/CBI, 2CBV, 2CBZ, CBZ, 2CBH and CBONE support is **not** claimed. Lawful fixtures, independent semantic oracles, decryption/decoder qualification or configured external backends remain represented as BLOCKED/PARTIAL/UNSUPPORTED exactly as the typed matrix states.

## DONE gate

Section 0 is not DONE merely because this receipt exists. The exact PR head must pass the dedicated convergence workflow on Ubuntu 22.04 and Windows 2025. Queued, pending, cancelled or stale-head Actions are not PASS. Any later source/head movement requires re-qualification.

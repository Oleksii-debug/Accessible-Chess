# Release compliance evidence

This workline is intentionally separate from the active P0 Windows/NVDA release path. It does not change chess rules, PGN, Books, Library, accessibility behavior, packaging behavior, or the acceptance state of the current Windows candidate.

## What this evidence proves

`tools/generate_release_compliance.py` produces two deterministic files from one exact repository commit:

- `accessible-chess.spdx.json` — an SPDX 2.3 file-level inventory of the declared runtime/release-input scope;
- `accessible-chess.provenance.json` — exact source commit, product version, declared scope, per-file SHA-256 hashes, and a digest over the canonical inventory;
- `accessible-chess.evidence.sha256` — deterministic SHA-256 manifest binding the two JSON evidence files for later byte readback.

The default scope is the shipping application/runtime material currently owned by this lane: `acs/`, `web/`, `packaging/`, both V2 launchers, `VERSION.txt`, and the shipped Ukrainian/English hotkey references.

The generator rejects missing inputs, path traversal, symlinks, malformed or non-current source commit identity, scoped uncommitted runtime bytes, and timezone-free timestamps. Verification regenerates the evidence from the exact clean Git source tree and requires byte-for-byte equality, including the checksum manifest.

## Claims deliberately not made

This evidence is not a license scanner and does not infer legal ownership from file names or source text. SPDX package/file license fields therefore use `NOASSERTION`. The package is marked `filesAnalyzed=false` because this is a bounded runtime-input inventory, not a claim that every repository or third-party build component has been fully analyzed.

The evidence also records:

- `human_tested=false`;
- `nvda_verified=false`;
- `final_windows_zip=false`;
- `license_inference_performed=false`.

Generating or verifying these files cannot promote any of those states.

This first compliance slice does **not** claim code signing, secure automatic update, vulnerability-disclosure handling, support-lifecycle policy, formal regulatory conformity, or a complete third-party dependency SBOM. Those require separate authorities and evidence.

## Qualification

The dedicated Linux and Windows workflow compiles the generator, runs focused adversarial regressions, generates the evidence twice from the exact checked-out commit, proves byte determinism, verifies the first copy against the source tree, and requires a clean Git worktree afterward.

Manual equivalent:

```text
python tools/generate_release_compliance.py generate --root . --source-commit <40-hex-commit> --created <RFC3339-time> --output-dir <directory>
python tools/generate_release_compliance.py verify --root . --source-commit <same-commit> --created <same-time> --evidence-dir <directory>
```

Release/P0 integration remains owned by the canonical Full Product and release-control lineages. This compliance work must not be used to bypass their exact-head CI, fresh-extraction checks, artifact readback, human acceptance, or physical NVDA verification.

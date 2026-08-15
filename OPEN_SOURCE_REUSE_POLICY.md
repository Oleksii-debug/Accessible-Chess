# Accessible Chess — reuse-first open-source policy

## Goal

Do not reimplement mature generic chess infrastructure when a well-tested, license-compatible component can be adopted safely. Reuse must reduce delivery time and defect risk without sacrificing NVDA accessibility, modular boundaries, data fidelity, security, or the option to distribute Accessible Chess as a closed-source/commercial product later.

## Mandatory decision rule

Before implementing a generic capability from scratch (move legality, PGN/FEN parsing, board widget, engine protocol, database codec, importer, OAuth helper, etc.), perform a bounded reuse scan and record the choice:

1. candidate component/repository and exact version/commit;
2. license and redistribution obligations;
3. maintenance/activity and test quality;
4. compatibility with our architecture and accessibility contract;
5. data-loss/format limitations;
6. whether direct adoption, adaptation, separate-process integration, or clean implementation is safest.

Do not replace working Accessible Chess code merely because an external library exists. Adopt only when the migration is smaller and safer than maintaining our current implementation.

## License policy

Preferred for code embedded in the proprietary/closed-source-capable core or web client: MIT, BSD-2-Clause/BSD-3-Clause, Apache-2.0, ISC and similarly permissive licenses. Preserve required notices and attribution.

GPL/AGPL code must NOT be copied, pasted, linked, imported, bundled into the same combined work, or used as a client-side web component without an explicit repository-level licensing decision. GPL/AGPL projects may still be studied for public interfaces, behavior, tests, protocols and architectural ideas, but code reuse must respect the license.

A GPL program that is designed to run as a separate process may be integrated through a documented protocol when legally compatible. Current example: Stockfish through UCI as a separate executable, with the exact Stockfish license/source offer/source pointer required by its GPL distribution terms.

Never copy proprietary ChessBase/Fritz/Chess.com code. Their public behavior, documented APIs, file samples owned/provided by the user, published specifications and independently licensed open-source readers/converters may be used as evidence. Proprietary source files remain read-only.

## Immediate high-value candidates

### ChessBase CBH/CBG family

Evaluate `asdfjkl/cbh2pgn` (MIT) as a decoder reference/brick. Its own repository says it currently handles standard games and variations but not annotations and depends on `python-chess` for chess operations. `python-chess` is GPL-3.0-or-later, so do not simply add the whole dependency to a closed-source-capable Accessible Chess build.

Preferred experiment: reuse or adapt only the MIT-licensed CBH/CBG decoding portions behind `acs/chessbase_*` adapters, preserving the MIT notice, and connect them to our own neutral GameTree/chess core instead of importing `python-chess`. Keep source read-only. Validate on provided samples, compare move trees and metadata, and report partial/unsupported fields exactly.

Do not claim full ChessBase compatibility from the converter: it explicitly does not convert annotations and has other limitations.

### PGN/FEN/chess rules

Current Accessible Chess already has an internal GameTree/PGN implementation. Do not rewrite it wholesale. Differential-test it against mature implementations and reuse permissive components where they materially reduce risk.

For the future web/PWA client, `chess.js` is a strong candidate for browser-side standard chess legality/FEN/PGN utility under BSD-2-Clause. Keep the authoritative application/domain model neutral so the Windows client and web client do not fork the product rules.

### Web chessboard

Do not copy Lichess Chessground or Lichess PGN Viewer into a closed-source web client: both state GPL-3.0 obligations for the combined website work. For a closed-source-capable product, evaluate permissive alternatives such as `gchessboard` (MIT), `chessboard-element` (MIT), `cm-chessboard` code (MIT; audit separate piece-asset licenses), or a small Accessible Chess-specific semantic board if those widgets cannot meet the NVDA contract.

Accessibility remains a hard gate: an MIT widget is not automatically acceptable if its keyboard/screen-reader semantics are weaker than our current accessible board contract.

### Lichess server code

Lichess `lila` is AGPL-3.0-or-later. Do not copy its server implementation into a closed-source Accessible Chess backend. It is useful as public prior art for architecture, protocols, scaling and behavior. Some separate Lichess libraries have permissive licenses (for example `scalachess` is MIT) and can be considered individually after language/architecture cost analysis.

## Third-party inventory

Maintain a machine-readable and human-readable third-party inventory before release. At minimum record:

- component name;
- upstream repository;
- exact version/commit;
- license;
- whether embedded, linked, copied/adapted, data-only, or separate process;
- local files/modules that use it;
- required notices/source-offer obligations;
- security/update owner.

QA/Release must fail a production package if a bundled third-party component has no known license/provenance.

## Performance and architecture

Treat open-source code as bricks, not as the architecture. External libraries sit behind our ports/adapters. Do not leak their proprietary/GPL-specific types into core contracts. Keep one source of truth for game state, history, notation, keybindings, database identity and book position.

Every adopted brick requires regression tests against our acceptance gates and, where applicable, differential tests against our existing implementation and corpus. A faster implementation that loses PGN variations/comments, ChessBase metadata, history reversibility, or NVDA semantics is not an acceleration.
# cbh2pgn upstream source lock

Upstream: https://github.com/asdfjkl/cbh2pgn
Pinned commit: `42b3592738062db1f768239e85df1b98cb1cead9`
Pinned tree: `7b662270d819d98619d1855935beb48b05933425`
License: MIT; cached in this directory.

Pinned upstream files and blob SHAs:
- `LICENSE` — `c470e91e56687922599d21666e3a4d39094cb1c6`
- `README.md` — `4101356efc42f228d90936176364fd58dc429a6f`
- `cbh2pgn.py` — `b4649202fa1dc57f8967cc96a9a97f4beea1ca21`
- `game.py` — `e7e16647dfe2947915a3e40787310925caa5beb2`
- `header.py` — `81884b0dac69064823957d4eb4766eebc3657cc0`
- `player.py` — `c324d96aa4e3bd77b01e68865072609d79a7d25b`
- `tournament.py` — `8888863dcea39cc2834db017f46ab4681df040c2`

## Adaptation scope

The upstream implementation is useful because it contains actual classic CBG move/variation byte tables, de-obfuscation, starting-position decoding, CBH header/record reading and metadata readers. It is not accepted as a drop-in runtime dependency.

Upstream itself states these limits: standard games only, no Chess960, selected metadata, no game annotations. Its implementation imports GPL `python-chess`; Accessible Chess must replace that dependency at the boundary with our own chess core/GameTree before production integration.

## How workers consume this

Workers do not perform a fresh internet search. They use this exact lock and upstream commit as the source reference. Adapted code must carry the MIT copyright/license notice where required and must be mapped behind our existing read-only ChessBase adapter. Any field/encoding not verified against lawful samples remains `unsupported`/`partial`, never guessed.

This source lock is intentionally separate from `integration/accessible-chess-next` so upstream material cannot silently enter production without adapter/tests/license review.
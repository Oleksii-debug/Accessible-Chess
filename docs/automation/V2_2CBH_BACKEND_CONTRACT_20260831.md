# V2 2CBH backend qualification contract — 2026-08-31

Status: **BLOCKED / support not advertised / import not enabled**.

Parent evidence: PR #355, exact parent SHA `5ebdf9f9b6051fd25178b58aec29d0459f454daa`.

## Decision

This round did **not** find the evidence set required to turn 2CBH into Product support.  Accessible Chess therefore does not decode, import, publish, or advertise 2CBH.  The deliverable is the concrete backend/topology/immutability seam that a future qualified decoder must satisfy.

The canonical ChessBase boundary remains:

`external source -> isolated decoder/backend -> canonical legality + GameTree -> Library/PGN`

There is no second chess parser/core and no external ChessBase record type may become application truth.

## Authoritative format facts established

ChessBase documentation states that `*.2cbh` was introduced with ChessBase 17, uses fewer files than classic CBH, does not require the old search accelerators, and is supported by ChessBase 18.  Official ChessBase/Fritz documentation also describes conversion in both directions between 2CBH and older database/PGN formats.

Sources:

- https://help.chessbase.com/CBase/18/Eng/new_data_format_2cbh.htm
- https://help.chessbase.com/Fritz/19/Eng/new_data_format_2cbh.htm
- https://help.chessbase.com/CBase/18/Eng/faq_2cbh_format.htm

An official example previously inspected in PR #355 exposed these same-root filenames:

- `.2cba`
- `.2cbg`
- `.2cbh`
- `.2lcd`
- `.2lgd`
- `.2lid`
- `.ini`

That observation is **not** a normative component specification.  Neither the complete component set, semantic role of each companion, nor mandatory/optional status has been qualified.  This round intentionally does not create a hard-coded mapping for those suffixes.

## Decoder availability and licensing

### ChessBase 18

ChessBase is an authoritative commercial reader/writer/converter for 2CBH, but it is not a qualified Accessible Chess decoder backend.  No stable external decoder protocol, redistribution right, or automation contract was established for Product integration.

### Chess Combine beta

The current public Chess Combine download/release history (0.1.168 Beta at the time of this check) states that the product processes/opens CBH/2CBH databases.  This is a useful independent-reader lead.  It is **not qualified** as a Product backend because the public material inspected did not establish all of:

- a stable documented CLI/API for deterministic decoding/export;
- a backend protocol suitable for isolation;
- a license/permission for embedding or automated Product integration;
- reproducible independent semantic-oracle evidence for an exact lawful corpus.

Source: https://chesscombine.ru/download.html

### Open-source candidates already pinned by PR #355

Exact-tree probes remain negative for a 2CBH surface:

- `rolandlo/libcbh` `9641c5c3949d8fb210b17dd9aa54455645843696` — GPL-2.0; classic CBH reader; no 2CBH extension/fixture surface found.
- `foolnotion/scidb` `7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415` — GPL; classic CBH/CBF surface; no 2CBH extension/fixture surface found.
- `Isarhamster/chessx` `e734a075346ca2ad7e3f3e35b42140169637c5ca` — GPL-2.0-or-later; no 2CBH extension/fixture surface found.

Therefore a GPL decoder is **not** being added to the default Windows package.  In fact the new contract rejects any 2CBH descriptor that requests default Windows bundling.

## Real corpus and independent oracle

UltraCorr2025 is real 2CBH material and reports more than 2.68 million games, including annotations.  Its 2CBH distribution is an encrypted `UC-2025.2cbz`; current download access is for existing purchasers and does not provide a redistributable CI fixture, an automation password, or an independent exact semantic oracle.  It is useful real-world evidence, not an accepted Product test corpus.

Source: https://www.chessmail.com/UC-2025/Download-UC2025-newformat.html

Other downloadable 2CBH files are not accepted merely because they are public URLs.  Reuse/redistribution rights and semantic provenance must be established first.

No independent semantic oracle is qualified today.  Two leads remain valid but incomplete:

1. a lawful reproducible open-PGN -> 2CBH generation route, with the original PGN/GameTree as the independent oracle;
2. a Chess Combine/ChessBase export path, only if its automation interface, lawful use and independence from the future decoder are demonstrated.

Until one route covers real semantic features such as comments, NAG, nested and sibling variations, unusual starts, zero-ply games, metadata and results, support remains blocked.

## Product package added by this round

`acs/chessbase_2cbh_backend.py` adds a fail-closed qualification boundary without enabling a decoder.

The shipping backend registry is empty.  A future backend descriptor must provide explicit evidence for:

- backend identity/version and exact executable SHA-256;
- external-executable protocol identity;
- license name/URL and automation-interface evidence;
- an evidence-qualified family topology;
- lawful independent semantic-oracle identity/equivalence;
- durable evidence references.

Topology rules are supplied by that evidence package.  `TwoCbhMemberRule` contains only `suffix` and `required/optional` classification; it deliberately has **no semantic-role field**.  The module contains no guessed built-in companion mapping for `.2cba/.2cbg/.2lcd/.2lgd/.2lid`.

A qualified future source capture is read-only and fail-closed:

- primary must be a regular non-indirected `.2cbh` file;
- same-root members are selected only from the explicit qualified contract;
- required missing member fails;
- optional absence is tolerated only when evidence explicitly classifies it optional;
- symlink/reparse members fail;
- every accepted file is streamed through SHA-256;
- device/inode/size/mtime are checked around hashing;
- topology and bytes are re-captured after future decoder execution; any change invalidates all output;
- report projection removes workstation directory paths.

Default safety bounds are explicit: 32 members, 8 GiB/member, 32 GiB/family, 1 MiB hash chunks, future decoder timeout 120 s (hard configuration ceiling 600 s), stdout 64 MiB, stderr 1 MiB.

These are pre-decode boundary contracts.  They do not claim that any current decoder understands 2CBH.

## Remaining gate before real support

2CBH may move from BLOCKED only after one exact evidence chain proves all of:

1. complete qualified family topology, including mandatory/optional status;
2. a reproducible isolated external decoder and lawful automation/license terms;
3. a lawful real or reproducibly generated corpus;
4. an independent PGN/GameTree semantic oracle for the exact corpus;
5. decoder output revalidated by the canonical Board/GameTree path;
6. source immutability before/after decode;
7. atomic Library publication;
8. `2CBH -> canonical GameTree -> Library -> Search/Open -> PGN export -> reopen` semantic equivalence;
9. Windows execution evidence for the exact backend while the default Accessible Chess package remains backend-free.

Until then:

- `2CBH=BLOCKED`
- `product_decoder_available=false`
- `product_safe_to_import=false`
- `support_promotion_allowed=false`

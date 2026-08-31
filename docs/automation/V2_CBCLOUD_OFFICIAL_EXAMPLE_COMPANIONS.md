# V2 CBCLOUD official-example companion evidence

ROLE: `V2-CHESSBASE-FORMATS`

Ownership: `ACCESSIBLE-CHESS-V2-CBCLOUD-OFFICIAL-EXAMPLE-COMPANIONS-20260831`

Parent: PR #404 exact `a1b88d947b526d86c6a2dbdbcce32c4b4e4b0830`.

## Verdict

`CBCLOUD=BLOCKED`. This evidence-only successor narrows one topology uncertainty. It does not add Product recognition, a decoder, a guessed binary-role map, or user-facing support.

## What the official manuals actually show

ChessBase documentation independently states that the CBCloud format consists of exactly four files.

Two official manual editions expose real same-root directory examples:

- ChessBase 14 English manual: `WhiteRepertoire.cbcloud`, `WhiteRepertoire.cbclmov`, `WhiteRepertoire.cbclhdr`, `WhiteRepertoire.cbclatt`.
- ChessBase 13 German manual: `BlackRepertoire.cbcloud`, `BlackRepertoire.cbclmov`, `BlackRepertoire.cbclhdr`, `BlackRepertoire.cbclatt`.

Official sources:
- https://help.chessbase.com/cb14-eng.pdf
- https://help.chessbase.com/pdf/CBase/13/deu.pdf
- https://help.chessbase.com/CBase/16/Eng/database_functions_with_cloud_.htm
- https://help.chessbase.com/CBase/16/Eng/filenames.htm

This is enough to qualify the exact suffix set as **official-example observed**:

- `.cbcloud`
- `.cbclmov`
- `.cbclhdr`
- `.cbclatt`

It is not enough to claim that ChessBase publishes a normative specification saying all four are universally mandatory in every state of every CBCLOUD database, nor to assign binary semantics from their names.

## Screenshot/tool boundary

The project rule requires visual PDF verification rather than silently trusting text extraction. A web screenshot call was attempted against the official ChessBase manual PDF. The runtime could not materialize the oversized PDF as a screenshot-enabled PDF source; opening the English/German manuals failed on content-size limits and a direct screenshot call could not resolve the search-index PDF result as `application/pdf`.

Therefore this package does **not** upgrade the evidence to a screenshot-verified normative component/role specification. It records only what the official manual's indexed table/visual extraction exposes, corroborated across two official language editions and by current official HTML's independent four-file count.

## Secondary corroboration

Public Windows file-association catalogues independently list `cbcloud`, `cbclmov`, `cbclhdr`, and `cbclatt` as ChessBase database extensions. This is useful corroboration of extension existence only. It is not authoritative evidence for binary roles, requiredness or format semantics.

## Real-world acceptance remains open

The manual directory listings are real-product examples, but no exact downloadable family bytes are provided by the documentation. This cycle still lacks:

- lawfully reusable authentic four-file bytes;
- stable exact family hashes;
- explicit automated CI reuse/redistribution authority for those bytes;
- an independent PGN/GameTree oracle tied to those bytes;
- a licensed reader that actually decodes the family.

No semantic acceptance chain has run. The project real-world acceptance rule is therefore not satisfied.

## No inferred roles

Names such as `CBCLMOV`, `CBCLHDR`, and `CBCLATT` may look suggestive, but this package does not infer “moves”, “header”, or “annotations” binary responsibilities from naming alone. That would be a format-specification claim not supported by the verified evidence available here.

Likewise, Product must not hash only `.cbcloud` as whole-family integrity, must not invent optionality rules, and must not route these files through `libcbh` merely because official documentation says CBCLOUD can store the same logical game data as CBH.

## Promotion gate

Future CBCLOUD support still requires:

1. a normative or independently proven required/optional component contract;
2. qualified binary roles or a real licensed reader that makes roles operationally unnecessary;
3. lawfully reusable authentic four-file family bytes;
4. stable family hashes and independent semantic oracle;
5. bounded trusted decode/execution;
6. canonical legality/GameTree validation;
7. atomic ACSDB import with provenance;
8. Library/Search/Open;
9. PGN Export/Reopen where supported;
10. whole-family integrity and loss comparison;
11. applicable Windows runtime evidence before activation.

Until then: `CBCLOUD=BLOCKED`, `support_promotion_allowed=false`, `NVDA_VERIFIED=NO`.

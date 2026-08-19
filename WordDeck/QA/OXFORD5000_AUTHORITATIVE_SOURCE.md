# Oxford 5000 authoritative-source record

Updated: 2026-08-19

## Authority

Primary publisher/source: Oxford University Press / Oxford Learner's Dictionaries.

Official Oxford 3000/5000 interactive word-list page:
`https://www.oxfordlearnersdictionaries.com/us/wordlists/oxford3000-5000`

Official Oxford 5000 CEFR PDF:
`https://www.oxfordlearnersdictionaries.com/external/pdf/wordlists/oxford-3000-5000/The_Oxford_5000_by_CEFR_level.pdf`

Official Oxford 3000 CEFR PDF:
`https://www.oxfordlearnersdictionaries.com/external/pdf/wordlists/oxford-3000-5000/The_Oxford_3000_by_CEFR_level.pdf`

The Oxford 5000 PDF explicitly describes itself as the list of the additional 2,000 B2-C1 words beyond the Oxford 3000. It is therefore an authoritative membership source for the additional-word inventory.

## Reproducible machine path

WordDeck does not commit or ship a copied full Oxford HTML/PDF source. During Windows CI, `tools/fetch_oxford5000_official_html.py` retrieves the official interactive word-list page as a transient build input and fails closed unless the membership-bearing HTML is complete.

`tools/validate_oxford5000_official_inventory.py` then requires exactly 2,000 unique Oxford 5000 additional headwords and separately reports the exact row-preserving lexical identity count after POS/CEFR splitting.

`tools/validate_oxford5000_runtime_ledger.py --official-html ...` reconciles every locally activated or staged lexical identity against that official inventory and emits an exact unaccounted ledger.

The transient official HTML itself is intentionally not uploaded as a WordDeck build artifact. Only derived validation/accounting evidence is uploaded.

## 2026-08-19 targeted correction

The official Oxford 5000 PDF resolved the previously isolated post-`mutual` candidate set as genuine additional-list membership. Those rows now remain fail-closed only for translation QA rather than source-membership ambiguity.

One local structural error was corrected from the authoritative PDF: `nursing` is `adjective`, B2. The earlier staged `noun`, B2 identity was retired and its stable lexical ID was recomputed from the corrected headword/POS/CEFR identity.

## Safety rule

Third-party Oxford-list copies may be used for candidate discovery only. They are not accepted as final membership, POS or CEFR authority. Runtime activation requires the project source/sense/translation gates in addition to authoritative membership.

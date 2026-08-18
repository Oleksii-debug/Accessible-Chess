# Oxford 5000 structural audit — legacy staging 0001-0200

Date: 2026-08-18
Status: **PRODUCTION MERGE BLOCKED UNTIL ROW SPLIT IS APPLIED**

## Purpose

The emergency Oxford 5000 requirement preserves Oxford lexical rows by part of speech / CEFR distinction. The earlier `ox5000-add-0001..0200` staging IDs were created as translation-working IDs and in several places merged multiple official Oxford rows into one convenience row. Those IDs have **never been embedded into the production dictionary**, so correcting the staging structure does not change any existing WordDeck user progress or any Oxford 3000 stable ID.

Authoritative source of truth:
- Oxford Learner's Dictionaries, **Oxford 3000 and 5000** word list: https://www.oxfordlearnersdictionaries.com/us/wordlists/oxford3000-5000
- Oxford documentation confirms that the Oxford 5000 adds 2,000 B2-C1 items to the Oxford 3000 and exposes part of speech + CEFR per displayed list row.

A public historical scrape (`winterdl/oxford-5000-vocabulary-audio-definition`) was used only as a **QA comparison aid** to spot possible row-count/ordering problems. Its data is not authoritative, is not copied into WordDeck production data, and must never override the current Oxford page.

## Confirmed structural defects in the old staging

The current Oxford page explicitly presents the following as separate list rows, but old WordDeck staging combined them:

| Old staging ID | Old staging form | Required separate Oxford rows |
|---|---|---|
| `ox5000-add-0009` | `abuse` n., v. C1 | `abuse` noun C1; `abuse` verb C1 |
| `ox5000-add-0030` | `acid` n. B2, adj. C1 | `acid` adjective C1; `acid` noun B2 |
| `ox5000-add-0053` | `advocate` n., v. C1 | `advocate` noun C1; `advocate` verb C1 |
| `ox5000-add-0064` | `alert` v., n., adj. C1 | `alert` adjective C1; `alert` noun C1; `alert` verb C1 |
| `ox5000-add-0065` | `alien` n. B2, adj. C1 | `alien` adjective C1; `alien` noun B2 |
| `ox5000-add-0068` | `alike` adv., adj. C1 | `alike` adjective C1; `alike` adverb C1 |
| `ox5000-add-0080` | `amateur` adj., n. C1 | `amateur` adjective C1; `amateur` noun C1 |
| `ox5000-add-0122` | `assault` n., v. C1 | `assault` noun C1; `assault` verb C1 |
| `ox5000-add-0139` | `attribute` v., n. C1 | `attribute` noun C1; `attribute` verb C1 |
| `ox5000-add-0184` | `besides` prep., adv. B2 | `besides` adverb B2; `besides` preposition B2 |
| `ox5000-add-0187` | `bid` n., v. B2 | `bid` noun B2; `bid` verb B2 |
| `ox5000-add-0195` | `blast` n., v. C1 | `blast` noun C1; `blast` verb C1 |
| `ox5000-add-0197` | `blend` v., n. C1 | `blend` noun C1; `blend` verb C1 |

The current Oxford page also confirms a missing row between `assistance` and `assurance`:

- `assumption` — noun — B2

This row is absent from the old 0101-0200 extraction batch and must be added before any production merge.

## Corrected coverage interpretation

The old staging labels `0001-0200` represent **200 convenience translation groups, not 200 official Oxford lexical rows**.

After expanding the confirmed merged POS groups and restoring `assumption`, the same alphabetical span from `abolish` through noun `blow` corresponds to **215 separate Oxford rows**:

- old groups 0001-0100 -> 108 Oxford rows;
- old groups 0101-0200 -> 107 Oxford rows;
- cumulative through noun `blow` -> 215 Oxford rows.

This 215 figure is a structural checkpoint only. Production eligibility still requires per-row source/translation QA and a stable production ID; it must not be used to claim the full Oxford 5000 is complete.

## Stable-ID rule before embedding

Do **not** promote the old convenience IDs directly into the embedded dictionary. Canonical Oxford 5000 addition IDs must identify one lexical row, not a merged spelling group. The canonicalization pass must therefore:

1. keep every Oxford 3000 stable ID unchanged;
2. create one new stable ID per distinct Oxford 5000 addition row;
3. preserve exact Oxford headword, POS and CEFR on that row;
4. split existing Ukrainian translation material by POS rather than duplicate an undifferentiated multi-sense string;
5. add the missing `assumption` noun B2 row;
6. fail closed if an official row cannot be reconciled unambiguously;
7. only after canonicalization, generate addition audio keyed to those final IDs.

## Next action

Build a canonical row-level Oxford 5000 additions ledger from the official Oxford page, starting with the now-audited `abolish`..`blow` span, migrate the already reviewed Ukrainian material into its correct per-POS rows, and validate exact row order/count before embedding or audio generation. Continue extraction beyond `blow` only on this row-preserving model.

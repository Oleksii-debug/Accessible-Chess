# WordDeck

Accessible Windows vocabulary trainer designed for keyboard-first use with NVDA, JAWS and Narrator. Primary interaction uses native WinForms controls with accessible names and normal Windows focus/UI Automation behavior.

## Current approved-v1 feature set

- Recall vocabulary study over the complete accepted 5446-entry Oxford corpus.
- Study scopes: All, A1, A2, B1, B2 and C1.
- Five permanent core Recall decks plus user-created Recall decks.
- Spelling trainer with independent decks/statistics and deterministic/statistical Adaptive Coach behavior.
- Sentence Coach / Sentence Spelling over locally installed SentencePack data.
- British offline pronunciation assets for the accepted Oxford additions release baseline.
- Rebindable keyboard shortcuts with conflict detection and F1/help truth.
- Personal learning data under `%LOCALAPPDATA%\WordDeck`, outside the public program package.
- Reversible hiding of words from study without deleting canonical dictionary/audio data.
- Backups/recovery, migration, profile export/import and fail-closed protection against unreadable or incompatible state.

## Personal profile continuity

The full-v1 personal profile contains personal learning state for Recall, Spelling and Sentence modes. It does **not** contain the canonical dictionary, audio assets or SentencePack corpus files.

Older accepted V0.1 Recall-only profile files remain importable. Importing such a legacy profile changes Recall state only and preserves existing Spelling and Sentence state.

A full-v1 import validates profile/corpus compatibility before changing personal state and creates a three-module recovery bundle before persistent replacement. Unknown stable IDs from a compatible corpus are preserved for future migration rather than silently discarded.

## Keyboard and screen-reader contract

- Fast unmodified Up/Down Recall card navigation is limited to the focused English word/card surface.
- Up/Down in the Ukrainian translation text box keeps normal text/screen-reader reading behavior and must not change cards.
- Dictionary, Study scope and Deck ComboBoxes keep normal Up/Down selection behavior while focus remains in the selector.
- Selector changes must not intentionally throw focus back to the card.
- Dictionary selection does not require Enter merely to make normal arrow selection work.
- Spelling can be closed with the standard Windows `Alt+F4` command.
- F1 opens help for the current training context.

All configured application shortcuts are rebindable from the keyboard-shortcut settings UI. Standard Windows dialog/navigation keys remain standard controls rather than hidden mouse-only actions.

## SentencePack installation contract

SentencePack import is offline/local. A pack must contain valid EN-UA sentence data, provenance and licensing metadata and must pass bounded structural validation.

A new portable `json.gz` source and its SQLite runtime derivative are built and validated as one immutable generation. The SQLite derivative is cryptographically bound to the portable source. A small committed manifest selects the active generation; an interrupted replacement before that commit leaves the previous pack active. The previous verified manifest is retained as last-known-good recovery metadata.

Uncommitted/orphan generation files do not become active merely because they exist. Unsafe Windows/path identifiers and case-insensitive identity collisions are rejected.

A distributable production SentencePack must have independently acceptable source/licensing evidence. Synthetic self-test packs and data-generation tools are not a substitute for a real release corpus.

## Dictionary TSV format

Metadata lines begin with `#`, followed by a tab-separated table:

```text
#id=my-dictionary
#name=English to Ukrainian
#sourceLanguage=en
#targetLanguage=uk
entryId\tlevel\tsource\ttarget
my-0001\tA1\thello\tпривіт
```

## Build

Requires .NET 8 SDK on Windows for source builds. Release publishing uses self-contained `win-x64` output so the user package does not require a separately installed .NET runtime.

```powershell
dotnet publish .\WordDeck\WordDeck.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
```

Normal study must not require administrator elevation or a developer-specific directory. Release validation includes paths containing spaces and Cyrillic. Heavy integrity checks belong to explicit build/self-test workflows rather than normal UI startup.

## Release and personal-data safety

- Public packages must not contain `%LOCALAPPDATA%` state, exported personal profiles, recovery backups, credentials, tokens, cookies, browser profiles or private logs.
- Validation workflows must not rewrite canonical source as a side effect of testing.
- The accepted V0.1 release remains an immutable historical release and must not be silently rebuilt from later source under the same name.
- Normal study does not add telemetry or a new online service dependency.

## Accessibility release gate

Automated accessibility/UIA checks are necessary but do not equal a manual NVDA pass. A build is not considered independently accessibility-accepted until a human verifies the packaged EXE with NVDA, including:

1. Main window/menu discovery and logical Tab/focus order.
2. English word announcement and Recall Up/Down only on the intended word surface.
3. Native arrow reading in the Ukrainian translation field.
4. Dictionary/Scope/Deck ComboBox selection with focus retention and announced values.
5. Translation reveal, deck movement, hide/restore and profile flows from the keyboard.
6. Spelling and Sentence windows, F1/help and standard Alt+F4 close behavior.
7. Accessible errors for invalid/corrupt profile/state/SentencePack flows.
8. No mouse-only primary interaction or silent custom-drawn interaction region.

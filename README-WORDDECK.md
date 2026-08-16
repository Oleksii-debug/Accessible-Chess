# WordDeck (working name)

Accessible Windows flashcard trainer for vocabulary study with NVDA/JAWS/Narrator-friendly native WinForms controls.

## MVP behavior

- Embedded Oxford 3000 English→Ukrainian dictionary, preserving CEFR level and all 3308 source positions from the supplied CEFR list/translation file.
- Five independent user-controlled decks. New entries start in Deck 1.
- Randomized shuffle-bag presentation: every entry in the active deck appears once before reshuffling.
- English is shown by default; translation is revealed on demand.
- Move the current word directly to any deck.
- Switch to any deck at any time.
- Fully rebindable keyboard shortcuts with duplicate detection.
- Local persistent progress under `%LOCALAPPDATA%\WordDeck`.
- Import additional TSV dictionaries later without changing the executable.
- No canvas/custom-drawn primary UI: controls are native WinForms controls with accessible names and normal keyboard focus/UI Automation exposure.

## Default shortcuts

- Ctrl+Right — next random word
- Ctrl+Left — previous word in current session
- Ctrl+T — reveal translation
- Ctrl+R — refocus/repeat current English word
- Ctrl+1…Ctrl+5 — switch active deck
- Alt+1…Alt+5 — move current word to a specific deck
- Ctrl+K — shortcut settings
- F1 — help

All shortcuts are rebindable from Tools > Keyboard shortcuts.

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

Requires .NET 8 SDK on Windows.

```powershell
dotnet publish .\WordDeck\WordDeck.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
```

The GitHub Actions workflow publishes a `WordDeck-win-x64` artifact containing the single-file Windows executable.

## Accessibility release gate

A build is not considered release-ready until the packaged EXE is manually checked with NVDA for:

1. Main window title announcement.
2. Menu bar discoverability with Alt.
3. English word announcement when focus lands on the card.
4. Translation announcement after reveal shortcut.
5. Deck switching and word movement with keyboard only.
6. Shortcut settings operable and understandable with NVDA.
7. No silent custom-drawn/canvas regions for primary interaction.

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one match in {path}, got {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


main = "WordDeck/MainForm.cs"
replace_once(main, "internal sealed class MainForm : Form", "internal sealed partial class MainForm : Form")

replace_once(
    main,
    'Text = "F1: help. Ctrl+S saves now. Ctrl+1..5 switches decks inside the current scope; Alt+1..5 moves the current word. All shortcuts are rebindable."',
    'Text = "Down: next word. Up: true previous word. Ctrl+T: translation. Ctrl+1..5 switches decks; Alt+1..5 moves the current word. F1: help."',
)

replace_once(
    main,
    '''        var save = new ToolStripMenuItem("&Save progress now");
        save.Click += (_, _) => SaveProgressNow();
        var import = new ToolStripMenuItem("&Import dictionary...");
        import.Click += (_, _) => ImportDictionary();''',
    '''        var save = new ToolStripMenuItem("&Save progress now");
        save.Click += (_, _) => SaveProgressNow();
        var exportProfile = new ToolStripMenuItem("&Export personal progress profile...") { AccessibleName = "Export personal progress profile" };
        exportProfile.Click += (_, _) => ExportPersonalProfile();
        var importProfile = new ToolStripMenuItem("I&mport personal progress profile...") { AccessibleName = "Import personal progress profile" };
        importProfile.Click += (_, _) => ImportPersonalProfile();
        var resetLearning = new ToolStripMenuItem("&Reset Recall learning data...") { AccessibleName = "Reset Recall learning data with automatic backup" };
        resetLearning.Click += (_, _) => ResetLearningData();
        var import = new ToolStripMenuItem("&Import dictionary...");
        import.Click += (_, _) => ImportDictionary();''',
)

replace_once(
    main,
    '''        file.DropDownItems.Add(addWords);
        file.DropDownItems.Add(save);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(import);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(exit);''',
    '''        file.DropDownItems.Add(addWords);
        file.DropDownItems.Add(save);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(exportProfile);
        file.DropDownItems.Add(importProfile);
        file.DropDownItems.Add(resetLearning);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(import);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(exit);''',
)

replace_once(
    main,
    '''        var undoMove = new ToolStripMenuItem("&Undo last deck move");
        undoMove.Click += (_, _) => UndoLastMove();
        var createDeck = new ToolStripMenuItem("&Create deck...");''',
    '''        var undoMove = new ToolStripMenuItem("&Undo last deck move");
        undoMove.Click += (_, _) => UndoLastMove();
        var hideCurrent = new ToolStripMenuItem("&Hide current word from study...") { AccessibleName = "Hide current word from Recall study" };
        hideCurrent.Click += (_, _) => HideCurrentWord();
        var restoreHidden = new ToolStripMenuItem("&Restore hidden word...") { AccessibleName = "Restore a hidden Recall word" };
        restoreHidden.Click += (_, _) => RestoreHiddenWord();
        var restoreAllHidden = new ToolStripMenuItem("Restore &all hidden words...") { AccessibleName = "Restore all hidden Recall words" };
        restoreAllHidden.Click += (_, _) => RestoreAllHiddenWords();
        var createDeck = new ToolStripMenuItem("&Create deck...");''',
)

replace_once(
    main,
    '''        _deckMenu.DropDownItems.Add(moveCurrent);
        _deckMenu.DropDownItems.Add(undoMove);
        _deckMenu.DropDownItems.Add(new ToolStripSeparator());
        _deckMenu.DropDownItems.Add(createDeck);''',
    '''        _deckMenu.DropDownItems.Add(moveCurrent);
        _deckMenu.DropDownItems.Add(undoMove);
        _deckMenu.DropDownItems.Add(new ToolStripSeparator());
        _deckMenu.DropDownItems.Add(hideCurrent);
        _deckMenu.DropDownItems.Add(restoreHidden);
        _deckMenu.DropDownItems.Add(restoreAllHidden);
        _deckMenu.DropDownItems.Add(new ToolStripSeparator());
        _deckMenu.DropDownItems.Add(createDeck);''',
)

replace_once(
    main,
    '''        _state.ActiveDictionaryId = basePackage.Id;
        _lastMove = null;
        ReindexEntries();''',
    '''        _state.ActiveDictionaryId = basePackage.Id;
        _lastMove = null;
        _navigationHistory.Clear();
        ReindexEntries();''',
)

replace_once(
    main,
    '''        _current = null;
        _lastMove = null;
        _translationBox.Clear();''',
    '''        _current = null;
        _lastMove = null;
        _navigationHistory.Clear();
        _translationBox.Clear();''',
)

replace_once(
    main,
    '''        _scopeService.SetCurrentEntry(ActiveScopeId, null);
        _current = null;
        SelectActiveDeckInCombo();''',
    '''        _scopeService.SetCurrentEntry(ActiveScopeId, null);
        _current = null;
        _navigationHistory.Clear();
        SelectActiveDeckInCombo();''',
)

replace_once(
    main,
    '''    private IReadOnlyList<DictionaryEntry> EntriesInActiveDeck() =>
        _scopeService.EligibleEntries(ActiveScopeId)
            .Where(entry => string.Equals(_deckMap.GetValueOrDefault(entry.Id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
            .ToList();''',
    '''    private IReadOnlyList<DictionaryEntry> EntriesInActiveDeck() =>
        _scopeService.EligibleEntries(ActiveScopeId)
            .Where(entry => !UserProgressService.IsHidden(_state, entry.Id))
            .Where(entry => string.Equals(_deckMap.GetValueOrDefault(entry.Id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
            .ToList();''',
)

replace_once(
    main,
    '''            if (_entriesById.ContainsKey(id) && string.Equals(_deckMap.GetValueOrDefault(id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
                _shuffleBag.Enqueue(id);''',
    '''            if (_entriesById.ContainsKey(id) && !UserProgressService.IsHidden(_state, id) &&
                string.Equals(_deckMap.GetValueOrDefault(id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
                _shuffleBag.Enqueue(id);''',
)

replace_once(
    main,
    '''        if (id is not null && _entriesById.ContainsKey(id) &&
            string.Equals(_deckMap.GetValueOrDefault(id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))''',
    '''        if (id is not null && _entriesById.ContainsKey(id) && !UserProgressService.IsHidden(_state, id) &&
            string.Equals(_deckMap.GetValueOrDefault(id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))''',
)

replace_once(
    main,
    '''    private void NextWord()
    {
        IReadOnlyList<DictionaryEntry> active = EntriesInActiveDeck();''',
    '''    private void NextWord()
    {
        if (TryShowForwardHistory()) return;
        IReadOnlyList<DictionaryEntry> active = EntriesInActiveDeck();''',
)

replace_once(
    main,
    '''        _current = entry;
        _scopeService.SetCurrentEntry(ActiveScopeId, id);
        _wordBox.Text = entry.Source;''',
    '''        if (UserProgressService.IsHidden(_state, id)) return;
        _current = entry;
        if (!_showingHistoryNavigation) _navigationHistory.Visit(id);
        UserProgressService.RecordSeen(_state, id, ActiveScopeId, _activeDeckId);
        _scopeService.SetCurrentEntry(ActiveScopeId, id);
        _wordBox.Text = entry.Source;''',
)

replace_once(
    main,
    '''        _translationBox.Text = _current.Target;
        _translationBox.Focus();''',
    '''        _translationBox.Text = _current.Target;
        UserProgressService.RecordTranslationReveal(_state, _current.Id);
        SaveState();
        _translationBox.Focus();''',
)

old_counts = '''    private void UpdateCounts()
    {
        if (_package is null || _scopeService is null) return;
        string scopeId = ActiveScopeId;
        string summary = string.Join("; ", _decks.Decks.Select(deck =>
        {
            int count = _scopeService.Count(scopeId, deck.Id);
            string active = string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase) ? " active" : string.Empty;
            return $"{deck.Name}: {count} words{active}";
        }));
        _countLabel.Text = $"Scope {StudyScopeIds.DisplayName(scopeId)} — {summary}. Scope total: {_scopeService.ScopeTotal(scopeId)}.";
    }'''
new_counts = '''    private void UpdateCounts()
    {
        if (_package is null || _scopeService is null) return;
        string scopeId = ActiveScopeId;
        string summary = string.Join("; ", _decks.Decks.Select(deck =>
        {
            int count = AvailableDeckCount(scopeId, deck.Id);
            string active = string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase) ? " active" : string.Empty;
            return $"{deck.Name}: {count} available{active}";
        }));
        int canonical = _scopeService.ScopeTotal(scopeId);
        int available = AvailableScopeTotal(scopeId);
        int hidden = canonical - available;
        _countLabel.Text = $"Scope {StudyScopeIds.DisplayName(scopeId)} — {summary}. Available: {available}; canonical scope size: {canonical}; hidden in this scope: {hidden}.";
    }'''
replace_once(main, old_counts, new_counts)

replace_once(
    main,
    '''            "WordDeck shows only the English side of a Recall card by default. Reveal the Ukrainian translation only when needed. Both navigation shortcuts draw another random card from the active deck without repeating a word until the current shuffle bag is exhausted.\\r\\n\\r\\n" +''',
    '''            "WordDeck shows only the English side of a Recall card by default. Down Arrow moves to the next card; Up Arrow returns to the previous actually shown eligible card. After moving back, Down moves forward through history before drawing a new shuffled card. Left and Right remain normal text/caret navigation. Ctrl+Right and Ctrl+Left remain compatibility next/previous keys. Reveal the Ukrainian translation only when needed.\\r\\n\\r\\n" +''',
)

replace_once(
    main,
    '''            "Generated British pronunciation is an optional offline audio layer keyed by stable dictionary and entry IDs. " +
            $"Automatic pronunciation on card change is currently {audioMode}. If generated audio is unavailable, the normal screen-reader announcement remains the fallback.\\r\\n\\r\\n" +
            "Progress is saved automatically after changes and on normal exit. Ctrl+S creates an explicit checkpoint. state.json has a recovery backup.\\r\\n\\r\\n" +''',
    '''            "Generated British pronunciation is an optional offline audio layer keyed by stable dictionary and entry IDs. " +
            $"Automatic pronunciation on card change is currently {audioMode}. If generated audio is unavailable, WordDeck reports a readable status and the normal screen-reader announcement remains the fallback.\\r\\n\\r\\n" +
            "Personal progress is stored outside the program ZIP under %LOCALAPPDATA%\\\\WordDeck. New program ZIPs reuse that state automatically. File > Export personal progress profile creates a small user-state-only JSON for backup or transfer; Import validates it, creates a recovery copy and restores it atomically.\\r\\n\\r\\n" +
            "Deck > Hide current word removes a word only from normal Recall study. It does not delete the canonical dictionary, audio or saved deck assignments. Hidden words can be restored individually or all at once. File > Reset Recall learning data requires confirmation and creates a recovery profile before clearing learning overlays.\\r\\n\\r\\n" +
            "Progress is saved automatically after changes and on normal exit. Ctrl+S creates an explicit checkpoint. state.json has a recovery backup and the profile format is versioned for future migration.\\r\\n\\r\\n" +''',
)

replace_once(
    main,
    '''    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        string? action = _shortcuts.FindAction(keyData);''',
    '''    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (ShouldDeferUnmodifiedRecallArrow(keyData)) return base.ProcessCmdKey(ref msg, keyData);
        if (keyData == (Keys.Control | Keys.Right)) { NextWord(); return true; }
        if (keyData == (Keys.Control | Keys.Left)) { PreviousWord(); return true; }
        string? action = _shortcuts.FindAction(keyData);''',
)

replace_once(
    main,
    '''        if (action == ActionIds.NextWord) NextWord();
        else if (action == ActionIds.RevealTranslation) RevealTranslation();''',
    '''        if (action == ActionIds.NextWord) NextWord();
        else if (action == ActionIds.PreviousWord) PreviousWord();
        else if (action == ActionIds.RevealTranslation) RevealTranslation();''',
)

replace_once(
    main,
    '''        else if (action == ActionIds.UndoMove) UndoLastMove();
        else if (action == ActionIds.ShortcutSettings) OpenShortcutSettings();''',
    '''        else if (action == ActionIds.UndoMove) UndoLastMove();
        else if (action == ActionIds.HideCurrentWord) HideCurrentWord();
        else if (action == ActionIds.RestoreHiddenWords) RestoreHiddenWord();
        else if (action == ActionIds.RestoreAllHiddenWords) RestoreAllHiddenWords();
        else if (action == ActionIds.ExportProfile) ExportPersonalProfile();
        else if (action == ActionIds.ImportProfile) ImportPersonalProfile();
        else if (action == ActionIds.ResetLearningData) ResetLearningData();
        else if (action == ActionIds.ShortcutSettings) OpenShortcutSettings();''',
)

program = "WordDeck/Program.cs"
replace_once(
    program,
    '''                StudyScopeSelfTest.Run();
                SpellingSelfTest.Run();''',
    '''                StudyScopeSelfTest.Run();
                UserDataSelfTest.Run();
                SpellingSelfTest.Run();''',
)

selftest = "WordDeck/SelfTest.cs"
replace_once(selftest, 'Require(manager.Definitions.Count == 27, $"Expected 27 Recall/scope/core-deck actions, got {manager.Definitions.Count}.");',
             'Require(manager.Definitions.Count == 33, $"Expected 33 Recall/scope/core-deck actions, got {manager.Definitions.Count}.");')
replace_once(selftest, 'Require(manager.Definitions.Count == 29, "Creating a Recall user deck did not add switch/move actions.");',
             'Require(manager.Definitions.Count == 35, "Creating a Recall user deck did not add switch/move actions.");')
replace_once(
    selftest,
    '''        Require(manager.Get(ActionIds.SaveProgress) == (Keys.Control | Keys.S), "Ctrl+S save default changed.");
        Require(manager.Get(ActionIds.AddWords) == (Keys.Control | Keys.Shift | Keys.A), "Bulk-add default changed.");''',
    '''        Require(manager.Get(ActionIds.NextWord) == Keys.Down, "Down Arrow must be the primary Recall next-card key.");
        Require(manager.Get(ActionIds.PreviousWord) == Keys.Up, "Up Arrow must be the primary true previous-card key.");
        Require(manager.FindAction(Keys.Down) == ActionIds.NextWord && manager.FindAction(Keys.Up) == ActionIds.PreviousWord,
            "Recall Up/Down dispatch does not preserve distinct next/previous actions.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Left, out _), "Unmodified Left Arrow must remain standard caret/text navigation.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Right, out _), "Unmodified Right Arrow must remain standard caret/text navigation.");
        Require(manager.Get(ActionIds.SaveProgress) == (Keys.Control | Keys.S), "Ctrl+S save default changed.");
        Require(manager.Get(ActionIds.AddWords) == (Keys.Control | Keys.Shift | Keys.A), "Bulk-add default changed.");''',
)
replace_once(
    selftest,
    '''        Require(sanitized.All(path => path.EndsWith(Path.Combine("custom_dictionary_uk", "entry_1.mp3"), StringComparison.OrdinalIgnoreCase)), "Unsafe entry ID characters were not sanitized.");
    }''',
    '''        Require(sanitized.All(path => path.EndsWith(Path.Combine("custom_dictionary_uk", "entry_1.mp3"), StringComparison.OrdinalIgnoreCase)), "Unsafe entry ID characters were not sanitized.");
        using var audio = new PronunciationAudio();
        var package = new DictionaryPackage { Id = "self-test-dictionary", Name = "Self test", SourceLanguage = "en", TargetLanguage = "uk", Entries = Array.Empty<DictionaryEntry>() };
        var missingEntry = new DictionaryEntry("definitely-missing-self-test-audio", "A1", "missing", "відсутній");
        Require(!audio.TryPlay(package, missingEntry, out string? missingError) && missingError?.Contains("not installed", StringComparison.OrdinalIgnoreCase) == true,
            "Missing local pronunciation did not return a readable non-crashing status.");
    }''',
)

print("V0.1 user-safe UI integration patch applied exactly.")

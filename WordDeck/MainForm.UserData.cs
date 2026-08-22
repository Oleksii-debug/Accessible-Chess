namespace WordDeck;

internal sealed partial class MainForm
{
    private readonly RecallNavigationHistory _navigationHistory = new();
    private bool _showingHistoryNavigation;

    private bool IsCurrentRecallEligible(string entryId)
    {
        if (UserProgressService.IsHidden(_state, entryId)) return false;
        if (!_entriesById.TryGetValue(entryId, out DictionaryEntry? entry)) return false;
        if (!StudyScopeIds.Includes(ActiveScopeId, entry)) return false;
        return string.Equals(_deckMap.GetValueOrDefault(entryId, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase);
    }

    private bool TryShowForwardHistory(bool focusWord = true)
    {
        if (!_navigationHistory.TryForward(IsCurrentRecallEligible, out string? entryId) || entryId is null)
            return false;
        ShowHistoryEntry(entryId, focusWord);
        return true;
    }

    private void PreviousWord()
    {
        if (_navigationHistory.TryPrevious(IsCurrentRecallEligible, out string? entryId) && entryId is not null)
        {
            ShowHistoryEntry(entryId);
            return;
        }
        AnnounceStatus("No earlier eligible Recall card is available in this navigation history.");
        FocusCurrentWord();
    }

    private void ShowHistoryEntry(string entryId, bool focusWord = true)
    {
        _showingHistoryNavigation = true;
        try { ShowEntryById(entryId, focusWord); }
        finally { _showingHistoryNavigation = false; }
    }

    private bool ShouldDeferUnmodifiedRecallArrow(Keys keyData)
    {
        Keys code = keyData & Keys.KeyCode;
        Keys modifiers = keyData & Keys.Modifiers;
        if (modifiers != Keys.None || (code != Keys.Up && code != Keys.Down)) return false;

        // Fast Recall Up/Down is deliberately restricted to the English word
        // surface. Translation, ComboBoxes, menus and every other standard
        // control keep their native arrow-key behavior for keyboard/NVDA use.
        return !RecallKeyboardFocusPolicy.IsFastCardArrow(
            keyData,
            englishWordSurfaceFocused: ReferenceEquals(ActiveControl, _wordBox));
    }

    private void HideCurrentWord()
    {
        if (_current is null) { AnnounceStatus("No word is currently selected."); return; }
        string id = _current.Id;
        string word = _current.Source;
        DialogResult answer = MessageBox.Show(
            this,
            $"Hide {word} from normal Recall study in every scope? The canonical word, audio and deck assignments will be preserved and the word can be restored later.",
            "Hide word from study",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question,
            MessageBoxDefaultButton.Button2);
        if (answer != DialogResult.Yes) { FocusCurrentWord(); return; }

        UserProgressService.Hide(_state, id);
        _navigationHistory.Remove(id);
        RemoveFromShuffleBag(id);
        _scopeService.SetCurrentEntry(ActiveScopeId, null);
        _current = null;
        _translationBox.Clear();
        SaveState();
        UpdateCounts();
        AnnounceStatus($"Hidden {word} from normal Recall study. Its canonical dictionary entry, audio and per-scope deck assignments were preserved.");
        NextWord();
    }

    private void RestoreHiddenWord()
    {
        var options = _state.HiddenEntryIds
            .OrderBy(id => _entriesById.TryGetValue(id, out DictionaryEntry? entry) ? entry.Source : id, StringComparer.CurrentCultureIgnoreCase)
            .Select(id =>
            {
                string label = _entriesById.TryGetValue(id, out DictionaryEntry? entry)
                    ? $"{entry.Source} — {entry.Level}"
                    : $"{id} — not present in current corpus; preserved for future migration";
                return (Id: id, Label: label);
            }).ToList();
        if (options.Count == 0) { AnnounceStatus("There are no hidden Recall words to restore."); FocusCurrentWord(); return; }

        using var dialog = new HiddenWordRestoreDialog(options);
        if (dialog.ShowDialog(this) != DialogResult.OK || string.IsNullOrWhiteSpace(dialog.SelectedEntryId))
        {
            FocusCurrentWord();
            return;
        }
        string id = dialog.SelectedEntryId;
        UserProgressService.Restore(_state, id);
        SaveState();
        RestoreSequenceForScope();
        UpdateCounts();
        string word = _entriesById.TryGetValue(id, out DictionaryEntry? entry) ? entry.Source : id;
        AnnounceStatus($"Restored {word} to normal Recall study. Existing per-scope deck assignments were kept.");
        FocusCurrentWord();
    }

    private void RestoreAllHiddenWords()
    {
        if (_state.HiddenEntryIds.Count == 0) { AnnounceStatus("There are no hidden Recall words to restore."); FocusCurrentWord(); return; }
        DialogResult answer = MessageBox.Show(this, $"Restore all {_state.HiddenEntryIds.Count} hidden words to normal Recall study?", "Restore all hidden words", MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2);
        if (answer != DialogResult.Yes) { FocusCurrentWord(); return; }
        int restored = UserProgressService.RestoreAll(_state);
        SaveState();
        RestoreSequenceForScope();
        UpdateCounts();
        AnnounceStatus($"Restored {restored} hidden words. Their previous valid deck assignments remain in place.");
        FocusCurrentWord();
    }

    // The historical V0.1 File-menu actions and their configurable shortcuts now
    // route through the full-v1 profile service. A user who chooses the standard
    // "personal profile" path must not unknowingly export only Recall while
    // Spelling and Sentence progress remain behind.
    private void ExportPersonalProfile() => ExportUnifiedPersonalProfileInteractive();

    private void ImportPersonalProfile() => ImportUnifiedPersonalProfileInteractive();

    private void ResetLearningData()
    {
        DialogResult answer = MessageBox.Show(
            this,
            "Reset Recall learning progress? This clears hidden-word state, study history, current cards, shuffle progress and word-to-deck assignments. Canonical dictionary/audio files, custom cards, deck definitions, shortcuts and pronunciation preference are not deleted. An automatic recovery profile is created first.",
            "Reset WordDeck learning data",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2);
        if (answer != DialogResult.Yes) { FocusCurrentWord(); return; }

        try
        {
            SaveState();
            string recovery = _store.CreateRecoveryProfile(_state, "pre-reset");
            UserProgressService.ResetLearningData(_state);
            AppStateStore.Normalize(_state);
            _navigationHistory.Clear();
            DictionaryPackage selected = _state.ActiveDictionaryId is not null && _packages.TryGetValue(_state.ActiveDictionaryId, out DictionaryPackage? package)
                ? package
                : _packages.Values.First();
            ActivatePackage(selected);
            RestoreCurrentOrNextWord();
            AnnounceStatus($"Recall learning data reset. All canonical words are available again with safe default assignments. Recovery profile: {recovery}");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Reset failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            AnnounceStatus("Reset failed. WordDeck did not intentionally delete canonical dictionary or audio files.");
        }
        FocusCurrentWord();
    }

    private int AvailableScopeTotal(string scopeId) =>
        _scopeService.EligibleEntries(scopeId).Count(entry => !UserProgressService.IsHidden(_state, entry.Id));

    private int AvailableDeckCount(string scopeId, string deckId) =>
        _scopeService.EligibleEntries(scopeId).Count(entry =>
            !UserProgressService.IsHidden(_state, entry.Id) &&
            string.Equals(_scopeService.Assignments(scopeId).GetValueOrDefault(entry.Id, _decks.FirstDeck.Id), deckId, StringComparison.OrdinalIgnoreCase));
}

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

    private bool TryShowForwardHistory()
    {
        if (!_navigationHistory.TryForward(IsCurrentRecallEligible, out string? entryId) || entryId is null)
            return false;
        ShowHistoryEntry(entryId);
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

    private void ShowHistoryEntry(string entryId)
    {
        _showingHistoryNavigation = true;
        try { ShowEntryById(entryId); }
        finally { _showingHistoryNavigation = false; }
    }

    private bool ShouldDeferUnmodifiedRecallArrow(Keys keyData)
    {
        Keys code = keyData & Keys.KeyCode;
        Keys modifiers = keyData & Keys.Modifiers;
        if (modifiers != Keys.None || (code != Keys.Up && code != Keys.Down)) return false;
        if (MainMenuStrip?.ContainsFocus == true) return true;
        Control? active = ActiveControl;
        if (active is ComboBox) return true;
        // Up/Down are intentionally fast Recall keys only on the two main study
        // text surfaces. Standard controls elsewhere keep native arrow behavior.
        return active != _wordBox && active != _translationBox;
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

    private void ExportPersonalProfile()
    {
        SaveState();
        using var dialog = new SaveFileDialog
        {
            Title = "Export WordDeck personal progress profile",
            Filter = "WordDeck personal profile (*.json)|*.json",
            FileName = "WordDeck-profile-v1.json",
            AddExtension = true,
            DefaultExt = "json"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) { FocusCurrentWord(); return; }
        try
        {
            _store.ExportProfile(_state, dialog.FileName);
            AnnounceStatus($"Personal WordDeck profile exported to {dialog.FileName}. It contains study state only, not the canonical dictionary or audio files.");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Profile export failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        FocusCurrentWord();
    }

    private void ImportPersonalProfile()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Import WordDeck personal progress profile",
            Filter = "WordDeck personal profile (*.json)|*.json|All files (*.*)|*.*"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) { FocusCurrentWord(); return; }
        try
        {
            SaveState();
            var knownEntries = _packages.Values.SelectMany(package => package.Entries.Select(entry => entry.Id))
                .Concat(_state.CustomEntriesByDictionary.Values.SelectMany(list => list.Select(entry => entry.Id)))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();
            ProfileImportResult result = _store.ImportProfile(dialog.FileName, _state, knownEntries, _packages.Keys);
            _navigationHistory.Clear();
            _autoPronunciationMenuItem.Checked = _state.AutoPlayPronunciationOnCardChange;
            DictionaryPackage selected = _state.ActiveDictionaryId is not null && _packages.TryGetValue(_state.ActiveDictionaryId, out DictionaryPackage? package)
                ? package
                : _packages.Values.First();
            ActivatePackage(selected);
            RestoreCurrentOrNextWord();
            string quarantine = result.QuarantinedIds.Count == 0
                ? "No unknown stable IDs were found."
                : $"{result.QuarantinedIds.Count} unknown IDs were preserved in quarantine for future migration.";
            AnnounceStatus($"Personal profile imported successfully. A pre-import recovery profile was saved at {result.BackupPath}. {quarantine}");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Profile import failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            AnnounceStatus("Profile import failed. Existing personal state was not replaced.");
        }
        FocusCurrentWord();
    }

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

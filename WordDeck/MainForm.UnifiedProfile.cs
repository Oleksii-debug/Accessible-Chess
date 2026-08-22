namespace WordDeck;

internal sealed partial class MainForm
{
    internal void ExportUnifiedPersonalProfileInteractive()
    {
        SaveState();
        using var dialog = new SaveFileDialog
        {
            Title = "Export complete WordDeck personal progress profile",
            Filter = "WordDeck personal profile (*.json)|*.json",
            FileName = "WordDeck-profile-v3.json",
            AddExtension = true,
            DefaultExt = "json"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) { FocusCurrentWord(); return; }
        try
        {
            new UnifiedProfileService(_store).Export(_state, dialog.FileName);
            AnnounceStatus($"Complete personal profile exported to {dialog.FileName}. Recall, Spelling and Sentence learning state are included; canonical dictionary, audio and SentencePack content are not copied into the profile.");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Complete profile export failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            AnnounceStatus("Complete profile export failed. Existing personal state was not changed.");
        }
        FocusCurrentWord();
    }

    internal void ImportUnifiedPersonalProfileInteractive()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Import complete WordDeck personal progress profile",
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
            UnifiedProfileImportResult result = new UnifiedProfileService(_store).Import(
                dialog.FileName, _state, knownEntries, _packages.Keys);

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
            string modes = result.SentenceImported
                ? "Recall, Spelling and Sentence state were restored."
                : result.SpellingImported
                    ? "This older profile restored Recall and Spelling state; current Sentence state was intentionally preserved."
                    : "This V0.1 profile restored Recall state; current Spelling and Sentence state were intentionally preserved.";
            AnnounceStatus($"Personal profile imported successfully. {modes} Recovery backups were created before replacement. {quarantine}");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Complete profile import failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            AnnounceStatus("Complete profile import failed. Existing personal state was not replaced.");
        }
        FocusCurrentWord();
    }
}

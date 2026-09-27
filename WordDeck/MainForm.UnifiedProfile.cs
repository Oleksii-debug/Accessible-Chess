namespace WordDeck;

internal sealed partial class MainForm
{
    internal void ExportUnifiedPersonalProfileInteractive()
    {
        SaveState();
        using var dialog = new SaveFileDialog
        {
            Title = "Export unified WordDeck personal progress profile",
            Filter = "WordDeck personal profile (*.json)|*.json",
            FileName = "WordDeck-profile-v5.json",
            AddExtension = true,
            DefaultExt = "json"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) { FocusCurrentWord(); return; }
        try
        {
            new UnifiedProfileService(_store).Export(_state, dialog.FileName);
            AnnounceStatus(BuildUnifiedProfileExportSuccessStatus(dialog.FileName));
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Unified profile export failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            AnnounceStatus("Unified profile export failed. Existing personal state was not changed.");
        }
        FocusCurrentWord();
    }

    internal void ImportUnifiedPersonalProfileInteractive()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Import unified WordDeck personal progress profile",
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
            string modes = result.CourseImported
                ? "Recall, Spelling, Sentence, Listening and unified Course/Story learner-state were restored; separate per-course Story/Course progress files were not imported."
                : result.ListeningImported
                    ? "This older profile restored Recall, Spelling, Sentence and Listening state; current unified Course/Story learner-state and separate per-course Story/Course progress were intentionally preserved."
                    : result.SentenceImported
                        ? "This older profile restored Recall, Spelling and Sentence state; current Listening, unified Course/Story learner-state and separate per-course Story/Course progress were intentionally preserved."
                        : result.SpellingImported
                            ? "This older profile restored Recall and Spelling state; current Sentence, Listening, unified Course/Story learner-state and separate per-course Story/Course progress were intentionally preserved."
                            : "This V0.1 profile restored Recall state; current Spelling, Sentence, Listening, unified Course/Story learner-state and separate per-course Story/Course progress were intentionally preserved.";
            AnnounceStatus($"Personal profile imported successfully. {modes} Recovery backups were created before replacement. {quarantine}");
        }
        catch (IncompletePersonalStateRecoveryException ex)
        {
            MessageBox.Show(this, ex.Message, "Unified profile import failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            AnnounceStatus(BuildUnifiedProfileImportFailureStatus(ex));
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Unified profile import failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            AnnounceStatus(BuildUnifiedProfileImportFailureStatus(ex));
        }
        FocusCurrentWord();
    }

    internal static string BuildUnifiedProfileExportSuccessStatus(string destinationPath)
    {
        if (string.IsNullOrWhiteSpace(destinationPath)) throw new ArgumentException("Profile destination path is required.", nameof(destinationPath));
        return $"Unified personal profile exported to {destinationPath}. Recall, Spelling, Sentence, Listening and unified Course/Story learner-state are included. Separate per-course Story/Course progress files and private Reading books/positions are not included in this JSON; canonical dictionary, audio, course content and SentencePack content are also not copied.";
    }

    internal static string BuildUnifiedProfileImportFailureStatus(Exception error)
    {
        ArgumentNullException.ThrowIfNull(error);
        return error is IncompletePersonalStateRecoveryException
            ? "Unified profile import failed and automatic recovery was incomplete. Do not continue learning until personal state is restored from the pre-import recovery backups."
            : "Unified profile import failed. Existing personal state was not replaced.";
    }
}
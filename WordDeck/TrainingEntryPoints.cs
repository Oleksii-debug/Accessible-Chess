namespace WordDeck;

internal static class TrainingEntryPoints
{
    public static void Install(MainForm main)
    {
        MenuStrip? menu = main.Controls.OfType<MenuStrip>().FirstOrDefault();
        if (menu is null) return;

        // Install the current, dynamically generated help route before loading
        // optional training state. F1 and the visible Help menu must remain
        // truthful and usable even if Spelling/Sentence state needs recovery.
        main.InstallCurrentHelpRoute(menu);

        ToolStripMenuItem? tools = menu.Items.OfType<ToolStripMenuItem>()
            .FirstOrDefault(item => (item.Text ?? string.Empty).Replace("&", string.Empty).Equals("Tools", StringComparison.OrdinalIgnoreCase));
        if (tools is null) return;

        SpellingStateSession spelling;
        try
        {
            spelling = TrainingStateContinuityGuard.LoadSpelling();
        }
        catch (Exception ex)
        {
            AddUnavailableTrainingItems(tools, ex.Message);
            AddUnifiedProfileItems(tools, main, insertIndex: 2);
            return;
        }

        AppState appState = main.SharedAppStateForTraining;
        var shortcutManager = new ShortcutManager(appState, spelling.State.Decks, ShortcutDispatchContext.All);
        main.RefreshTrainingShortcutDefinitions(spelling.State.Decks);

        var openSpelling = new ToolStripMenuItem("Open &Spelling trainer...")
        {
            AccessibleName = "Open Spelling trainer",
            ShortcutKeys = shortcutManager.Get(ActionIds.OpenSpelling),
            ShowShortcutKeys = true
        };
        openSpelling.Click += (_, _) => OpenSpelling(main);

        var openSentence = new ToolStripMenuItem("Open S&entence Spelling trainer...")
        {
            AccessibleName = "Open Sentence Spelling trainer",
            ShortcutKeys = shortcutManager.Get(ActionIds.OpenSentenceCoach),
            ShowShortcutKeys = true
        };
        openSentence.Click += (_, _) => OpenSentenceCoach(main);

        var settings = new ToolStripMenuItem("Training &keyboard shortcuts...")
        {
            AccessibleName = "Spelling and Sentence Spelling keyboard shortcuts"
        };
        settings.Click += (_, _) => OpenTrainingShortcutSettings(main, openSpelling, openSentence);

        tools.DropDownItems.Insert(0, openSpelling);
        tools.DropDownItems.Insert(1, openSentence);
        tools.DropDownItems.Insert(2, settings);
        AddUnifiedProfileItems(tools, main, insertIndex: 3);
    }

    private static void AddUnifiedProfileItems(ToolStripMenuItem tools, MainForm main, int insertIndex)
    {
        var exportProfile = new ToolStripMenuItem("Export complete personal &profile...")
        {
            AccessibleName = "Export complete Recall Spelling and Sentence personal profile"
        };
        exportProfile.Click += (_, _) => main.ExportUnifiedPersonalProfileInteractive();

        var importProfile = new ToolStripMenuItem("Import complete personal pro&file...")
        {
            AccessibleName = "Import complete Recall Spelling and Sentence personal profile"
        };
        importProfile.Click += (_, _) => main.ImportUnifiedPersonalProfileInteractive();

        tools.DropDownItems.Insert(insertIndex, exportProfile);
        tools.DropDownItems.Insert(insertIndex + 1, importProfile);
        tools.DropDownItems.Insert(insertIndex + 2, new ToolStripSeparator());
    }

    private static void OpenTrainingShortcutSettings(MainForm owner, ToolStripMenuItem spellingItem, ToolStripMenuItem sentenceItem)
    {
        try
        {
            SpellingStateSession spelling = TrainingStateContinuityGuard.LoadSpelling();
            AppState appState = owner.SharedAppStateForTraining;
            var shortcuts = new ShortcutManager(appState, spelling.State.Decks, ShortcutDispatchContext.All);
            using var dialog = new ShortcutSettingsForm(shortcuts);
            dialog.ShowDialog(owner);
            owner.SaveSharedStateAfterTraining();
            owner.RefreshTrainingShortcutDefinitions(spelling.State.Decks);
            spellingItem.ShortcutKeys = shortcuts.Get(ActionIds.OpenSpelling);
            sentenceItem.ShortcutKeys = shortcuts.Get(ActionIds.OpenSentenceCoach);
        }
        catch (Exception ex)
        {
            ShowProtectedProgressError(owner, "Training shortcuts", ex);
        }
    }

    private static void OpenSpelling(MainForm owner)
    {
        try
        {
            AppState appState = owner.SharedAppStateForTraining;
            SpellingStateSession spelling = TrainingStateContinuityGuard.LoadSpelling();
            var shortcuts = new ShortcutManager(appState, spelling.State.Decks, ShortcutDispatchContext.Spelling);
            DictionaryPackage package = owner.ActivePackageForTraining;

            using IDisposable reviewPriority = SpellingReviewOrder.BeginSession(spelling.State, package.Id);
            using var form = new SpellingForm(appState, spelling.State, spelling.Store, shortcuts, package);
            using var blankSubmitGuard = BlankLearningSubmissionGuard.Attach(form, "Type English spelling answer");
            KeyboardSelectorFocusGuard.Attach(form, "Spelling study scope", "Active spelling deck");
            form.ShowDialog(owner);
            owner.SaveSharedStateAfterTraining();
            owner.RefreshTrainingShortcutDefinitions(spelling.State.Decks);
        }
        catch (Exception ex)
        {
            ShowProtectedProgressError(owner, "Spelling", ex);
        }
    }

    private static void OpenSentenceCoach(MainForm owner)
    {
        try
        {
            AppState appState = owner.SharedAppStateForTraining;
            SpellingStateSession spelling = TrainingStateContinuityGuard.LoadSpelling();
            SentenceStateSession sentence = TrainingStateContinuityGuard.LoadSentence();
            var shortcuts = new ShortcutManager(appState, spelling.State.Decks, ShortcutDispatchContext.Sentence);
            DictionaryPackage package = owner.ActivePackageForTraining;

            using var form = new SentenceCoachForm(
                appState,
                spelling.State,
                shortcuts,
                package,
                new SentencePackStore(),
                sentence.Store,
                sentence.State);
            using var blankSubmitGuard = BlankLearningSubmissionGuard.Attach(form, "Type the English sentence words");
            KeyboardSelectorFocusGuard.Attach(form, "Sentence pack", "Sentence training spelling deck", "Number of target words per sentence");
            form.ShowDialog(owner);
            owner.SaveSharedStateAfterTraining();
            owner.RefreshTrainingShortcutDefinitions(spelling.State.Decks);
        }
        catch (Exception ex)
        {
            ShowProtectedProgressError(owner, "Sentence Spelling", ex);
        }
    }

    private static void AddUnavailableTrainingItems(ToolStripMenuItem tools, string reason)
    {
        var unavailable = new ToolStripMenuItem("Training progress needs recovery")
        {
            AccessibleName = "Training progress needs recovery",
            AccessibleDescription = reason,
            Enabled = false
        };
        tools.DropDownItems.Insert(0, unavailable);
        tools.DropDownItems.Insert(1, new ToolStripSeparator());
    }

    private static void ShowProtectedProgressError(IWin32Window owner, string area, Exception ex)
    {
        MessageBox.Show(
            owner,
            $"{area} was not opened because WordDeck could not safely load its learning state. Existing progress files were left untouched.\n\n{ex.Message}",
            "WordDeck protected your learning progress",
            MessageBoxButtons.OK,
            MessageBoxIcon.Warning);
    }
}

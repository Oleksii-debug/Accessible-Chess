namespace WordDeck;

internal static class TrainingEntryPoints
{
    public static void Install(MainForm main)
    {
        MenuStrip? menu = main.Controls.OfType<MenuStrip>().FirstOrDefault();
        if (menu is null) return;
        ToolStripMenuItem? tools = menu.Items.OfType<ToolStripMenuItem>()
            .FirstOrDefault(item => (item.Text ?? string.Empty).Replace("&", string.Empty).Equals("Tools", StringComparison.OrdinalIgnoreCase));
        if (tools is null) return;

        SpellingState spellingState;
        try
        {
            spellingState = TrainingStateContinuityGuard.LoadSpelling().State;
        }
        catch (InvalidDataException)
        {
            // Broken optional training state must not prevent Recall startup.
            // This normalized in-memory shape is used only to render default
            // shortcut labels; opening the affected trainer still fails closed.
            spellingState = SpellingStateStore.Normalize(new SpellingState());
        }
        var shortcutManager = new ShortcutManager(main.SharedAppStateForTraining, spellingState.Decks);

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
        tools.DropDownItems.Insert(3, new ToolStripSeparator());
    }

    private static void OpenTrainingShortcutSettings(MainForm owner, ToolStripMenuItem spellingItem, ToolStripMenuItem sentenceItem)
    {
        try
        {
            SpellingState spellingState = TrainingStateContinuityGuard.LoadSpelling().State;
            var shortcuts = new ShortcutManager(owner.SharedAppStateForTraining, spellingState.Decks);
            using var dialog = new ShortcutSettingsForm(shortcuts);
            dialog.ShowDialog(owner);
            owner.SaveSharedStateAfterTraining();
            spellingItem.ShortcutKeys = shortcuts.Get(ActionIds.OpenSpelling);
            sentenceItem.ShortcutKeys = shortcuts.Get(ActionIds.OpenSentenceCoach);
        }
        catch (InvalidDataException ex)
        {
            ShowTrainingStateError(owner, ex.Message);
        }
    }

    private static void OpenSpelling(MainForm owner)
    {
        try
        {
            SpellingStateSession session = TrainingStateContinuityGuard.LoadSpelling();
            var shortcuts = new ShortcutManager(owner.SharedAppStateForTraining, session.State.Decks);
            using var form = new SpellingForm(
                owner.SharedAppStateForTraining,
                session.State,
                session.Store,
                shortcuts,
                owner.ActivePackageForTraining);
            form.ShowDialog(owner);
            owner.SaveSharedStateAfterTraining();
        }
        catch (InvalidDataException ex)
        {
            ShowTrainingStateError(owner, ex.Message);
        }
    }

    private static void OpenSentenceCoach(MainForm owner)
    {
        try
        {
            SpellingStateSession spellingSession = TrainingStateContinuityGuard.LoadSpelling();
            SentenceStateSession sentenceSession = TrainingStateContinuityGuard.LoadSentence();
            var shortcuts = new ShortcutManager(owner.SharedAppStateForTraining, spellingSession.State.Decks);
            using var form = new SentenceCoachForm(
                owner.SharedAppStateForTraining,
                spellingSession.State,
                shortcuts,
                owner.ActivePackageForTraining,
                new SentencePackStore(),
                sentenceSession.Store,
                sentenceSession.State);
            form.ShowDialog(owner);
            owner.SaveSharedStateAfterTraining();
        }
        catch (InvalidDataException ex)
        {
            ShowTrainingStateError(owner, ex.Message);
        }
    }

    private static void ShowTrainingStateError(Form owner, string message)
    {
        MessageBox.Show(
            owner,
            message + Environment.NewLine + Environment.NewLine +
            "The existing files were left untouched. Restore a known-good backup before continuing this training mode.",
            "WordDeck protected training progress",
            MessageBoxButtons.OK,
            MessageBoxIcon.Error);
    }
}

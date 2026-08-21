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

        SpellingState spellingState = new SpellingStateStore().Load();
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
        // Use the Recall window's live AppState instance. A second Load() here
        // creates a stale-write race: whichever module saves last wins.
        SpellingState spellingState = new SpellingStateStore().Load();
        var shortcuts = new ShortcutManager(owner.SharedAppStateForTraining, spellingState.Decks);
        using var dialog = new ShortcutSettingsForm(shortcuts);
        dialog.ShowDialog(owner);
        owner.SaveSharedStateAfterTraining();
        spellingItem.ShortcutKeys = shortcuts.Get(ActionIds.OpenSpelling);
        sentenceItem.ShortcutKeys = shortcuts.Get(ActionIds.OpenSentenceCoach);
    }

    private static void OpenSpelling(MainForm owner)
    {
        var spellingStore = new SpellingStateStore();
        SpellingState spellingState = spellingStore.Load();
        var shortcuts = new ShortcutManager(owner.SharedAppStateForTraining, spellingState.Decks);

        using var form = new SpellingForm(
            owner.SharedAppStateForTraining,
            spellingState,
            spellingStore,
            shortcuts,
            owner.ActivePackageForTraining);
        form.ShowDialog(owner);
        owner.SaveSharedStateAfterTraining();
    }

    private static void OpenSentenceCoach(MainForm owner)
    {
        SpellingState spellingState = new SpellingStateStore().Load();
        var shortcuts = new ShortcutManager(owner.SharedAppStateForTraining, spellingState.Decks);
        var sentenceStateStore = new SentenceCoachStateStore();
        SentenceCoachState sentenceState = sentenceStateStore.Load();

        using var form = new SentenceCoachForm(
            owner.SharedAppStateForTraining,
            spellingState,
            shortcuts,
            owner.ActivePackageForTraining,
            new SentencePackStore(),
            sentenceStateStore,
            sentenceState);
        form.ShowDialog(owner);
        owner.SaveSharedStateAfterTraining();
    }
}

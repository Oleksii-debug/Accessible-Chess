namespace WordDeck;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
        {
            try
            {
                SpellingSelfTest.Run();
                SentenceCoachSelfTest.Run();
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"WordDeck extended self-test FAILED: {ex}");
                return 1;
            }
            return SelfTest.Run();
        }

        ApplicationConfiguration.Initialize();
        AccessibilityAnnouncer.Install();

        var main = new MainForm();
        InstallSpellingEntryPoint(main);
        Application.Run(main);
        return 0;
    }

    private static void InstallSpellingEntryPoint(MainForm main)
    {
        MenuStrip? menu = main.Controls.OfType<MenuStrip>().FirstOrDefault();
        if (menu is null)
            return;

        ToolStripMenuItem? tools = menu.Items.OfType<ToolStripMenuItem>()
            .FirstOrDefault(item => (item.Text ?? string.Empty).Replace("&", string.Empty).Equals("Tools", StringComparison.OrdinalIgnoreCase));
        if (tools is null)
            return;

        AppState appState = new AppStateStore().Load();
        var spellingStore = new SpellingStateStore();
        SpellingState spellingState = spellingStore.Load();
        var shortcutManager = new ShortcutManager(appState, spellingState.Decks);
        var open = new ToolStripMenuItem("Open &Spelling trainer...")
        {
            AccessibleName = "Open Spelling trainer",
            ShortcutKeys = shortcutManager.Get(ActionIds.OpenSpelling),
            ShowShortcutKeys = true
        };
        open.Click += (_, _) => OpenSpelling(main);

        var settings = new ToolStripMenuItem("Spelling &keyboard shortcuts...")
        {
            AccessibleName = "Spelling keyboard shortcuts"
        };
        settings.Click += (_, _) => OpenSpellingShortcutSettings(main, open);

        tools.DropDownItems.Insert(0, open);
        tools.DropDownItems.Insert(1, settings);
        tools.DropDownItems.Insert(2, new ToolStripSeparator());
    }

    private static void OpenSpellingShortcutSettings(Form owner, ToolStripMenuItem openItem)
    {
        var appStore = new AppStateStore();
        AppState appState = appStore.Load();
        SpellingState spellingState = new SpellingStateStore().Load();
        var shortcuts = new ShortcutManager(appState, spellingState.Decks);
        using var dialog = new ShortcutSettingsForm(shortcuts);
        dialog.ShowDialog(owner);
        appStore.Save(appState);
        openItem.ShortcutKeys = shortcuts.Get(ActionIds.OpenSpelling);
    }

    private static void OpenSpelling(MainForm owner)
    {
        var appStore = new AppStateStore();
        AppState appState = appStore.Load();
        var spellingStore = new SpellingStateStore();
        SpellingState spellingState = spellingStore.Load();
        var shortcuts = new ShortcutManager(appState, spellingState.Decks);
        DictionaryPackage package = BuildActivePackage(appState);

        using var form = new SpellingForm(appState, spellingState, spellingStore, shortcuts, package);
        form.ShowDialog(owner);
        appStore.Save(appState);
    }

    private static DictionaryPackage BuildActivePackage(AppState state)
    {
        DictionaryPackage basePackage = DictionaryLoader.LoadEmbeddedOxford();
        if (!string.IsNullOrWhiteSpace(state.ActiveDictionaryId) &&
            !string.Equals(state.ActiveDictionaryId, basePackage.Id, StringComparison.OrdinalIgnoreCase))
        {
            var store = new AppStateStore();
            foreach (string path in store.EnumerateDictionaryFiles())
            {
                try
                {
                    DictionaryPackage candidate = DictionaryLoader.LoadFromFile(path);
                    if (string.Equals(candidate.Id, state.ActiveDictionaryId, StringComparison.OrdinalIgnoreCase))
                    {
                        basePackage = candidate;
                        break;
                    }
                }
                catch
                {
                    // An invalid optional import must not prevent Spelling from opening.
                }
            }
        }

        if (!state.CustomEntriesByDictionary.TryGetValue(basePackage.Id, out List<CustomEntryRecord>? custom) || custom.Count == 0)
            return basePackage;

        var seen = new HashSet<string>(basePackage.Entries.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
        var entries = new List<DictionaryEntry>(basePackage.Entries);
        foreach (CustomEntryRecord record in custom)
            if (seen.Add(record.Id))
                entries.Add(new DictionaryEntry(record.Id, record.Level, record.Source, record.Target));

        return new DictionaryPackage
        {
            Id = basePackage.Id,
            Name = basePackage.Name,
            SourceLanguage = basePackage.SourceLanguage,
            TargetLanguage = basePackage.TargetLanguage,
            Entries = entries
        };
    }
}

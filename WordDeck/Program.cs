namespace WordDeck;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length > 0 && args[0].Equals("--build-tatoeba-sentence-pack", StringComparison.OrdinalIgnoreCase))
            return BuildTatoebaSentencePack(args);

        if (args.Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
        {
            try
            {
                SpellingSelfTest.Run();
                SentenceCoachSelfTest.Run();
                TatoebaSentencePackSelfTest.Run();
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

    private static int BuildTatoebaSentencePack(string[] args)
    {
        if (args.Length is < 3 or > 4)
        {
            Console.Error.WriteLine("Usage: WordDeck.exe --build-tatoeba-sentence-pack <en-uk-pairs.tsv> <output.json> [pack-id]");
            return 2;
        }

        try
        {
            string inputPath = Path.GetFullPath(args[1]);
            string outputPath = Path.GetFullPath(args[2]);
            string packId = args.Length == 4 ? args[3].Trim() : $"tatoeba-en-uk-{DateTime.UtcNow:yyyyMMdd}";
            if (!File.Exists(inputPath))
                throw new FileNotFoundException("Tatoeba EN-UA pair export was not found.", inputPath);

            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            IEnumerable<TatoebaSentencePair> pairs = TatoebaPairTsv.ParseLines(File.ReadLines(inputPath));
            (SentencePack pack, SentencePackBuildReport report) = TatoebaSentencePackBuilder.Build(
                pairs,
                dictionary,
                packId,
                "Tatoeba EN-UA sentence-pair export; built by WordDeck development importer. Upstream sentence and translation IDs are preserved per record.",
                "CC BY 2.0 FR; verify the selected upstream export/subset before redistribution and preserve attribution.");

            string? directory = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrWhiteSpace(directory))
                Directory.CreateDirectory(directory);
            File.WriteAllText(outputPath, SentencePackJson.Serialize(pack));

            Console.WriteLine($"SentencePack written: {outputPath}");
            Console.WriteLine($"Input pairs: {report.InputPairs}; accepted: {report.AcceptedPairs}; rejected: {report.RejectedPairs}; indexed entry references: {report.IndexedEntryIds}; off-list tokens: {report.OffListTokens}.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"SentencePack build FAILED: {ex.Message}");
            return 1;
        }
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

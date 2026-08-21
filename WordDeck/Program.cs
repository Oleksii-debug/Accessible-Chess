namespace WordDeck;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length > 0 && args[0].Equals("--build-tatoeba-sentence-pack", StringComparison.OrdinalIgnoreCase))
            return BuildTatoebaSentencePack(args);

        if (args.Length > 0 && args[0].Equals("--measure-sentence-pack", StringComparison.OrdinalIgnoreCase))
            return SentencePackDiagnostics.Run(args);

        if (args.Length > 0 && args[0].Equals("--export-oxford5000-audio-source", StringComparison.OrdinalIgnoreCase))
            return ExportOxford5000AudioSource(args);

        if (args.Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
        {
            try
            {
                StudyScopeSelfTest.Run();
                UserDataSelfTest.Run();
                SpellingSelfTest.Run();
                SentenceCoachSelfTest.Run();
                SentencePackStoreSelfTest.Run();
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
        InstallTrainingEntryPoints(main);
        Application.Run(main);
        return 0;
    }

    private static int ExportOxford5000AudioSource(string[] args)
    {
        if (args.Length != 2)
        {
            Console.Error.WriteLine("Usage: WordDeck.exe --export-oxford5000-audio-source <output.tsv>");
            return 2;
        }

        try
        {
            string outputPath = Path.GetFullPath(args[1]);
            IReadOnlyList<DictionaryEntry> additions = ReviewedOxford5000Bootstrap.BuildEntriesForTest();
            if (additions.Count != ReviewedOxford5000Bootstrap.ExpectedCanonicalRows)
                throw new InvalidDataException($"Expected {ReviewedOxford5000Bootstrap.ExpectedCanonicalRows} verified Oxford 5000 additions, got {additions.Count}.");

            string? directory = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);

            using var writer = new StreamWriter(outputPath, false, new System.Text.UTF8Encoding(false));
            writer.WriteLine("entry_id\tlevel\tsource");
            var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (DictionaryEntry entry in additions)
            {
                if (!ids.Add(entry.Id))
                    throw new InvalidDataException($"Duplicate Oxford 5000 audio stable ID: {entry.Id}.");
                if (string.IsNullOrWhiteSpace(entry.Source) || string.IsNullOrWhiteSpace(entry.Level))
                    throw new InvalidDataException($"Oxford 5000 audio source contains incomplete entry {entry.Id}.");
                if (entry.Source.Contains('\t') || entry.Source.Contains('\r') || entry.Source.Contains('\n'))
                    throw new InvalidDataException($"Oxford 5000 audio source is not TSV-safe: {entry.Id}.");
                writer.Write(entry.Id);
                writer.Write('\t');
                writer.Write(entry.Level);
                writer.Write('\t');
                writer.WriteLine(entry.Source);
            }

            Console.WriteLine($"Oxford 5000 verified audio source written: {outputPath}; rows={additions.Count}.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Oxford 5000 audio-source export FAILED: {ex.Message}");
            return 1;
        }
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

            TatoebaImportMetadata metadata = TatoebaImportProvenance.Resolve(inputPath);
            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            IEnumerable<TatoebaSentencePair> pairs = TatoebaPairTsv.ParseLines(File.ReadLines(inputPath));
            (SentencePack pack, SentencePackBuildReport report) = TatoebaSentencePackBuilder.Build(
                pairs, dictionary, packId, metadata.Provenance, metadata.License);

            string? directory = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
            File.WriteAllText(outputPath, SentencePackJson.Serialize(pack));

            Console.WriteLine($"SentencePack written: {outputPath}");
            Console.WriteLine($"License metadata: {metadata.License}; verified CC0 manifest: {metadata.VerifiedCc0Manifest}; verified attributed CC-BY manifest: {metadata.VerifiedAttributedCcByManifest}.");
            Console.WriteLine($"Input pairs: {report.InputPairs}; accepted: {report.AcceptedPairs}; rejected: {report.RejectedPairs}; indexed entry references: {report.IndexedEntryIds}; off-list tokens: {report.OffListTokens}.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"SentencePack build FAILED: {ex.Message}");
            return 1;
        }
    }

    private static void InstallTrainingEntryPoints(MainForm main)
    {
        MenuStrip? menu = main.Controls.OfType<MenuStrip>().FirstOrDefault();
        if (menu is null) return;
        ToolStripMenuItem? tools = menu.Items.OfType<ToolStripMenuItem>()
            .FirstOrDefault(item => (item.Text ?? string.Empty).Replace("&", string.Empty).Equals("Tools", StringComparison.OrdinalIgnoreCase));
        if (tools is null) return;

        var openSpelling = new ToolStripMenuItem("Open &Spelling trainer...")
        {
            AccessibleName = "Open Spelling trainer",
            ShortcutKeys = Keys.None,
            ShowShortcutKeys = true
        };
        openSpelling.Click += (_, _) => OpenSpelling(main);

        var openSentence = new ToolStripMenuItem("Open S&entence Spelling trainer...")
        {
            AccessibleName = "Open Sentence Spelling trainer",
            ShortcutKeys = Keys.None,
            ShowShortcutKeys = true
        };
        openSentence.Click += (_, _) => OpenSentenceCoach(main);

        var settings = new ToolStripMenuItem("Training &keyboard shortcuts...")
        {
            AccessibleName = "Spelling and Sentence Spelling keyboard shortcuts"
        };
        settings.Click += (_, _) =>
        {
            OpenTrainingShortcutSettings(main);
            RefreshTrainingMenuShortcutLabels(openSpelling, openSentence);
        };

        tools.DropDownOpening += (_, _) => RefreshTrainingMenuShortcutLabels(openSpelling, openSentence);
        tools.DropDownItems.Insert(0, openSpelling);
        tools.DropDownItems.Insert(1, openSentence);
        tools.DropDownItems.Insert(2, settings);
        tools.DropDownItems.Insert(3, new ToolStripSeparator());
        RefreshTrainingMenuShortcutLabels(openSpelling, openSentence);

        // Menu ShortcutKeys used to become stale when the shared binding was
        // changed elsewhere. A single message filter now resolves the persisted
        // binding at dispatch time, while the menu renders the same live binding
        // as display text. The filter only launches training from the MainForm and
        // only handles Help/Settings when a training form is active.
        Application.AddMessageFilter(new TrainingShortcutMessageFilter(main));
    }

    private static void RefreshTrainingMenuShortcutLabels(ToolStripMenuItem spellingItem, ToolStripMenuItem sentenceItem)
    {
        try
        {
            AppState appState = new AppStateStore().Load();
            SpellingState spellingState = new SpellingStateStore().Load();
            var shortcuts = new ShortcutManager(appState, spellingState.Decks);
            spellingItem.ShortcutKeyDisplayString = ShortcutFormatter.Format(shortcuts.Get(ActionIds.OpenSpelling));
            sentenceItem.ShortcutKeyDisplayString = ShortcutFormatter.Format(shortcuts.Get(ActionIds.OpenSentenceCoach));
        }
        catch (InvalidDataException)
        {
            spellingItem.ShortcutKeyDisplayString = "State unavailable";
            sentenceItem.ShortcutKeyDisplayString = "State unavailable";
        }
    }

    private static void OpenTrainingShortcutSettings(Form owner)
    {
        try
        {
            var appStore = new AppStateStore();
            AppState appState = appStore.Load();
            SpellingState spellingState = new SpellingStateStore().Load();
            var shortcuts = new ShortcutManager(appState, spellingState.Decks);
            using var dialog = new ShortcutSettingsForm(shortcuts);
            dialog.ShowDialog(owner);
            appStore.Save(appState);
        }
        catch (Exception ex)
        {
            MessageBox.Show(owner, ex.Message, "Keyboard shortcut settings failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static void ShowTrainingHelp(Form owner)
    {
        try
        {
            AppState appState = new AppStateStore().Load();
            SpellingState spellingState = new SpellingStateStore().Load();
            var shortcuts = new ShortcutManager(appState, spellingState.Decks);
            IReadOnlyList<ShortcutDefinition> definitions = shortcuts.Definitions
                .Where(definition =>
                    definition.Id == ActionIds.Help ||
                    definition.Id == ActionIds.ShortcutSettings ||
                    definition.Id == ActionIds.OpenSpelling ||
                    definition.Id == ActionIds.OpenSentenceCoach ||
                    definition.Description.StartsWith("Spelling:", StringComparison.OrdinalIgnoreCase) ||
                    definition.Description.StartsWith("Sentence Spelling:", StringComparison.OrdinalIgnoreCase))
                .ToList();
            string lines = string.Join(Environment.NewLine, definitions.Select(definition =>
                $"{definition.Description}: {ShortcutFormatter.Format(shortcuts.Get(definition.Id))}"));
            string scope = spellingState.ActiveScopeIdByDictionary.Count == 0
                ? StudyScopeIds.DisplayName(StudyScopeIds.All)
                : StudyScopeIds.DisplayName(spellingState.ActiveScopeIdByDictionary.Values.First());
            string help =
                "WORDDECK SPELLING HELP\r\n\r\n" +
                "Spelling uses Ukrainian prompts and exact English typing. Press Enter to check the current card. A wrong answer stays on the same card. Showing the answer or using a pronunciation hint never passes the card automatically.\r\n\r\n" +
                "Spelling has independent All/A1/A2/B1/B2/C1 deck assignments. Hidden words are excluded without deleting the canonical dictionary or audio. The current saved Spelling scope is " + scope + ".\r\n\r\n" +
                "Adaptive Coach is deterministic and local. Automatic moves are limited to the five core Spelling decks. User-created decks are never redistributed automatically. Coach decisions can be undone while the recorded assignment still matches.\r\n\r\n" +
                "CURRENT TRAINING SHORTCUTS\r\n" + lines + "\r\n\r\n" +
                "Use the keyboard shortcut settings command to rebind actions. Conflicts and Windows-reserved combinations fail closed.";

            using var form = new Form
            {
                Text = "WordDeck Spelling help",
                Width = 820,
                Height = 650,
                StartPosition = FormStartPosition.CenterParent,
                AccessibleName = "WordDeck Spelling help"
            };
            var box = new TextBox
            {
                Dock = DockStyle.Fill,
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                Text = help,
                AccessibleName = "WordDeck Spelling help text"
            };
            form.Controls.Add(box);
            form.Shown += (_, _) =>
            {
                box.Focus();
                box.SelectionStart = 0;
                box.SelectionLength = 0;
            };
            form.ShowDialog(owner);
        }
        catch (Exception ex)
        {
            MessageBox.Show(owner, ex.Message, "Spelling help unavailable", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private sealed class TrainingShortcutMessageFilter : IMessageFilter
    {
        private const int WmKeyDown = 0x0100;
        private const int WmSysKeyDown = 0x0104;
        private readonly MainForm _main;
        private bool _handling;

        public TrainingShortcutMessageFilter(MainForm main) => _main = main;

        public bool PreFilterMessage(ref Message m)
        {
            if (_handling || (m.Msg != WmKeyDown && m.Msg != WmSysKeyDown)) return false;
            Form? active = Form.ActiveForm;
            if (active is null) return false;

            try
            {
                AppState appState = new AppStateStore().Load();
                SpellingState spellingState = new SpellingStateStore().Load();
                var shortcuts = new ShortcutManager(appState, spellingState.Decks);
                Keys keyData = (Keys)m.WParam.ToInt32() | Control.ModifierKeys;

                if (ReferenceEquals(active, _main))
                {
                    if (keyData == shortcuts.Get(ActionIds.OpenSpelling))
                    {
                        _handling = true;
                        try { OpenSpelling(_main); } finally { _handling = false; }
                        return true;
                    }
                    if (keyData == shortcuts.Get(ActionIds.OpenSentenceCoach))
                    {
                        _handling = true;
                        try { OpenSentenceCoach(_main); } finally { _handling = false; }
                        return true;
                    }
                    return false;
                }

                bool trainingActive = active is SpellingForm || active is SentenceCoachForm;
                if (!trainingActive) return false;

                if (keyData == shortcuts.Get(ActionIds.Help))
                {
                    _handling = true;
                    try { ShowTrainingHelp(active); } finally { _handling = false; }
                    return true;
                }
                if (keyData == shortcuts.Get(ActionIds.ShortcutSettings))
                {
                    _handling = true;
                    try { OpenTrainingShortcutSettings(active); } finally { _handling = false; }
                    return true;
                }
            }
            catch (InvalidDataException)
            {
                // State corruption is handled by normal WordDeck state loading.
                // Do not mask it with a second silent shortcut state.
            }
            return false;
        }
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

    private static void OpenSentenceCoach(MainForm owner)
    {
        var appStore = new AppStateStore();
        AppState appState = appStore.Load();
        SpellingState spellingState = new SpellingStateStore().Load();
        var shortcuts = new ShortcutManager(appState, spellingState.Decks);
        DictionaryPackage package = BuildActivePackage(appState);
        var sentenceStateStore = new SentenceCoachStateStore();
        SentenceCoachState sentenceState = sentenceStateStore.Load();

        using var form = new SentenceCoachForm(
            appState,
            spellingState,
            shortcuts,
            package,
            new SentencePackStore(),
            sentenceStateStore,
            sentenceState);
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
                    // An invalid optional import must not prevent training modes from opening.
                }
            }
        }

        if (!state.CustomEntriesByDictionary.TryGetValue(basePackage.Id, out List<CustomEntryRecord>? custom) || custom.Count == 0)
            return basePackage;

        var seen = new HashSet<string>(basePackage.Entries.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
        var entries = new List<DictionaryEntry>(basePackage.Entries);
        foreach (CustomEntryRecord record in custom)
            if (seen.Add(record.Id)) entries.Add(new DictionaryEntry(record.Id, record.Level, record.Source, record.Target));

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
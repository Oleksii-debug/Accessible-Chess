using System.Runtime.CompilerServices;
using System.Text.Json;
using WordDeck;

internal static class ProfileContinuityTests
{
    [ModuleInitializer]
    internal static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck R3 profile Київ {Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            DictionaryEntry target = dictionary.Entries.First();
            string packSource = Path.Combine(root, "profile-pack.json.gz");
            SentencePackIo.WriteGZip(packSource, BuildPack(target));
            InstalledSentencePack installed = new SentencePackStore(root).Import(packSource);

            var appStore = new AppStateStore(root);
            var sentenceStore = new SentenceCoachStateStore(root);
            var coordinator = new PersonalProfileCoordinator(appStore, root);

            var state = new AppState { ActiveDictionaryId = dictionary.Id };
            AppStateStore.Normalize(state);
            state.HiddenEntryIds.Add(target.Id);
            var sentence = new SentenceCoachState
            {
                ActivePackId = installed.PackId,
                TargetCount = 1,
                CurrentSentenceId = "profile-sentence",
                CurrentTargetEntryId = target.Id,
                CurrentTargetEntryIds = new List<string> { target.Id },
                RecentSentenceIds = new List<string> { "profile-sentence" }
            };
            sentence.StatsByDictionary[dictionary.Id] = new Dictionary<string, SentenceTargetStats>(StringComparer.OrdinalIgnoreCase)
            {
                [target.Id] = new SentenceTargetStats { CompletedReviews = 3, FirstTrySuccesses = 2, WrongAttempts = 1 }
            };
            sentenceStore.Save(sentence);

            string profile = Path.Combine(root, "combined-profile.json");
            coordinator.Export(state, profile);
            Require(File.ReadAllText(profile).Contains("SentenceState", StringComparison.Ordinal),
                "Combined profile export omitted SentenceState.");

            var destination = new AppState { ActiveDictionaryId = dictionary.Id };
            AppStateStore.Normalize(destination);
            sentenceStore.Save(new SentenceCoachState { ActivePackId = installed.PackId, TargetCount = 1 });
            ProfileImportResult result = coordinator.Import(profile, destination, dictionary.Entries.Select(entry => entry.Id), new[] { dictionary.Id });
            Require(File.Exists(result.BackupPath), "Combined profile import did not create a pre-import recovery profile.");
            Require(destination.HiddenEntryIds.Contains(target.Id), "Combined profile import lost Recall hidden-word state.");
            SentenceCoachState restored = sentenceStore.Load();
            Require(restored.ActivePackId == installed.PackId && restored.CurrentSentenceId == "profile-sentence",
                "Combined profile import lost Sentence pack/current exercise state.");
            Require(restored.StatsByDictionary[dictionary.Id][target.Id].CompletedReviews == 3,
                "Combined profile import lost Sentence statistics.");

            string incompatible = Path.Combine(root, "incompatible-profile.json");
            string json = File.ReadAllText(profile).Replace(AppStateStore.CorpusIdentity, "incompatible-corpus", StringComparison.Ordinal);
            File.WriteAllText(incompatible, json);
            destination.HiddenEntryIds.Clear();
            SentenceCoachState beforeSentence = sentenceStore.Load();
            ExpectFailure(
                () => coordinator.Import(incompatible, destination, dictionary.Entries.Select(entry => entry.Id), new[] { dictionary.Id }),
                "Incompatible-corpus combined profile was accepted.");
            Require(destination.HiddenEntryIds.Count == 0,
                "Incompatible-corpus profile mutated Recall state before rejection.");
            Require(sentenceStore.Load().CurrentSentenceId == beforeSentence.CurrentSentenceId,
                "Incompatible-corpus profile mutated Sentence state before rejection.");

            string legacy = Path.Combine(root, "legacy-v01-profile.json");
            appStore.ExportProfile(state, legacy);
            var preservedSentence = new SentenceCoachState
            {
                ActivePackId = installed.PackId,
                TargetCount = 1,
                CurrentSentenceId = "preserve-existing-sentence",
                CurrentTargetEntryId = target.Id,
                CurrentTargetEntryIds = new List<string> { target.Id }
            };
            sentenceStore.Save(preservedSentence);
            coordinator.Import(legacy, destination, dictionary.Entries.Select(entry => entry.Id), new[] { dictionary.Id });
            Require(sentenceStore.Load().CurrentSentenceId == "preserve-existing-sentence",
                "Legacy V0.1 profile without SentenceState wiped existing Sentence progress.");

            Console.WriteLine("R3 combined personal-profile continuity tests passed.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static SentencePack BuildPack(DictionaryEntry target)
    {
        const string english = "we learn words";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        var pack = new SentencePack
        {
            PackId = "profile-pack-r3",
            Provenance = "Synthetic Round-3 profile fixture",
            License = "CC0 1.0",
            Sentences = new List<SentenceRecord>
            {
                new()
                {
                    Id = "profile-sentence",
                    English = english,
                    Ukrainian = "Ми вивчаємо слова",
                    Source = "Synthetic Round-3 profile fixture",
                    License = "CC0 1.0",
                    Tokens = tokens,
                    Lemmas = tokens.ToList(),
                    TargetEntryIds = new List<string> { target.Id },
                    EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { [target.Id] = target.Level },
                    DifficultyLevel = target.Level
                }
            }
        };
        pack.Validate();
        return pack;
    }

    private static void ExpectFailure(Action action, string message)
    {
        try { action(); }
        catch { return; }
        throw new InvalidDataException(message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}

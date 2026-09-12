using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace WordDeck;

internal static class UnifiedProfileSelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        Run();
    }

    internal static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck unified profile Київ {Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            const string dictionaryId = "oxford-3000-en-uk";
            const string knownId = "word-a";
            var appStore = new AppStateStore(root);
            var spellingStore = new SpellingStateStore(root);
            var sentenceStore = new SentenceCoachStateStore(root);
            var listeningStore = new ListeningStateStore(root);
            AppState app = AppStateStore.Normalize(new AppState { ActiveDictionaryId = dictionaryId });
            app.HiddenEntryIds.Add(knownId);
            appStore.Save(app);

            SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
            spelling.StatsByDictionary[dictionaryId] = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase)
            {
                [knownId] = new SpellingEntryStats { CompletedReviews = 4, FirstTrySuccesses = 3, CurrentStreak = 2 }
            };
            spellingStore.Save(spelling);

            SentenceCoachState sentence = SentenceCoachStateStore.Normalize(new SentenceCoachState { TargetCount = 1 });
            sentence.StatsByDictionary[dictionaryId] = new Dictionary<string, SentenceTargetStats>(StringComparer.OrdinalIgnoreCase)
            {
                [knownId] = new SentenceTargetStats { CompletedReviews = 2, FirstTrySuccesses = 1 }
            };
            sentenceStore.Save(sentence);

            ListeningCoachState listening = ListeningStateStore.Normalize(new ListeningCoachState { ActiveScopeId = StudyScopeIds.B1 });
            listening.StatsByDictionary[dictionaryId] = new Dictionary<string, ListeningItemStats>(StringComparer.OrdinalIgnoreCase)
            {
                ["word:" + knownId] = new ListeningItemStats { CompletedReviews = 3, CorrectReviews = 2, WrongAttempts = 1 }
            };
            listeningStore.Save(listening);

            var service = new UnifiedProfileService(appStore, root);
            string profile = Path.Combine(root, "WordDeck-profile-v4.json");
            service.Export(app, profile);
            using (JsonDocument exported = JsonDocument.Parse(File.ReadAllText(profile)))
            {
                Require(exported.RootElement.GetProperty("ProfileSchemaVersion").GetInt32() == 4, "Unified export did not use schema 4.");
                Require(exported.RootElement.TryGetProperty("SpellingState", out _), "Unified export lost Spelling state.");
                Require(exported.RootElement.TryGetProperty("SentenceState", out _), "Unified export lost Sentence state.");
                Require(exported.RootElement.TryGetProperty("ListeningState", out _), "Unified export lost Listening state.");
            }

            app.HiddenEntryIds.Clear();
            appStore.Save(app);
            spellingStore.Save(SpellingStateStore.Normalize(new SpellingState()));
            sentenceStore.Save(SentenceCoachStateStore.Normalize(new SentenceCoachState()));
            listeningStore.Save(ListeningStateStore.Normalize(new ListeningCoachState()));

            UnifiedProfileImportResult result = service.Import(profile, app, new[] { knownId }, new[] { dictionaryId });
            Require(result.SpellingImported && result.SentenceImported && result.ListeningImported && result.SourceProfileSchemaVersion == 4,
                "Unified profile did not report all four states imported.");
            Require(app.HiddenEntryIds.Contains(knownId), "Unified profile lost Recall hidden state.");
            Require(spellingStore.Load().StatsByDictionary[dictionaryId][knownId].CompletedReviews == 4,
                "Unified profile lost Spelling statistics.");
            Require(sentenceStore.Load().StatsByDictionary[dictionaryId][knownId].CompletedReviews == 2,
                "Unified profile lost Sentence statistics.");
            Require(listeningStore.Load().StatsByDictionary[dictionaryId]["word:" + knownId].CompletedReviews == 3,
                "Unified profile lost Listening statistics.");
            Require(File.Exists(result.RecallBackupPath) && File.Exists(result.SpellingBackupPath!) && File.Exists(result.SentenceBackupPath!) && File.Exists(result.ListeningBackupPath!),
                "Unified profile import did not create recovery evidence for all four existing states.");

            ListeningCoachState listeningBeforeV3 = listeningStore.Load();
            listeningBeforeV3.ActiveScopeId = StudyScopeIds.C1;
            listeningBeforeV3.History.Add(new ListeningHistoryRecord { AtUtc = DateTimeOffset.UtcNow, DictionaryId = dictionaryId, ExerciseId = "word:" + knownId, Kind = ListeningExerciseKind.Word });
            listeningStore.Save(listeningBeforeV3);
            JsonObject v3Json = JsonNode.Parse(File.ReadAllText(profile))?.AsObject()
                ?? throw new InvalidDataException("Could not construct schema-3 compatibility fixture.");
            v3Json["ProfileSchemaVersion"] = 3;
            v3Json.Remove("ListeningSchemaVersion");
            v3Json.Remove("ListeningState");
            string v3 = Path.Combine(root, "WordDeck-profile-v3.json");
            File.WriteAllText(v3, v3Json.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            UnifiedProfileImportResult v3Result = service.Import(v3, app, new[] { knownId }, new[] { dictionaryId });
            Require(v3Result.SourceProfileSchemaVersion == 3 && v3Result.SentenceImported && !v3Result.ListeningImported,
                "Schema-3 compatibility path did not preserve current Listening state.");
            Require(listeningStore.Load().ActiveScopeId == StudyScopeIds.C1 && listeningStore.Load().History.Any(item => item.ExerciseId == "word:" + knownId),
                "Importing schema-3 unexpectedly replaced Listening state.");

            SentenceCoachState sentenceBeforeLegacy = sentenceStore.Load();
            sentenceBeforeLegacy.RecentSentenceIds.Add("sentinel-sentence");
            sentenceStore.Save(sentenceBeforeLegacy);
            ListeningCoachState listeningBeforeLegacy = listeningStore.Load();
            listeningBeforeLegacy.SelectionCounter = 77;
            listeningStore.Save(listeningBeforeLegacy);
            string v2 = Path.Combine(root, "WordDeck-profile-v2.json");
            new SpellingProfileService(appStore, spellingStore).Export(app, spellingStore.Load(), v2);
            UnifiedProfileImportResult v2Result = service.Import(v2, app, new[] { knownId }, new[] { dictionaryId });
            Require(v2Result.SourceProfileSchemaVersion == 2 && v2Result.SpellingImported && !v2Result.SentenceImported && !v2Result.ListeningImported,
                "Schema-2 compatibility path was not preserved.");
            Require(sentenceStore.Load().RecentSentenceIds.Contains("sentinel-sentence"),
                "Importing a schema-2 profile unexpectedly replaced Sentence state.");
            Require(listeningStore.Load().SelectionCounter == 77,
                "Importing a schema-2 profile unexpectedly replaced Listening state.");

            WordDeckUnifiedProfile incompatibleProfile = JsonSerializer.Deserialize<WordDeckUnifiedProfile>(File.ReadAllText(profile))
                ?? throw new InvalidDataException("Could not construct incompatible-profile test fixture.");
            incompatibleProfile.CorpusIdentity = "different-corpus:1";
            string bad = Path.Combine(root, "incompatible-v4.json");
            File.WriteAllText(bad, JsonSerializer.Serialize(incompatibleProfile, new JsonSerializerOptions { WriteIndented = true }));
            string appBefore = JsonSerializer.Serialize(app);
            string spellingBefore = JsonSerializer.Serialize(spellingStore.Load());
            string sentenceBefore = JsonSerializer.Serialize(sentenceStore.Load());
            string listeningBefore = JsonSerializer.Serialize(listeningStore.Load());
            bool rejected = false;
            try { _ = service.Import(bad, app, new[] { knownId }, new[] { dictionaryId }); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "Incompatible-corpus unified profile was accepted.");
            Require(JsonSerializer.Serialize(app) == appBefore &&
                    JsonSerializer.Serialize(spellingStore.Load()) == spellingBefore &&
                    JsonSerializer.Serialize(sentenceStore.Load()) == sentenceBefore &&
                    JsonSerializer.Serialize(listeningStore.Load()) == listeningBefore,
                "Rejected unified profile mutated existing personal state.");

            Console.WriteLine("WordDeck unified profile acceptance passed: schema-4 Recall+Spelling+Sentence+Listening export/import/recovery, schema-3/2 compatibility and incompatible-corpus fail-closed behavior verified.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}

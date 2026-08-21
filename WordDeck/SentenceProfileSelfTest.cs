namespace WordDeck;

internal static class SentenceProfileSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck R2 profile Київ {Guid.NewGuid():N}");
        string otherRoot = Path.Combine(Path.GetTempPath(), $"WordDeck R2 profile missing pack {Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            Directory.CreateDirectory(otherRoot);

            var appStore = new AppStateStore(root);
            AppState app = AppStateStore.Normalize(new AppState());
            var sentenceStore = new SentenceCoachStateStore(root);
            var sentenceState = BuildSentenceState("profile-pack", "known-1");
            sentenceStore.Save(sentenceState);

            string packSource = Path.Combine(root, "profile-pack-source.json.gz");
            SentencePackIo.WriteGZip(packSource, BuildPack("profile-pack", "known-1"));
            _ = new SentencePackStore(root).Import(packSource);

            var coordinator = new PersonalProfileCoordinator(appStore, root);
            string profilePath = Path.Combine(root, "combined-profile.json");
            coordinator.Export(app, profilePath);
            string exported = File.ReadAllText(profilePath);
            Require(exported.Contains("SentenceState", StringComparison.Ordinal) &&
                    exported.Contains("profile-pack", StringComparison.Ordinal) &&
                    exported.Contains("known-1", StringComparison.Ordinal),
                "New personal profile export did not include Sentence personal state.");

            sentenceStore.Save(BuildSentenceState("profile-pack", "known-2"));
            ProfileImportResult imported = coordinator.Import(
                profilePath,
                app,
                new[] { "known-1", "known-2" },
                new[] { "oxford-3000-en-uk" });
            Require(!string.IsNullOrWhiteSpace(imported.BackupPath) && File.Exists(imported.BackupPath),
                "Coordinated profile import did not retain the base pre-import recovery profile.");
            SentenceCoachState restored = sentenceStore.Load();
            Require(restored.ActivePackId == "profile-pack" && restored.CurrentTargetEntryIds.SequenceEqual(new[] { "known-1" }),
                "Sentence selected pack/current exercise did not round-trip through personal profile export/import.");
            Require(restored.StatsByDictionary["dict"]["known-1"].CompletedReviews == 7,
                "Sentence learning statistics did not round-trip through the personal profile.");

            string legacyProfile = Path.Combine(root, "legacy-v01-profile.json");
            appStore.ExportProfile(app, legacyProfile);
            SentenceCoachState beforeLegacy = BuildSentenceState("profile-pack", "known-2");
            sentenceStore.Save(beforeLegacy);
            _ = coordinator.Import(
                legacyProfile,
                app,
                new[] { "known-1", "known-2" },
                new[] { "oxford-3000-en-uk" });
            SentenceCoachState afterLegacy = sentenceStore.Load();
            Require(afterLegacy.CurrentTargetEntryIds.SequenceEqual(new[] { "known-2" }),
                "Legacy V0.1 personal profile unexpectedly erased unrelated newer Sentence state.");

            string badCorpusProfile = Path.Combine(root, "bad-corpus-profile.json");
            File.WriteAllText(
                badCorpusProfile,
                exported.Replace(AppStateStore.CorpusIdentity, "incompatible-corpus", StringComparison.Ordinal));
            SentenceCoachState beforeBadCorpus = sentenceStore.Load();
            ExpectInvalid(() => coordinator.Import(
                badCorpusProfile,
                app,
                new[] { "known-1", "known-2" },
                new[] { "oxford-3000-en-uk" }),
                "Incompatible corpus profile was accepted.");
            Require(sentenceStore.Load().CurrentTargetEntryIds.SequenceEqual(beforeBadCorpus.CurrentTargetEntryIds),
                "Rejected incompatible corpus profile changed Sentence state.");

            string badTargetProfile = Path.Combine(root, "bad-target-profile.json");
            File.WriteAllText(
                badTargetProfile,
                exported.Replace("known-1", "missing-target", StringComparison.Ordinal));
            ExpectInvalid(() => coordinator.Import(
                badTargetProfile,
                app,
                new[] { "known-1", "known-2" },
                new[] { "oxford-3000-en-uk" }),
                "Profile containing a non-existing Sentence target stable ID was accepted.");

            var otherAppStore = new AppStateStore(otherRoot);
            AppState otherApp = AppStateStore.Normalize(new AppState());
            var otherSentenceStore = new SentenceCoachStateStore(otherRoot);
            otherSentenceStore.Save(BuildSentenceState(null, "known-2"));
            var otherCoordinator = new PersonalProfileCoordinator(otherAppStore, otherRoot);
            ExpectInvalid(() => otherCoordinator.Import(
                profilePath,
                otherApp,
                new[] { "known-1", "known-2" },
                new[] { "oxford-3000-en-uk" }),
                "Sentence profile referencing a missing local SentencePack was accepted.");
            Require(otherSentenceStore.Load().CurrentTargetEntryIds.SequenceEqual(new[] { "known-2" }),
                "Rejected missing-pack profile changed existing Sentence state.");

            SentenceCoachState beforeRecallReset = sentenceStore.Load();
            UserProgressService.ResetLearningData(app);
            AppStateStore.Normalize(app);
            SentenceCoachState afterRecallReset = sentenceStore.Load();
            Require(afterRecallReset.CurrentTargetEntryIds.SequenceEqual(beforeRecallReset.CurrentTargetEntryIds) &&
                    afterRecallReset.StatsByDictionary["dict"]["known-2"].CompletedReviews == beforeRecallReset.StatsByDictionary["dict"]["known-2"].CompletedReviews,
                "Recall reset destroyed unrelated Sentence personal state.");

            Console.WriteLine("WordDeck Sentence profile self-test passed: new profile round-trip, legacy V0.1 compatibility, invalid corpus/target/missing-pack fail-closed, Recall reset isolation validated.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
            try { if (Directory.Exists(otherRoot)) Directory.Delete(otherRoot, true); } catch { }
        }
    }

    private static SentenceCoachState BuildSentenceState(string? packId, string targetId)
    {
        var state = new SentenceCoachState
        {
            ActivePackId = packId,
            ActiveSpellingDeckId = SpellingDeckIds.Core(2),
            TargetCount = 1,
            CurrentSentenceId = "sentence-profile",
            CurrentTargetEntryId = targetId,
            CurrentTargetEntryIds = new List<string> { targetId },
            RecentSentenceIds = new List<string> { "sentence-profile" }
        };
        state.StatsByDictionary["dict"] = new Dictionary<string, SentenceTargetStats>(StringComparer.OrdinalIgnoreCase)
        {
            [targetId] = new SentenceTargetStats
            {
                CompletedReviews = 7,
                FirstTrySuccesses = 5,
                WrongAttempts = 2,
                ShowAnswerUses = 1,
                LastReviewedUtc = DateTimeOffset.UtcNow
            }
        };
        return SentenceCoachStateStore.Normalize(state);
    }

    private static SentencePack BuildPack(string packId, string targetId)
    {
        const string english = "we learn words";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        return new SentencePack
        {
            PackId = packId,
            Provenance = "Synthetic Sentence profile regression fixture",
            License = "CC0-1.0",
            Sentences = new List<SentenceRecord>
            {
                new()
                {
                    Id = "sentence-profile",
                    English = english,
                    Ukrainian = "Ми вивчаємо слова",
                    Source = "Synthetic Sentence profile regression fixture",
                    License = "CC0-1.0",
                    Tokens = tokens,
                    Lemmas = tokens.ToList(),
                    TargetEntryIds = new List<string> { targetId },
                    EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { [targetId] = "A1" },
                    DifficultyLevel = "A1"
                }
            }
        };
    }

    private static void ExpectInvalid(Action action, string message)
    {
        try { action(); }
        catch (InvalidDataException) { return; }
        throw new InvalidDataException(message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}

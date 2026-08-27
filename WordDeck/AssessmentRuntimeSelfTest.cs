using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class AssessmentRuntimeSelfTest
{
    public static void Run()
    {
        TestVersionedUnseenAndSeparation();
        TestRetakeRotation();
        TestDifficultyRouting();
        TestResumePersistenceAndFailClosedVersion();
        Console.WriteLine("WordDeck assessment runtime self-test PASS.");
    }

    private static void TestVersionedUnseenAndSeparation()
    {
        AssessmentItemPool pool = BuildPool(1, 1);
        var runtime = new AssessmentRuntime();
        DateTimeOffset t = new(2026, 8, 27, 6, 0, 0, TimeSpan.Zero);

        AssessmentSessionState practice = runtime.StartSession(pool, AssessmentMode.Practice, 1, false, t, sessionId: "practice-one");
        Require(practice.ItemOrder[0].ItemId == "item.a", "deterministic first item changed");
        runtime.RecordAttempt(practice.SessionId, pool, AssessmentMark.Correct, usedHint: true, nowUtc: t.AddMinutes(1), attemptId: "practice-attempt-one");
        Require(!runtime.IsUnseen(pool.Items[0]), "practice exposure did not mark item seen");

        AssessmentItem sameContentInNewPool = BuildPool(2, 1).Items[0];
        AssessmentItem changedContent = BuildPool(3, 2).Items[0];
        Require(!runtime.IsUnseen(sameContentInNewPool), "pool repack incorrectly reset unseen state");
        Require(runtime.IsUnseen(changedContent), "item version change did not create new unseen content");

        AssessmentSessionState formal = runtime.StartSession(pool, AssessmentMode.Assessment, 4, true, t.AddMinutes(2), sessionId: "formal-one");
        bool hintRejected = false;
        try { runtime.RecordAttempt(formal.SessionId, pool, AssessmentMark.Correct, usedHint: true, attemptId: "illegal-hint"); }
        catch (InvalidOperationException) { hintRejected = true; }
        Require(hintRejected && formal.Cursor == 0, "formal hint/reveal boundary failed");

        int n = 0;
        while (!formal.IsComplete)
        {
            AssessmentItem current = runtime.ResumeSession(formal.SessionId, pool).CurrentItem!;
            AssessmentMark mark = current.Key.ItemId is "item.a" or "item.c" ? AssessmentMark.Correct : AssessmentMark.Incorrect;
            runtime.RecordAttempt(formal.SessionId, pool, mark, nowUtc: t.AddMinutes(10 + n), attemptId: $"formal-attempt-{n}");
            n++;
        }

        AssessmentResultSummary result = runtime.BuildAssessmentResults(formal.SessionId);
        Require(result.SkillResults.Count == 2, "skill result grouping failed");
        Require(result.SkillResults.All(x => x.Attempts == 2 && x.Correct == 1 && x.Incorrect == 1), "skill result counts failed");
        Require(result.SkillResults.Sum(x => x.Attempts) == 4, "practice leaked into formal result");
        Require(!result.PsychometricCalibrationApplied && !result.AiCanonicalAssessorUsed, "runtime claimed forbidden calibration or AI authority");
        Require(runtime.GetAttemptHistory(AssessmentMode.Practice).Count == 1, "practice history missing");
        Require(runtime.GetAttemptHistory(AssessmentMode.Assessment).Count == 4, "formal history count wrong");

        bool practiceResultRejected = false;
        try { _ = runtime.BuildAssessmentResults(practice.SessionId); }
        catch (InvalidOperationException) { practiceResultRejected = true; }
        Require(practiceResultRejected, "practice session produced formal assessment results");
    }

    private static void TestRetakeRotation()
    {
        AssessmentItemPool pool = BuildPool(1, 1);
        var runtime = new AssessmentRuntime();
        DateTimeOffset t = new(2026, 8, 27, 7, 0, 0, TimeSpan.Zero);
        AssessmentSessionState first = runtime.StartSession(pool, AssessmentMode.Assessment, 4, false, t, 0, "retake-first");
        for (int i = 0; i < 4; i++)
            runtime.RecordAttempt(first.SessionId, pool, AssessmentMark.Correct, nowUtc: t.AddMinutes(i + 1), attemptId: $"retake-a{i}");

        AssessmentSessionState second = runtime.StartSession(pool, AssessmentMode.Assessment, 2, false, t.AddHours(1), 2, "retake-second");
        string[] ids = second.ItemOrder.Select(x => x.ItemId).ToArray();
        Require(ids.SequenceEqual(new[] { "item.a", "item.b" }, StringComparer.Ordinal), "retake rotation did not avoid recent items");
    }

    private static void TestDifficultyRouting()
    {
        DateTimeOffset t = new(2026, 8, 27, 8, 0, 0, TimeSpan.Zero);
        var history = new List<AssessmentAttempt>();
        history.Add(H("single", "skill.single", AssessmentMode.Assessment, AssessmentMark.Correct, t));
        for (int i = 0; i < 4; i++) history.Add(H($"low{i}", "skill.low", AssessmentMode.Assessment, AssessmentMark.Incorrect, t.AddMinutes(i)));
        for (int i = 0; i < 6; i++) history.Add(H($"practice{i}", "skill.low", AssessmentMode.Practice, AssessmentMark.Correct, t.AddMinutes(10 + i)));
        for (int i = 0; i < 5; i++) history.Add(H($"highc{i}", "skill.high", AssessmentMode.Assessment, AssessmentMark.Correct, t.AddMinutes(20 + i)));
        history.Add(H("highi", "skill.high", AssessmentMode.Assessment, AssessmentMark.Incorrect, t.AddMinutes(26)));
        for (int i = 0; i < 4; i++) history.Add(H($"midc{i}", "skill.mid", AssessmentMode.Assessment, AssessmentMark.Correct, t.AddMinutes(30 + i)));
        for (int i = 0; i < 2; i++) history.Add(H($"midi{i}", "skill.mid", AssessmentMode.Assessment, AssessmentMark.Incorrect, t.AddMinutes(34 + i)));

        Require(AssessmentDifficultyHeuristic.SuggestTier(history, "skill.single") == 2, "one item changed difficulty tier");
        Require(AssessmentDifficultyHeuristic.SuggestTier(history, "skill.low") == 1, "low evidence route failed");
        Require(AssessmentDifficultyHeuristic.SuggestTier(history, "skill.high") == 3, "high evidence route failed");
        Require(AssessmentDifficultyHeuristic.SuggestTier(history, "skill.mid") == 2, "middle evidence route failed");
        Require(AssessmentDifficultyHeuristic.SuggestTier(history, "skill.none") == 2, "missing evidence should stay neutral");
    }

    private static void TestResumePersistenceAndFailClosedVersion()
    {
        string root = Path.Combine(Path.GetTempPath(), "worddeck-assessment-" + Guid.NewGuid().ToString("N"));
        string path = Path.Combine(root, "assessment-runtime.json");
        try
        {
            AssessmentItemPool pool = BuildPool(1, 1);
            var runtime = new AssessmentRuntime();
            DateTimeOffset t = new(2026, 8, 27, 9, 0, 0, TimeSpan.Zero);
            AssessmentSessionState session = runtime.StartSession(pool, AssessmentMode.Assessment, 3, true, t, sessionId: "resume-one");
            runtime.RecordAttempt(session.SessionId, pool, AssessmentMark.Correct, nowUtc: t.AddMinutes(1), attemptId: "resume-attempt");
            AssessmentItemKey expected = session.ItemOrder[1];

            var store = new AssessmentRuntimeStateStore(path);
            store.Save(runtime.State);
            var reloaded = new AssessmentRuntime(store.Load());
            AssessmentResumeSnapshot snapshot = reloaded.ResumeSession(session.SessionId, pool);
            Require(snapshot.CompletedItems == 1 && snapshot.TotalItems == 3 && snapshot.CurrentItem?.Key == expected, "resume state changed item order or cursor");

            bool wrongPoolRejected = false;
            try { _ = reloaded.ResumeSession(session.SessionId, BuildPool(2, 1)); }
            catch (InvalidDataException) { wrongPoolRejected = true; }
            Require(wrongPoolRejected, "resume accepted wrong pool version");

            store.Save(reloaded.State);
            Require(File.Exists(store.BackupPath), "second save did not create backup");

            var newer = new AssessmentRuntimeState { SchemaVersion = AssessmentRuntimeState.CurrentSchemaVersion + 1 };
            bool newerRejected = false;
            try { _ = new AssessmentRuntime(newer); }
            catch (InvalidDataException) { newerRejected = true; }
            Require(newerRejected, "newer unknown state schema did not fail closed");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    private static AssessmentItemPool BuildPool(int poolVersion, int itemAVersion)
    {
        var pool = new AssessmentItemPool
        {
            PoolId = "assessment.core",
            Version = poolVersion,
            Items = new()
            {
                I(poolVersion, "item.a", itemAVersion, "skill.alpha", 1),
                I(poolVersion, "item.b", 1, "skill.alpha", 2),
                I(poolVersion, "item.c", 1, "skill.beta", 2),
                I(poolVersion, "item.d", 1, "skill.beta", 3)
            }
        };
        pool.Validate();
        return pool;
    }

    private static AssessmentItem I(int poolVersion, string id, int itemVersion, string skill, int tier) =>
        new(new AssessmentItemKey("assessment.core", poolVersion, id, itemVersion), skill, tier);

    private static AssessmentAttempt H(string id, string skill, AssessmentMode mode, AssessmentMark mark, DateTimeOffset at) => new()
    {
        AttemptId = "history-" + id,
        SessionId = "history-session",
        Mode = mode,
        ItemKey = new AssessmentItemKey("assessment.history", 1, "item." + id, 1),
        SkillId = skill,
        DifficultyTier = 2,
        Mark = mark,
        RecordedAtUtc = at
    };

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Assessment runtime self-test failed: " + message);
    }
}

internal static class AssessmentRuntimeSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            AssessmentRuntimeSelfTest.Run();
    }
}

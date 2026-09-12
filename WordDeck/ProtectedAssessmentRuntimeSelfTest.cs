using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ProtectedAssessmentRuntimeSelfTest
{
    public static void Run()
    {
        TestCanonicalOrderExposureAndRecovery();
        TestFreshEquivalentRetakeFallback();
        TestTamperedOrderFailsClosed();
        TestTamperedExposureGroupFailsClosed();
        TestSameExposureGroupReserveFailsClosed();
        Console.WriteLine("WordDeck protected assessment runtime self-test PASS.");
    }

    private static void TestCanonicalOrderExposureAndRecovery()
    {
        (AssessmentItemPool pool, ProtectedAssessmentFormContract contract) = BuildProtectedForm();
        string root = Path.Combine(Path.GetTempPath(), "worddeck-protected-assessment-" + Guid.NewGuid().ToString("N"));
        string path = Path.Combine(root, "protected-assessment.json");
        DateTimeOffset t = new(2026, 9, 11, 20, 0, 0, TimeSpan.Zero);

        try
        {
            var runtime = new ProtectedAssessmentRuntime(pool, contract);
            AssessmentSessionState session = runtime.StartSession(t, "protected-first");
            Require(session.ItemOrder.Select(x => x.ItemId).SequenceEqual(
                new[] { "prod.identity.a", "recv.identity.a", "general.check" },
                StringComparer.Ordinal), "canonical protected form order was not installed");

            AssessmentResumeSnapshot first = runtime.ResumeSession(session.SessionId, t.AddMinutes(1));
            Require(first.CurrentItem?.Key.ItemId == "prod.identity.a", "first protected item changed");
            Require(runtime.BindingState.Exposures.Count == 1, "presentation did not persist exposure");
            Require(!runtime.IsUnseen(pool.Resolve(session.ItemOrder[0])), "presented protected item remained unseen");

            AssessmentResumeSnapshot repeated = runtime.ResumeSession(session.SessionId, t.AddMinutes(2));
            Require(repeated.CurrentItem?.Key.ItemId == "prod.identity.a", "repeat resume changed current item");
            Require(runtime.BindingState.Exposures.Count == 1, "repeat resume duplicated exposure");

            var store = new ProtectedAssessmentRuntimeStateStore(path);
            store.Save(runtime.CreateSnapshot());
            ProtectedAssessmentRuntimeSnapshot loaded = store.Load();
            var recovered = new ProtectedAssessmentRuntime(pool, contract, loaded.RuntimeState, loaded.BindingState);
            AssessmentResumeSnapshot afterRecovery = recovered.ResumeSession(session.SessionId, t.AddMinutes(3));
            Require(afterRecovery.CurrentItem?.Key.ItemId == "prod.identity.a", "recovery changed protected item before commitment");
            Require(recovered.BindingState.Exposures.Count == 1, "recovery lost or duplicated exposure state");

            recovered.RecordAttempt(session.SessionId, AssessmentMark.Correct, t.AddMinutes(4), "protected-a1");
            AssessmentResumeSnapshot receptive = recovered.ResumeSession(session.SessionId, t.AddMinutes(5));
            Require(receptive.CurrentItem?.Key.ItemId == "recv.identity.a", "canonical second item changed after recovery");
            recovered.RecordAttempt(session.SessionId, AssessmentMark.Correct, t.AddMinutes(6), "protected-a2");
            recovered.RecordAttempt(session.SessionId, AssessmentMark.Correct, t.AddMinutes(7), "protected-a3");
            Require(recovered.RuntimeState.Sessions.Single(x => x.SessionId == session.SessionId).IsComplete,
                "protected session did not complete");

            store.Save(recovered.CreateSnapshot());
            Require(File.Exists(store.BackupPath), "protected assessment second save did not create backup");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    private static void TestFreshEquivalentRetakeFallback()
    {
        (AssessmentItemPool pool, ProtectedAssessmentFormContract contract) = BuildProtectedForm();
        DateTimeOffset t = new(2026, 9, 11, 21, 0, 0, TimeSpan.Zero);
        var runtime = new ProtectedAssessmentRuntime(pool, contract);

        AssessmentSessionState first = runtime.StartSession(t, "retake-one");
        AssessmentResumeSnapshot firstView = runtime.ResumeSession(first.SessionId, t.AddMinutes(1));
        Require(firstView.CurrentItem?.Key.ItemId == "prod.identity.a", "initial productive item was not primary form item");
        runtime.RecordAttempt(first.SessionId, AssessmentMark.Correct, t.AddMinutes(2), "retake-one-a1");
        runtime.RecordAttempt(first.SessionId, AssessmentMark.Correct, t.AddMinutes(3), "retake-one-a2");
        runtime.RecordAttempt(first.SessionId, AssessmentMark.Correct, t.AddMinutes(4), "retake-one-a3");

        AssessmentSessionState second = runtime.StartSession(t.AddHours(1), "retake-two");
        AssessmentResumeSnapshot secondView = runtime.ResumeSession(second.SessionId, t.AddHours(1).AddMinutes(1));
        Require(secondView.CurrentItem?.Key.ItemId == "prod.identity.b", "contaminated independent evidence did not route to first fresh reserve");
        Require(second.ItemOrder[0].ItemId == "prod.identity.b", "fresh reserve replacement was not persisted into fixed session order");
        runtime.RecordAttempt(second.SessionId, AssessmentMark.Correct, t.AddHours(1).AddMinutes(2), "retake-two-a1");

        AssessmentSessionState third = runtime.StartSession(t.AddHours(2), "retake-three");
        AssessmentResumeSnapshot thirdView = runtime.ResumeSession(third.SessionId, t.AddHours(2).AddMinutes(1));
        Require(thirdView.CurrentItem?.Key.ItemId == "prod.identity.c", "second retake did not advance to next fresh reserve");
        runtime.RecordAttempt(third.SessionId, AssessmentMark.Correct, t.AddHours(2).AddMinutes(2), "retake-three-a1");

        AssessmentSessionState exhausted = runtime.StartSession(t.AddHours(3), "retake-exhausted");
        bool failedClosed = false;
        try { _ = runtime.ResumeSession(exhausted.SessionId, t.AddHours(3).AddMinutes(1)); }
        catch (InvalidOperationException) { failedClosed = true; }
        Require(failedClosed, "exhausted fresh-equivalent inventory did not fail closed");
        Require(exhausted.Cursor == 0, "fresh-equivalent failure advanced protected session cursor");
    }

    private static void TestTamperedOrderFailsClosed()
    {
        (AssessmentItemPool pool, ProtectedAssessmentFormContract contract) = BuildProtectedForm();
        var runtime = new ProtectedAssessmentRuntime(pool, contract);
        AssessmentSessionState session = runtime.StartSession(sessionId: "tamper-one");
        ProtectedAssessmentRuntimeSnapshot snapshot = runtime.CreateSnapshot();

        (snapshot.RuntimeState.Sessions[0].ItemOrder[0], snapshot.RuntimeState.Sessions[0].ItemOrder[1]) =
            (snapshot.RuntimeState.Sessions[0].ItemOrder[1], snapshot.RuntimeState.Sessions[0].ItemOrder[0]);
        snapshot.BindingState.Sessions[0].ItemOrder = snapshot.RuntimeState.Sessions[0].ItemOrder.ToList();

        bool rejected = false;
        try { _ = new ProtectedAssessmentRuntime(pool, contract, snapshot.RuntimeState, snapshot.BindingState); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "tampered receptive-first protected administration order was accepted");
        Require(session.Cursor == 0, "tamper test unexpectedly changed source session cursor");
    }

    private static void TestTamperedExposureGroupFailsClosed()
    {
        (AssessmentItemPool pool, ProtectedAssessmentFormContract contract) = BuildProtectedForm();
        DateTimeOffset t = new(2026, 9, 11, 22, 0, 0, TimeSpan.Zero);
        var runtime = new ProtectedAssessmentRuntime(pool, contract);
        AssessmentSessionState session = runtime.StartSession(t, "tamper-exposure-group");
        _ = runtime.ResumeSession(session.SessionId, t.AddMinutes(1));
        ProtectedAssessmentRuntimeSnapshot snapshot = runtime.CreateSnapshot();
        Require(snapshot.BindingState.Exposures.Count == 1, "tamper exposure fixture did not record presentation");

        snapshot.BindingState.Exposures[0].ExposureGroupId = "identity-forged";

        bool rejected = false;
        try { _ = new ProtectedAssessmentRuntime(pool, contract, snapshot.RuntimeState, snapshot.BindingState); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "tampered protected exposure group was accepted on recovery");
    }

    private static void TestSameExposureGroupReserveFailsClosed()
    {
        (AssessmentItemPool pool, ProtectedAssessmentFormContract contract) = BuildProtectedForm();
        var runtime = new ProtectedAssessmentRuntime(pool, contract);
        _ = runtime.StartSession(sessionId: "tamper-same-group-reserve");
        ProtectedAssessmentRuntimeSnapshot snapshot = runtime.CreateSnapshot();

        AssessmentItemKey forgedFallback = pool.Items.Single(x => x.Key.ItemId == "prod.identity.same-group").Key;
        snapshot.RuntimeState.Sessions[0].ItemOrder[0] = forgedFallback;
        snapshot.BindingState.Sessions[0].ItemOrder[0] = forgedFallback;

        bool rejected = false;
        try { _ = new ProtectedAssessmentRuntime(pool, contract, snapshot.RuntimeState, snapshot.BindingState); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "same-exposure-group reserve was accepted as a persisted fresh-equivalent fallback");
    }

    private static (AssessmentItemPool Pool, ProtectedAssessmentFormContract Contract) BuildProtectedForm()
    {
        const string poolId = "assessment.m02.protected";
        const int version = 12;
        var pool = new AssessmentItemPool
        {
            PoolId = poolId,
            Version = version,
            Items = new()
            {
                Item(poolId, version, "prod.identity.a", "skill.speaking", 2),
                Item(poolId, version, "recv.identity.a", "skill.listening", 2),
                Item(poolId, version, "general.check", "skill.grammar", 2),
                Item(poolId, version, "prod.identity.same-group", "skill.speaking", 2),
                Item(poolId, version, "prod.identity.b", "skill.speaking", 2),
                Item(poolId, version, "prod.identity.c", "skill.speaking", 2)
            }
        };
        pool.Validate();

        var contract = new ProtectedAssessmentFormContract
        {
            PoolId = poolId,
            PoolVersion = version,
            FormAssemblyVersion = "m02.v1.2",
            Bindings = new()
            {
                Binding(poolId, version, "prod.identity.a", 1, "identity-a", "spoken-identity", ProtectedAssessmentEvidenceRole.IndependentProductive, true, false),
                Binding(poolId, version, "recv.identity.a", 2, "identity-a", "spoken-identity", ProtectedAssessmentEvidenceRole.Receptive, false, false),
                Binding(poolId, version, "general.check", 3, "general-a", "general-check", ProtectedAssessmentEvidenceRole.General, false, false),
                Binding(poolId, version, "prod.identity.same-group", 100, "identity-a", "spoken-identity", ProtectedAssessmentEvidenceRole.IndependentProductive, true, true),
                Binding(poolId, version, "prod.identity.b", 101, "identity-b", "spoken-identity", ProtectedAssessmentEvidenceRole.IndependentProductive, true, true),
                Binding(poolId, version, "prod.identity.c", 102, "identity-c", "spoken-identity", ProtectedAssessmentEvidenceRole.IndependentProductive, true, true)
            }
        };
        contract.Validate(pool);
        return (pool, contract);
    }

    private static AssessmentItem Item(string poolId, int poolVersion, string itemId, string skillId, int tier) =>
        new(new AssessmentItemKey(poolId, poolVersion, itemId, 1), skillId, tier);

    private static ProtectedAssessmentItemBinding Binding(
        string poolId,
        int poolVersion,
        string itemId,
        int order,
        string exposureGroup,
        string evidenceFamily,
        ProtectedAssessmentEvidenceRole role,
        bool requiresFresh,
        bool reserve) => new(
            new AssessmentItemKey(poolId, poolVersion, itemId, 1),
            order,
            exposureGroup,
            evidenceFamily,
            role,
            requiresFresh,
            reserve);

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Protected assessment runtime self-test failed: " + message);
    }
}

internal static class ProtectedAssessmentRuntimeSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ProtectedAssessmentRuntimeSelfTest.Run();
    }
}

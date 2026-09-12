using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ListeningContractsSelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase))) return;
        Run();
    }

    private static void Run()
    {
        TestGistDetailMultiSpeakerContract();
        TestReplayPolicy();
        TestSentenceApprovalIsExplicit();
        TestInvalidTranscriptFailsClosed();
        Console.WriteLine("WordDeck Listening contracts self-test passed: gist/detail, multi-speaker transcript, replay policy and explicit pack approval validated.");
    }

    private static void TestGistDetailMultiSpeakerContract()
    {
        var speakers = new[]
        {
            new ListeningSpeakerMetadata("speaker-a", "Speaker A", "interviewer"),
            new ListeningSpeakerMetadata("speaker-b", "Speaker B", "guest")
        };
        var transcript = new ListeningTranscriptContract(
            "A short interview transcript.",
            ListeningTranscriptAvailability.AfterReveal,
            new[]
            {
                new ListeningTranscriptTurn("speaker-a", "What changed?", TimeSpan.Zero, TimeSpan.FromSeconds(2)),
                new ListeningTranscriptTurn("speaker-b", "The plan changed.", TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(5))
            });
        var audio = new ListeningAudioContract(
            "asset-interview-1",
            ListeningAudioUnitKind.Passage,
            "en-GB",
            "approved-listening-pack",
            "synthetic-test-fixture-only",
            speakers,
            transcript,
            ListeningReplayPolicy.OneReplayAssessment,
            new[]
            {
                new ListeningComprehensionPrompt("gist-1", ListeningComprehensionKind.Gist, "What is the exchange mainly about?", new[] { "a changed plan" }),
                new ListeningComprehensionPrompt("detail-1", ListeningComprehensionKind.Detail, "Who says the plan changed?", new[] { "speaker b" })
            },
            ApprovedForProduction: true);

        audio.Validate();
        Require(audio.Prompts.Select(x => x.Kind).SequenceEqual(new[] { ListeningComprehensionKind.Gist, ListeningComprehensionKind.Detail }),
            "Gist/detail prompts were not preserved by the presentation-neutral contract.");
        Require(audio.Speakers.Count == 2 && audio.Transcript!.Turns.Count == 2,
            "Multi-speaker metadata/transcript turns were not preserved.");
    }

    private static void TestReplayPolicy()
    {
        ListeningReplayPolicy one = ListeningReplayPolicy.OneReplayAssessment;
        Require(one.Allows(0, completed: false, revealed: false), "First assessment replay should be allowed.");
        Require(!one.Allows(1, completed: false, revealed: false), "Assessment replay maximum was not enforced.");
        Require(!one.Allows(0, completed: true, revealed: false), "Assessment replay after completion was not blocked.");
        Require(!one.Allows(0, completed: false, revealed: true), "Assessment replay after reveal was not blocked.");
        Require(ListeningReplayPolicy.UnlimitedPractice.Allows(1000, completed: true, revealed: true),
            "Practice replay policy unexpectedly imposed a limit.");
    }

    private static void TestSentenceApprovalIsExplicit()
    {
        ListeningAudioPackApproval denied = ListeningAudioPackApproval.Unapproved("sentence-pack");
        Require(!denied.MatchesApprovedPack("sentence-pack"), "Default sentence audio approval was not fail-closed.");

        var approved = new ListeningAudioPackApproval("sentence-pack", "AUDIT-APPROVAL-TEST", true);
        Require(approved.MatchesApprovedPack("sentence-pack"), "Explicit matching approval was rejected.");
        Require(!approved.MatchesApprovedPack("other-pack"), "Approval token leaked across pack identity.");
    }

    private static void TestInvalidTranscriptFailsClosed()
    {
        bool rejected = false;
        try
        {
            new ListeningAudioContract(
                "asset-bad",
                ListeningAudioUnitKind.Sentence,
                "en-GB",
                "pack",
                "test",
                new[] { new ListeningSpeakerMetadata("known") },
                new ListeningTranscriptContract(null, ListeningTranscriptAvailability.AfterCheck,
                    new[] { new ListeningTranscriptTurn("unknown", "text") }),
                ListeningReplayPolicy.UnlimitedPractice,
                Array.Empty<ListeningComprehensionPrompt>(),
                ApprovedForProduction: false).Validate();
        }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "Transcript with unknown speaker did not fail closed.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Listening contracts self-test failed: " + message);
    }
}

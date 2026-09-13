using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class StoryCourseProductiveUiSelfTest
{
    internal static void Run()
    {
        Require(
            StoryCourseRuntimeForm.SubmissionKindForCurrentUi(StoryCourseProductiveChannel.Writing) ==
            StoryCourseProductiveSubmissionKind.RequiredChannelPerformance,
            "Writing UI did not preserve real typed writing as the required productive channel.");

        Require(
            StoryCourseRuntimeForm.SubmissionKindForCurrentUi(StoryCourseProductiveChannel.Speaking) ==
            StoryCourseProductiveSubmissionKind.TypedFallback,
            "Speaking UI fabricated microphone/speech-channel evidence without a bound capture provider.");

        Require(
            StoryCourseRuntimeForm.SubmissionKindForCurrentUi(StoryCourseProductiveChannel.Mixed) ==
            StoryCourseProductiveSubmissionKind.TypedFallback,
            "Mixed productive UI fabricated full channel completion without a bound speech provider.");

        bool invalidRejected = false;
        try
        {
            _ = StoryCourseRuntimeForm.SubmissionKindForCurrentUi((StoryCourseProductiveChannel)999);
        }
        catch (InvalidDataException)
        {
            invalidRejected = true;
        }
        Require(invalidRejected, "Undefined productive channel was accepted by learner-facing UI policy.");

        Console.WriteLine("WordDeck Story/Course productive UI policy self-test PASS.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Story/Course productive UI self-test failed: " + message);
    }
}

internal static class StoryCourseProductiveUiSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            StoryCourseProductiveUiSelfTest.Run();
    }
}

using WordDeck;

try
{
    SpeechPracticeRuntimeSelfTest.Run();
    WindowsMicrophoneCaptureProviderSelfTest.Run();
    Console.WriteLine("WordDeck speech runtime + Windows microphone capture self-tests PASS.");
    return 0;
}
catch (Exception ex)
{
    Console.Error.WriteLine($"WordDeck speech runtime + Windows microphone capture self-tests FAILED: {ex}");
    return 1;
}

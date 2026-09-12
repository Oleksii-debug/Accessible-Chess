using WordDeck;

try
{
    SpeechPracticeRuntimeSelfTest.Run();
    Console.WriteLine("WordDeck speech runtime foundation self-test PASS.");
    return 0;
}
catch (Exception ex)
{
    Console.Error.WriteLine($"WordDeck speech runtime foundation self-test FAILED: {ex}");
    return 1;
}

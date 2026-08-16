namespace WordDeck;

internal static class SelfTest
{
    private static readonly IReadOnlyDictionary<string, int> ExpectedLevelCounts =
        new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["A1"] = 900,
            ["A2"] = 872,
            ["B1"] = 809,
            ["B2"] = 727
        };

    public static int Run()
    {
        try
        {
            DictionaryPackage package = DictionaryLoader.LoadEmbeddedOxford();
            Require(package.Id == "oxford-3000-en-uk", $"Unexpected dictionary id: {package.Id}");
            Require(package.SourceLanguage.Equals("en", StringComparison.OrdinalIgnoreCase), "Source language must be en.");
            Require(package.TargetLanguage.Equals("uk", StringComparison.OrdinalIgnoreCase), "Target language must be uk.");
            Require(package.Entries.Count == 3308, $"Expected 3308 entries, got {package.Entries.Count}.");

            var actualCounts = package.Entries
                .GroupBy(entry => entry.Level, StringComparer.OrdinalIgnoreCase)
                .ToDictionary(group => group.Key, group => group.Count(), StringComparer.OrdinalIgnoreCase);

            foreach ((string level, int expected) in ExpectedLevelCounts)
            {
                int actual = actualCounts.GetValueOrDefault(level);
                Require(actual == expected, $"Expected {expected} {level} entries, got {actual}.");
            }

            Require(actualCounts.Count == ExpectedLevelCounts.Count, "Unexpected CEFR levels found in embedded dictionary.");
            Require(package.Entries.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() == package.Entries.Count,
                "Duplicate entry IDs found.");
            Require(package.Entries.All(entry => !string.IsNullOrWhiteSpace(entry.Source) && !string.IsNullOrWhiteSpace(entry.Target)),
                "Blank source or translation found.");

            DictionaryEntry first = package.Entries[0];
            DictionaryEntry last = package.Entries[^1];
            Require(first.Id == "oxford-a1-0001" && first.Source == "a, an", "Unexpected first Oxford entry.");
            Require(last.Id == "oxford-b2-0727" && last.Source == "zone", "Unexpected last Oxford entry.");

            Console.WriteLine("WordDeck self-test passed: Oxford dictionary 3308 entries (A1 900, A2 872, B1 809, B2 727).");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"WordDeck self-test FAILED: {ex}");
            return 1;
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidDataException(message);
    }
}

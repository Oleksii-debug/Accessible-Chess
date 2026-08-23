using System.Text.Json;

namespace WordDeck;

internal static class ContextStableIdentityEvidenceFileVerifier
{
    public static int Run(string[] args)
    {
        if (args.Length != 2)
        {
            Console.Error.WriteLine("Usage: WordDeck.exe --verify-context-stable-identity-evidence <evidence.json>");
            return 2;
        }

        try
        {
            string path = Path.GetFullPath(args[1]);
            if (!File.Exists(path))
                throw new FileNotFoundException("Stable-identity evidence file was not found.", path);

            string json = File.ReadAllText(path);
            ContextStableIdentityCoverageEvidenceDocument document = JsonSerializer.Deserialize<ContextStableIdentityCoverageEvidenceDocument>(json)
                ?? throw new InvalidDataException("Stable-identity evidence document is empty or invalid JSON.");

            if (!ContextStableIdentityCoverageEvidenceBuilder.VerifyDigest(document))
                throw new InvalidDataException("Stable-identity evidence digest does not match its canonical payload.");

            Console.WriteLine($"Context stable-identity evidence digest PASS: {path}");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Context stable-identity evidence verification FAILED: {ex.Message}");
            return 1;
        }
    }
}

using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class SentencePackReleaseReadinessSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            SentencePackReleaseReadinessSelfTest.Run();
    }
}

internal static class SentencePackReleaseReadinessSelfTest
{
    public static void Run()
    {
        SentencePack cc0 = BuildPack("release-ready-cc0", "CC0-1.0", "verified curated product source");
        SentencePackReleaseReadiness ready = SentencePackReleaseReadinessService.Evaluate(
            cc0,
            "sha256:source-identity",
            "sha256:derivative-identity",
            declaredSynthetic: false,
            attributionText: null);
        Require(ready.Ready && ready.Descriptor is not null, "Release-ready CC0 SentencePack was not accepted by the product readiness gate.");

        SentencePackReleaseReadiness synthetic = SentencePackReleaseReadinessService.Evaluate(
            cc0,
            "sha256:source-identity",
            "sha256:derivative-identity",
            declaredSynthetic: true,
            attributionText: null);
        Require(!synthetic.Ready && synthetic.Blockers.Any(x => x.Contains("synthetic", StringComparison.OrdinalIgnoreCase)),
            "Synthetic SentencePack was not explicitly blocked from production readiness.");

        SentencePack ccby = BuildPack("release-ccby", "CC BY 4.0", "verified attributed product source");
        SentencePackReleaseReadiness missingAttribution = SentencePackReleaseReadinessService.Evaluate(
            ccby,
            "sha256:source-identity",
            "sha256:derivative-identity",
            declaredSynthetic: false,
            attributionText: "");
        Require(!missingAttribution.Ready && missingAttribution.Blockers.Any(x => x.Contains("attribution", StringComparison.OrdinalIgnoreCase)),
            "Attribution-required SentencePack passed without a product attribution surface.");

        SentencePackReleaseReadiness attributed = SentencePackReleaseReadinessService.Evaluate(
            ccby,
            "sha256:source-identity",
            "sha256:derivative-identity",
            declaredSynthetic: false,
            attributionText: "Example corpus contributors — CC BY 4.0 — provenance retained with the installed pack.");
        Require(attributed.Ready, "Attributed SentencePack did not pass after required attribution was supplied.");

        SentencePackReleaseReadiness noIdentity = SentencePackReleaseReadinessService.Evaluate(
            cc0,
            "",
            "sha256:derivative-identity",
            declaredSynthetic: false,
            attributionText: null);
        Require(!noIdentity.Ready && noIdentity.Blockers.Any(x => x.Contains("identity", StringComparison.OrdinalIgnoreCase)),
            "SentencePack with missing source identity passed product readiness.");

        Console.WriteLine("WordDeck R4b SentencePack release readiness passed: synthetic data, missing identities and missing attribution fail closed while explicit release-ready metadata passes.");
    }

    private static SentencePack BuildPack(string packId, string license, string provenance)
    {
        const string english = "we learn words";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = provenance,
            License = license,
            Sentences = new()
            {
                new SentenceRecord
                {
                    Id = packId + "-sentence-1",
                    English = english,
                    Ukrainian = "Ми вивчаємо слова",
                    Source = "verified product source",
                    License = license,
                    Tokens = tokens,
                    Lemmas = tokens.ToList(),
                    TargetEntryIds = new() { "entry-1" },
                    EntryLevels = new(StringComparer.OrdinalIgnoreCase) { ["entry-1"] = "A1" },
                    DifficultyLevel = "A1"
                }
            }
        };
        pack.Validate();
        return pack;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}

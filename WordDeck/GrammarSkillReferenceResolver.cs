using System.Runtime.CompilerServices;

namespace WordDeck;

/// <summary>
/// Canonical cross-mode boundary for resolving Grammar skill references.
/// Other learning modes must consume this resolver instead of copying the
/// Grammar skill catalog, so future catalog changes cannot silently drift.
/// </summary>
internal static class GrammarSkillReferenceResolver
{
    private static readonly IReadOnlyDictionary<string, string> LegacyAliases =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["grammar.present-simple.statement"] = "present.simple.core",
            ["grammar.present-simple.question"] = "present.simple.questions-negatives",
            ["grammar.present-simple.negative"] = "present.simple.questions-negatives",
            ["grammar.past-simple.statement"] = "past.simple.regular",
            ["grammar.past-simple.question"] = "past.simple.questions-negatives",
            ["grammar.past-simple.negative"] = "past.simple.questions-negatives",
            ["grammar.future-intention"] = "future.going-to",
            ["grammar.passive-basic"] = "passive.past-simple",
            ["grammar.aspect-contrast"] = "present-perfect.vs-past-simple",
            ["grammar.be-present.statement"] = "verb.be.present",
            ["grammar.be-present.question"] = "verb.be.present",
            ["grammar.be-present.negative"] = "verb.be.present",
            ["grammar.be-past.question"] = "past.simple.be",
            ["grammar.modal-obligation"] = "modals.must-have-to",
            ["grammar.modal-question"] = "modals.must-have-to",
            ["grammar.modal-possibility"] = "modals.can-could"
        };

    public static string Resolve(string skillId)
    {
        if (string.IsNullOrWhiteSpace(skillId))
            throw new InvalidDataException("Grammar skill reference cannot be blank.");

        string candidate = LegacyAliases.TryGetValue(skillId.Trim(), out string? mapped)
            ? mapped
            : skillId.Trim();

        if (!GrammarSkillCatalog.ById.ContainsKey(candidate))
            throw new InvalidDataException($"Unknown Grammar skill reference '{skillId}'.");

        return GrammarSkillCatalog.ById[candidate].SkillId;
    }

    public static IReadOnlyList<string> Normalize(IEnumerable<string>? skillIds)
    {
        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string raw in skillIds ?? Array.Empty<string>())
        {
            string resolved = Resolve(raw);
            if (seen.Add(resolved)) result.Add(resolved);
        }
        return result;
    }

    public static bool IsKnown(string? skillId)
    {
        if (string.IsNullOrWhiteSpace(skillId)) return false;
        try
        {
            _ = Resolve(skillId);
            return true;
        }
        catch (InvalidDataException)
        {
            return false;
        }
    }
}

internal static class GrammarSkillReferenceResolverSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;

        Require(GrammarSkillReferenceResolver.Resolve("present.simple.core") == "present.simple.core",
            "Canonical Grammar ID did not resolve to itself.");
        Require(GrammarSkillReferenceResolver.Resolve("grammar.present-simple.statement") == "present.simple.core",
            "Narrative legacy Present Simple alias did not resolve to the canonical Grammar skill.");
        Require(GrammarSkillReferenceResolver.Resolve("grammar.future-intention") == "future.going-to",
            "Narrative future-intention alias did not resolve to the canonical Grammar skill.");

        IReadOnlyList<string> normalized = GrammarSkillReferenceResolver.Normalize(new[]
        {
            "grammar.present-simple.statement",
            "present.simple.core",
            "grammar.modal-obligation"
        });
        Require(normalized.Count == 2 && normalized[0] == "present.simple.core" && normalized[1] == "modals.must-have-to",
            "Grammar reference normalization did not deduplicate aliases deterministically.");

        bool rejected = false;
        try { _ = GrammarSkillReferenceResolver.Resolve("grammar.nonexistent-skill"); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "Unknown cross-mode Grammar skill reference did not fail closed.");

        Console.WriteLine("WordDeck Grammar cross-mode reference self-test PASS.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Grammar reference self-test failed: " + message);
    }
}

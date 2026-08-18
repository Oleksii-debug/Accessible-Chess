using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace WordDeck;

/// <summary>
/// Emergency beta bridge from the already reviewed Oxford 5000 QA ledgers to production
/// lexical rows. This is deliberately strict and temporary: once the full canonical Oxford
/// 5000 ledger is source-extracted, DictionaryLoader can embed that generated ledger directly.
/// </summary>
internal static class ReviewedOxford5000Bootstrap
{
    private const int ExpectedLegacyGroups = 200;
    public const int ExpectedCanonicalRows = 215;

    private static readonly Dictionary<string, string> PosAbbreviations = new(StringComparer.Ordinal)
    {
        ["n."] = "noun",
        ["v."] = "verb",
        ["adj."] = "adjective",
        ["adv."] = "adverb",
        ["prep."] = "preposition",
        ["conj."] = "conjunction",
        ["pron."] = "pronoun",
        ["det."] = "determiner",
        ["exclam."] = "exclamation",
        ["modal v."] = "modal verb",
        ["number"] = "number"
    };

    private sealed record CanonicalCandidate(
        string Id,
        string Source,
        string PartOfSpeech,
        string Level,
        string Target,
        int MajorOrder,
        int MinorOrder);

    public static DictionaryPackage AppendTo(DictionaryPackage baseline)
    {
        ArgumentNullException.ThrowIfNull(baseline);
        List<CanonicalCandidate> canonical = BuildCanonicalRows();
        var existingIds = new HashSet<string>(baseline.Entries.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
        foreach (CanonicalCandidate row in canonical)
        {
            if (!existingIds.Add(row.Id))
                throw new InvalidDataException($"Oxford 5000 beta row collides with existing dictionary entry ID '{row.Id}'.");
        }

        var entries = new List<DictionaryEntry>(baseline.Entries.Count + canonical.Count);
        entries.AddRange(baseline.Entries);
        entries.AddRange(canonical.Select(row => new DictionaryEntry(row.Id, row.Level, row.Source, row.Target)));

        return new DictionaryPackage
        {
            // Keep the existing durable dictionary ID so users' Oxford 3000 Recall progress
            // migrates losslessly into the All workspace as verified additions arrive.
            Id = baseline.Id,
            Name = "Oxford 5000 English-Ukrainian — verified beta",
            SourceLanguage = baseline.SourceLanguage,
            TargetLanguage = baseline.TargetLanguage,
            Entries = entries
        };
    }

    internal static IReadOnlyList<DictionaryEntry> BuildEntriesForTest() =>
        BuildCanonicalRows().Select(row => new DictionaryEntry(row.Id, row.Level, row.Source, row.Target)).ToArray();

    private static List<CanonicalCandidate> BuildCanonicalRows()
    {
        Dictionary<string, Dictionary<string, string>> legacy = LoadVerifiedLegacyRows();
        (Dictionary<string, List<Dictionary<string, string>>> splits, List<Dictionary<string, string>> missing) = LoadSplitMap();

        var result = new List<CanonicalCandidate>();
        foreach ((string legacyId, Dictionary<string, string> row) in legacy.OrderBy(pair => LegacyNumber(pair.Key)))
        {
            int number = LegacyNumber(legacyId);
            if (splits.TryGetValue(legacyId, out List<Dictionary<string, string>>? splitRows))
            {
                for (int minor = 0; minor < splitRows.Count; minor++)
                {
                    Dictionary<string, string> split = splitRows[minor];
                    string source = Required(split, "source");
                    string pos = Required(split, "part_of_speech");
                    string level = Required(split, "level").ToUpperInvariant();
                    string target = Required(split, "ukrainian");
                    ValidateLevel(level);
                    result.Add(new CanonicalCandidate(LexicalEntryId(source, pos, level), source, pos, level, target, number * 10, minor));
                }
                continue;
            }

            (string pos, string level) = ParseSingleMeta(Required(row, "meta"), Required(row, "level"));
            string sourceValue = Required(row, "source");
            result.Add(new CanonicalCandidate(
                LexicalEntryId(sourceValue, pos, level), sourceValue, pos, level,
                Required(row, "ukrainian"), number * 10, 0));
        }

        int missingMinor = 0;
        foreach (Dictionary<string, string> row in missing)
        {
            string source = Required(row, "source");
            string pos = Required(row, "part_of_speech");
            string level = Required(row, "level").ToUpperInvariant();
            string target = Required(row, "ukrainian");
            ValidateLevel(level);
            result.Add(new CanonicalCandidate(LexicalEntryId(source, pos, level), source, pos, level, target, 1295, ++missingMinor));
        }

        result = result.OrderBy(row => row.MajorOrder).ThenBy(row => row.MinorOrder).ToList();
        if (result.Count != ExpectedCanonicalRows)
            throw new InvalidDataException($"Expected {ExpectedCanonicalRows} canonical Oxford 5000 beta rows through noun blow, got {result.Count}.");

        var identities = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (CanonicalCandidate row in result)
        {
            string identity = $"{row.Source}\u001f{row.PartOfSpeech}\u001f{row.Level}";
            if (!identities.Add(identity))
                throw new InvalidDataException($"Duplicate canonical Oxford 5000 lexical identity: {identity}.");
            if (!ids.Add(row.Id))
                throw new InvalidDataException($"Canonical Oxford 5000 stable-ID collision: {row.Id}.");
            if (string.IsNullOrWhiteSpace(row.Target))
                throw new InvalidDataException($"Blank Ukrainian translation for canonical Oxford 5000 row {row.Id}.");
        }

        CanonicalCandidate first = result[0];
        CanonicalCandidate last = result[^1];
        if (first is not { Source: "abolish", PartOfSpeech: "verb", Level: "C1" })
            throw new InvalidDataException("Canonical Oxford 5000 beta ledger does not start with abolish verb C1.");
        if (last is not { Source: "blow", PartOfSpeech: "noun", Level: "B2" })
            throw new InvalidDataException("Canonical Oxford 5000 beta ledger does not end with blow noun B2.");
        if (!result.Any(row => row is { Source: "assumption", PartOfSpeech: "noun", Level: "B2" }))
            throw new InvalidDataException("Audited assumption noun B2 row is missing from canonical Oxford 5000 beta ledger.");
        return result;
    }

    private static Dictionary<string, Dictionary<string, string>> LoadVerifiedLegacyRows()
    {
        string[] resources =
        {
            "oxford5000_additions_translation.tsv",
            "oxford5000_additions_second_pass_0101_0120.tsv",
            "oxford5000_additions_second_pass_0121_0140.tsv",
            "oxford5000_additions_second_pass_0141_0200.tsv"
        };
        var rows = new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);
        foreach (string resource in resources)
        {
            foreach (Dictionary<string, string> row in ReadEmbeddedTsv(resource))
            {
                string id = Required(row, "id");
                if (!string.Equals(Required(row, "status"), "verified", StringComparison.Ordinal))
                    throw new InvalidDataException($"Oxford 5000 beta refuses non-verified legacy row {id}.");
                _ = Required(row, "ukrainian");
                if (!rows.TryAdd(id, row))
                    throw new InvalidDataException($"Duplicate reviewed Oxford 5000 legacy ID {id}.");
            }
        }

        if (rows.Count != ExpectedLegacyGroups)
            throw new InvalidDataException($"Expected exactly {ExpectedLegacyGroups} reviewed legacy translation groups, got {rows.Count}.");
        for (int number = 1; number <= ExpectedLegacyGroups; number++)
        {
            string expected = $"ox5000-add-{number:0000}";
            if (!rows.ContainsKey(expected))
                throw new InvalidDataException($"Reviewed Oxford 5000 legacy coverage is missing {expected}.");
        }
        return rows;
    }

    private static (Dictionary<string, List<Dictionary<string, string>>> Splits, List<Dictionary<string, string>> Missing) LoadSplitMap()
    {
        var splits = new Dictionary<string, List<Dictionary<string, string>>>(StringComparer.OrdinalIgnoreCase);
        var missing = new List<Dictionary<string, string>>();
        foreach (Dictionary<string, string> row in ReadEmbeddedTsv("oxford5000_legacy_split_map_0001_0200.tsv"))
        {
            if (!string.Equals(Required(row, "status"), "verified", StringComparison.Ordinal))
                throw new InvalidDataException("Oxford 5000 split map contains a non-verified row.");
            string legacyId = Required(row, "legacy_id");
            _ = Required(row, "source");
            _ = Required(row, "part_of_speech");
            ValidateLevel(Required(row, "level").ToUpperInvariant());
            _ = Required(row, "ukrainian");
            if (legacyId == "__missing__")
            {
                missing.Add(row);
                continue;
            }
            _ = LegacyNumber(legacyId);
            if (!splits.TryGetValue(legacyId, out List<Dictionary<string, string>>? list))
                splits[legacyId] = list = new List<Dictionary<string, string>>();
            list.Add(row);
        }
        return (splits, missing);
    }

    private static List<Dictionary<string, string>> ReadEmbeddedTsv(string fileName)
    {
        Assembly assembly = Assembly.GetExecutingAssembly();
        string resourceName = assembly.GetManifestResourceNames().SingleOrDefault(name => name.EndsWith(fileName, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidOperationException($"Embedded Oxford QA resource not found: {fileName}.");
        using Stream stream = assembly.GetManifestResourceStream(resourceName)
            ?? throw new InvalidOperationException($"Could not open embedded Oxford QA resource: {resourceName}.");
        using var reader = new StreamReader(stream, Encoding.UTF8, true);
        string? headerLine = reader.ReadLine();
        if (headerLine is null)
            throw new InvalidDataException($"Embedded Oxford QA resource {fileName} is empty.");
        string[] headers = headerLine.Split('\t');
        var result = new List<Dictionary<string, string>>();
        string? line;
        while ((line = reader.ReadLine()) is not null)
        {
            if (string.IsNullOrWhiteSpace(line))
                continue;
            string[] fields = line.Split('\t');
            if (fields.Length != headers.Length)
                throw new InvalidDataException($"Malformed TSV row in embedded Oxford QA resource {fileName}.");
            var row = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < headers.Length; i++)
                row[headers[i]] = fields[i];
            result.Add(row);
        }
        return result;
    }

    internal static string LexicalEntryId(string source, string partOfSpeech, string level)
    {
        string identity = string.Join('\u001f', source.Trim().ToLowerInvariant(), partOfSpeech.Trim().ToLowerInvariant(), level.Trim().ToLowerInvariant());
        string hex = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity))).ToLowerInvariant();
        return $"ox5000-{hex[..20]}";
    }

    private static (string PartOfSpeech, string Level) ParseSingleMeta(string meta, string declaredLevel)
    {
        string normalized = string.Join(' ', meta.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        if (normalized.Contains(',') || declaredLevel.Contains('/'))
            throw new InvalidDataException($"Merged Oxford 5000 meta must be resolved by split map: {meta} / {declaredLevel}.");
        Match match = Regex.Match(normalized, @"\b([ABC][12])$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        if (!match.Success)
            throw new InvalidDataException($"Could not parse Oxford 5000 CEFR from meta '{meta}'.");
        string level = match.Groups[1].Value.ToUpperInvariant();
        ValidateLevel(level);
        if (!string.Equals(level, declaredLevel.Trim(), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"Oxford 5000 declared level '{declaredLevel}' disagrees with meta '{meta}'.");
        string posAbbreviation = normalized[..match.Index].Trim();
        if (!PosAbbreviations.TryGetValue(posAbbreviation, out string? pos))
            throw new InvalidDataException($"Unknown Oxford 5000 POS abbreviation '{posAbbreviation}' in meta '{meta}'.");
        return (pos, level);
    }

    private static int LegacyNumber(string id)
    {
        Match match = Regex.Match(id, @"^ox5000-add-(\d{4})$", RegexOptions.CultureInvariant);
        if (!match.Success)
            throw new InvalidDataException($"Unexpected Oxford 5000 legacy ID '{id}'.");
        return int.Parse(match.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture);
    }

    private static string Required(Dictionary<string, string> row, string field)
    {
        if (!row.TryGetValue(field, out string? value) || string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"Oxford 5000 QA row has blank required field '{field}'.");
        return value.Trim();
    }

    private static void ValidateLevel(string level)
    {
        if (level is not ("B2" or "C1"))
            throw new InvalidDataException($"Oxford 5000 exclusive beta row has unsupported CEFR '{level}'.");
    }
}

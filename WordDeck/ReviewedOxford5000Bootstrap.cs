using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace WordDeck;

internal static class ReviewedOxford5000Bootstrap
{
    private const int ExpectedLegacyGroups = 200;
    private const int ExpectedPostBlowRows = 43;
    private const int StandardSliceRows = 29;
    public const int ExpectedCanonicalRows = 780;

    private static readonly Dictionary<string, string> PosAbbreviations = new(StringComparer.Ordinal)
    {
        ["n."] = "noun", ["v."] = "verb", ["adj."] = "adjective", ["adv."] = "adverb",
        ["prep."] = "preposition", ["conj."] = "conjunction", ["pron."] = "pronoun",
        ["det."] = "determiner", ["exclam."] = "exclamation", ["modal v."] = "modal verb",
        ["number"] = "number"
    };

    private sealed record CanonicalCandidate(string Id, string Source, string PartOfSpeech, string Level,
        string Target, int MajorOrder, int MinorOrder);

    public static DictionaryPackage AppendTo(DictionaryPackage baseline)
    {
        ArgumentNullException.ThrowIfNull(baseline);
        List<CanonicalCandidate> canonical = BuildCanonicalRows();
        var existingIds = new HashSet<string>(baseline.Entries.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
        foreach (CanonicalCandidate row in canonical)
            if (!existingIds.Add(row.Id))
                throw new InvalidDataException($"Oxford 5000 beta row collides with existing dictionary entry ID '{row.Id}'.");

        var entries = new List<DictionaryEntry>(baseline.Entries.Count + canonical.Count);
        entries.AddRange(baseline.Entries);
        entries.AddRange(canonical.Select(row => new DictionaryEntry(row.Id, row.Level, row.Source, row.Target)));
        return new DictionaryPackage
        {
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
                    AddCanonical(result, Required(split, "source"), Required(split, "part_of_speech"),
                        Required(split, "level"), Required(split, "ukrainian"), number * 10, minor);
                }
                continue;
            }

            (string pos, string level) = ParseSingleMeta(Required(row, "meta"), Required(row, "level"));
            AddCanonical(result, Required(row, "source"), pos, level, Required(row, "ukrainian"), number * 10, 0);
        }

        int missingMinor = 0;
        foreach (Dictionary<string, string> row in missing)
            AddCanonical(result, Required(row, "source"), Required(row, "part_of_speech"),
                Required(row, "level"), Required(row, "ukrainian"), 1295, ++missingMinor);

        AppendVerifiedSlice(result, "oxford5000_source_after_blow_c1_0001_0043.tsv", ExpectedPostBlowRows, 1995);
        AppendVerifiedSlice(result, "oxford5000_source_after_chamber_c1_0001_0029.tsv", StandardSliceRows, 1996);
        AppendVerifiedSlice(result, "oxford5000_source_after_colonial_c1_0001_0029.tsv", StandardSliceRows, 1997);
        AppendVerifiedSlice(result, "oxford5000_source_after_compute_c1_0001_0029.tsv", StandardSliceRows, 1998);
        AppendVerifiedSlice(result, "oxford5000_source_after_constitution_c1_0001_0029.tsv", StandardSliceRows, 1999);
        AppendVerifiedSlice(result, "oxford5000_source_after_correlation_c1_0001_0029.tsv", StandardSliceRows, 2001);
        AppendVerifiedSlice(result, "oxford5000_source_after_directory_c1_0001_0029.tsv", StandardSliceRows, 2003);
        AppendVerifiedSlice(result, "oxford5000_source_after_dam_c1_0001_0029.tsv", StandardSliceRows, 2004);
        AppendVerifiedSlice(result, "oxford5000_source_after_dominance_c1_0001_0029.tsv", StandardSliceRows, 2005);
        AppendVerifiedSlice(result, "oxford5000_source_after_embarrassment_c1_0001_0029.tsv", StandardSliceRows, 2006);
        AppendVerifiedSlice(result, "oxford5000_source_after_equality_c1_0001_0029.tsv", StandardSliceRows, 2007);
        AppendVerifiedSlice(result, "oxford5000_source_after_explosive_adj_c1_0001_0029.tsv", StandardSliceRows, 2008);
        AppendVerifiedSlice(result, "oxford5000_source_after_flesh_c1_0001_0029.tsv", StandardSliceRows, 2009);
        AppendVerifiedSlice(result, "oxford5000_source_after_governance_c1_0001_0029.tsv", StandardSliceRows, 2010);
        AppendVerifiedSlice(result, "oxford5000_source_after_harsh_c1_0001_0029.tsv", StandardSliceRows, 2011);
        AppendVerifiedSlice(result, "oxford5000_source_after_imagery_c1_0001_0029.tsv", StandardSliceRows, 2012);
        AppendVerifiedSlice(result, "oxford5000_source_after_injustice_c1_0001_0029.tsv", StandardSliceRows, 2013);
        AppendVerifiedSlice(result, "oxford5000_source_after_interim_c1_0001_0029.tsv", StandardSliceRows, 2014);

        // Deployment remains the historical enumeration tail for old regression fixtures.
        // Stable lexical IDs, not row position, are the durable identity contract.
        AppendVerifiedSlice(result, "oxford5000_source_after_deployment_c1_0001_0029.tsv", StandardSliceRows, 9999);

        result = result.OrderBy(row => row.MajorOrder).ThenBy(row => row.MinorOrder).ToList();
        if (result.Count != ExpectedCanonicalRows)
            throw new InvalidDataException($"Expected {ExpectedCanonicalRows} canonical Oxford 5000 beta rows, got {result.Count}.");

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

        RequirePresence(result, "abolish", "verb", "C1");
        RequirePresence(result, "blow", "noun", "B2");
        RequirePresence(result, "assumption", "noun", "B2");
        RequirePresence(result, "colonial", "adjective", "C1");
        RequirePresence(result, "compute", "verb", "C1");
        RequirePresence(result, "constitution", "noun", "C1");
        RequirePresence(result, "correlation", "noun", "C1");
        RequirePresence(result, "dam", "noun", "C1");
        RequirePresence(result, "directory", "noun", "C1");
        RequirePresence(result, "dominance", "noun", "C1");
        RequirePresence(result, "excess", "noun", "C1");
        RequirePresence(result, "explosive", "noun", "C1");
        RequirePresence(result, "flesh", "noun", "C1");
        RequirePresence(result, "governance", "noun", "C1");
        RequirePresence(result, "harsh", "adjective", "C1");
        RequirePresence(result, "imagery", "noun", "C1");
        RequirePresence(result, "injustice", "noun", "C1");
        RequirePresence(result, "interim", "adjective", "C1");
        RequirePresence(result, "large-scale", "adjective", "C1");
        if (result[^1] is not { Source: "deployment", PartOfSpeech: "noun", Level: "C1" })
            throw new InvalidDataException("Canonical Oxford 5000 beta ledger historical regression tail changed unexpectedly.");
        return result;
    }

    private static void AddCanonical(List<CanonicalCandidate> result, string source, string pos, string level,
        string target, int majorOrder, int minorOrder)
    {
        source = source.Trim();
        pos = pos.Trim();
        level = level.Trim().ToUpperInvariant();
        target = target.Trim();
        ValidateLevel(level);
        if (source.Length == 0 || pos.Length == 0 || target.Length == 0)
            throw new InvalidDataException("Oxford 5000 canonical row contains a blank required field.");
        result.Add(new CanonicalCandidate(LexicalEntryId(source, pos, level), source, pos, level, target, majorOrder, minorOrder));
    }

    private static void AppendVerifiedSlice(List<CanonicalCandidate> result, string fileName, int expectedRows, int majorOrder)
    {
        List<Dictionary<string, string>> rows = ReadEmbeddedTsv(fileName);
        if (rows.Count != expectedRows)
            throw new InvalidDataException($"Expected {expectedRows} verified Oxford 5000 rows in {fileName}, got {rows.Count}.");

        for (int i = 0; i < rows.Count; i++)
        {
            Dictionary<string, string> row = rows[i];
            string status = Required(row, "status");
            if (!string.Equals(status, "verified", StringComparison.Ordinal))
                throw new InvalidDataException($"Oxford 5000 beta refuses row {i + 1} in {fileName} with status '{status}'.");
            string source = Required(row, "source");
            string pos = Required(row, "part_of_speech");
            string level = Required(row, "level").ToUpperInvariant();
            string target = Required(row, "ukrainian");
            string suppliedId = Required(row, "entry_id");
            ValidateLevel(level);
            string canonicalId = LexicalEntryId(source, pos, level);
            if (!string.Equals(suppliedId, canonicalId, StringComparison.Ordinal))
                throw new InvalidDataException($"Oxford 5000 stable ID mismatch for {source} {pos} {level}: supplied {suppliedId}, expected {canonicalId}.");
            result.Add(new CanonicalCandidate(canonicalId, source, pos, level, target, majorOrder, i + 1));
        }
    }

    private static Dictionary<string, Dictionary<string, string>> LoadVerifiedLegacyRows()
    {
        string[] resources =
        {
            "oxford5000_additions_translation.tsv", "oxford5000_additions_second_pass_0101_0120.tsv",
            "oxford5000_additions_second_pass_0121_0140.tsv", "oxford5000_additions_second_pass_0141_0200.tsv"
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
        string resourceName = assembly.GetManifestResourceNames()
            .SingleOrDefault(name => name.EndsWith(fileName, StringComparison.OrdinalIgnoreCase))
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
            if (string.IsNullOrWhiteSpace(line)) continue;
            string[] fields = line.Split('\t');
            if (fields.Length != headers.Length)
                throw new InvalidDataException($"Malformed TSV row in embedded Oxford QA resource {fileName}.");
            var row = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < headers.Length; i++) row[headers[i]] = fields[i];
            result.Add(row);
        }
        return result;
    }

    internal static string LexicalEntryId(string source, string partOfSpeech, string level)
    {
        string identity = string.Join('\u001f', source.Trim().ToLowerInvariant(),
            partOfSpeech.Trim().ToLowerInvariant(), level.Trim().ToLowerInvariant());
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

    private static string Required(Dictionary<string, string> row, string key)
    {
        if (!row.TryGetValue(key, out string? value) || string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"Required Oxford 5000 field '{key}' is blank.");
        return value.Trim();
    }

    private static void ValidateLevel(string level)
    {
        if (level is not "B2" and not "C1")
            throw new InvalidDataException($"Oxford 5000 addition level '{level}' is unsupported; expected B2 or C1.");
    }

    private static void RequirePresence(IEnumerable<CanonicalCandidate> rows, string source, string pos, string level)
    {
        if (!rows.Any(row => row.Source == source && row.PartOfSpeech == pos && row.Level == level))
            throw new InvalidDataException($"Verified Oxford 5000 row is missing from canonical ledger: {source} {pos} {level}.");
    }
}
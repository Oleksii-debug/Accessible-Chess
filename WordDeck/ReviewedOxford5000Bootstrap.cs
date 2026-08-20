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
    private const int HistoricalDeploymentMajorOrder = 2004;
    private const int VerifiedPostMutualRows = 28;
    public const int ExpectedCanonicalRows = 982;

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
        AppendVerifiedSlice(result, "oxford5000_source_after_dam_c1_0001_0029.tsv", StandardSliceRows, HistoricalDeploymentMajorOrder);
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
        AppendVerifiedSlice(result, "oxford5000_source_after_large_scale_c1_0001_0029.tsv", StandardSliceRows, 2015);
        AppendVerifiedSlice(result, "oxford5000_source_after_limb_c1_0001_0029.tsv", StandardSliceRows, 2016);
        AppendVerifiedSlice(result, "oxford5000_source_after_manipulate_c1_0001_0029.tsv", StandardSliceRows, 2017);
        AppendVerifiedSlice(result, "oxford5000_source_after_merit_c1_0001_0029.tsv", StandardSliceRows, 2018);
        AppendVerifiedSlice(result, "oxford5000_source_after_mutual_verified_c1_0001_0028.tsv", VerifiedPostMutualRows, 2019);
        AppendVerifiedSlice(result, "oxford5000_source_after_mutual_verified_b2c1_0001_0029.tsv", StandardSliceRows, 2020);
        AppendVerifiedSlice(result, "oxford5000_source_after_offspring_verified_c1_0001_0029.tsv", StandardSliceRows, 2021);

        // The post-deployment slice is intentionally later than the historical deployment boundary.
        // Stable lexical IDs and the explicit historical boundary below are the durable regression contract.
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
        RequirePresence(result, "laser", "noun", "C1");
        RequirePresence(result, "limb", "noun", "C1");
        RequirePresence(result, "line-up", "noun", "C1");
        RequirePresence(result, "manipulate", "verb", "C1");
        RequirePresence(result, "manipulation", "noun", "C1");
        RequirePresence(result, "merit", "noun", "C1");
        RequirePresence(result, "methodology", "noun", "C1");
        RequirePresence(result, "minute", "adjective", "C1");
        RequirePresence(result, "mutual", "adjective", "C1");
        RequirePresence(result, "namely", "adverb", "C1");
        RequirePresence(result, "offspring", "noun", "C1");
        RequirePresence(result, "myth", "noun", "B2");
        RequirePresence(result, "net", "adjective", "C1");
        RequirePresence(result, "nursing", "noun", "B2");
        RequirePresence(result, "occupation", "noun", "B2");
        RequirePresence(result, "offender", "noun", "B2");
        RequirePresence(result, "operational", "adjective", "C1");
        RequirePresence(result, "passing", "noun", "C1");
        RequirePresence(result, "deployment", "noun", "C1");

        CanonicalCandidate? historicalDeploymentBoundary = result.SingleOrDefault(row =>
            row.Source == "deployment" && row.PartOfSpeech == "noun" && row.Level == "C1");
        if (historicalDeploymentBoundary is null ||
            historicalDeploymentBoundary.MajorOrder != HistoricalDeploymentMajorOrder ||
            historicalDeploymentBoundary.MinorOrder != StandardSliceRows)
        {
            throw new InvalidDataException(
                "Canonical Oxford 5000 beta historical deployment/noun/C1 boundary changed unexpectedly.");
        }
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
            string legacyId = Required(row, "legacy_id");
            string relation = Required(row, "relation");
            if (relation == "split")
            {
                if (!splits.TryGetValue(legacyId, out List<Dictionary<string, string>>? list))
                {
                    list = new List<Dictionary<string, string>>();
                    splits[legacyId] = list;
                }
                list.Add(row);
            }
            else if (relation == "missing")
            {
                missing.Add(row);
            }
            else
            {
                throw new InvalidDataException($"Unknown Oxford 5000 legacy split relation '{relation}'.");
            }
        }
        return (splits, missing);
    }

    private static (string Pos, string Level) ParseSingleMeta(string meta, string fallbackLevel)
    {
        Match match = Regex.Match(meta, @"^(?<pos>.+?)\s+(?<level>[ABC][12])$");
        if (match.Success)
        {
            string rawPos = match.Groups["pos"].Value.Trim();
            string pos = PosAbbreviations.GetValueOrDefault(rawPos, rawPos.TrimEnd('.'));
            return (pos, match.Groups["level"].Value.ToUpperInvariant());
        }
        string level = fallbackLevel.ToUpperInvariant();
        ValidateLevel(level);
        return ("unknown", level);
    }

    private static int LegacyNumber(string id)
    {
        Match match = Regex.Match(id, @"(\d+)$");
        if (!match.Success || !int.TryParse(match.Groups[1].Value, out int number))
            throw new InvalidDataException($"Invalid legacy Oxford 5000 ID '{id}'.");
        return number;
    }

    private static string LexicalEntryId(string source, string pos, string level)
    {
        string identity = string.Join("\u001f", source.Trim().ToLowerInvariant(), pos.Trim().ToLowerInvariant(), level.Trim().ToLowerInvariant());
        byte[] digest = SHA256.HashData(Encoding.UTF8.GetBytes(identity));
        return $"ox5000-{Convert.ToHexString(digest)[..20].ToLowerInvariant()}";
    }

    private static void ValidateLevel(string level)
    {
        if (level is not ("B2" or "C1"))
            throw new InvalidDataException($"Unsupported Oxford 5000 level '{level}'.");
    }

    private static string Required(Dictionary<string, string> row, string key)
    {
        if (!row.TryGetValue(key, out string? value) || string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"Oxford 5000 QA row is missing required value '{key}'.");
        return value.Trim();
    }

    private static void RequirePresence(List<CanonicalCandidate> rows, string source, string pos, string level)
    {
        if (!rows.Any(row => row.Source == source && row.PartOfSpeech == pos && row.Level == level))
            throw new InvalidDataException($"Required canonical Oxford 5000 lexical identity is missing: {source}/{pos}/{level}.");
    }

    private static List<Dictionary<string, string>> ReadEmbeddedTsv(string fileName)
    {
        Assembly assembly = Assembly.GetExecutingAssembly();
        string suffix = $"QA.{fileName}";
        string resourceName = assembly.GetManifestResourceNames()
            .SingleOrDefault(name => name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"Embedded Oxford 5000 QA resource was not found: {fileName}.");
        using Stream stream = assembly.GetManifestResourceStream(resourceName)
            ?? throw new InvalidDataException($"Unable to open Oxford 5000 QA resource: {resourceName}.");
        using var reader = new StreamReader(stream, Encoding.UTF8, true);
        string text = reader.ReadToEnd();
        string[] lines = text.Split(new[] { "\r\n", "\n" }, StringSplitOptions.None)
            .Where(line => line.Length > 0)
            .ToArray();
        if (lines.Length < 2)
            throw new InvalidDataException($"Oxford 5000 QA resource has no data rows: {fileName}.");
        string[] headers = lines[0].Split('\t').Select(x => x.Trim()).ToArray();
        var rows = new List<Dictionary<string, string>>();
        for (int i = 1; i < lines.Length; i++)
        {
            string[] values = lines[i].Split('\t');
            if (values.Length != headers.Length)
                throw new InvalidDataException($"Oxford 5000 QA resource {fileName} line {i + 1} has {values.Length} columns; expected {headers.Length}.");
            var row = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            for (int j = 0; j < headers.Length; j++) row[headers[j]] = values[j].Trim();
            rows.Add(row);
        }
        return rows;
    }
}

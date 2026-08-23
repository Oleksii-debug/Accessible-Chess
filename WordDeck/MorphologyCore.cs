using System.Globalization;
using System.Text;

namespace WordDeck;

internal enum MorphologyRelationKind
{
    Derivation = 1,
    Prefix = 2,
    Suffix = 3,
    Root = 4,
    Compound = 5
}

internal sealed record MorphologySourceMetadata(
    string SourceId,
    string SourceName,
    string License,
    string Attribution,
    string? SourceUri = null,
    string? Version = null);

internal sealed record MorphologyRelation(
    string Id,
    string FamilyId,
    string FromEntryId,
    string ToEntryId,
    MorphologyRelationKind Kind,
    string? Morpheme,
    string EvidenceRef,
    int SourceLine = 0);

internal sealed class MorphologyOverlayPackage
{
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; init; } = CurrentSchemaVersion;
    public required string PackageId { get; init; }
    public required MorphologySourceMetadata Source { get; init; }
    public required IReadOnlyList<MorphologyRelation> Relations { get; init; }
}

internal sealed record MorphologyValidationIssue(
    int SourceLine,
    string RelationId,
    string Code,
    string Message);

internal sealed record MorphologyImportResult(
    MorphologyOverlayPackage? Package,
    IReadOnlyList<MorphologyValidationIssue> Issues);

internal sealed record MorphologyBuildResult(
    MorphologyOverlay Overlay,
    IReadOnlyList<MorphologyValidationIssue> Issues)
{
    public int AcceptedRelations => Overlay.RelationCount;
    public int RejectedRelations => Issues.Count(issue => issue.RelationId.Length > 0);
}

internal sealed record MorphologyIntegrationTarget(
    string EntryId,
    string Source,
    string Level,
    string FamilyId,
    MorphologyRelationKind RelationKind);

internal sealed record MorphologyExercise(
    string ExerciseId,
    string Prompt,
    string SourceEntryId,
    string TargetEntryId,
    string AcceptedAnswer,
    MorphologyRelationKind RelationKind,
    string RelationId)
{
    public bool Check(string? answer)
    {
        if (string.IsNullOrWhiteSpace(answer)) return false;
        string normalized = answer.Trim().Normalize(NormalizationForm.FormC);
        string expected = AcceptedAnswer.Trim().Normalize(NormalizationForm.FormC);
        return normalized.Equals(expected, StringComparison.OrdinalIgnoreCase);
    }
}

/// <summary>
/// Immutable, source-backed relation overlay. Canonical DictionaryEntry IDs are never
/// replaced or merged; all family information remains a separate graph over those IDs.
/// </summary>
internal sealed class MorphologyOverlay
{
    private readonly IReadOnlyDictionary<string, DictionaryEntry> _entries;
    private readonly IReadOnlyDictionary<string, IReadOnlyList<MorphologyRelation>> _byEntry;
    private readonly IReadOnlyDictionary<string, IReadOnlyList<MorphologyRelation>> _byFamily;

    internal MorphologyOverlay(
        IReadOnlyDictionary<string, DictionaryEntry> entries,
        IReadOnlyList<MorphologyRelation> relations)
    {
        _entries = entries;
        Relations = relations;

        var byEntry = new Dictionary<string, List<MorphologyRelation>>(StringComparer.OrdinalIgnoreCase);
        var byFamily = new Dictionary<string, List<MorphologyRelation>>(StringComparer.OrdinalIgnoreCase);
        foreach (MorphologyRelation relation in relations)
        {
            Add(byEntry, relation.FromEntryId, relation);
            Add(byEntry, relation.ToEntryId, relation);
            Add(byFamily, relation.FamilyId, relation);
        }

        _byEntry = byEntry.ToDictionary(
            pair => pair.Key,
            pair => (IReadOnlyList<MorphologyRelation>)pair.Value
                .OrderBy(item => item.Id, StringComparer.OrdinalIgnoreCase)
                .ToArray(),
            StringComparer.OrdinalIgnoreCase);
        _byFamily = byFamily.ToDictionary(
            pair => pair.Key,
            pair => (IReadOnlyList<MorphologyRelation>)pair.Value
                .OrderBy(item => item.Id, StringComparer.OrdinalIgnoreCase)
                .ToArray(),
            StringComparer.OrdinalIgnoreCase);
    }

    public IReadOnlyList<MorphologyRelation> Relations { get; }
    public int RelationCount => Relations.Count;

    public IReadOnlyList<MorphologyRelation> GetRelations(
        string entryId,
        MorphologyRelationKind? kind = null)
    {
        if (string.IsNullOrWhiteSpace(entryId) || !_byEntry.TryGetValue(entryId, out IReadOnlyList<MorphologyRelation>? relations))
            return Array.Empty<MorphologyRelation>();
        if (kind is null) return relations;
        return relations.Where(relation => relation.Kind == kind.Value).ToArray();
    }

    public IReadOnlyList<string> GetFamilyMembers(string entryId, int maxNodes = 128)
    {
        if (maxNodes is < 1 or > 4096)
            throw new ArgumentOutOfRangeException(nameof(maxNodes), "Family traversal bound must be between 1 and 4096.");
        if (!_entries.ContainsKey(entryId)) return Array.Empty<string>();

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { entryId };
        var queue = new Queue<string>();
        queue.Enqueue(entryId);
        while (queue.Count > 0 && seen.Count < maxNodes)
        {
            string current = queue.Dequeue();
            foreach (MorphologyRelation relation in GetRelations(current))
            {
                string neighbor = relation.FromEntryId.Equals(current, StringComparison.OrdinalIgnoreCase)
                    ? relation.ToEntryId
                    : relation.FromEntryId;
                if (seen.Count >= maxNodes) break;
                if (seen.Add(neighbor)) queue.Enqueue(neighbor);
            }
        }

        return seen.OrderBy(id => id, StringComparer.OrdinalIgnoreCase).ToArray();
    }

    public IReadOnlyList<MorphologyIntegrationTarget> GetIntegrationTargets(string entryId, int maxTargets = 32)
    {
        if (maxTargets is < 1 or > 256)
            throw new ArgumentOutOfRangeException(nameof(maxTargets));

        var result = new List<MorphologyIntegrationTarget>();
        foreach (MorphologyRelation relation in GetRelations(entryId))
        {
            string otherId = relation.FromEntryId.Equals(entryId, StringComparison.OrdinalIgnoreCase)
                ? relation.ToEntryId
                : relation.FromEntryId;
            if (!_entries.TryGetValue(otherId, out DictionaryEntry? entry)) continue;
            result.Add(new MorphologyIntegrationTarget(entry.Id, entry.Source, entry.Level, relation.FamilyId, relation.Kind));
            if (result.Count >= maxTargets) break;
        }
        return result;
    }

    public MorphologyExercise? CreateRecallExercise(string entryId, int sequence = 0)
    {
        IReadOnlyList<MorphologyRelation> relations = GetRelations(entryId);
        if (relations.Count == 0 || !_entries.TryGetValue(entryId, out DictionaryEntry? sourceEntry)) return null;
        int index = Math.Abs(sequence % relations.Count);
        MorphologyRelation relation = relations[index];
        string targetId = relation.FromEntryId.Equals(entryId, StringComparison.OrdinalIgnoreCase)
            ? relation.ToEntryId
            : relation.FromEntryId;
        if (!_entries.TryGetValue(targetId, out DictionaryEntry? targetEntry)) return null;

        string relationLabel = relation.Kind switch
        {
            MorphologyRelationKind.Derivation => "словотвірно пов'язану форму",
            MorphologyRelationKind.Prefix => "форму, пов'язану префіксом",
            MorphologyRelationKind.Suffix => "форму, пов'язану суфіксом",
            MorphologyRelationKind.Root => "форму зі спільним коренем",
            MorphologyRelationKind.Compound => "пов'язану складну форму",
            _ => "пов'язану форму"
        };
        string prompt = $"Введіть {relationLabel} для англійського слова «{sourceEntry.Source}».";
        return new MorphologyExercise(
            $"morph:{relation.Id}:{entryId}",
            prompt,
            entryId,
            targetId,
            targetEntry.Source,
            relation.Kind,
            relation.Id);
    }

    private static void Add(
        Dictionary<string, List<MorphologyRelation>> index,
        string key,
        MorphologyRelation relation)
    {
        if (!index.TryGetValue(key, out List<MorphologyRelation>? list))
        {
            list = new List<MorphologyRelation>();
            index[key] = list;
        }
        list.Add(relation);
    }
}

internal static class MorphologyOverlayBuilder
{
    public static MorphologyBuildResult Build(MorphologyOverlayPackage package, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(package);
        ArgumentNullException.ThrowIfNull(dictionary);

        var entries = dictionary.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        var issues = new List<MorphologyValidationIssue>();

        if (package.SchemaVersion != MorphologyOverlayPackage.CurrentSchemaVersion)
            issues.Add(PackageIssue("package.schema", $"Unsupported morphology schema version {package.SchemaVersion}."));
        if (!IsSafeToken(package.PackageId))
            issues.Add(PackageIssue("package.id", "Package ID is missing or contains control characters."));
        ValidateSource(package.Source, issues);

        if (issues.Any(issue => issue.RelationId.Length == 0))
            return new MorphologyBuildResult(new MorphologyOverlay(entries, Array.Empty<MorphologyRelation>()), issues);

        var accepted = new List<MorphologyRelation>();
        var relationIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var signatures = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (MorphologyRelation relation in package.Relations)
        {
            string id = relation.Id?.Trim() ?? string.Empty;
            int before = issues.Count;
            if (!IsSafeToken(id)) Add("relation.id", "Relation ID is missing or contains control characters.");
            else if (!relationIds.Add(id)) Add("relation.duplicate-id", $"Duplicate relation ID '{id}'.");
            if (!IsSafeToken(relation.FamilyId)) Add("relation.family", "Family ID is missing or contains control characters.");
            if (string.IsNullOrWhiteSpace(relation.FromEntryId) || string.IsNullOrWhiteSpace(relation.ToEntryId))
                Add("relation.endpoint", "Both canonical entry IDs are required.");
            else if (relation.FromEntryId.Equals(relation.ToEntryId, StringComparison.OrdinalIgnoreCase))
                Add("relation.self-link", "A relation cannot link an entry to itself.");
            if (!entries.ContainsKey(relation.FromEntryId)) Add("relation.unknown-from", $"Unknown canonical entry ID '{relation.FromEntryId}'.");
            if (!entries.ContainsKey(relation.ToEntryId)) Add("relation.unknown-to", $"Unknown canonical entry ID '{relation.ToEntryId}'.");
            if (!Enum.IsDefined(typeof(MorphologyRelationKind), relation.Kind)) Add("relation.kind", "Unsupported relation kind.");
            if (!IsSafeText(relation.EvidenceRef)) Add("relation.evidence", "A source evidence reference is required.");

            if (relation.Kind is MorphologyRelationKind.Prefix or MorphologyRelationKind.Suffix or MorphologyRelationKind.Root)
            {
                if (!IsSafeText(relation.Morpheme))
                    Add("relation.morpheme", $"{relation.Kind} relations require an explicit morpheme/root value.");
            }

            string signature = string.Join('|',
                relation.FromEntryId.Trim(),
                relation.ToEntryId.Trim(),
                relation.Kind.ToString(),
                relation.Morpheme?.Trim() ?? string.Empty);
            if (issues.Count == before && !signatures.Add(signature))
                Add("relation.duplicate-edge", "Duplicate relation edge.");

            if (issues.Count == before)
                accepted.Add(relation with
                {
                    Id = id,
                    FamilyId = relation.FamilyId.Trim(),
                    FromEntryId = relation.FromEntryId.Trim(),
                    ToEntryId = relation.ToEntryId.Trim(),
                    Morpheme = relation.Morpheme?.Trim(),
                    EvidenceRef = relation.EvidenceRef.Trim()
                });

            void Add(string code, string message) =>
                issues.Add(new MorphologyValidationIssue(relation.SourceLine, id, code, message));
        }

        return new MorphologyBuildResult(new MorphologyOverlay(entries, accepted), issues);
    }

    private static void ValidateSource(MorphologySourceMetadata source, List<MorphologyValidationIssue> issues)
    {
        if (!IsSafeToken(source.SourceId)) issues.Add(PackageIssue("source.id", "Source ID is required."));
        if (!IsSafeText(source.SourceName)) issues.Add(PackageIssue("source.name", "Source name is required."));
        if (!IsSafeText(source.License)) issues.Add(PackageIssue("source.license", "License information is required before relations can be accepted."));
        if (!IsSafeText(source.Attribution)) issues.Add(PackageIssue("source.attribution", "Attribution is required before relations can be accepted."));
        if (source.SourceUri is { Length: > 0 } uri && !Uri.TryCreate(uri, UriKind.Absolute, out _))
            issues.Add(PackageIssue("source.uri", "Source URI must be absolute when supplied."));
    }

    private static MorphologyValidationIssue PackageIssue(string code, string message) => new(0, string.Empty, code, message);

    private static bool IsSafeToken(string? value) =>
        !string.IsNullOrWhiteSpace(value) && value.All(ch => ch != '\t' && ch != '\r' && ch != '\n' && !char.IsControl(ch));

    private static bool IsSafeText(string? value) => IsSafeToken(value);
}

/// <summary>
/// Production ingestion contract. It imports only explicit stable-ID relations;
/// it never guesses a family from spelling, suffixes, or equal surface forms.
/// Invalid rows are quarantined while valid rows continue through validation.
/// </summary>
internal static class MorphologyOverlayTsv
{
    private static readonly string[] Header =
    {
        "relationId", "familyId", "fromEntryId", "toEntryId", "kind", "morpheme", "evidenceRef"
    };

    public static MorphologyImportResult Parse(string text)
    {
        var metadata = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var relations = new List<MorphologyRelation>();
        var issues = new List<MorphologyValidationIssue>();
        bool headerSeen = false;
        int lineNumber = 0;

        using var reader = new StringReader(text ?? string.Empty);
        string? line;
        while ((line = reader.ReadLine()) is not null)
        {
            lineNumber++;
            if (string.IsNullOrWhiteSpace(line)) continue;
            if (line.StartsWith('#'))
            {
                int equals = line.IndexOf('=');
                if (equals > 1) metadata[line[1..equals].Trim()] = line[(equals + 1)..].Trim();
                continue;
            }

            string[] parts = line.Split('\t');
            if (!headerSeen)
            {
                headerSeen = true;
                if (parts.Length != Header.Length || !parts.Select(item => item.Trim()).SequenceEqual(Header, StringComparer.OrdinalIgnoreCase))
                {
                    issues.Add(new MorphologyValidationIssue(lineNumber, string.Empty, "tsv.header", "Morphology TSV header is invalid."));
                    return new MorphologyImportResult(null, issues);
                }
                continue;
            }

            if (parts.Length != Header.Length)
            {
                issues.Add(new MorphologyValidationIssue(lineNumber, string.Empty, "tsv.columns", "Morphology row must contain exactly seven tab-separated columns."));
                continue;
            }

            string relationId = parts[0].Trim();
            if (!Enum.TryParse(parts[4].Trim(), true, out MorphologyRelationKind kind) || !Enum.IsDefined(typeof(MorphologyRelationKind), kind))
            {
                issues.Add(new MorphologyValidationIssue(lineNumber, relationId, "tsv.kind", $"Unknown relation kind '{parts[4].Trim()}'."));
                continue;
            }

            relations.Add(new MorphologyRelation(
                relationId,
                parts[1].Trim(),
                parts[2].Trim(),
                parts[3].Trim(),
                kind,
                string.IsNullOrWhiteSpace(parts[5]) ? null : parts[5].Trim(),
                parts[6].Trim(),
                lineNumber));
        }

        if (!headerSeen)
        {
            issues.Add(new MorphologyValidationIssue(0, string.Empty, "tsv.empty", "Morphology TSV contains no header/data."));
            return new MorphologyImportResult(null, issues);
        }

        int schema = MorphologyOverlayPackage.CurrentSchemaVersion;
        if (metadata.TryGetValue("schemaVersion", out string? schemaText) && !int.TryParse(schemaText, NumberStyles.None, CultureInfo.InvariantCulture, out schema))
            schema = -1;

        var package = new MorphologyOverlayPackage
        {
            SchemaVersion = schema,
            PackageId = metadata.GetValueOrDefault("packageId", string.Empty),
            Source = new MorphologySourceMetadata(
                metadata.GetValueOrDefault("sourceId", string.Empty),
                metadata.GetValueOrDefault("sourceName", string.Empty),
                metadata.GetValueOrDefault("license", string.Empty),
                metadata.GetValueOrDefault("attribution", string.Empty),
                metadata.GetValueOrDefault("sourceUri"),
                metadata.GetValueOrDefault("version")),
            Relations = relations
        };
        return new MorphologyImportResult(package, issues);
    }
}
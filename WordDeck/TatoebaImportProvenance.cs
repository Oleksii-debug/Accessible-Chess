using System.Security.Cryptography;
using System.Text.Json;

namespace WordDeck;

internal sealed record TatoebaImportMetadata(
    string Provenance,
    string License,
    bool VerifiedCc0Manifest,
    bool VerifiedAttributedCcByManifest = false);

internal static class TatoebaImportProvenance
{
    private const int SupportedManifestSchemaVersion = 1;
    private const string VerifiedCc0Filter = "CC0 1.0 on BOTH sentence sides";
    private const string VerifiedCcByFilter = "CC BY 2.0 FR with BOTH sentence-owner usernames retained";
    private static readonly string[] Cc0CurrentInputs = { "english_cc0", "ukrainian_cc0", "links" };
    private static readonly string[] CcByCurrentInputs = { "english_detailed", "ukrainian_detailed", "links" };
    private static readonly string[] Cc0LegacyInputs = { "english_cc0", "ukrainian_cc0", "english_ukrainian_links" };
    private static readonly string[] CcByLegacyInputs = { "english_detailed", "ukrainian_detailed", "english_ukrainian_links" };

    public static TatoebaImportMetadata Resolve(string pairTsvPath)
    {
        if (string.IsNullOrWhiteSpace(pairTsvPath))
            throw new ArgumentException("Tatoeba pair TSV path is required.", nameof(pairTsvPath));

        string fullPairPath = Path.GetFullPath(pairTsvPath);
        if (!File.Exists(fullPairPath))
            throw new FileNotFoundException("Tatoeba pair TSV was not found.", fullPairPath);

        string manifestPath = fullPairPath + ".manifest.json";
        if (!File.Exists(manifestPath))
            throw new InvalidDataException("Tatoeba pair TSV has no adjacent verified provenance manifest. Refusing to invent a redistribution license.");

        try
        {
            using JsonDocument document = JsonDocument.Parse(File.ReadAllText(manifestPath));
            JsonElement root = document.RootElement;

            if (!root.TryGetProperty("schema_version", out JsonElement schemaElement) ||
                !schemaElement.TryGetInt32(out int schemaVersion) ||
                schemaVersion != SupportedManifestSchemaVersion)
            {
                throw new InvalidDataException("Tatoeba provenance manifest has an unsupported or missing schema_version.");
            }

            bool hasLegacySources = root.TryGetProperty("sources", out JsonElement legacySources) && legacySources.ValueKind == JsonValueKind.Object;
            if (root.TryGetProperty("source", out JsonElement sourceElement) && sourceElement.ValueKind == JsonValueKind.String)
            {
                string source = sourceElement.GetString() ?? string.Empty;
                if (string.IsNullOrWhiteSpace(source) || !source.Contains("Tatoeba", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Tatoeba provenance manifest does not identify Tatoeba as its source.");
            }
            else if (!hasLegacySources)
            {
                throw new InvalidDataException("Tatoeba provenance manifest is missing a source identity/evidence block.");
            }

            if (root.TryGetProperty("output", out JsonElement outputElement))
            {
                if (outputElement.ValueKind != JsonValueKind.String ||
                    !string.Equals(outputElement.GetString(), Path.GetFileName(fullPairPath), StringComparison.Ordinal))
                {
                    throw new InvalidDataException("Tatoeba provenance manifest output name does not match the selected pair TSV.");
                }
            }
            else if (!hasLegacySources)
            {
                throw new InvalidDataException("Tatoeba provenance manifest is missing its output file identity.");
            }

            string licenseFilter = RequireString(root, "license_filter");
            string expectedOutputHash = RequireSha256(root, "output_sha256");

            using FileStream stream = File.OpenRead(fullPairPath);
            string actualHash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
            if (!string.Equals(actualHash, expectedOutputHash, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Tatoeba provenance manifest SHA-256 does not match the selected pair TSV.");

            if (string.Equals(licenseFilter, VerifiedCc0Filter, StringComparison.Ordinal))
            {
                ValidateOfficialSourceEvidence(root, Cc0CurrentInputs, Cc0LegacyInputs, requireAttributionPolicy: false);
                string provenance =
                    "Tatoeba official weekly EN-UA exports filtered by WordDeck so BOTH English and Ukrainian sentence IDs are independently present in the official CC0 sentence exports. Official acquisition URLs and upstream/input plus output SHA-256 evidence were retained in the adjacent manifest; the selected pair TSV hash was verified before import.";
                return new TatoebaImportMetadata(provenance, "CC0 1.0", true);
            }

            if (string.Equals(licenseFilter, VerifiedCcByFilter, StringComparison.Ordinal))
            {
                string declaredLicense = RequireString(root, "license");
                if (!string.Equals(declaredLicense, "CC BY 2.0 FR", StringComparison.Ordinal))
                    throw new InvalidDataException("Attributed Tatoeba manifest does not declare the expected CC BY 2.0 FR license.");
                ValidateOfficialSourceEvidence(root, CcByCurrentInputs, CcByLegacyInputs, requireAttributionPolicy: true);

                string provenance =
                    "Tatoeba official weekly detailed EN-UA sentence exports linked by upstream sentence IDs. WordDeck retained nonblank Tatoeba owner usernames for BOTH sentence sides; official acquisition URLs and upstream/input plus output SHA-256 evidence were retained in the adjacent manifest and verified before import. Per-sentence author attribution is embedded in each SentenceRecord.Source.";
                return new TatoebaImportMetadata(provenance, "CC BY 2.0 FR", false, true);
            }

            throw new InvalidDataException("Tatoeba provenance manifest uses an unapproved or unknown license_filter. Refusing to build a redistributable SentencePack.");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("Tatoeba provenance manifest is malformed JSON.", ex);
        }
    }

    private static void ValidateOfficialSourceEvidence(
        JsonElement root,
        IReadOnlyList<string> currentInputs,
        IReadOnlyList<string> legacyInputs,
        bool requireAttributionPolicy)
    {
        bool hasCurrentUrls = root.TryGetProperty("official_urls", out JsonElement urls) && urls.ValueKind == JsonValueKind.Object;
        bool hasCurrentHashes = root.TryGetProperty("input_sha256", out JsonElement hashes) && hashes.ValueKind == JsonValueKind.Object;
        bool currentShape = hasCurrentUrls && hasCurrentHashes;
        if (currentShape)
        {
            foreach (string input in currentInputs)
            {
                ValidateOfficialUrl(RequireObjectString(urls, input, "official_urls"), input);
                string hash = RequireObjectString(hashes, input, "input_sha256");
                if (!IsSha256(hash))
                    throw new InvalidDataException($"Tatoeba provenance manifest input_sha256.{input} is not a valid SHA-256 digest.");
            }

            if (!root.TryGetProperty("stats", out JsonElement stats) || stats.ValueKind != JsonValueKind.Object ||
                !stats.TryGetProperty("pairs_emitted", out JsonElement emitted) || !emitted.TryGetInt32(out int pairCount) || pairCount <= 0)
            {
                throw new InvalidDataException("Tatoeba provenance manifest transformation statistics contain no positive pairs_emitted count.");
            }

            if (requireAttributionPolicy)
                _ = RequireString(root, "attribution_policy");
            return;
        }

        if (!root.TryGetProperty("sources", out JsonElement sources) || sources.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("Tatoeba provenance manifest is missing official source acquisition/hash evidence.");
        foreach (string input in legacyInputs)
        {
            if (!sources.TryGetProperty(input, out JsonElement evidence) || evidence.ValueKind != JsonValueKind.Object)
                throw new InvalidDataException($"Tatoeba provenance manifest is missing sources.{input} evidence.");
            ValidateOfficialUrl(RequireObjectString(evidence, "url", $"sources.{input}"), input);
            string hash = RequireObjectString(evidence, "sha256", $"sources.{input}");
            if (!IsSha256(hash))
                throw new InvalidDataException($"Tatoeba provenance manifest sources.{input}.sha256 is invalid.");
            if (!evidence.TryGetProperty("bytes", out JsonElement bytes) || !bytes.TryGetInt64(out long byteCount) || byteCount <= 0)
                throw new InvalidDataException($"Tatoeba provenance manifest sources.{input}.bytes is missing or invalid.");
        }

        if (!root.TryGetProperty("pair_count", out JsonElement legacyPairCount) ||
            !legacyPairCount.TryGetInt32(out int legacyPairs) || legacyPairs <= 0)
        {
            throw new InvalidDataException("Tatoeba legacy provenance manifest contains no positive pair_count.");
        }
        string selectionRule = RequireString(root, "selection_rule");
        if (requireAttributionPolicy && !selectionRule.Contains("owner", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Attributed Tatoeba legacy provenance selection_rule does not document owner attribution retention.");
    }

    private static void ValidateOfficialUrl(string urlText, string input)
    {
        if (!Uri.TryCreate(urlText, UriKind.Absolute, out Uri? uri) ||
            !string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(uri.Host, "downloads.tatoeba.org", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException($"Tatoeba provenance manifest {input} acquisition URL is not an official HTTPS downloads.tatoeba.org URL.");
        }
    }

    private static string RequireSha256(JsonElement root, string propertyName)
    {
        string value = RequireString(root, propertyName).Trim();
        if (!IsSha256(value))
            throw new InvalidDataException($"Tatoeba provenance manifest contains an invalid {propertyName} value.");
        return value;
    }

    private static bool IsSha256(string value) => value.Length == 64 && value.All(Uri.IsHexDigit);

    private static string RequireObjectString(JsonElement root, string propertyName, string objectName)
    {
        if (!root.TryGetProperty(propertyName, out JsonElement element) || element.ValueKind != JsonValueKind.String)
            throw new InvalidDataException($"Tatoeba provenance manifest is missing {objectName}.{propertyName}.");
        string? value = element.GetString();
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"Tatoeba provenance manifest contains blank {objectName}.{propertyName}.");
        return value;
    }

    private static string RequireString(JsonElement root, string propertyName)
    {
        if (!root.TryGetProperty(propertyName, out JsonElement element) || element.ValueKind != JsonValueKind.String)
            throw new InvalidDataException($"Tatoeba provenance manifest is missing {propertyName}.");
        string? value = element.GetString();
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"Tatoeba provenance manifest contains a blank {propertyName}.");
        return value;
    }
}

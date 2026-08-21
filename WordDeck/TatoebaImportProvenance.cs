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

            string licenseFilter = RequireString(root, "license_filter");
            string expectedOutputHash = RequireString(root, "output_sha256").Trim();
            if (expectedOutputHash.Length != 64 || expectedOutputHash.Any(ch => !Uri.IsHexDigit(ch)))
                throw new InvalidDataException("Tatoeba provenance manifest contains an invalid output_sha256 value.");

            using FileStream stream = File.OpenRead(fullPairPath);
            string actualHash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
            if (!string.Equals(actualHash, expectedOutputHash, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Tatoeba provenance manifest SHA-256 does not match the selected pair TSV.");

            if (string.Equals(licenseFilter, VerifiedCc0Filter, StringComparison.Ordinal))
            {
                string provenance =
                    "Tatoeba official weekly EN-UA exports filtered by WordDeck so BOTH English and Ukrainian sentence IDs are independently present in the official CC0 sentence exports. Upstream sentence IDs are preserved; adjacent manifest SHA-256 was verified against this pair TSV.";
                return new TatoebaImportMetadata(provenance, "CC0 1.0", true);
            }

            if (string.Equals(licenseFilter, VerifiedCcByFilter, StringComparison.Ordinal))
            {
                string declaredLicense = RequireString(root, "license");
                if (!string.Equals(declaredLicense, "CC BY 2.0 FR", StringComparison.Ordinal))
                    throw new InvalidDataException("Attributed Tatoeba manifest does not declare the expected CC BY 2.0 FR license.");

                string provenance =
                    "Tatoeba official weekly detailed EN-UA sentence exports linked by upstream sentence IDs. WordDeck retained a nonblank Tatoeba owner username for BOTH sentence sides and verified the adjacent manifest SHA-256 against this pair TSV. Per-sentence author attribution is embedded in each SentenceRecord.Source.";
                return new TatoebaImportMetadata(provenance, "CC BY 2.0 FR", false, true);
            }

            throw new InvalidDataException("Tatoeba provenance manifest uses an unapproved or unknown license_filter. Refusing to build a redistributable SentencePack.");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("Tatoeba provenance manifest is malformed JSON.", ex);
        }
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

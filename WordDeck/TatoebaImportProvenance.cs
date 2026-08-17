using System.Security.Cryptography;
using System.Text.Json;

namespace WordDeck;

internal sealed record TatoebaImportMetadata(string Provenance, string License, bool VerifiedCc0Manifest);

internal static class TatoebaImportProvenance
{
    private const string VerifiedCc0Filter = "CC0 1.0 on BOTH sentence sides";

    public static TatoebaImportMetadata Resolve(string pairTsvPath)
    {
        string fallbackProvenance =
            "Tatoeba EN-UA sentence-pair export; built by WordDeck development importer. Upstream sentence and translation IDs are preserved per record.";
        string fallbackLicense =
            "CC BY 2.0 FR; verify the selected upstream export/subset before redistribution and preserve attribution.";

        string manifestPath = pairTsvPath + ".manifest.json";
        if (!File.Exists(manifestPath))
            return new TatoebaImportMetadata(fallbackProvenance, fallbackLicense, false);

        try
        {
            using JsonDocument document = JsonDocument.Parse(File.ReadAllText(manifestPath));
            JsonElement root = document.RootElement;
            string? licenseFilter = root.TryGetProperty("license_filter", out JsonElement filterElement)
                ? filterElement.GetString()
                : null;
            string? expectedOutputHash = root.TryGetProperty("output_sha256", out JsonElement hashElement)
                ? hashElement.GetString()
                : null;

            if (!string.Equals(licenseFilter, VerifiedCc0Filter, StringComparison.Ordinal) ||
                string.IsNullOrWhiteSpace(expectedOutputHash))
                return new TatoebaImportMetadata(fallbackProvenance, fallbackLicense, false);

            using FileStream stream = File.OpenRead(pairTsvPath);
            string actualHash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
            if (!string.Equals(actualHash, expectedOutputHash.Trim(), StringComparison.OrdinalIgnoreCase))
                return new TatoebaImportMetadata(fallbackProvenance, fallbackLicense, false);

            string provenance =
                "Tatoeba official weekly EN-UA exports filtered by WordDeck so BOTH English and Ukrainian sentence IDs are independently present in the official CC0 sentence exports. Upstream sentence IDs are preserved; adjacent manifest SHA-256 was verified against this pair TSV.";
            return new TatoebaImportMetadata(provenance, "CC0 1.0", true);
        }
        catch (JsonException)
        {
            return new TatoebaImportMetadata(fallbackProvenance, fallbackLicense, false);
        }
        catch (IOException)
        {
            return new TatoebaImportMetadata(fallbackProvenance, fallbackLicense, false);
        }
    }
}

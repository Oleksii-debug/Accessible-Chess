namespace WordDeck;

internal sealed record SentencePackReleaseReadiness(
    bool Ready,
    SentencePackProductDescriptor? Descriptor,
    IReadOnlyList<string> Blockers,
    string AttributionText)
{
    public string Status => Ready
        ? "SentencePack data is structurally, legally and provenance-ready for product release."
        : "SentencePack is not release-ready: " + string.Join("; ", Blockers);
}

internal static class SentencePackReleaseReadinessService
{
    public static SentencePackReleaseReadiness Evaluate(
        SentencePack pack,
        string sourceIdentity,
        string derivativeIdentity,
        bool declaredSynthetic,
        string? attributionText)
    {
        ArgumentNullException.ThrowIfNull(pack);
        var blockers = new List<string>();

        try
        {
            SentencePackStructuralLimits.Validate(pack);
            SentencePackLicenseValidator.ValidateForInstallation(pack);
        }
        catch (Exception ex) when (ex is InvalidDataException or ArgumentException)
        {
            blockers.Add("technical/legal validation failed: " + ex.Message);
        }

        if (declaredSynthetic)
            blockers.Add("the pack is explicitly synthetic/test data");
        if (string.IsNullOrWhiteSpace(sourceIdentity))
            blockers.Add("source content identity is missing");
        if (string.IsNullOrWhiteSpace(derivativeIdentity))
            blockers.Add("installed/derivative content identity is missing");

        string attribution = (attributionText ?? string.Empty).Trim();
        bool requiresAttribution = pack.License.Contains("BY", StringComparison.OrdinalIgnoreCase);
        if (requiresAttribution && attribution.Length == 0)
            blockers.Add("the declared license requires an attribution surface, but release attribution text is missing");
        if (attribution.Length > 16_384)
            blockers.Add("release attribution text exceeds the bounded product contract");
        if (attribution.IndexOfAny(new[] { '\0' }) >= 0)
            blockers.Add("release attribution text contains invalid control data");

        SentencePackProductDescriptor? descriptor = null;
        if (blockers.Count == 0)
        {
            descriptor = new SentencePackProductDescriptor(
                pack.PackId,
                pack.Provenance,
                pack.License,
                pack.SentenceCount,
                sourceIdentity.Trim(),
                derivativeIdentity.Trim(),
                IsSynthetic: false);
            try { descriptor.ValidateForRelease(); }
            catch (InvalidDataException ex) { blockers.Add(ex.Message); descriptor = null; }
        }

        return new SentencePackReleaseReadiness(blockers.Count == 0, descriptor, blockers.ToArray(), attribution);
    }
}

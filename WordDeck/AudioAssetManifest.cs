using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace WordDeck;

/// <summary>
/// Stable content-type identifiers for offline WordDeck audio assets.
/// Keep these values presentation-neutral so WinForms and future clients can
/// consume the same manifest without owning audio-generation details.
/// </summary>
internal static class AudioAssetKinds
{
    public const string Word = "word";
    public const string Sentence = "sentence";
    public const string Dialogue = "dialogue";
    public const string Story = "story";
    public const string ListeningPassage = "listening-passage";

    public static readonly IReadOnlySet<string> Supported = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        Word,
        Sentence,
        Dialogue,
        Story,
        ListeningPassage
    };
}

internal static class AudioProductionKinds
{
    public const string Human = "human";
    public const string Tts = "tts";

    public static readonly IReadOnlySet<string> Supported = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        Human,
        Tts
    };
}

/// <summary>
/// Versioned, offline-only asset inventory. The manifest contains provenance
/// and integrity metadata only; it never stores credentials and never fetches
/// audio from the network.
/// </summary>
internal sealed class AudioAssetManifest
{
    public const string CurrentSchema = "worddeck-audio-assets-v1";

    [JsonPropertyName("schema")]
    public string Schema { get; set; } = CurrentSchema;

    [JsonPropertyName("pack_id")]
    public string PackId { get; set; } = string.Empty;

    [JsonPropertyName("pack_version")]
    public string PackVersion { get; set; } = string.Empty;

    [JsonPropertyName("assets")]
    public List<AudioAssetRecord> Assets { get; set; } = new();
}

internal sealed class AudioAssetRecord
{
    [JsonPropertyName("asset_id")]
    public string AssetId { get; set; } = string.Empty;

    [JsonPropertyName("text_id")]
    public string TextId { get; set; } = string.Empty;

    [JsonPropertyName("content_type")]
    public string ContentType { get; set; } = string.Empty;

    [JsonPropertyName("speaker")]
    public string Speaker { get; set; } = string.Empty;

    [JsonPropertyName("accent")]
    public string Accent { get; set; } = string.Empty;

    [JsonPropertyName("production")]
    public string Production { get; set; } = string.Empty;

    [JsonPropertyName("speed")]
    public double Speed { get; set; }

    [JsonPropertyName("level")]
    public string Level { get; set; } = string.Empty;

    [JsonPropertyName("license")]
    public string License { get; set; } = string.Empty;

    [JsonPropertyName("source")]
    public string Source { get; set; } = string.Empty;

    [JsonPropertyName("hash")]
    public string Hash { get; set; } = string.Empty;

    [JsonPropertyName("duration_ms")]
    public long DurationMs { get; set; }

    [JsonPropertyName("pack_version")]
    public string PackVersion { get; set; } = string.Empty;

    // Required operational metadata. Asset IDs identify records; this path
    // identifies the corresponding local file within the pack root.
    [JsonPropertyName("relative_path")]
    public string RelativePath { get; set; } = string.Empty;
}

internal static class AudioAssetManifestJson
{
    private const long MaxManifestBytes = 32L * 1024 * 1024;

    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = false,
        AllowTrailingCommas = false,
        ReadCommentHandling = JsonCommentHandling.Disallow,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        WriteIndented = true
    };

    public static AudioAssetManifest Load(string json)
    {
        if (string.IsNullOrWhiteSpace(json))
            throw new InvalidDataException("Audio asset manifest is empty.");

        AudioAssetManifest manifest;
        try
        {
            manifest = JsonSerializer.Deserialize<AudioAssetManifest>(json, Options)
                ?? throw new InvalidDataException("Audio asset manifest is empty.");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException($"Audio asset manifest JSON is invalid: {ex.Message}", ex);
        }

        AudioAssetManifestValidator.Validate(manifest);
        return manifest;
    }

    public static AudioAssetManifest LoadFile(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        var info = new FileInfo(path);
        if (!info.Exists)
            throw new FileNotFoundException("Audio asset manifest was not found.", path);
        if (info.Length > MaxManifestBytes)
            throw new InvalidDataException($"Audio asset manifest is too large ({info.Length} bytes). Maximum is {MaxManifestBytes} bytes.");
        return Load(File.ReadAllText(info.FullName));
    }

    public static string Serialize(AudioAssetManifest manifest)
    {
        AudioAssetManifestValidator.Validate(manifest);
        return JsonSerializer.Serialize(manifest, Options) + Environment.NewLine;
    }
}

internal static class AudioAssetManifestValidator
{
    private static readonly Regex HashPattern = new("^sha256:[0-9a-fA-F]{64}$", RegexOptions.CultureInvariant | RegexOptions.Compiled);

    public static void Validate(AudioAssetManifest manifest)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        if (!string.Equals(manifest.Schema, AudioAssetManifest.CurrentSchema, StringComparison.Ordinal))
            throw new InvalidDataException($"Unsupported audio manifest schema '{manifest.Schema}'. Expected '{AudioAssetManifest.CurrentSchema}'.");
        RequireText(manifest.PackId, "pack_id");
        RequireText(manifest.PackVersion, "pack_version");
        if (manifest.Assets is null)
            throw new InvalidDataException("Audio asset manifest assets collection is missing.");

        var assetIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (AudioAssetRecord asset in manifest.Assets)
        {
            if (asset is null)
                throw new InvalidDataException("Audio asset manifest contains a null asset record.");
            ValidateAsset(manifest, asset, assetIds);
        }
    }

    private static void ValidateAsset(AudioAssetManifest manifest, AudioAssetRecord asset, HashSet<string> assetIds)
    {
        RequireText(asset.AssetId, "asset_id");
        RequireText(asset.TextId, $"{asset.AssetId}.text_id");
        RequireText(asset.ContentType, $"{asset.AssetId}.content_type");
        RequireText(asset.Speaker, $"{asset.AssetId}.speaker");
        RequireText(asset.Accent, $"{asset.AssetId}.accent");
        RequireText(asset.Production, $"{asset.AssetId}.production");
        RequireText(asset.Level, $"{asset.AssetId}.level");
        RequireText(asset.License, $"{asset.AssetId}.license");
        RequireText(asset.Source, $"{asset.AssetId}.source");
        RequireText(asset.Hash, $"{asset.AssetId}.hash");
        RequireText(asset.PackVersion, $"{asset.AssetId}.pack_version");
        RequireText(asset.RelativePath, $"{asset.AssetId}.relative_path");

        if (!assetIds.Add(asset.AssetId))
            throw new InvalidDataException($"Duplicate audio asset ID '{asset.AssetId}'.");
        if (!AudioAssetKinds.Supported.Contains(asset.ContentType))
            throw new InvalidDataException($"Audio asset '{asset.AssetId}' has unsupported content_type '{asset.ContentType}'.");
        if (!AudioProductionKinds.Supported.Contains(asset.Production))
            throw new InvalidDataException($"Audio asset '{asset.AssetId}' must declare production as human or tts.");
        if (!double.IsFinite(asset.Speed) || asset.Speed is < 0.25 or > 4.0)
            throw new InvalidDataException($"Audio asset '{asset.AssetId}' has invalid speed {asset.Speed}. Expected 0.25..4.0.");
        if (asset.DurationMs <= 0)
            throw new InvalidDataException($"Audio asset '{asset.AssetId}' must have a positive duration_ms.");
        if (!HashPattern.IsMatch(asset.Hash))
            throw new InvalidDataException($"Audio asset '{asset.AssetId}' must use hash format sha256:<64 hexadecimal characters>.");
        if (!string.Equals(asset.PackVersion, manifest.PackVersion, StringComparison.Ordinal))
            throw new InvalidDataException($"Audio asset '{asset.AssetId}' pack_version '{asset.PackVersion}' does not match manifest pack_version '{manifest.PackVersion}'.");

        ValidateRelativePath(asset.AssetId, asset.RelativePath);
    }

    private static void RequireText(string? value, string field)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"Audio manifest field '{field}' must not be blank.");
        if (value.Length > 2048)
            throw new InvalidDataException($"Audio manifest field '{field}' is unreasonably long.");
        if (value.Any(char.IsControl))
            throw new InvalidDataException($"Audio manifest field '{field}' contains control characters.");
    }

    private static void ValidateRelativePath(string assetId, string relativePath)
    {
        if (Path.IsPathRooted(relativePath) || relativePath.Contains(':'))
            throw new InvalidDataException($"Audio asset '{assetId}' relative_path must stay inside the pack root.");

        string[] parts = relativePath.Replace('\\', '/').Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 0 || parts.Any(part => part is "." or ".."))
            throw new InvalidDataException($"Audio asset '{assetId}' relative_path is unsafe.");
    }

    public static string ResolveAssetPath(string packRoot, AudioAssetRecord asset)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(packRoot);
        ArgumentNullException.ThrowIfNull(asset);
        ValidateRelativePath(asset.AssetId, asset.RelativePath);

        string root = Path.GetFullPath(packRoot);
        string relative = asset.RelativePath.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
        string candidate = Path.GetFullPath(Path.Combine(root, relative));
        string rootPrefix = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
        StringComparison comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
        if (!candidate.StartsWith(rootPrefix, comparison))
            throw new InvalidDataException($"Audio asset '{asset.AssetId}' resolves outside the pack root.");
        return candidate;
    }

    public static string ComputeHashDescriptor(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        using FileStream stream = File.OpenRead(path);
        byte[] digest = SHA256.HashData(stream);
        return "sha256:" + Convert.ToHexString(digest).ToLowerInvariant();
    }

    public static int VerifyAllFiles(AudioAssetManifest manifest, string packRoot)
    {
        Validate(manifest);
        int verified = 0;
        foreach (AudioAssetRecord asset in manifest.Assets)
        {
            string path = ResolveAssetPath(packRoot, asset);
            if (!File.Exists(path))
                throw new InvalidDataException($"Audio asset '{asset.AssetId}' is missing local file '{asset.RelativePath}'.");
            string actual = ComputeHashDescriptor(path);
            if (!string.Equals(actual, asset.Hash, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"Audio asset '{asset.AssetId}' failed SHA-256 integrity verification.");
            verified++;
        }
        return verified;
    }
}

/// <summary>
/// Immutable lookup facade used by learning modes. Lookup is by stable asset ID
/// or by canonical text ID plus content type; no UI or network dependency is
/// introduced here.
/// </summary>
internal sealed class AudioAssetCatalog
{
    private readonly AudioAssetManifest _manifest;
    private readonly Dictionary<string, AudioAssetRecord> _byAssetId;
    private readonly Dictionary<string, List<AudioAssetRecord>> _byTextKey;

    public AudioAssetCatalog(AudioAssetManifest manifest)
    {
        AudioAssetManifestValidator.Validate(manifest);
        _manifest = manifest;
        _byAssetId = manifest.Assets.ToDictionary(asset => asset.AssetId, StringComparer.OrdinalIgnoreCase);
        _byTextKey = new Dictionary<string, List<AudioAssetRecord>>(StringComparer.OrdinalIgnoreCase);
        foreach (AudioAssetRecord asset in manifest.Assets)
        {
            string key = MakeTextKey(asset.ContentType, asset.TextId);
            if (!_byTextKey.TryGetValue(key, out List<AudioAssetRecord>? values))
            {
                values = new List<AudioAssetRecord>();
                _byTextKey[key] = values;
            }
            values.Add(asset);
        }
        foreach (List<AudioAssetRecord> values in _byTextKey.Values)
            values.Sort((left, right) => StringComparer.OrdinalIgnoreCase.Compare(left.AssetId, right.AssetId));
    }

    public string PackId => _manifest.PackId;
    public string PackVersion => _manifest.PackVersion;
    public IReadOnlyList<AudioAssetRecord> Assets => _manifest.Assets;

    public bool TryGetAsset(string assetId, out AudioAssetRecord? asset) => _byAssetId.TryGetValue(assetId, out asset);

    public IReadOnlyList<AudioAssetRecord> FindByText(string contentType, string textId)
    {
        if (!AudioAssetKinds.Supported.Contains(contentType))
            throw new ArgumentOutOfRangeException(nameof(contentType), contentType, "Unsupported audio content type.");
        ArgumentException.ThrowIfNullOrWhiteSpace(textId);
        return _byTextKey.TryGetValue(MakeTextKey(contentType, textId), out List<AudioAssetRecord>? values)
            ? values
            : Array.Empty<AudioAssetRecord>();
    }

    private static string MakeTextKey(string contentType, string textId) => contentType + "\u001f" + textId;
}

internal static class AudioAssetManifestDiagnostics
{
    public static int Run(string[] args)
    {
        if (args.Length != 3)
        {
            Console.Error.WriteLine("Usage: WordDeck.exe --validate-audio-asset-manifest <manifest.json> <pack-root>");
            return 2;
        }

        try
        {
            AudioAssetManifest manifest = AudioAssetManifestJson.LoadFile(Path.GetFullPath(args[1]));
            int verified = AudioAssetManifestValidator.VerifyAllFiles(manifest, Path.GetFullPath(args[2]));
            string byKind = string.Join(", ", manifest.Assets
                .GroupBy(asset => asset.ContentType, StringComparer.OrdinalIgnoreCase)
                .OrderBy(group => group.Key, StringComparer.OrdinalIgnoreCase)
                .Select(group => $"{group.Key}={group.Count()}"));
            Console.WriteLine($"Audio asset manifest passed: pack={manifest.PackId}; version={manifest.PackVersion}; verified={verified}; {byKind}.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Audio asset manifest validation FAILED: {ex.Message}");
            return 1;
        }
    }
}

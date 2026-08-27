namespace WordDeck;

internal static class AudioAssetManifestSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck-AudioAssetManifest-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            const string packVersion = "1.2.3-test";
            string[] kinds =
            {
                AudioAssetKinds.Word,
                AudioAssetKinds.Sentence,
                AudioAssetKinds.Dialogue,
                AudioAssetKinds.Story,
                AudioAssetKinds.ListeningPassage
            };

            var manifest = new AudioAssetManifest
            {
                PackId = "synthetic-manifest-self-test",
                PackVersion = packVersion
            };

            for (int i = 0; i < kinds.Length; i++)
            {
                string relative = Path.Combine(kinds[i], $"asset-{i + 1}.mp3").Replace('\\', '/');
                string path = Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                File.WriteAllBytes(path, Enumerable.Range(0, 1024 + i).Select(value => (byte)((value + i) % 251)).ToArray());
                manifest.Assets.Add(new AudioAssetRecord
                {
                    AssetId = $"asset-{i + 1}",
                    TextId = $"text-{i + 1}",
                    ContentType = kinds[i],
                    Speaker = i == 2 ? "synthetic-cast-a-b" : $"synthetic-speaker-{i + 1}",
                    Accent = "en-GB",
                    Production = i % 2 == 0 ? AudioProductionKinds.Tts : AudioProductionKinds.Human,
                    Speed = 1.0,
                    Level = i switch { 0 => "A1", 1 => "A2", 2 => "B1", 3 => "B2", _ => "C1" },
                    License = "synthetic-test-only",
                    Source = "generated-in-memory-self-test-fixture",
                    Hash = AudioAssetManifestValidator.ComputeHashDescriptor(path),
                    DurationMs = 900 + (i * 100),
                    PackVersion = packVersion,
                    RelativePath = relative
                });
            }

            AudioAssetManifestValidator.Validate(manifest);
            string json = AudioAssetManifestJson.Serialize(manifest);
            AudioAssetManifest loaded = AudioAssetManifestJson.Load(json);
            var catalog = new AudioAssetCatalog(loaded);

            Require(catalog.Assets.Count == 5, "Expected five audio content kinds in manifest self-test.");
            foreach (string kind in kinds)
                Require(catalog.Assets.Count(asset => asset.ContentType == kind) == 1, $"Missing content type {kind}.");
            Require(catalog.FindByText(AudioAssetKinds.Dialogue, "text-3").Single().AssetId == "asset-3", "Dialogue stable text lookup failed.");
            Require(catalog.TryGetAsset("ASSET-5", out AudioAssetRecord? found) && found?.ContentType == AudioAssetKinds.ListeningPassage,
                "Case-insensitive stable asset lookup failed.");
            Require(AudioAssetManifestValidator.VerifyAllFiles(loaded, root) == 5, "Manifest file/hash verification did not cover all assets.");

            AudioAssetRecord first = loaded.Assets[0];
            string firstPath = AudioAssetManifestValidator.ResolveAssetPath(root, first);
            File.AppendAllText(firstPath, "tampered");
            ExpectInvalid(() => AudioAssetManifestValidator.VerifyAllFiles(loaded, root), "tampered hash");

            var traversal = Clone(first);
            traversal.AssetId = "unsafe-path";
            traversal.RelativePath = "../outside.mp3";
            var unsafeManifest = NewSingleAsset(packVersion, traversal);
            ExpectInvalid(() => AudioAssetManifestValidator.Validate(unsafeManifest), "path traversal");

            var mismatched = Clone(first);
            mismatched.AssetId = "wrong-version";
            mismatched.PackVersion = "different";
            var mismatchedManifest = NewSingleAsset(packVersion, mismatched);
            ExpectInvalid(() => AudioAssetManifestValidator.Validate(mismatchedManifest), "pack version mismatch");

            var duplicateManifest = new AudioAssetManifest { PackId = "duplicate-test", PackVersion = packVersion };
            AudioAssetRecord duplicateA = Clone(first);
            duplicateA.AssetId = "duplicate-id";
            duplicateA.PackVersion = packVersion;
            AudioAssetRecord duplicateB = Clone(first);
            duplicateB.AssetId = "DUPLICATE-ID";
            duplicateB.PackVersion = packVersion;
            duplicateManifest.Assets.Add(duplicateA);
            duplicateManifest.Assets.Add(duplicateB);
            ExpectInvalid(() => AudioAssetManifestValidator.Validate(duplicateManifest), "duplicate asset IDs");

            Console.WriteLine("Audio asset manifest self-test passed: five content types, strict schema/provenance, safe paths, version matching, stable lookup and SHA-256 tamper detection validated.");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static AudioAssetManifest NewSingleAsset(string version, AudioAssetRecord asset)
    {
        var manifest = new AudioAssetManifest { PackId = "single-test", PackVersion = version };
        manifest.Assets.Add(asset);
        return manifest;
    }

    private static AudioAssetRecord Clone(AudioAssetRecord source) => new()
    {
        AssetId = source.AssetId,
        TextId = source.TextId,
        ContentType = source.ContentType,
        Speaker = source.Speaker,
        Accent = source.Accent,
        Production = source.Production,
        Speed = source.Speed,
        Level = source.Level,
        License = source.License,
        Source = source.Source,
        Hash = source.Hash,
        DurationMs = source.DurationMs,
        PackVersion = source.PackVersion,
        RelativePath = source.RelativePath
    };

    private static void ExpectInvalid(Action action, string label)
    {
        try
        {
            action();
        }
        catch (InvalidDataException)
        {
            return;
        }
        throw new InvalidDataException($"Audio asset manifest self-test failed: {label} was accepted.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}

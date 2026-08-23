using Microsoft.Data.Sqlite;
using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextCorpusCoverageEvidenceSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextCorpusCoverageEvidenceSelfTest.Run();
    }
}

internal static class ContextCorpusCoverageEvidenceSelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        var lexicon = new ContextTargetLexicon(dictionary);
        Require(dictionary.Entries.Count == 5446, "embedded Oxford universe is not 5,446 entries");

        (DictionaryEntry homographA, DictionaryEntry homographB) = FindHomographPair(dictionary, lexicon);
        DictionaryEntry[] unique = FindUniqueLexicalEntries(dictionary, lexicon, 8);

        string root = Path.Combine(Path.GetTempPath(), "WordDeck R4d corpus evidence Київ " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        string databasePath = Path.Combine(root, "fixture sentence corpus.sqlite");
        try
        {
            SentencePack pack = BuildPack(
                "r4d-coverage-evidence-fixture",
                MakeSentence("homograph-pair", new[] { homographA, homographB, unique[0] }, "A2"),
                MakeSentence("natural-triple", new[] { unique[1], unique[2], unique[3] }, "B1"),
                MakeSentence("single-only", new[] { unique[4] }, "A1"));
            SentencePackSqlitePrototype.Build(databasePath, pack);
            SqliteConnection.ClearAllPools();

            bool syntheticRejected = false;
            try
            {
                _ = ContextCorpusCoverageEvidenceBuilder.Build(
                    databasePath,
                    dictionary,
                    new ContextCorpusCoverageMeasurementRequest(ContextCorpusKind.SyntheticFixture));
            }
            catch (InvalidDataException) { syntheticRejected = true; }
            Require(syntheticRejected, "synthetic corpus evidence did not fail closed without explicit test opt-in");

            var syntheticRequest = new ContextCorpusCoverageMeasurementRequest(
                ContextCorpusKind.SyntheticFixture,
                AllowSyntheticFixtures: true);
            ContextCorpusCoverageEvidenceDocument first = ContextCorpusCoverageEvidenceBuilder.Build(databasePath, dictionary, syntheticRequest);
            ContextCorpusCoverageEvidenceDocument second = ContextCorpusCoverageEvidenceBuilder.Build(databasePath, dictionary, syntheticRequest);

            Require(ContextCorpusCoverageEvidenceBuilder.VerifyEvidenceDigest(first), "evidence digest did not verify");
            Require(first.EvidenceDigestSha256 == second.EvidenceDigestSha256, "identical input produced a different deterministic evidence digest");
            Require(first.ToCanonicalJson() == second.ToCanonicalJson(), "identical input produced different canonical JSON");
            Require(!first.Payload.CanSupportRealCorpusCoverageClaim, "synthetic fixture was eligible for a real-corpus coverage claim");
            Require(!first.Payload.RedistributionApproved, "coverage evidence incorrectly approved redistribution");
            Require(first.Payload.DictionaryEntryCount == 5446 && first.Payload.ExactOxford5446Verified, "evidence was not bound to the exact 5,446-entry dictionary universe");
            Require(first.Payload.OneTarget.CoveredEntryCount == 7, $"expected 7 one-target fixture IDs, got {first.Payload.OneTarget.CoveredEntryCount}");
            Require(first.Payload.TwoTarget.CoveredEntryCount == 6, $"expected 6 natural two-target fixture IDs, got {first.Payload.TwoTarget.CoveredEntryCount}");
            Require(first.Payload.ThreeTarget.CoveredEntryCount == 3, $"expected 3 natural three-target fixture IDs, got {first.Payload.ThreeTarget.CoveredEntryCount}");
            Require(!first.Payload.ThreeTarget.CoveredEntryIds.Contains(homographA.Id, StringComparer.OrdinalIgnoreCase) &&
                    !first.Payload.ThreeTarget.CoveredEntryIds.Contains(homographB.Id, StringComparer.OrdinalIgnoreCase) &&
                    !first.Payload.ThreeTarget.CoveredEntryIds.Contains(unique[0].Id, StringComparer.OrdinalIgnoreCase),
                "same-written-form stable IDs inflated a three-target coverage claim");

            foreach (ContextCoverageDepthEvidence depth in new[] { first.Payload.OneTarget, first.Payload.TwoTarget, first.Payload.ThreeTarget })
            {
                Require(depth.ScopeEntryCount == 5446, $"{depth.RequiredTargetCount}-target evidence did not use all 5,446 stable IDs");
                Require(depth.CoveredEntryCount + depth.UncoveredEntryCount == 5446, $"{depth.RequiredTargetCount}-target evidence did not exactly partition 5,446 IDs");
                Require(IsOrdinalSorted(depth.CoveredEntryIds), $"{depth.RequiredTargetCount}-target covered IDs are not deterministically sorted");
                Require(IsOrdinalSorted(depth.UncoveredEntryIds), $"{depth.RequiredTargetCount}-target gap IDs are not deterministically sorted");
                Require(depth.CoveredEntryIds.Intersect(depth.UncoveredEntryIds, StringComparer.OrdinalIgnoreCase).Count() == 0,
                    $"{depth.RequiredTargetCount}-target evidence overlaps covered and uncovered IDs");
            }

            bool missingIdentityRejected = false;
            try
            {
                _ = ContextCorpusCoverageEvidenceBuilder.Build(
                    databasePath,
                    dictionary,
                    new ContextCorpusCoverageMeasurementRequest(ContextCorpusKind.RealCorpus));
            }
            catch (InvalidDataException) { missingIdentityRejected = true; }
            Require(missingIdentityRejected, "real corpus measurement accepted an unbound SQLite artifact");

            string exactSha = ContextCorpusCoverageEvidenceBuilder.ComputeDatabaseSha256(databasePath);
            bool wrongIdentityRejected = false;
            try
            {
                _ = ContextCorpusCoverageEvidenceBuilder.Build(
                    databasePath,
                    dictionary,
                    new ContextCorpusCoverageMeasurementRequest(
                        ContextCorpusKind.RealCorpus,
                        new string('0', 64),
                        pack.PackId));
            }
            catch (InvalidDataException) { wrongIdentityRejected = true; }
            Require(wrongIdentityRejected, "real corpus measurement accepted the wrong expected SQLite SHA-256");

            ContextCorpusCoverageEvidenceDocument exactIdentity = ContextCorpusCoverageEvidenceBuilder.Build(
                databasePath,
                dictionary,
                new ContextCorpusCoverageMeasurementRequest(
                    ContextCorpusKind.RealCorpus,
                    exactSha,
                    pack.PackId));
            Require(exactIdentity.Payload.ExactDatabaseIdentityVerified, "exact real-corpus-shaped identity was not verified in the contract test");
            Require(exactIdentity.Payload.CanSupportRealCorpusCoverageClaim, "exact real-corpus-shaped identity did not become coverage-evidence eligible");
            Require(!exactIdentity.Payload.RedistributionApproved, "exact coverage identity incorrectly became redistribution approval");

            ContextCorpusCoverageEvidenceDocument local = ContextCorpusCoverageEvidenceBuilder.Build(
                databasePath,
                dictionary,
                new ContextCorpusCoverageMeasurementRequest(ContextCorpusKind.LocalUserText));
            Require(local.Payload.PrivacyLocalOnly, "local user-text evidence lost privacy-local status");
            Require(!local.Payload.CanSupportRealCorpusCoverageClaim, "local user-text evidence became public real-corpus evidence");

            string mutatedPath = Path.Combine(root, "mutated corpus.sqlite");
            File.Copy(databasePath, mutatedPath, overwrite: true);
            using (FileStream append = new(mutatedPath, FileMode.Append, FileAccess.Write, FileShare.None)) append.WriteByte(0);
            string mutatedSha = ContextCorpusCoverageEvidenceBuilder.ComputeDatabaseSha256(mutatedPath);
            Require(mutatedSha != exactSha, "database byte mutation did not change the bound SQLite SHA-256");
            ContextCorpusCoverageEvidencePayload mutatedPayload = first.Payload with
            {
                DatabaseSha256 = mutatedSha,
                DatabaseBytes = new FileInfo(mutatedPath).Length
            };
            Require(ContextCorpusCoverageEvidenceBuilder.ComputeEvidenceDigest(mutatedPayload) != first.EvidenceDigestSha256,
                "database identity mutation did not change the evidence payload digest");

            string blankProvenancePath = Path.Combine(root, "blank provenance.sqlite");
            File.Copy(databasePath, blankProvenancePath, overwrite: true);
            using (var connection = new SqliteConnection(new SqliteConnectionStringBuilder
            {
                DataSource = blankProvenancePath,
                Mode = SqliteOpenMode.ReadWrite,
                Pooling = false
            }.ToString()))
            {
                connection.Open();
                using SqliteCommand command = connection.CreateCommand();
                command.CommandText = "UPDATE metadata SET value = '' WHERE key = 'provenance';";
                command.ExecuteNonQuery();
            }
            SqliteConnection.ClearAllPools();
            bool blankProvenanceRejected = false;
            try
            {
                _ = ContextCorpusCoverageEvidenceBuilder.Build(
                    blankProvenancePath,
                    dictionary,
                    new ContextCorpusCoverageMeasurementRequest(ContextCorpusKind.LocalUserText));
            }
            catch (InvalidDataException) { blankProvenanceRejected = true; }
            Require(blankProvenanceRejected, "blank SQLite provenance was accepted as corpus evidence");

            Console.WriteLine(
                $"Context R4d corpus evidence self-test PASS: exact 5446 lexical coverage one={first.Payload.OneTarget.CoveredEntryCount}, " +
                $"two={first.Payload.TwoTarget.CoveredEntryCount}, three={first.Payload.ThreeTarget.CoveredEntryCount}; " +
                "synthetic/local/real identity boundaries, deterministic JSON/digest, mutation detection and homograph safety verified.");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static SentencePack BuildPack(string packId, params SentenceRecord[] sentences)
    {
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "WordDeck R4d deterministic coverage-evidence contract fixture; test only",
            License = "CC0-1.0",
            Sentences = sentences.ToList()
        };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord MakeSentence(string id, IReadOnlyList<DictionaryEntry> targets, string difficulty)
    {
        string english = "Context coverage evidence test sentence.";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = "Тестове речення для перевірки покриття.",
            Source = "WordDeck R4d synthetic contract fixture",
            License = "CC0-1.0",
            Tokens = tokens,
            Lemmas = tokens.ToList(),
            TargetEntryIds = targets.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).ToList(),
            EntryLevels = targets
                .GroupBy(entry => entry.Id, StringComparer.OrdinalIgnoreCase)
                .ToDictionary(group => group.Key, group => group.First().Level, StringComparer.OrdinalIgnoreCase),
            DifficultyLevel = difficulty,
            OffListTokenCount = 0
        };
    }

    private static (DictionaryEntry A, DictionaryEntry B) FindHomographPair(DictionaryPackage dictionary, ContextTargetLexicon lexicon)
    {
        IGrouping<string, DictionaryEntry>? group = dictionary.Entries
            .GroupBy(entry => lexicon.LexicalKeyFor(entry.Id), StringComparer.OrdinalIgnoreCase)
            .FirstOrDefault(items => items.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() >= 2);
        if (group is null)
            throw new InvalidOperationException("R4d corpus evidence self-test expected at least one same-written-form Oxford stable-ID group.");
        DictionaryEntry[] entries = group.Take(2).ToArray();
        return (entries[0], entries[1]);
    }

    private static DictionaryEntry[] FindUniqueLexicalEntries(DictionaryPackage dictionary, ContextTargetLexicon lexicon, int count)
    {
        var keyCounts = dictionary.Entries
            .GroupBy(entry => lexicon.LexicalKeyFor(entry.Id), StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.Count(), StringComparer.OrdinalIgnoreCase);
        DictionaryEntry[] result = dictionary.Entries
            .Where(entry => keyCounts[lexicon.LexicalKeyFor(entry.Id)] == 1)
            .Take(count)
            .ToArray();
        Require(result.Length == count, $"could not find {count} unique lexical entries for R4d evidence test");
        return result;
    }

    private static bool IsOrdinalSorted(IReadOnlyList<string> values) =>
        values.SequenceEqual(values.OrderBy(value => value, StringComparer.Ordinal));

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Context R4d corpus evidence self-test failed: " + message);
    }
}

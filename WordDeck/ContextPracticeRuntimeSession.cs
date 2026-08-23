namespace WordDeck;

internal sealed record ContextRuntimeRequest(
    IReadOnlyCollection<string> ScopeEntryIds,
    ContextStudyPoolPreset PoolPreset,
    int TargetCount,
    IReadOnlyDictionary<string, SentenceTargetStats>? SentenceStats = null,
    IReadOnlyCollection<string>? RecentSentenceIds = null,
    int MaxCardsPerAnchor = 12,
    int CandidateLimit = 256,
    int MaxAnchorAttempts = 40);

internal sealed record ContextRuntimeResult(
    ContextStudyPoolSelection StudyPool,
    ContextVocabularySnapshot VocabularySnapshot,
    ContextCoverageEvidence Coverage,
    IReadOnlyList<string> UnresolvedStableEntryIds,
    ContextPracticeCard? Card,
    string? AnchorEntryId,
    string Explanation);

internal static class InstalledContextSourceFactory
{
    public static IContextSentenceSource Create(
        InstalledSentencePack installed,
        ContextCorpusKind kind = ContextCorpusKind.RealCorpus)
    {
        ArgumentNullException.ThrowIfNull(installed);
        if (kind == ContextCorpusKind.LocalUserText)
            throw new InvalidDataException(
                "Installed public SentencePacks cannot be silently reclassified as local user text. Book/text ingestion must attach its own privacy-local source identity and location metadata.");

        if (!string.IsNullOrWhiteSpace(installed.SqlitePath))
            return new ContextSentenceSqliteSource(installed.SqlitePath, kind);

        SentencePack? pack = installed.PortablePack;
        if (pack is null)
        {
            if (string.IsNullOrWhiteSpace(installed.Path) || !File.Exists(installed.Path))
                throw new InvalidDataException("Installed SentencePack has no readable portable or SQLite source.");
            pack = SentencePackIo.Read(installed.Path);
        }

        if (!string.Equals(pack.PackId, installed.PackId, StringComparison.Ordinal) ||
            !string.Equals(pack.License, installed.License, StringComparison.Ordinal) ||
            pack.SentenceCount != installed.SentenceCount)
            throw new InvalidDataException("Installed SentencePack metadata does not match its portable source.");

        var descriptor = new ContextSourceDescriptor(
            pack.PackId,
            kind,
            pack.Provenance,
            pack.License,
            PrivacyLocalOnly: false);
        return new SentenceCorpusContextSource(pack, descriptor);
    }
}

internal sealed class ContextPracticeRuntimeSession
{
    private readonly DictionaryPackage _dictionary;
    private readonly ContextTargetLexicon _lexicon;
    private readonly ContextVocabularySnapshot _vocabulary;
    private readonly IContextSentenceSource _source;
    private readonly ContextProductUseOptions _productOptions;

    public ContextPracticeRuntimeSession(
        DictionaryPackage dictionary,
        AppState recallState,
        SpellingState spellingState,
        IContextSentenceSource source,
        ContextProductUseOptions? productOptions = null)
    {
        _dictionary = dictionary ?? throw new ArgumentNullException(nameof(dictionary));
        _source = source ?? throw new ArgumentNullException(nameof(source));
        _productOptions = productOptions ?? new ContextProductUseOptions();
        ContextPracticeProductFacade.ValidateSourceForProductUse(_source, _productOptions);
        _lexicon = new ContextTargetLexicon(_dictionary);
        _vocabulary = ContextVocabularySnapshotBuilder.Build(_dictionary, recallState, spellingState);
    }

    public ContextRuntimeResult SelectNext(ContextRuntimeRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (request.TargetCount is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(request.TargetCount));
        if (request.MaxCardsPerAnchor is < 1 or > ContextPracticeService.MaxResults)
            throw new ArgumentOutOfRangeException(nameof(request.MaxCardsPerAnchor));
        if (request.CandidateLimit < request.MaxCardsPerAnchor || request.CandidateLimit > ContextPracticeService.MaxCandidateLimit)
            throw new ArgumentOutOfRangeException(nameof(request.CandidateLimit));
        if (request.MaxAnchorAttempts is < 1 or > 200)
            throw new ArgumentOutOfRangeException(nameof(request.MaxAnchorAttempts));

        string[] requestedScope = ContextTargetIds.NormalizeStudyPool(request.ScopeEntryIds);
        if (requestedScope.Length == 0)
            throw new InvalidDataException("Context Practice runtime requires a non-empty study scope.");

        var validIds = new HashSet<string>(
            _dictionary.Entries.Select(entry => ContextTargetIds.NormalizeSingle(entry.Id)),
            StringComparer.OrdinalIgnoreCase);
        string[] validScope = requestedScope.Where(validIds.Contains).ToArray();
        if (validScope.Length == 0)
            throw new InvalidDataException("Context Practice study scope contains no stable IDs from the active dictionary.");
        if (validScope.Length != requestedScope.Length)
            throw new InvalidDataException("Context Practice study scope contains stable IDs outside the active dictionary.");

        IReadOnlyList<string> unresolved = ContextStableIdentityResolution.UnresolvedStableIds(_lexicon, validScope);
        IReadOnlyList<string> resolvedScope = ContextStableIdentityResolution.ResolvedStudyPool(_lexicon, validScope);
        if (resolvedScope.Count == 0)
        {
            throw new InvalidDataException(
                "Context Practice study scope contains only unresolved homographic stable IDs. " +
                "Surface-form corpus evidence cannot choose their POS/sense identity; explicit disambiguating evidence is required before these IDs can become learner-progress targets.");
        }

        string[] ordered = OrderStudyTargets(resolvedScope, request.SentenceStats);
        ContextStudyPoolSelection pool = ContextStudyPoolBuilder.Build(ordered, request.PoolPreset);
        ContextCoverageEvidence coverage = ContextPracticeProductFacade.AnalyzeNaturalCoverage(
            _source,
            _lexicon,
            pool.EntryIds,
            request.TargetCount,
            _productOptions);
        string ambiguityNote = unresolved.Count == 0
            ? string.Empty
            : $" {unresolved.Count} unresolved homographic stable ID(s) were excluded from target selection until POS/sense evidence can disambiguate them.";

        if (coverage.Coverage.CoveredEntryCount == 0)
        {
            return new ContextRuntimeResult(
                pool,
                _vocabulary,
                coverage,
                unresolved,
                null,
                null,
                $"The selected {PoolLabel(pool)} pool has no natural {request.TargetCount}-target coverage in source '{_source.Descriptor.SourceId}'. No sentence was fabricated.{ambiguityNote}");
        }

        var covered = new HashSet<string>(coverage.Coverage.CoveredEntryIds, StringComparer.OrdinalIgnoreCase);
        string[] anchors = pool.EntryIds.Where(covered.Contains).Take(request.MaxAnchorAttempts).ToArray();
        foreach (string anchor in anchors)
        {
            ContextPracticeApplicationResult candidate = ContextPracticeApplicationService.BuildCards(
                _source,
                _lexicon,
                pool.EntryIds,
                new ContextPracticeApplicationRequest(
                    anchor,
                    request.TargetCount,
                    ContextStudyPoolPreset.Full,
                    _vocabulary.Vocabulary,
                    request.RecentSentenceIds,
                    request.MaxCardsPerAnchor,
                    request.CandidateLimit,
                    MaxNaturalTargetSets: Math.Min(ContextNaturalTargetPlanner.MaxPlannedSets, 40)),
                _productOptions);

            ContextPracticeCard? card = candidate.Cards.FirstOrDefault();
            if (card is null)
                continue;

            return new ContextRuntimeResult(
                pool,
                _vocabulary,
                coverage,
                unresolved,
                card,
                anchor,
                $"Natural {request.TargetCount}-target sentence selected from the {PoolLabel(pool)} pool. Difficulty used the learner's real Recall/Spelling vocabulary evidence before CEFR. Source, license and provenance remain attached to the card.{ambiguityNote}");
        }

        return new ContextRuntimeResult(
            pool,
            _vocabulary,
            coverage,
            unresolved,
            null,
            null,
            $"Coverage exists in the {PoolLabel(pool)} pool, but no bounded candidate survived the current ranking/search limits. No sentence was fabricated; increase the bounded search only through an explicit product decision.{ambiguityNote}");
    }

    private string[] OrderStudyTargets(
        IReadOnlyCollection<string> scopeEntryIds,
        IReadOnlyDictionary<string, SentenceTargetStats>? sentenceStats)
    {
        return scopeEntryIds
            .Select(ContextTargetIds.NormalizeSingle)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(id => LearnerMasteryRank(id))
            .ThenByDescending(id => Weakness(sentenceStats is not null && sentenceStats.TryGetValue(id, out SentenceTargetStats? stats) ? stats : null))
            .ThenBy(id => sentenceStats is not null && sentenceStats.TryGetValue(id, out SentenceTargetStats? stats) && stats?.LastReviewedUtc is not null
                ? stats.LastReviewedUtc.Value
                : DateTimeOffset.MinValue)
            .ThenBy(id => id, StringComparer.Ordinal)
            .ToArray();
    }

    private int LearnerMasteryRank(string entryId)
    {
        if (_vocabulary.Vocabulary.IsKnown(entryId)) return 2;
        if (_vocabulary.Vocabulary.IsLearning(entryId)) return 0;
        return 1;
    }

    private static int Weakness(SentenceTargetStats? stats) =>
        stats is null
            ? 1000
            : Math.Max(0, stats.WrongAttempts) * 8 +
              Math.Max(0, stats.ShowAnswerUses) * 6 -
              Math.Max(0, stats.FirstTrySuccesses) * 2 -
              Math.Max(0, stats.CompletedReviews);

    private static string PoolLabel(ContextStudyPoolSelection pool) => pool.Preset switch
    {
        ContextStudyPoolPreset.Thirty => "30-word",
        ContextStudyPoolPreset.Hundred => "100-word",
        ContextStudyPoolPreset.TwoHundred => "200-word",
        ContextStudyPoolPreset.Full => "full",
        _ => "study"
    };
}

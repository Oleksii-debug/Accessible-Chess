using System.Runtime.CompilerServices;

namespace WordDeck;

/// <summary>
/// Cross-level truth from the governed G-A1-06 source. These are the levels at
/// which each atomic node may eventually reach FE/CM/PM across the Complete
/// English/Deep Grammar graph. They are deliberately separate from the smaller
/// evidence contribution ceiling of this A1 module.
/// </summary>
internal sealed record GovernedGrammarCrossLevelNode(
    string AtomicSkillId,
    string FamiliarityExposureLevel,
    string ControlledMasteryLevel,
    string ProductiveMasteryLevel,
    string A106ContributionLevel,
    GovernedGrammarMasteryStage A106HighestContributionStage);

internal static class GovernedGrammarA106MasteryGraph
{
    private static readonly IReadOnlyDictionary<string, GovernedGrammarCrossLevelNode> Nodes =
        new Dictionary<string, GovernedGrammarCrossLevelNode>(StringComparer.OrdinalIgnoreCase)
        {
            ["present.continuous-form"] = new(
                "present.continuous-form",
                FamiliarityExposureLevel: "A1",
                ControlledMasteryLevel: "A1",
                ProductiveMasteryLevel: "A1",
                A106ContributionLevel: "A1",
                A106HighestContributionStage: GovernedGrammarMasteryStage.ProductiveMastery),
            ["present.continuous-use"] = new(
                "present.continuous-use",
                FamiliarityExposureLevel: "A1",
                ControlledMasteryLevel: "A1",
                ProductiveMasteryLevel: "A2",
                A106ContributionLevel: "A1",
                A106HighestContributionStage: GovernedGrammarMasteryStage.ControlledMastery),
            ["present.state-dynamic-basic"] = new(
                "present.state-dynamic-basic",
                FamiliarityExposureLevel: "A1",
                ControlledMasteryLevel: "A2",
                ProductiveMasteryLevel: "B1",
                A106ContributionLevel: "A1",
                A106HighestContributionStage: GovernedGrammarMasteryStage.FamiliarityExposure),
            ["present.simple-vs-continuous"] = new(
                "present.simple-vs-continuous",
                FamiliarityExposureLevel: "A1",
                ControlledMasteryLevel: "A2",
                ProductiveMasteryLevel: "B1",
                A106ContributionLevel: "A1",
                A106HighestContributionStage: GovernedGrammarMasteryStage.FamiliarityExposure)
        };

    public static GovernedGrammarCrossLevelNode GetNode(string atomicSkillId)
    {
        if (string.IsNullOrWhiteSpace(atomicSkillId))
            throw new ArgumentException("Atomic grammar skill id is required.", nameof(atomicSkillId));
        string id = atomicSkillId.Trim();
        if (!Nodes.TryGetValue(id, out GovernedGrammarCrossLevelNode? node))
            throw new InvalidDataException($"G-A1-06 mastery graph does not own atomic grammar node '{id}'.");
        return node;
    }

    public static IReadOnlyList<GovernedGrammarCrossLevelNode> GetNodes() =>
        Nodes.Values.OrderBy(node => node.AtomicSkillId, StringComparer.OrdinalIgnoreCase).ToArray();
}

/// <summary>
/// Learner-facing Fast Track policy needed by the UI adapter. The runtime can
/// expose this contract without teaching the UI a new assessment framework.
/// </summary>
internal sealed record GovernedGrammarFastTrackPresentationPolicy(
    string ItemId,
    bool ShowGrammarLabelBeforeCommitment,
    bool ShowAnswerConstructionBeforeCommitment,
    bool AllowHintBeforeCommitment,
    bool AllowRevealBeforeCommitment);

internal static class GovernedGrammarA106PresentationPolicy
{
    public static GovernedGrammarFastTrackPresentationPolicy GetFastTrackPolicy(string itemId)
    {
        GovernedGrammarItemContract item = GovernedGrammarA106Runtime.GetItem(itemId);
        if (item.ExposureClass != GovernedGrammarExposureClass.FastTrackVerify)
            throw new InvalidDataException($"G-A1-06 item '{item.ItemId}' is not a Fast Track verify item.");

        return item.ItemId.ToUpperInvariant() switch
        {
            "FT06-05" => new(
                item.ItemId,
                ShowGrammarLabelBeforeCommitment: false,
                ShowAnswerConstructionBeforeCommitment: false,
                AllowHintBeforeCommitment: false,
                AllowRevealBeforeCommitment: false),
            "FT06-06" => new(
                item.ItemId,
                ShowGrammarLabelBeforeCommitment: false,
                ShowAnswerConstructionBeforeCommitment: false,
                AllowHintBeforeCommitment: false,
                AllowRevealBeforeCommitment: false),
            _ => throw new InvalidDataException($"G-A1-06 has no governed Fast Track presentation policy for '{item.ItemId}'.")
        };
    }
}

internal static class GovernedGrammarA106MasteryGraphSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            GovernedGrammarA106MasteryGraphSelfTest.Run();
    }
}

internal static class GovernedGrammarA106MasteryGraphSelfTest
{
    public static void Run()
    {
        IReadOnlyList<GovernedGrammarCrossLevelNode> nodes = GovernedGrammarA106MasteryGraph.GetNodes();
        Require(nodes.Count == 4, "Expected exactly four governed G-A1-06 atomic graph nodes.");

        AssertNode("present.continuous-form", "A1", "A1", "A1", GovernedGrammarMasteryStage.ProductiveMastery);
        AssertNode("present.continuous-use", "A1", "A1", "A2", GovernedGrammarMasteryStage.ControlledMastery);
        AssertNode("present.state-dynamic-basic", "A1", "A2", "B1", GovernedGrammarMasteryStage.FamiliarityExposure);
        AssertNode("present.simple-vs-continuous", "A1", "A2", "B1", GovernedGrammarMasteryStage.FamiliarityExposure);

        GovernedGrammarFastTrackPresentationPolicy ft05 =
            GovernedGrammarA106PresentationPolicy.GetFastTrackPolicy("FT06-05");
        Require(!ft05.ShowGrammarLabelBeforeCommitment &&
                !ft05.ShowAnswerConstructionBeforeCommitment &&
                !ft05.AllowHintBeforeCommitment &&
                !ft05.AllowRevealBeforeCommitment,
            "FT06-05 must remain hidden-label/no-hint/no-reveal before commitment.");
    }

    private static void AssertNode(
        string atomicSkillId,
        string feLevel,
        string cmLevel,
        string pmLevel,
        GovernedGrammarMasteryStage a106HighestStage)
    {
        GovernedGrammarCrossLevelNode node = GovernedGrammarA106MasteryGraph.GetNode(atomicSkillId);
        Require(node.FamiliarityExposureLevel == feLevel,
            $"{atomicSkillId} FE level changed from governed graph '{feLevel}'.");
        Require(node.ControlledMasteryLevel == cmLevel,
            $"{atomicSkillId} CM level changed from governed graph '{cmLevel}'.");
        Require(node.ProductiveMasteryLevel == pmLevel,
            $"{atomicSkillId} PM level changed from governed graph '{pmLevel}'.");
        Require(node.A106ContributionLevel == "A1" && node.A106HighestContributionStage == a106HighestStage,
            $"{atomicSkillId} G-A1-06 contribution ceiling changed from governed graph.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("GovernedGrammarA106MasteryGraphSelfTest: " + message);
    }
}

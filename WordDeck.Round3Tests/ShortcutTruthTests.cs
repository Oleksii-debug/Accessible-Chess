using System.Runtime.CompilerServices;
using System.Windows.Forms;
using WordDeck;

internal static class ShortcutTruthTests
{
    [ModuleInitializer]
    internal static void Run()
    {
        var state = new AppState();
        AppStateStore.Normalize(state);
        string preservedDynamic = ActionIds.SpellingSwitchDeck("spelling-custom-r3");
        state.Shortcuts[preservedDynamic] = (Keys.Control | Keys.Shift | Keys.D9).ToString();

        var recallWindowManager = new ShortcutManager(state);
        Require(recallWindowManager.Definitions.Any(def => def.Id == ActionIds.OpenSpelling),
            "Recall-window shortcut definitions omitted static Spelling help/rebinding truth.");
        Require(recallWindowManager.Definitions.Any(def => def.Id == ActionIds.OpenSentenceCoach),
            "Recall-window shortcut definitions omitted static Sentence help/rebinding truth.");
        Require(recallWindowManager.FindAction(Keys.Control | Keys.Shift | Keys.S) is null,
            "Recall MainForm manager would swallow the Open Spelling shortcut instead of letting the menu/training entry point handle it.");
        Require(recallWindowManager.FindAction(Keys.Control | Keys.Shift | Keys.E) is null,
            "Recall MainForm manager would swallow the Open Sentence shortcut instead of letting the menu/training entry point handle it.");
        recallWindowManager.RefreshDeckDefinitions();
        Require(state.Shortcuts.ContainsKey(preservedDynamic),
            "Recall-only shortcut refresh deleted a dynamic Spelling shortcut without Spelling deck context.");

        var spellingDecks = new List<DeckDefinition>
        {
            new() { Id = SpellingDeckIds.Core(1), Name = "Spelling deck 1", IsCore = true, Order = 0 }
        };
        var trainingManager = new ShortcutManager(state, spellingDecks);
        Require(trainingManager.FindAction(trainingManager.Get(ActionIds.OpenSpelling)) == ActionIds.OpenSpelling,
            "Training manager does not dispatch the configured Open Spelling action.");
        Require(trainingManager.FindAction(trainingManager.Get(ActionIds.OpenSentenceCoach)) == ActionIds.OpenSentenceCoach,
            "Training manager does not dispatch the configured Open Sentence action.");

        Console.WriteLine("R3 shortcut/F1 truth tests passed.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}

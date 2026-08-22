namespace WordDeck;

internal sealed partial class MainForm
{
    // Training modes must operate on the same live AppState instance as Recall.
    // Loading a second AppStateStore copy here can later overwrite newer
    // shortcuts/profile/Recall changes when either copy is persisted.
    internal AppState SharedAppStateForTraining => _state;
    internal DictionaryPackage ActivePackageForTraining => _package;
    internal void SaveSharedStateAfterTraining() => SaveState();

    // Keep one complete shortcut registry for F1/settings while the main form's
    // dispatch context remains Recall-only. That lets help show the current
    // Spelling/Sentence and dynamic spelling-deck assignments without causing
    // the Recall form to swallow training-window accelerators.
    internal void RefreshTrainingShortcutDefinitions(IEnumerable<DeckDefinition> spellingDecks) =>
        _shortcuts.RefreshDeckDefinitions(spellingDecks);
}

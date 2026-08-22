namespace WordDeck;

internal sealed partial class MainForm
{
    // Training modes must operate on the same live AppState instance as Recall.
    // Loading a second AppStateStore copy here can later overwrite newer
    // shortcuts/profile/Recall changes when either copy is persisted.
    internal AppState SharedAppStateForTraining => _state;
    internal DictionaryPackage ActivePackageForTraining => _package;
    internal void SaveSharedStateAfterTraining() => SaveState();
}

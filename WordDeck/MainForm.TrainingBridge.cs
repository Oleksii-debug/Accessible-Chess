namespace WordDeck;

internal sealed partial class MainForm
{
    // Training entry points must use the same in-memory AppState instance as
    // Recall. Loading a second copy of state.json in the same process allows a
    // later Recall save to overwrite shortcut/profile changes made by Spelling
    // or Sentence Spelling.
    internal AppState SharedAppStateForTraining => _state;

    internal DictionaryPackage ActivePackageForTraining => _package;

    internal void SaveSharedStateAfterTraining()
    {
        SaveState();
    }
}

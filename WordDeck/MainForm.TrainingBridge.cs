namespace WordDeck;

internal sealed partial class MainForm
{
    internal AppState SharedAppStateForTraining => _state;

    internal DictionaryPackage ActivePackageForTraining => _package;

    internal void SaveSharedStateAfterTraining()
    {
        SaveState();
    }
}

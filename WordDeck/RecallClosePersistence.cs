namespace WordDeck;

internal static class RecallClosePersistence
{
    public static bool TrySave(Action saveAction, out string? error)
    {
        ArgumentNullException.ThrowIfNull(saveAction);
        try
        {
            saveAction();
            error = null;
            return true;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            return false;
        }
    }
}

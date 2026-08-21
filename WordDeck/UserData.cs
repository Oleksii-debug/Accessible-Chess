namespace WordDeck;

internal sealed class WordStudyHistory
{
    public int SeenCount { get; set; }
    public DateTimeOffset? LastSeenUtc { get; set; }
    public int TranslationRevealCount { get; set; }
    public string? LastScopeId { get; set; }
    public string? LastDeckId { get; set; }
}

internal sealed class WordDeckProfile
{
    public int ProfileSchemaVersion { get; set; } = AppStateStore.ProfileSchemaVersion;
    public int StateSchemaVersion { get; set; } = AppStateStore.CurrentSchemaVersion;
    public string SourceAppVersion { get; set; } = AppStateStore.SourceAppVersion;
    public string CorpusIdentity { get; set; } = AppStateStore.CorpusIdentity;
    public DateTimeOffset ExportedAtUtc { get; set; } = DateTimeOffset.UtcNow;
    public AppState State { get; set; } = new();
}

internal sealed record ProfileImportResult(string BackupPath, IReadOnlyList<string> QuarantinedIds);

internal static class UserProgressService
{
    public static bool IsHidden(AppState state, string entryId) =>
        state.HiddenEntryIds.Contains(entryId);

    public static bool Hide(AppState state, string entryId)
    {
        if (string.IsNullOrWhiteSpace(entryId)) return false;
        return state.HiddenEntryIds.Add(entryId);
    }

    public static bool Restore(AppState state, string entryId) =>
        state.HiddenEntryIds.Remove(entryId);

    public static int RestoreAll(AppState state)
    {
        int count = state.HiddenEntryIds.Count;
        state.HiddenEntryIds.Clear();
        return count;
    }

    public static void RecordSeen(AppState state, string entryId, string scopeId, string deckId)
    {
        WordStudyHistory history = GetOrCreateHistory(state, entryId);
        history.SeenCount++;
        history.LastSeenUtc = DateTimeOffset.UtcNow;
        history.LastScopeId = scopeId;
        history.LastDeckId = deckId;
    }

    public static void RecordTranslationReveal(AppState state, string entryId)
    {
        WordStudyHistory history = GetOrCreateHistory(state, entryId);
        history.TranslationRevealCount++;
    }

    public static void ResetLearningData(AppState state)
    {
        state.HiddenEntryIds.Clear();
        state.StudyHistoryByEntryId.Clear();
        state.QuarantinedProfileEntryIds.Clear();
        state.RecallStudyScopesByDictionary.Clear();
        state.DeckIdsByDictionary.Clear();
        state.DecksByDictionary.Clear();
        state.CurrentEntryIdByDictionary.Clear();
        state.ActiveDeckId = DeckIds.Core(1);
        state.ActiveDeck = 1;
    }

    private static WordStudyHistory GetOrCreateHistory(AppState state, string entryId)
    {
        if (!state.StudyHistoryByEntryId.TryGetValue(entryId, out WordStudyHistory? history) || history is null)
        {
            history = new WordStudyHistory();
            state.StudyHistoryByEntryId[entryId] = history;
        }
        return history;
    }
}

internal sealed class RecallNavigationHistory
{
    private readonly List<string> _entryIds = new();
    private int _index = -1;

    public int Count => _entryIds.Count;

    public void Clear()
    {
        _entryIds.Clear();
        _index = -1;
    }

    public void Visit(string entryId)
    {
        if (string.IsNullOrWhiteSpace(entryId)) return;
        if (_index >= 0 && _index < _entryIds.Count &&
            string.Equals(_entryIds[_index], entryId, StringComparison.OrdinalIgnoreCase))
            return;

        if (_index < _entryIds.Count - 1)
            _entryIds.RemoveRange(_index + 1, _entryIds.Count - _index - 1);

        if (_entryIds.Count == 0 || !string.Equals(_entryIds[^1], entryId, StringComparison.OrdinalIgnoreCase))
            _entryIds.Add(entryId);
        _index = _entryIds.Count - 1;
    }

    public bool TryPrevious(Func<string, bool> eligible, out string? entryId)
    {
        for (int i = _index - 1; i >= 0; i--)
        {
            if (!eligible(_entryIds[i])) continue;
            _index = i;
            entryId = _entryIds[i];
            return true;
        }
        entryId = null;
        return false;
    }

    public bool TryForward(Func<string, bool> eligible, out string? entryId)
    {
        for (int i = _index + 1; i < _entryIds.Count; i++)
        {
            if (!eligible(_entryIds[i])) continue;
            _index = i;
            entryId = _entryIds[i];
            return true;
        }
        entryId = null;
        return false;
    }

    public void Remove(string entryId)
    {
        for (int i = _entryIds.Count - 1; i >= 0; i--)
        {
            if (!string.Equals(_entryIds[i], entryId, StringComparison.OrdinalIgnoreCase)) continue;
            _entryIds.RemoveAt(i);
            if (i < _index) _index--;
            else if (i == _index) _index = i - 1;
        }
        if (_entryIds.Count == 0) _index = -1;
    }
}

internal sealed class HiddenWordRestoreDialog : Form
{
    private sealed record HiddenOption(string Id, string Label)
    {
        public override string ToString() => Label;
    }

    private readonly ListBox _list;
    public string? SelectedEntryId => (_list.SelectedItem as HiddenOption)?.Id;

    public HiddenWordRestoreDialog(IEnumerable<(string Id, string Label)> hiddenWords)
    {
        Text = "Restore hidden word";
        Width = 620;
        Height = 480;
        StartPosition = FormStartPosition.CenterParent;
        AccessibleName = "Restore hidden word";

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(12)
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var label = new Label
        {
            AutoSize = true,
            Text = "Choose a hidden word to restore to normal Recall study:",
            AccessibleName = "Restore hidden word instructions"
        };
        _list = new ListBox
        {
            Dock = DockStyle.Fill,
            AccessibleName = "Hidden words",
            AccessibleDescription = "Choose one hidden word and activate Restore."
        };
        foreach ((string id, string text) in hiddenWords)
            _list.Items.Add(new HiddenOption(id, text));
        if (_list.Items.Count > 0) _list.SelectedIndex = 0;

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, FlowDirection = FlowDirection.RightToLeft };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true, AccessibleName = "Cancel restore" };
        var restore = new Button { Text = "Restore", DialogResult = DialogResult.OK, AutoSize = true, AccessibleName = "Restore selected hidden word" };
        restore.Enabled = _list.Items.Count > 0;
        buttons.Controls.Add(cancel);
        buttons.Controls.Add(restore);

        root.Controls.Add(label, 0, 0);
        root.Controls.Add(_list, 0, 1);
        root.Controls.Add(buttons, 0, 2);
        Controls.Add(root);
        AcceptButton = restore;
        CancelButton = cancel;
        Shown += (_, _) => _list.Focus();
    }
}

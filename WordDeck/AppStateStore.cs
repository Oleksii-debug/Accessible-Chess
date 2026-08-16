using System.Text.Json;

namespace WordDeck;

internal sealed class AppStateStore
{
    private readonly string _root;
    private readonly string _statePath;
    private readonly string _backupPath;
    public string DictionaryDirectory { get; }

    public AppStateStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal AppStateStore(string root)
    {
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("State root directory must not be blank.", nameof(root));

        _root = root;
        DictionaryDirectory = Path.Combine(_root, "Dictionaries");
        _statePath = Path.Combine(_root, "state.json");
        _backupPath = Path.Combine(_root, "state.backup.json");
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(DictionaryDirectory);
    }

    public AppState Load()
    {
        AppState? primary = TryLoad(_statePath);
        if (primary is not null)
            return Normalize(primary);

        AppState? backup = TryLoad(_backupPath);
        if (backup is not null)
            return Normalize(backup);

        return new AppState();
    }

    public void Save(AppState state)
    {
        string temp = _statePath + ".tmp";
        string json = JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(temp, json);

        // Keep the last parseable state as a recovery point. Never overwrite a good backup
        // with a corrupted primary file.
        if (TryLoad(_statePath) is not null)
            File.Copy(_statePath, _backupPath, true);

        File.Move(temp, _statePath, true);
    }

    public string ImportDictionary(string sourcePath)
    {
        string fileName = Path.GetFileName(sourcePath);
        string destination = Path.Combine(DictionaryDirectory, fileName);
        File.Copy(sourcePath, destination, true);
        return destination;
    }

    public IEnumerable<string> EnumerateDictionaryFiles() =>
        Directory.EnumerateFiles(DictionaryDirectory, "*.tsv", SearchOption.TopDirectoryOnly);

    private static AppState? TryLoad(string path)
    {
        try
        {
            if (!File.Exists(path))
                return null;
            string json = File.ReadAllText(path);
            return JsonSerializer.Deserialize<AppState>(json);
        }
        catch
        {
            return null;
        }
    }

    private static AppState Normalize(AppState state)
    {
        state.ActiveDeck = Math.Clamp(state.ActiveDeck, 1, 5);
        state.DecksByDictionary ??= new Dictionary<string, Dictionary<string, int>>(StringComparer.OrdinalIgnoreCase);
        state.Shortcuts ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        state.DecksByDictionary = state.DecksByDictionary.ToDictionary(
            pair => pair.Key,
            pair => new Dictionary<string, int>(pair.Value ?? new Dictionary<string, int>(), StringComparer.OrdinalIgnoreCase),
            StringComparer.OrdinalIgnoreCase);
        state.Shortcuts = new Dictionary<string, string>(state.Shortcuts, StringComparer.OrdinalIgnoreCase);
        return state;
    }
}

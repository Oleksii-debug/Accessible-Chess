using System.Text.Json;

namespace WordDeck;

internal sealed class AppStateStore
{
    private readonly string _root;
    private readonly string _statePath;
    public string DictionaryDirectory { get; }

    public AppStateStore()
    {
        _root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck");
        DictionaryDirectory = Path.Combine(_root, "Dictionaries");
        _statePath = Path.Combine(_root, "state.json");
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(DictionaryDirectory);
    }

    public AppState Load()
    {
        try
        {
            if (!File.Exists(_statePath))
                return new AppState();
            string json = File.ReadAllText(_statePath);
            return JsonSerializer.Deserialize<AppState>(json) ?? new AppState();
        }
        catch
        {
            return new AppState();
        }
    }

    public void Save(AppState state)
    {
        string temp = _statePath + ".tmp";
        string json = JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(temp, json);
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
}

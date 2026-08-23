namespace WordDeck;

internal sealed record DictionaryEntry(string Id, string Level, string Source, string Target);

internal sealed class DictionaryPackage
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required string SourceLanguage { get; init; }
    public required string TargetLanguage { get; init; }
    public required IReadOnlyList<DictionaryEntry> Entries { get; init; }
}

using System.Runtime.CompilerServices;
using System.Text;

namespace WordDeck;

internal static class DictionaryLoaderSafetySelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg =>
                string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase)))
            DictionaryLoaderSafetySelfTest.Run();
    }
}

internal static class DictionaryLoaderSafetySelfTest
{
    public static void Run()
    {
        string root = Path.Combine(
            Path.GetTempPath(),
            "WordDeck словник import safety " + Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(root);
            TestNormalUnicodePathAndStableFallbackIdentity(root);
            TestOversizedFileRejectedBeforeRead(root);
            TestOversizedRowAndFieldRejected();
            TestEntryCountGuard();
            Console.WriteLine(
                "WordDeck dictionary import safety self-test passed: Unicode/space paths, stable fallback identity, file/row/field limits and entry-count bounds verified.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestNormalUnicodePathAndStableFallbackIdentity(string root)
    {
        const string body =
            "entryId\tlevel\tsource\ttarget\n" +
            "\tA1\tapple\tяблуко\n" +
            "fixed-id\tA2\ttake care\tпіклуватися\n";

        string first = Path.Combine(root, "мій словник один.tsv");
        string second = Path.Combine(root, "інше ім'я.tsv");
        File.WriteAllText(first, body, new UTF8Encoding(false));
        File.WriteAllText(second, body, new UTF8Encoding(false));

        DictionaryPackage a = DictionaryLoader.LoadFromFile(first);
        DictionaryPackage b = DictionaryLoader.LoadFromFile(second);

        Require(a.Entries.Count == 2 && a.Entries[0].Source == "apple" && a.Entries[0].Target == "яблуко",
            "Normal UTF-8 dictionary in a Unicode/space path did not load correctly.");
        Require(a.Id == b.Id && a.Id.StartsWith("imported-", StringComparison.Ordinal),
            "Content-derived fallback dictionary identity changed with the file path.");
        Require(a.Entries[0].Id.StartsWith(a.Id + ":", StringComparison.Ordinal),
            "Blank imported entry ID did not receive a stable dictionary-derived fallback ID.");
        Require(a.Entries[1].Id == "fixed-id",
            "Explicit imported stable entry ID changed.");
    }

    private static void TestOversizedFileRejectedBeforeRead(string root)
    {
        string path = Path.Combine(root, "too-large.tsv");
        using (FileStream stream = new(path, FileMode.Create, FileAccess.Write, FileShare.None))
            stream.SetLength(DictionaryLoader.MaxImportedFileBytes + 1);

        bool rejected = false;
        try { _ = DictionaryLoader.LoadFromFile(path); }
        catch (InvalidDataException ex)
        {
            rejected = ex.Message.Contains("import limit", StringComparison.OrdinalIgnoreCase);
        }

        Require(rejected, "Oversized imported dictionary was not rejected by the pre-read file-size boundary.");
    }

    private static void TestOversizedRowAndFieldRejected()
    {
        string tooLongField = new('x', DictionaryLoader.MaxFieldChars + 1);
        bool fieldRejected = false;
        try
        {
            _ = DictionaryLoader.Parse($"id\tA1\t{tooLongField}\tпереклад");
        }
        catch (InvalidDataException ex)
        {
            fieldRejected = ex.Message.Contains("source word", StringComparison.OrdinalIgnoreCase);
        }
        Require(fieldRejected, "Oversized dictionary field was accepted.");

        string tooLongRow = "id\tA1\tword\t" + new string('у', DictionaryLoader.MaxLineChars + 1);
        bool rowRejected = false;
        try { _ = DictionaryLoader.Parse(tooLongRow); }
        catch (InvalidDataException ex)
        {
            rowRejected = ex.Message.Contains("row 1", StringComparison.OrdinalIgnoreCase) &&
                          ex.Message.Contains("character import limit", StringComparison.OrdinalIgnoreCase);
        }
        Require(rowRejected, "Oversized dictionary row was accepted.");
    }

    private static void TestEntryCountGuard()
    {
        DictionaryLoader.EnsureEntryCountWithinLimit(DictionaryLoader.MaxEntries);
        bool rejected = false;
        try { DictionaryLoader.EnsureEntryCountWithinLimit(DictionaryLoader.MaxEntries + 1); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "Dictionary entry-count boundary accepted one entry beyond the supported maximum.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidDataException("Dictionary import safety self-test failed: " + message);
    }
}

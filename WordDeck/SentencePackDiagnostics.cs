using System.Diagnostics;
using System.Text.Json;

namespace WordDeck;

internal sealed record SentencePackLoadDiagnostics(
    string PackPath,
    long FileBytes,
    int Sentences,
    long ElapsedMilliseconds,
    long ManagedBytesBefore,
    long ManagedBytesAfter,
    long ManagedBytesDelta,
    long WorkingSetBytesBefore,
    long WorkingSetBytesAfter,
    long WorkingSetBytesDelta,
    SentencePackSqliteMetrics? SqlitePrototype = null);

internal static class SentencePackDiagnostics
{
    public static int Run(string[] args)
    {
        if (args.Length < 2 || args.Length > 6)
        {
            Console.Error.WriteLine("Usage: WordDeck.exe --measure-sentence-pack <pack.json|pack.json.gz> [report.json] [--sqlite <output.sqlite> [target-entry-id]]");
            return 2;
        }

        try
        {
            string packPath = Path.GetFullPath(args[1]);
            if (!File.Exists(packPath))
                throw new FileNotFoundException("SentencePack file was not found.", packPath);

            string? reportPath = null;
            int optionIndex = 2;
            if (args.Length > 2 && !args[2].Equals("--sqlite", StringComparison.OrdinalIgnoreCase))
            {
                reportPath = Path.GetFullPath(args[2]);
                optionIndex = 3;
            }

            string? sqlitePath = null;
            string sqliteTarget = "oxford-a1-0001";
            if (optionIndex < args.Length)
            {
                if (!args[optionIndex].Equals("--sqlite", StringComparison.OrdinalIgnoreCase) || optionIndex + 1 >= args.Length)
                    throw new ArgumentException("Unknown SentencePack measurement option.");
                sqlitePath = Path.GetFullPath(args[optionIndex + 1]);
                if (optionIndex + 2 < args.Length && !string.IsNullOrWhiteSpace(args[optionIndex + 2]))
                    sqliteTarget = args[optionIndex + 2].Trim();
            }

            GC.Collect();
            GC.WaitForPendingFinalizers();
            GC.Collect();

            long managedBefore = GC.GetTotalMemory(forceFullCollection: true);
            using Process process = Process.GetCurrentProcess();
            process.Refresh();
            long workingSetBefore = process.WorkingSet64;

            var stopwatch = Stopwatch.StartNew();
            SentencePack pack = SentencePackIo.Read(packPath);
            stopwatch.Stop();

            long managedAfter = GC.GetTotalMemory(forceFullCollection: false);
            process.Refresh();
            long workingSetAfter = process.WorkingSet64;

            SentencePackSqliteMetrics? sqliteMetrics = null;
            if (sqlitePath is not null)
            {
                // Build/query is intentionally a development measurement only. Runtime Sentence Coach
                // continues using JSON/GZIP until this disk-backed path proves a clear win.
                sqliteMetrics = SentencePackSqlitePrototype.Measure(packPath, sqlitePath, new[] { sqliteTarget });
            }

            var report = new SentencePackLoadDiagnostics(
                packPath,
                new FileInfo(packPath).Length,
                pack.Sentences.Count,
                stopwatch.ElapsedMilliseconds,
                managedBefore,
                managedAfter,
                managedAfter - managedBefore,
                workingSetBefore,
                workingSetAfter,
                workingSetAfter - workingSetBefore,
                sqliteMetrics);

            string json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
            Console.WriteLine(json);

            if (reportPath is not null)
            {
                string? directory = Path.GetDirectoryName(reportPath);
                if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
                File.WriteAllText(reportPath, json);
            }

            GC.KeepAlive(pack);
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"SentencePack measurement FAILED: {ex.Message}");
            return 1;
        }
    }
}

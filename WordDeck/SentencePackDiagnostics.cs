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
    long WorkingSetBytesDelta);

internal static class SentencePackDiagnostics
{
    public static int Run(string[] args)
    {
        if (args.Length is < 2 or > 3)
        {
            Console.Error.WriteLine("Usage: WordDeck.exe --measure-sentence-pack <pack.json|pack.json.gz> [report.json]");
            return 2;
        }

        try
        {
            string packPath = Path.GetFullPath(args[1]);
            if (!File.Exists(packPath))
                throw new FileNotFoundException("SentencePack file was not found.", packPath);

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

            // Validation performed by SentencePackIo.Read builds the same in-memory
            // indexes used by Sentence Coach, so the after-sample reflects the
            // complete runtime pack rather than JSON objects alone.
            long managedAfter = GC.GetTotalMemory(forceFullCollection: false);
            process.Refresh();
            long workingSetAfter = process.WorkingSet64;

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
                workingSetAfter - workingSetBefore);

            string json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
            Console.WriteLine(json);

            if (args.Length == 3)
            {
                string reportPath = Path.GetFullPath(args[2]);
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

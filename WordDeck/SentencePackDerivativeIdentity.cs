using System.Security.Cryptography;
using System.Text;
using Microsoft.Data.Sqlite;

namespace WordDeck;

internal static class SentencePackDerivativeIdentity
{
    private const string FingerprintKey = "source_logical_sha256";
    private const string PortableHashKey = "portable_file_sha256";
    private const string SourceVersionKey = "source_pack_version";

    public static string LogicalFingerprint(SentencePack pack)
    {
        SentencePackStructuralLimits.Validate(pack);
        byte[] bytes = Encoding.UTF8.GetBytes(SentencePackJson.Serialize(pack));
        return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    }

    public static string FileHash(string path)
    {
        using FileStream stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    public static void Stamp(string sqlitePath, SentencePack pack, string portablePath)
    {
        string logical = LogicalFingerprint(pack);
        string portable = FileHash(portablePath);
        using SqliteConnection connection = Open(sqlitePath, readOnly: false);
        Upsert(connection, FingerprintKey, logical);
        Upsert(connection, PortableHashKey, portable);
        Upsert(connection, SourceVersionKey, pack.Version.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    public static void VerifyCandidate(string sqlitePath, SentencePack pack, string portablePath)
    {
        using SqliteConnection connection = Open(sqlitePath, readOnly: true);
        string expectedLogical = LogicalFingerprint(pack);
        string expectedPortable = FileHash(portablePath);
        RequireEqual(connection, FingerprintKey, expectedLogical);
        RequireEqual(connection, PortableHashKey, expectedPortable);
        RequireEqual(connection, SourceVersionKey, pack.Version.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    public static bool MatchesInstalledPortable(string sqlitePath, string portablePath)
    {
        if (!File.Exists(sqlitePath) || !File.Exists(portablePath))
            return false;
        try
        {
            using SqliteConnection connection = Open(sqlitePath, readOnly: true);
            string? stored = Read(connection, PortableHashKey);
            // Pre-Round-2 derivative: allow legacy discovery rather than forcing an eager rebuild at startup.
            // A subsequent explicit import/replacement stamps and verifies the strong identity metadata.
            if (string.IsNullOrWhiteSpace(stored))
                return true;
            return string.Equals(stored, FileHash(portablePath), StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    private static SqliteConnection Open(string path, bool readOnly)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = Path.GetFullPath(path),
            Mode = readOnly ? SqliteOpenMode.ReadOnly : SqliteOpenMode.ReadWrite,
            Cache = SqliteCacheMode.Private,
            Pooling = false
        };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        return connection;
    }

    private static void Upsert(SqliteConnection connection, string key, string value)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "INSERT INTO metadata(key, value) VALUES ($key, $value) ON CONFLICT(key) DO UPDATE SET value = excluded.value;";
        command.Parameters.AddWithValue("$key", key);
        command.Parameters.AddWithValue("$value", value);
        command.ExecuteNonQuery();
    }

    private static void RequireEqual(SqliteConnection connection, string key, string expected)
    {
        string? actual = Read(connection, key);
        if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"SQLite SentencePack derivative identity metadata '{key}' does not match the validated portable source.");
    }

    private static string? Read(SqliteConnection connection, string key)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT value FROM metadata WHERE key = $key;";
        command.Parameters.AddWithValue("$key", key);
        return command.ExecuteScalar() as string;
    }
}

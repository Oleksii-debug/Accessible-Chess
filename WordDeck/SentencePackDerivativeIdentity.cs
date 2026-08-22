using System.Security.Cryptography;
using System.Text;
using Microsoft.Data.Sqlite;

namespace WordDeck;

internal static class SentencePackDerivativeIdentity
{
    internal const string FingerprintKey = "source_logical_sha256";
    internal const string PortableHashKey = "portable_file_sha256";
    internal const string SourceVersionKey = "source_pack_version";

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
        using SqliteConnection connection = Open(sqlitePath, readOnly: false);
        Upsert(connection, FingerprintKey, LogicalFingerprint(pack));
        Upsert(connection, PortableHashKey, FileHash(portablePath));
        Upsert(connection, SourceVersionKey, pack.Version.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    public static void VerifyCandidate(string sqlitePath, SentencePack pack, string portablePath)
    {
        using SqliteConnection connection = Open(sqlitePath, readOnly: true);
        RequireEqual(connection, FingerprintKey, LogicalFingerprint(pack));
        RequireEqual(connection, PortableHashKey, FileHash(portablePath));
        RequireEqual(connection, SourceVersionKey, pack.Version.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    public static bool MatchesInstalledPortable(string sqlitePath, string portablePath, bool allowLegacyUnstamped = true)
    {
        if (!File.Exists(sqlitePath) || !File.Exists(portablePath)) return false;
        try
        {
            using SqliteConnection connection = Open(sqlitePath, readOnly: true);
            string? stored = Read(connection, PortableHashKey);
            if (string.IsNullOrWhiteSpace(stored)) return allowLegacyUnstamped;
            return string.Equals(stored, FileHash(portablePath), StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    public static string? ReadMetadata(string sqlitePath, string key)
    {
        using SqliteConnection connection = Open(sqlitePath, readOnly: true);
        return Read(connection, key);
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

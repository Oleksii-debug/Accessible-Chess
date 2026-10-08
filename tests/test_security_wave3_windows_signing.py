from pathlib import Path


def test_wave3_windows_signing_is_oidc_managed_sha256_timestamped_and_fail_closed():
    root=Path(__file__).resolve().parents[1]
    text=(root/".github/workflows/security-wave3-windows-signing.yml").read_text(encoding="utf-8")
    assert "environment: production-signing" in text
    assert "id-token: write" in text
    assert "azure/login@a641126d1b8aa4d1fa005f4f92df94a3a4c4c906" in text
    assert "Azure/artifact-signing-action@c7ab2a863ab5f9a846ddb8265964877ef296ee82" in text
    assert "file-digest: SHA256" in text
    assert "timestamp-rfc3161: https://timestamp.acs.microsoft.com" in text
    assert "timestamp-digest: SHA256" in text
    assert "Get-AuthenticodeSignature" in text
    assert "SignatureStatus]::Valid" in text
    assert "EXPECTED_AUTHENTICODE_PUBLISHER" in text
    assert "azure-client-secret" not in text
    assert "BEGIN PRIVATE KEY" not in text

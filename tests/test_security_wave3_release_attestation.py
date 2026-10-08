from pathlib import Path


def test_wave3_release_attestation_is_reusable_tag_bound_and_keyless():
    root=Path(__file__).resolve().parents[1]
    text=(root/".github/workflows/security-wave3-release-attestation.yml").read_text(encoding="utf-8")
    assert "workflow_call:" in text
    assert "environment: production-signing" in text
    assert "id-token: write" in text
    assert "attestations: write" in text
    assert "actions/attest-build-provenance@e8998f949152b193b063cb0ec769d69d929409be" in text
    assert "actions/attest-sbom@bd218ad0dbcb3e146bd073d1d9c6d78e08aa8a0b" in text
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in text
    assert "refs/tags/v" in text
    assert "secrets." not in text
    assert "BEGIN PRIVATE KEY" not in text
    assert "SPDX-2.3" in text

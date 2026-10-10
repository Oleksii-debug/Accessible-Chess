from dataclasses import replace
import unittest

from acs.section52_release_gate import ReleaseAudience, ReleaseGateInput, Section52ReleaseError, qualify_release


class Section52ReleaseGateTests(unittest.TestCase):
    def evidence(self, audience=ReleaseAudience.PUBLIC_RELEASE):
        return ReleaseGateInput(
            audience=audience, source_sha="a" * 40, package_sha256="b" * 64,
            sbom_package_sha256="b" * 64, provenance_package_sha256="b" * 64,
            preflight_passed=True, receipt_verified=True, authenticode_valid=True,
            timestamped=True, license_manifest_complete=True, corpus_kind=audience.value,
            credentials_embedded=False,
            support_url="https://github.com/Oleksii-debug/Accessible-Chess/security/advisories/new",
            update_actions=frozenset({"release.status", "release.check_update", "release.apply_update"}),
        )

    def test_public_and_owner_variants_share_exact_release_chain(self):
        for audience in ReleaseAudience:
            result = qualify_release(self.evidence(audience))
            self.assertEqual(result["repository_gate"], "PASS")
            self.assertEqual(result["audience"], audience.value)
            self.assertFalse(result["publication_authorized"])
            self.assertEqual(result["physical_acceptance"], "EXTERNAL_NOT_PERFORMED")

    def test_exact_package_identity_binds_sbom_and_provenance(self):
        for field in ("sbom_package_sha256", "provenance_package_sha256"):
            with self.assertRaisesRegex(Section52ReleaseError, "identities differ"):
                qualify_release(replace(self.evidence(), **{field: "c" * 64}))

    def test_unsigned_untimestamped_unlicensed_or_credentials_fail_closed(self):
        for field, value in (("authenticode_valid", False), ("timestamped", False), ("license_manifest_complete", False), ("credentials_embedded", True)):
            with self.subTest(field=field), self.assertRaises(Section52ReleaseError):
                qualify_release(replace(self.evidence(), **{field: value}))

    def test_corpus_kind_and_accessible_update_surface_are_exact(self):
        with self.assertRaisesRegex(Section52ReleaseError, "corpus policy"):
            qualify_release(replace(self.evidence(), corpus_kind="TEST_BUILD"))
        with self.assertRaisesRegex(Section52ReleaseError, "update action"):
            qualify_release(replace(self.evidence(), update_actions=frozenset({"release.status"})))

    def test_only_physical_acceptance_authorizes_publication(self):
        result = qualify_release(replace(self.evidence(), clean_windows_launch=True, owner_nvda_accepted=True))
        self.assertTrue(result["publication_authorized"])
        self.assertEqual(result["physical_acceptance"], "PASS")

    def test_support_endpoint_is_canonical_https_without_credentials(self):
        for url in ("http://example.org", " https://example.org", "https://u:p@example.org", "https://example.org/a#fragment"):
            with self.subTest(url=url), self.assertRaises(Section52ReleaseError):
                qualify_release(replace(self.evidence(), support_url=url))


if __name__ == "__main__":
    unittest.main()

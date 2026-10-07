from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest

from acs.spdx_sbom import (
    ComponentRecord,
    SbomError,
    build_spdx_document,
    canonical_spdx_json,
    spdx_sha256,
    validate_spdx_document,
)


CREATED = datetime(2026, 9, 26, 21, 0, 0, tzinfo=timezone.utc)
SOURCE = "1" * 40
PRODUCT = "2" * 64


def component(name: str, version: str, digest: str, *, purl: str | None = None):
    return ComponentRecord(
        name=name,
        version=version,
        artifact_sha256=digest,
        license_declared="MIT",
        supplier="Organization: Example Upstream",
        download_location="https://example.invalid/releases/source.tar.gz",
        purl=purl,
    )


class SpdxSbomTests(unittest.TestCase):
    def build(self, components):
        return build_spdx_document(
            product_version="0.4.0-dev3",
            source_sha=SOURCE,
            product_sha256=PRODUCT,
            components=components,
            created_at=CREATED,
        )

    def test_document_is_spdx_23_and_binds_exact_release_identity(self):
        doc = self.build(
            [component("python-chess", "1.11.2", "a" * 64, purl="pkg:pypi/python-chess@1.11.2")]
        )
        self.assertEqual(doc["spdxVersion"], "SPDX-2.3")
        self.assertEqual(doc["dataLicense"], "CC0-1.0")
        self.assertEqual(doc["SPDXID"], "SPDXRef-DOCUMENT")
        self.assertEqual(doc["documentDescribes"], ["SPDXRef-Package-AccessibleChess"])
        product = doc["packages"][0]
        self.assertEqual(product["versionInfo"], "0.4.0-dev3")
        self.assertEqual(product["checksums"], [{"algorithm": "SHA256", "checksumValue": PRODUCT}])
        self.assertEqual(
            product["externalRefs"],
            [{
                "referenceCategory": "OTHER",
                "referenceType": "accessible-chess-source-commit",
                "referenceLocator": SOURCE,
            }],
        )
        self.assertEqual(doc["creationInfo"]["created"], "2026-09-26T21:00:00Z")
        validate_spdx_document(doc)

    def test_component_order_does_not_change_canonical_bytes(self):
        a = component("Alpha", "1.0", "a" * 64, purl="pkg:pypi/alpha@1.0")
        b = component("Beta", "2.0", "b" * 64, purl="pkg:pypi/beta@2.0")
        first = self.build([a, b])
        second = self.build([b, a])
        self.assertEqual(canonical_spdx_json(first), canonical_spdx_json(second))
        self.assertEqual(spdx_sha256(first), spdx_sha256(second))
        self.assertEqual(
            [p["name"] for p in first["packages"]],
            ["Accessible Chess", "Alpha", "Beta"],
        )

    def test_component_relationships_are_exact_and_deterministic(self):
        doc = self.build([
            component("Alpha", "1.0", "a" * 64),
            component("Beta", "2.0", "b" * 64),
        ])
        ids = [package["SPDXID"] for package in doc["packages"]]
        self.assertEqual(
            doc["relationships"],
            [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-AccessibleChess",
                },
                {
                    "spdxElementId": "SPDXRef-Package-AccessibleChess",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": ids[1],
                },
                {
                    "spdxElementId": "SPDXRef-Package-AccessibleChess",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": ids[2],
                },
            ],
        )

    def test_duplicate_component_identity_fails_closed(self):
        with self.assertRaisesRegex(SbomError, "duplicate component identity"):
            self.build([
                component("Alpha", "1.0", "a" * 64),
                component("alpha", "1.0", "b" * 64),
            ])

    def test_duplicate_purl_fails_closed(self):
        with self.assertRaisesRegex(SbomError, "duplicate component purl"):
            self.build([
                component("Alpha", "1.0", "a" * 64, purl="pkg:pypi/shared@1"),
                component("Beta", "1.0", "b" * 64, purl="pkg:pypi/shared@1"),
            ])

    def test_unqualified_or_ambiguous_input_is_rejected(self):
        bad = [
            dict(name=" Alpha", version="1", artifact_sha256="a" * 64, license_declared="MIT"),
            dict(name="Alpha", version="1", artifact_sha256="A" * 64, license_declared="MIT"),
            dict(name="Alpha", version="1", artifact_sha256="a" * 63, license_declared="MIT"),
            dict(name="Alpha", version="1", artifact_sha256="a" * 64, license_declared="NONE"),
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(SbomError):
                    ComponentRecord(**kwargs)
        with self.assertRaises(SbomError):
            self.build([object()])
        with self.assertRaises(SbomError):
            build_spdx_document(
                product_version="0.4.0-dev3",
                source_sha="A" * 40,
                product_sha256=PRODUCT,
                components=[],
                created_at=CREATED,
            )
        with self.assertRaises(SbomError):
            build_spdx_document(
                product_version="0.4.0-dev3",
                source_sha=SOURCE,
                product_sha256=PRODUCT,
                components=[],
                created_at=CREATED.replace(microsecond=1),
            )

    def test_purl_and_supplier_contracts_are_strict(self):
        with self.assertRaises(SbomError):
            ComponentRecord(
                name="Alpha",
                version="1",
                artifact_sha256="a" * 64,
                license_declared="MIT",
                supplier="Example Upstream",
            )
        with self.assertRaises(SbomError):
            ComponentRecord(
                name="Alpha",
                version="1",
                artifact_sha256="a" * 64,
                license_declared="MIT",
                purl="https://example.invalid/not-a-purl",
            )

    def test_tampering_package_checksum_or_relationship_fails_validation(self):
        doc = self.build([component("Alpha", "1.0", "a" * 64)])
        tampered = deepcopy(doc)
        tampered["packages"][1]["checksums"][0]["checksumValue"] = "A" * 64
        with self.assertRaises(SbomError):
            validate_spdx_document(tampered)

        tampered = deepcopy(doc)
        tampered["relationships"][1]["relatedSpdxElement"] = "SPDXRef-Package-Unknown"
        with self.assertRaisesRegex(SbomError, "relationship graph"):
            validate_spdx_document(tampered)

    def test_unknown_document_or_package_fields_fail_closed(self):
        doc = self.build([component("Alpha", "1.0", "a" * 64)])
        tampered = deepcopy(doc)
        tampered["unexpected"] = True
        with self.assertRaises(SbomError):
            validate_spdx_document(tampered)

        tampered = deepcopy(doc)
        tampered["packages"][1]["unexpected"] = True
        with self.assertRaises(SbomError):
            validate_spdx_document(tampered)

    def test_canonical_json_is_single_line_utf8_json_with_terminal_newline(self):
        doc = self.build([component("Бібліотека", "1.0", "a" * 64)])
        encoded = canonical_spdx_json(doc)
        self.assertTrue(encoded.endswith("\n"))
        self.assertEqual(encoded.count("\n"), 1)
        parsed = json.loads(encoded)
        self.assertEqual(parsed["packages"][1]["name"], "Бібліотека")
        self.assertIn("Бібліотека", encoded)

    def test_namespace_changes_when_exact_release_identity_changes(self):
        first = self.build([])
        second = build_spdx_document(
            product_version="0.4.0-dev3",
            source_sha=SOURCE,
            product_sha256="3" * 64,
            components=[],
            created_at=CREATED,
        )
        self.assertNotEqual(first["documentNamespace"], second["documentNamespace"])
        self.assertNotEqual(spdx_sha256(first), spdx_sha256(second))


if __name__ == "__main__":
    unittest.main()

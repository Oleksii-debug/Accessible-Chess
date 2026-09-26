from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from acs.spdx_sbom import (
    ComponentRecord,
    SbomError,
    build_spdx_document,
    canonical_spdx_json,
    generate_spdx_file,
    load_release_manifest,
    spdx_sha256,
    validate_spdx_document,
)
from tools.generate_spdx_sbom import main

CREATED = datetime(2026, 9, 26, 21, 0, 0, tzinfo=timezone.utc)
SOURCE = "1" * 40
PRODUCT = "2" * 64


def part(
    name: str = "Alpha",
    version: str = "1.0",
    digest: str = "a" * 64,
    purl: str | None = None,
):
    return ComponentRecord(
        name=name,
        version=version,
        artifact_sha256=digest,
        license_declared="MIT",
        supplier="Organization: Example Upstream",
        download_location="https://example.invalid/source.tar.gz",
        purl=purl,
    )


class SpdxSbomTests(unittest.TestCase):
    def build(self, parts=()):
        return build_spdx_document(
            product_version="0.4.0-dev3",
            source_sha=SOURCE,
            product_sha256=PRODUCT,
            components=parts,
            created_at=CREATED,
        )

    def manifest(self):
        return {
            "schema_version": 1,
            "created_at": "2026-09-26T21:00:00Z",
            "product": {
                "version": "0.4.0-dev3",
                "source_sha": SOURCE,
                "sha256": PRODUCT,
            },
            "components": [
                {
                    "name": "Alpha",
                    "version": "1.0",
                    "artifact_sha256": "a" * 64,
                    "license_declared": "MIT",
                    "purl": "pkg:pypi/alpha@1.0",
                }
            ],
        }

    def test_exact_release_identity_uses_standard_gitoid(self):
        doc = self.build(
            [part(purl="pkg:pypi/alpha@1.0")]
        )
        product = doc["packages"][0]
        self.assertEqual(
            product["externalRefs"],
            [
                {
                    "referenceCategory": "PERSISTENT-ID",
                    "referenceType": "gitoid",
                    "referenceLocator": (
                        "gitoid:commit:sha1:" + SOURCE
                    ),
                }
            ],
        )
        validate_spdx_document(doc)

    def test_component_order_is_byte_deterministic(self):
        a = part("Alpha", "1", "a" * 64)
        b = part("Beta", "2", "b" * 64)
        left = self.build([a, b])
        right = self.build([b, a])
        self.assertEqual(
            canonical_spdx_json(left),
            canonical_spdx_json(right),
        )
        self.assertEqual(
            spdx_sha256(left),
            spdx_sha256(right),
        )

    def test_relationship_graph_matches_inventory(self):
        doc = self.build([part()])
        ids = [
            package["SPDXID"]
            for package in doc["packages"]
        ]
        self.assertEqual(
            doc["relationships"][1]["relatedSpdxElement"],
            ids[1],
        )
        broken = deepcopy(doc)
        broken["relationships"][1][
            "relatedSpdxElement"
        ] = "SPDXRef-Package-Other"
        with self.assertRaisesRegex(
            SbomError,
            "relationship graph",
        ):
            validate_spdx_document(broken)

    def test_duplicates_fail_closed(self):
        with self.assertRaisesRegex(
            SbomError,
            "duplicate component identity",
        ):
            self.build(
                [
                    part("Alpha", "1", "a" * 64),
                    part("alpha", "1", "b" * 64),
                ]
            )
        with self.assertRaisesRegex(
            SbomError,
            "duplicate component purl",
        ):
            self.build(
                [
                    part(
                        "Alpha",
                        "1",
                        "a" * 64,
                        "pkg:pypi/shared@1",
                    ),
                    part(
                        "Beta",
                        "1",
                        "b" * 64,
                        "pkg:pypi/shared@1",
                    ),
                ]
            )

    def test_invalid_component_facts_fail_closed(self):
        for kwargs in (
            {"artifact_sha256": "A" * 64},
            {"artifact_sha256": "a" * 63},
            {"license_declared": "NONE"},
            {"supplier": "Unknown"},
            {"purl": "https://example.invalid/not-purl"},
        ):
            base = {
                "name": "Alpha",
                "version": "1",
                "artifact_sha256": "a" * 64,
                "license_declared": "MIT",
            }
            base.update(kwargs)
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(SbomError):
                    ComponentRecord(**base)

    def test_tampered_gitoid_is_rejected(self):
        doc = self.build([])
        broken = deepcopy(doc)
        broken["packages"][0]["externalRefs"][0][
            "referenceLocator"
        ] = "gitoid:commit:sha1:" + "A" * 40
        with self.assertRaises(SbomError):
            validate_spdx_document(broken)

    def test_namespace_changes_with_release_hash(self):
        first = self.build([])
        second = build_spdx_document(
            product_version="0.4.0-dev3",
            source_sha=SOURCE,
            product_sha256="3" * 64,
            components=[],
            created_at=CREATED,
        )
        self.assertNotEqual(
            first["documentNamespace"],
            second["documentNamespace"],
        )

    def test_manifest_duplicate_keys_and_unknown_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            duplicate = root / "dup.json"
            duplicate.write_text(
                '{"schema_version":1,'
                '"schema_version":1,'
                '"created_at":"2026-09-26T21:00:00Z",'
                '"product":{},'
                '"components":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                SbomError,
                "duplicate JSON key",
            ):
                load_release_manifest(duplicate)

            value = self.manifest()
            value["unexpected"] = True
            bad = root / "bad.json"
            bad.write_text(
                json.dumps(value),
                encoding="utf-8",
            )
            with self.assertRaises(SbomError):
                load_release_manifest(bad)

    def test_generate_is_atomic_and_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest()),
                encoding="utf-8",
            )
            output = root / "release.spdx.json"
            first = generate_spdx_file(
                manifest,
                output,
            )
            second = generate_spdx_file(
                manifest,
                output,
            )
            self.assertEqual(first, second)
            self.assertEqual(
                first,
                output.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                json.loads(first)["spdxVersion"],
                "SPDX-2.3",
            )

    def test_symlink_input_and_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(self.manifest()),
                encoding="utf-8",
            )
            link = root / "linked.json"
            try:
                link.symlink_to(manifest.name)
            except (OSError, NotImplementedError):
                self.skipTest("symlink unavailable")
            with self.assertRaisesRegex(
                SbomError,
                "non-symlink",
            ):
                load_release_manifest(link)

            target = root / "target.json"
            target.write_text(
                "KEEP",
                encoding="utf-8",
            )
            outlink = root / "out.json"
            outlink.symlink_to(target.name)
            with self.assertRaisesRegex(
                SbomError,
                "non-symlink",
            ):
                generate_spdx_file(
                    manifest,
                    outlink,
                )
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "KEEP",
            )

    def test_cli_fails_without_publishing_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.manifest()
            value["product"]["sha256"] = "bad"
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(value),
                encoding="utf-8",
            )
            output = root / "out.json"
            self.assertEqual(
                main(
                    [
                        "--input",
                        str(manifest),
                        "--output",
                        str(output),
                    ]
                ),
                2,
            )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

import dataclasses
import tempfile
import unittest
from pathlib import Path

from acs import chessbase_2cbh_backend as twocbh


class V2TwoCbhBackendContractTests(unittest.TestCase):
    def _contract(
        self,
        *,
        optional: bool = True,
        qualified: bool = True,
        reject_unlisted: bool = False,
    ) -> twocbh.TwoCbhFamilyContract:
        return twocbh.TwoCbhFamilyContract(
            evidence_id="test-evidence-v1",
            members=(
                twocbh.TwoCbhMemberRule(
                    ".parta", twocbh.TwoCbhRequirement.REQUIRED
                ),
                twocbh.TwoCbhMemberRule(
                    ".partb",
                    twocbh.TwoCbhRequirement.OPTIONAL
                    if optional
                    else twocbh.TwoCbhRequirement.REQUIRED,
                ),
            ),
            topology_evidence_qualified=qualified,
            reject_unlisted_same_root_files=reject_unlisted,
        )

    def _descriptor(
        self,
        *,
        contract: twocbh.TwoCbhFamilyContract | None = None,
        lawful: bool = True,
        independent: bool = True,
        equivalent: bool = True,
        refs: tuple[str, ...] = ("test-ref",),
    ) -> twocbh.TwoCbhBackendDescriptor:
        return twocbh.TwoCbhBackendDescriptor(
            backend_id="test-2cbh-backend",
            backend_version="1.0",
            executable_sha256="a" * 64,
            protocol_id="accessible-chess-2cbh-test-v1",
            license_name="test-only",
            license_url="https://example.invalid/license",
            automation_interface_evidence="test-only external executable protocol",
            family_contract=contract or self._contract(),
            oracle_id="test-independent-oracle",
            oracle_lawful_for_testing=lawful,
            oracle_independent_of_decoder=independent,
            oracle_semantic_equivalence_proven=equivalent,
            evidence_references=refs,
        )

    def _write_family(
        self,
        root: Path,
        *,
        part_b: bool = False,
        extra: bool = False,
    ) -> Path:
        primary = root / "sample.2cbh"
        primary.write_bytes(b"primary")
        (root / "sample.parta").write_bytes(b"required")
        if part_b:
            (root / "sample.partb").write_bytes(b"optional")
        if extra:
            (root / "sample.extra").write_bytes(b"unqualified")
        return primary

    def test_shipping_registry_is_empty_and_does_not_advertise_decoder(self):
        registry = twocbh.default_twocbh_backend_registry()
        self.assertEqual(registry.descriptors(), ())
        self.assertFalse(registry.decoder_available)

    def test_unqualified_topology_or_oracle_cannot_register(self):
        registry = twocbh.TwoCbhBackendRegistry()
        candidates = (
            self._descriptor(contract=self._contract(qualified=False)),
            self._descriptor(lawful=False),
            self._descriptor(independent=False),
            self._descriptor(equivalent=False),
            self._descriptor(refs=()),
        )
        for descriptor in candidates:
            with self.subTest(descriptor=descriptor):
                self.assertFalse(descriptor.qualified)
                with self.assertRaises(twocbh.TwoCbhQualificationError):
                    registry.register(descriptor)
        self.assertFalse(registry.decoder_available)

    def test_qualified_descriptor_registers_only_explicitly(self):
        registry = twocbh.TwoCbhBackendRegistry()
        descriptor = self._descriptor()
        self.assertTrue(descriptor.qualified)
        registry.register(descriptor)
        self.assertTrue(registry.decoder_available)
        self.assertIs(registry.get(descriptor.backend_id), descriptor)
        with self.assertRaises(twocbh.TwoCbhQualificationError):
            registry.register(descriptor)

    def test_default_windows_backend_bundling_is_forbidden_by_contract(self):
        kwargs = dict(
            backend_id="test-2cbh-backend",
            backend_version="1.0",
            executable_sha256="b" * 64,
            protocol_id="accessible-chess-2cbh-test-v1",
            license_name="test-only",
            license_url="https://example.invalid/license",
            automation_interface_evidence="test-only external executable protocol",
            family_contract=self._contract(),
            oracle_id="test-independent-oracle",
            oracle_lawful_for_testing=True,
            oracle_independent_of_decoder=True,
            oracle_semantic_equivalence_proven=True,
            evidence_references=("test-ref",),
            default_windows_bundle_allowed=True,
        )
        with self.assertRaises(ValueError):
            twocbh.TwoCbhBackendDescriptor(**kwargs)

    def test_member_rules_have_no_semantic_role_field(self):
        fields = {field.name for field in dataclasses.fields(twocbh.TwoCbhMemberRule)}
        self.assertEqual(fields, {"suffix", "requirement"})
        self.assertNotIn("role", fields)
        source = Path(twocbh.__file__).read_text(encoding="utf-8").casefold()
        for unqualified_suffix in (".2cba", ".2cbg", ".2lcd", ".2lgd", ".2lid"):
            self.assertNotIn(unqualified_suffix, source)

    def test_duplicate_member_suffixes_are_rejected_case_insensitively(self):
        with self.assertRaises(ValueError):
            twocbh.TwoCbhFamilyContract(
                evidence_id="test-evidence-v1",
                members=(
                    twocbh.TwoCbhMemberRule(
                        ".parta", twocbh.TwoCbhRequirement.REQUIRED
                    ),
                    twocbh.TwoCbhMemberRule(
                        ".PARTA", twocbh.TwoCbhRequirement.OPTIONAL
                    ),
                ),
                topology_evidence_qualified=True,
            )

    def test_capture_uses_only_evidence_qualified_required_optional_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_family(root)
            descriptor = self._descriptor()
            evidence = twocbh.capture_twocbh_bundle(primary, descriptor)
            self.assertEqual([item.suffix for item in evidence.files], [".2cbh", ".parta"])
            self.assertEqual(
                [item.requirement for item in evidence.files],
                [twocbh.TwoCbhRequirement.REQUIRED, twocbh.TwoCbhRequirement.REQUIRED],
            )
            self.assertGreater(evidence.total_bytes, 0)
            self.assertEqual(evidence.backend_id, descriptor.backend_id)

    def test_missing_required_member_fails_closed_but_optional_may_be_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = root / "sample.2cbh"
            primary.write_bytes(b"primary")
            with self.assertRaises(twocbh.TwoCbhSourceError):
                twocbh.capture_twocbh_bundle(primary, self._descriptor())

            (root / "sample.parta").write_bytes(b"required")
            evidence = twocbh.capture_twocbh_bundle(primary, self._descriptor())
            self.assertEqual(len(evidence.files), 2)

            descriptor = self._descriptor(contract=self._contract(optional=False))
            with self.assertRaises(twocbh.TwoCbhSourceError):
                twocbh.capture_twocbh_bundle(primary, descriptor)

    def test_primary_must_be_real_2cbh_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrong = root / "sample.bin"
            wrong.write_bytes(b"primary")
            with self.assertRaises(twocbh.TwoCbhSourceError):
                twocbh.capture_twocbh_bundle(wrong, self._descriptor())

    def test_unqualified_descriptor_cannot_even_capture_source_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = self._write_family(Path(tmp))
            descriptor = self._descriptor(contract=self._contract(qualified=False))
            with self.assertRaises(twocbh.TwoCbhQualificationError):
                twocbh.capture_twocbh_bundle(primary, descriptor)

    def test_source_mutation_invalidates_all_captured_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_family(root)
            descriptor = self._descriptor()
            evidence = twocbh.capture_twocbh_bundle(primary, descriptor)
            (root / "sample.parta").write_bytes(b"changed")
            with self.assertRaises(twocbh.TwoCbhSourceChangedError):
                twocbh.verify_twocbh_bundle_unchanged(evidence, descriptor)

    def test_new_optional_member_after_capture_is_detected_as_topology_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_family(root)
            descriptor = self._descriptor()
            evidence = twocbh.capture_twocbh_bundle(primary, descriptor)
            (root / "sample.partb").write_bytes(b"late")
            with self.assertRaises(twocbh.TwoCbhSourceChangedError):
                twocbh.verify_twocbh_bundle_unchanged(evidence, descriptor)

    def test_explicit_strict_topology_rejects_unlisted_same_root_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_family(root, extra=True)
            permissive = self._descriptor(contract=self._contract(reject_unlisted=False))
            twocbh.capture_twocbh_bundle(primary, permissive)

            strict = self._descriptor(contract=self._contract(reject_unlisted=True))
            with self.assertRaises(twocbh.TwoCbhSourceError):
                twocbh.capture_twocbh_bundle(primary, strict)

    def test_symlink_member_is_rejected_when_platform_can_create_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = root / "sample.2cbh"
            primary.write_bytes(b"primary")
            target = root / "target.bin"
            target.write_bytes(b"target")
            link = root / "sample.parta"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable on this runner")
            with self.assertRaises(twocbh.TwoCbhSourceError):
                twocbh.capture_twocbh_bundle(primary, self._descriptor())

    def test_member_count_member_size_and_total_size_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_family(root, part_b=True)
            descriptor = self._descriptor()
            with self.assertRaises(twocbh.TwoCbhSourceError):
                twocbh.capture_twocbh_bundle(
                    primary,
                    descriptor,
                    limits=twocbh.TwoCbhResourceLimits(max_members=2),
                )
            with self.assertRaises(twocbh.TwoCbhSourceError):
                twocbh.capture_twocbh_bundle(
                    primary,
                    descriptor,
                    limits=twocbh.TwoCbhResourceLimits(
                        max_member_bytes=3,
                        max_total_bytes=3,
                    ),
                )
            with self.assertRaises(twocbh.TwoCbhSourceError):
                twocbh.capture_twocbh_bundle(
                    primary,
                    descriptor,
                    limits=twocbh.TwoCbhResourceLimits(
                        max_member_bytes=8,
                        max_total_bytes=12,
                    ),
                )

    def test_report_projection_does_not_expose_workstation_parent_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = self._write_family(root)
            evidence = twocbh.capture_twocbh_bundle(primary, self._descriptor())
            report = evidence.as_report_fields()
            self.assertEqual(report["primary_path"], "sample.2cbh")
            for item in report["files"]:
                self.assertNotIn(str(root), str(item["path"]))
                self.assertEqual(Path(str(item["path"])).name, str(item["path"]))


if __name__ == "__main__":
    unittest.main()

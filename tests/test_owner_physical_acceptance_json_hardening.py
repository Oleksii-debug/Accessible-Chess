from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import record_owner_physical_acceptance as acceptance_module
from scripts.record_owner_physical_acceptance import (
    OwnerPhysicalAcceptanceError,
    _canonical_object_from_bytes,
    verify_owner_physical_acceptance,
)
from tests.test_owner_physical_acceptance import (
    _machine_receipt,
    _record,
    _scenarios,
    _verify,
    _write_machine_receipt,
)


class OwnerPhysicalAcceptanceJsonHardeningTests(unittest.TestCase):
    def test_scenario_validation_rejects_active_mapping_before_hooks(self):
        touched = []

        class ActiveScenarios(dict):
            def __iter__(self):
                touched.append("iter")
                raise AssertionError("active scenario iteration executed")

            def get(self, key, default=None):
                touched.append("get")
                raise AssertionError("active scenario lookup executed")

        active = ActiveScenarios(_scenarios())
        with self.assertRaisesRegex(
            OwnerPhysicalAcceptanceError,
            "scenario_results must contain",
        ):
            acceptance_module._validate_scenarios(active)

        self.assertEqual(touched, [])

    def test_record_rejects_publication_not_bound_to_fsynced_staging_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            receipt = _machine_receipt(final_zip)
            _write_machine_receipt(machine, receipt)
            output = root / "physical.json"

            def publish_different_bytes(_source, destination, **_kwargs):
                Path(destination).write_bytes(b'{"forged":true}\n')

            with mock.patch.object(
                acceptance_module,
                "_final_zip_sha",
                return_value=receipt["archive_sha256"],
            ), mock.patch.object(
                acceptance_module.os,
                "link",
                side_effect=publish_different_bytes,
            ):
                with self.assertRaisesRegex(
                    OwnerPhysicalAcceptanceError,
                    "changed during atomic publication|published bytes do not match",
                ):
                    _record(machine, final_zip, output, _scenarios())

            self.assertTrue(output.exists())
            self.assertEqual(output.read_bytes(), b'{"forged":true}\n')

    def test_rejected_owned_publication_is_removed_and_exact_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "physical.json"
            payload = b'{"accepted":true}\n'
            real_stable_bytes = acceptance_module._stable_bytes
            rejected_once = False

            def reject_first_published_readback(path, *, label, maximum):
                nonlocal rejected_once
                if Path(path) == output and not rejected_once:
                    rejected_once = True
                    return b'{"accepted":false}\n'
                return real_stable_bytes(path, label=label, maximum=maximum)

            with mock.patch.object(
                acceptance_module,
                "_stable_bytes",
                side_effect=reject_first_published_readback,
            ):
                with self.assertRaisesRegex(
                    OwnerPhysicalAcceptanceError,
                    "published bytes do not match",
                ):
                    acceptance_module._publish_exclusive(output, payload)

            self.assertTrue(rejected_once)
            self.assertFalse(output.exists())

            acceptance_module._publish_exclusive(output, payload)
            self.assertEqual(output.read_bytes(), payload)

    def test_rejected_publication_preserves_raced_in_foreign_replacement(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "physical.json"
            payload = b'{"accepted":true}\n'
            foreign = b'{"foreign":true}\n'
            real_stable_bytes = acceptance_module._stable_bytes
            replaced = False

            def replace_before_readback(path, *, label, maximum):
                nonlocal replaced
                if Path(path) == output and not replaced:
                    replaced = True
                    output.unlink()
                    output.write_bytes(foreign)
                    return foreign
                return real_stable_bytes(path, label=label, maximum=maximum)

            with mock.patch.object(
                acceptance_module,
                "_stable_bytes",
                side_effect=replace_before_readback,
            ):
                with self.assertRaisesRegex(
                    OwnerPhysicalAcceptanceError,
                    "published bytes do not match",
                ):
                    acceptance_module._publish_exclusive(output, payload)

            self.assertTrue(replaced)
            self.assertTrue(output.exists())
            self.assertEqual(output.read_bytes(), foreign)

    def test_record_does_not_reopen_mutable_inputs_after_exclusive_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            receipt = _machine_receipt(final_zip)
            _write_machine_receipt(machine, receipt)
            output = root / "physical.json"

            with mock.patch.object(
                acceptance_module,
                "_final_zip_sha",
                return_value=receipt["archive_sha256"],
            ) as digest:
                value = _record(machine, final_zip, output, _scenarios())

            self.assertEqual(digest.call_count, 1)
            self.assertTrue(output.is_file())
            self.assertEqual(
                _verify(output, machine, final_zip),
                value,
            )

    def test_record_path_rejects_non_finite_unconsumed_machine_field(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            _write_machine_receipt(
                machine,
                _machine_receipt(final_zip, archive_path=float("nan")),
            )

            with self.assertRaisesRegex(
                OwnerPhysicalAcceptanceError,
                "non-finite JSON number",
            ):
                _record(
                    machine,
                    final_zip,
                    root / "physical.json",
                    _scenarios(),
                )

    def test_canonical_parser_rejects_non_finite_json_constants(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                payload = f'{{"value":{token}}}\n'.encode("utf-8")
                with self.assertRaisesRegex(
                    OwnerPhysicalAcceptanceError,
                    "non-finite JSON number",
                ):
                    _canonical_object_from_bytes(
                        payload,
                        label="physical acceptance evidence",
                        expected_keys={"value"},
                    )

    def test_canonical_parser_normalizes_lone_surrogate_failure(self):
        with self.assertRaisesRegex(
            OwnerPhysicalAcceptanceError,
            "invalid canonical JSON",
        ):
            _canonical_object_from_bytes(
                b'{"value":"\\ud800"}\n',
                label="physical acceptance evidence",
                expected_keys={"value"},
            )

    def test_canonical_parser_normalizes_excessive_nesting_failure(self):
        nested = "[" * 1500 + "0" + "]" * 1500
        payload = f'{{"value":{nested}}}\n'.encode("utf-8")
        with self.assertRaisesRegex(
            OwnerPhysicalAcceptanceError,
            "invalid canonical JSON",
        ):
            _canonical_object_from_bytes(
                payload,
                label="physical acceptance evidence",
                expected_keys={"value"},
            )

    def test_canonical_parser_still_accepts_finite_canonical_json(self):
        value = _canonical_object_from_bytes(
            b'{"value":1}\n',
            label="physical acceptance evidence",
            expected_keys={"value"},
        )
        self.assertEqual(value, {"value": 1})


if __name__ == "__main__":
    unittest.main()

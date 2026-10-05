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
    _write_machine_receipt,
)


class OwnerPhysicalAcceptanceJsonHardeningTests(unittest.TestCase):
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
                verify_owner_physical_acceptance(output, machine, final_zip),
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

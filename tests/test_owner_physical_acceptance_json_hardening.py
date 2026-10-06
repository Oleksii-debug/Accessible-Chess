from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
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

    def test_record_rejects_active_scenario_key_before_hash_or_publication(self):
        touched = []

        class ActiveScenarioKey(str):
            armed = False

            def __hash__(self):
                if type(self).armed:
                    touched.append("hash")
                    raise AssertionError("active scenario key hash executed")
                return super().__hash__()

            def __eq__(self, other):
                if type(self).armed:
                    touched.append("eq")
                    raise AssertionError("active scenario key equality executed")
                return super().__eq__(other)

        scenarios = _scenarios()
        canonical_key = next(iter(scenarios))
        active_key = ActiveScenarioKey(canonical_key)
        status = scenarios.pop(canonical_key)
        scenarios[active_key] = status
        ActiveScenarioKey.armed = True

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            receipt = _machine_receipt(final_zip)
            _write_machine_receipt(machine, receipt)
            output = root / "physical.json"

            with self.assertRaisesRegex(
                OwnerPhysicalAcceptanceError,
                "scenario_results keys must be exact text",
            ):
                _record(machine, final_zip, output, scenarios)

            self.assertEqual(touched, [])
            self.assertFalse(output.exists())

    def test_physical_snapshot_metadata_is_platform_fail_closed(self):
        base = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )
        ctime_drift = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=999,
        )
        missing_mtime = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_ctime_ns=456,
        )
        missing_ctime = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
        )
        bool_size = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=True,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )

        with mock.patch.object(
            acceptance_module,
            "_same_file_identity",
            return_value=True,
        ):
            with mock.patch.object(acceptance_module.os, "name", "nt"):
                self.assertTrue(
                    acceptance_module._same_file_snapshot(base, ctime_drift)
                )
                self.assertFalse(
                    acceptance_module._same_file_snapshot(base, missing_mtime)
                )

            with mock.patch.object(acceptance_module.os, "name", "posix"):
                self.assertTrue(
                    acceptance_module._same_file_snapshot(base, base)
                )
                self.assertFalse(
                    acceptance_module._same_file_snapshot(base, ctime_drift)
                )
                self.assertFalse(
                    acceptance_module._same_file_snapshot(base, missing_ctime)
                )
                self.assertFalse(
                    acceptance_module._same_file_snapshot(base, bool_size)
                )

    def test_physical_publication_snapshot_ignores_ctime_but_requires_mtime(self):
        base = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )
        ctime_drift = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=999,
        )
        mtime_drift = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=124,
            st_ctime_ns=456,
        )
        missing_mtime = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_ctime_ns=456,
        )

        with mock.patch.object(
            acceptance_module,
            "_same_file_identity",
            return_value=True,
        ):
            self.assertTrue(
                acceptance_module._same_publication_snapshot(
                    base,
                    ctime_drift,
                )
            )
            self.assertFalse(
                acceptance_module._same_publication_snapshot(
                    base,
                    mtime_drift,
                )
            )
            self.assertFalse(
                acceptance_module._same_publication_snapshot(
                    base,
                    missing_mtime,
                )
            )

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

    def test_post_link_readback_failure_cleans_owned_output_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "physical.json"
            payload = b'{"accepted":true}\n'

            with mock.patch.object(
                acceptance_module,
                "_stable_bytes",
                return_value=b'{"accepted":false}\n',
            ):
                with self.assertRaisesRegex(
                    OwnerPhysicalAcceptanceError,
                    "published bytes do not match",
                ):
                    acceptance_module._publish_exclusive(output, payload)

            self.assertFalse(output.exists())

            acceptance_module._publish_exclusive(output, payload)
            self.assertEqual(output.read_bytes(), payload)

    def test_post_link_durability_failure_cleans_owned_output_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "physical.json"
            payload = b'{"accepted":true}\n'

            with mock.patch.object(
                acceptance_module,
                "_sync_published_zip_namespace",
                side_effect=acceptance_module.Version2PortablePackageError(
                    "simulated durability failure"
                ),
            ):
                with self.assertRaisesRegex(
                    OwnerPhysicalAcceptanceError,
                    "durability could not be confirmed",
                ):
                    acceptance_module._publish_exclusive(output, payload)

            self.assertFalse(output.exists())

            acceptance_module._publish_exclusive(output, payload)
            self.assertEqual(output.read_bytes(), payload)

    def test_successful_publication_crosses_namespace_durability_barrier(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "physical.json"
            payload = b'{"accepted":true}\n'

            original = acceptance_module._sync_published_zip_namespace
            with mock.patch.object(
                acceptance_module,
                "_sync_published_zip_namespace",
                wraps=original,
            ) as durability:
                acceptance_module._publish_exclusive(output, payload)

            self.assertEqual(durability.call_count, 1)
            _args, kwargs = durability.call_args
            self.assertEqual(Path(_args[0]), output)
            self.assertIn("expected", kwargs)
            self.assertTrue(output.is_file())
            self.assertEqual(output.read_bytes(), payload)

    def test_post_link_cleanup_preserves_replaced_canonical_path(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "physical.json"
            payload = b'{"accepted":true}\n'
            foreign = b'{"foreign":true}\n'

            def replace_before_readback(path, **_kwargs):
                current = Path(path)
                current.unlink()
                current.write_bytes(foreign)
                return b'{"accepted":false}\n'

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

            self.assertTrue(output.is_file())
            self.assertEqual(output.read_bytes(), foreign)

    def test_post_link_same_bytes_foreign_identity_is_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "physical.json"
            foreign = root / "foreign.json"
            payload = b'{"accepted":true}\n'
            foreign.write_bytes(payload)

            def substitute_same_bytes(path, **_kwargs):
                current = Path(path)
                current.unlink()
                acceptance_module.os.link(foreign, current)
                return payload

            with mock.patch.object(
                acceptance_module,
                "_stable_bytes",
                side_effect=substitute_same_bytes,
            ):
                with self.assertRaisesRegex(
                    OwnerPhysicalAcceptanceError,
                    "changed during publication readback",
                ):
                    acceptance_module._publish_exclusive(output, payload)

            self.assertTrue(output.is_file())
            self.assertTrue(output.samefile(foreign))
            self.assertEqual(output.read_bytes(), payload)

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

    def test_verifier_rejects_boolean_finalizer_attempt_equal_to_one(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            receipt = _machine_receipt(final_zip, finalizer_run_attempt=1)
            _write_machine_receipt(machine, receipt)
            output = root / "physical.json"

            _record(machine, final_zip, output, _scenarios())
            value = acceptance_module._canonical_object_from_bytes(
                output.read_bytes(),
                label="owner physical acceptance record",
                expected_keys=acceptance_module.ACCEPTANCE_RECORD_KEYS,
            )
            value["machine_finalizer_run_attempt"] = True
            output.write_text(
                __import__("json").dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                OwnerPhysicalAcceptanceError,
                "finalizer run attempt must be a positive integer",
            ):
                _verify(output, machine, final_zip)

    def test_verifier_rejects_boolean_finalizer_run_id_equal_to_one(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            receipt = _machine_receipt(final_zip, finalizer_run_id=1)
            _write_machine_receipt(machine, receipt)
            output = root / "physical.json"

            _record(machine, final_zip, output, _scenarios())
            value = acceptance_module._canonical_object_from_bytes(
                output.read_bytes(),
                label="owner physical acceptance record",
                expected_keys=acceptance_module.ACCEPTANCE_RECORD_KEYS,
            )
            value["machine_finalizer_run_id"] = True
            output.write_text(
                __import__("json").dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                OwnerPhysicalAcceptanceError,
                "finalizer run id must be a positive integer",
            ):
                _verify(output, machine, final_zip)

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

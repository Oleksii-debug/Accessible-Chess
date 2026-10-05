from __future__ import annotations

import unittest

from scripts.record_owner_physical_acceptance import (
    OwnerPhysicalAcceptanceError,
    _canonical_object_from_bytes,
)


class OwnerPhysicalAcceptanceJsonHardeningTests(unittest.TestCase):
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

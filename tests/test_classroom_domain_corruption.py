from __future__ import annotations

import json
import unittest

from acs import classroom_domain as cd


class ClassroomDomainCorruptionTests(unittest.TestCase):
    def test_direct_text_rejects_unpaired_unicode_surrogates(self) -> None:
        for value in ("bad\ud800", "bad\udfff"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(cd.ClassroomDomainError):
                    cd.Student("s1", value)
                with self.assertRaises(cd.ClassroomDomainError):
                    cd.TeacherNote("n1", "s1", value, "2026-08-22T19:00:00Z")

    def test_literal_surrogate_json_fails_with_domain_error_before_utf8_size_crash(self) -> None:
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_json("\ud800")

    def test_escaped_surrogate_inside_record_fails_as_domain_corruption(self) -> None:
        record = cd.ClassroomSnapshot(students=(cd.Student("s1", "Alias"),)).to_record()
        record["students"][0]["pseudonym"] = "\ud800"
        text = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_json(text)

    def test_revision_is_bounded_to_cross_runtime_exact_json_integer(self) -> None:
        self.assertEqual(cd.Student("s1", "Alias", revision=cd.MAX_WIRE_INTEGER).revision, cd.MAX_WIRE_INTEGER)
        for value in (cd.MAX_WIRE_INTEGER + 1, 10**5000):
            with self.subTest(digits=len(str(value)) if value <= cd.MAX_WIRE_INTEGER + 1 else "huge"):
                with self.assertRaises(cd.ClassroomDomainError):
                    cd.Student("s1", "Alias", revision=value)
                with self.assertRaises(cd.ClassroomDomainError):
                    cd.Progress("p1", "s1", "c1", (), revision=value)

    def test_huge_json_integer_is_rejected_before_python_integer_digit_limit(self) -> None:
        huge = "9" * 5000
        text = '{"version":' + huge + '}'
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_json(text)

    def test_wire_integer_outside_exact_json_range_is_rejected(self) -> None:
        text = '{"version":9007199254740992}'
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_json(text)

    def test_deep_hostile_json_is_wrapped_as_domain_corruption(self) -> None:
        text = "[" * 1500 + "0" + "]" * 1500
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_json(text)

    def test_valid_non_ascii_unicode_round_trip_remains_deterministic(self) -> None:
        snapshot = cd.ClassroomSnapshot(
            students=(cd.Student("s1", "Кінь-♞"),),
        )
        text = snapshot.to_json()
        self.assertEqual(cd.ClassroomSnapshot.from_json(text), snapshot)
        self.assertEqual(cd.ClassroomSnapshot.from_json(text).to_json(), text)


if __name__ == "__main__":
    unittest.main()

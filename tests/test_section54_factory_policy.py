from __future__ import annotations

import unittest
from acs.format_factory_policy import (
    FactoryJobPolicy, FactoryPolicyError, FactorySelection,
    parse_selector_ranges, parse_factory_scope_command,
)

SOURCE_SHA = "d" * 64


def sample(**kw: object) -> FactoryJobPolicy:
    args: dict[str, object] = dict(
        source_sha256=SOURCE_SHA, source_id="book-17",
        selection=FactorySelection("all"), output_formats=("epub3", "pgn"),
        output_language="uk", allowed_external_search=False,
        allowed_external_ai=False,
    )
    args.update(kw)
    return FactoryJobPolicy(**args)


class FactoryPolicyTests(unittest.TestCase):
    def test_noncontiguous_ranges_normalize_without_duplicates(self) -> None:
        self.assertEqual(parse_selector_ranges("9-11, 1-2,2-4,8, 10"), ((1, 4), (8, 11)))

    def test_invalid_ranges_do_not_expand_unbounded(self) -> None:
        for value in ("0", "1-0", "1-999999", "-7", "1,,2", "1/2", "1000001"):
            with self.subTest(value=value), self.assertRaises(FactoryPolicyError):
                parse_selector_ranges(value)

    def test_scope_separation_is_explicit(self) -> None:
        self.assertNotEqual(FactorySelection.from_text("printed_pages", "2-4"),
                            FactorySelection.from_text("file_pages", "2-4"))
        with self.assertRaises(FactoryPolicyError):
            FactorySelection("all", ((1, 2),))

    def test_supported_natural_language_intent(self) -> None:
        self.assertEqual(parse_factory_scope_command("повністю всю книгу"), FactorySelection("all"))
        self.assertEqual(parse_factory_scope_command("лише глава 3"), FactorySelection.from_text("chapters", "3"))
        self.assertEqual(parse_factory_scope_command("сторінки 12–38"), FactorySelection.from_text("printed_pages", "12-38"))
        self.assertEqual(parse_factory_scope_command("до сторінки 60", printed_pages=False), FactorySelection.from_text("file_pages", "1-60"))
        self.assertEqual(parse_factory_scope_command("позиції 5–24"), FactorySelection.from_text("positions", "5-24"))
        self.assertEqual(parse_factory_scope_command("перші 20 партій"), FactorySelection.from_text("games", "1-20"))

    def test_ambiguous_scope_fails_closed(self) -> None:
        for cmd in ("зроби добре", "всі діаграми", "сторінки 3 або 5", "перші 0 партій"):
            with self.subTest(cmd=cmd), self.assertRaises(FactoryPolicyError):
                parse_factory_scope_command(cmd)

    def test_external_ai_requires_specific_consent_provider_model_limits(self) -> None:
        with self.assertRaises(FactoryPolicyError):
            sample(allowed_external_ai=True)
        policy = sample(
            allowed_external_ai=True, provider_id="mistral", model_id="mistral-small",
            max_input_tokens=1000, max_output_tokens=300,
        )
        self.assertTrue(policy.allowed_external_ai)
        self.assertEqual(policy.max_output_tokens, 300)

    def test_provider_fields_without_consent_forbidden(self) -> None:
        with self.assertRaises(FactoryPolicyError):
            sample(provider_id="mistral")
        with self.assertRaises(FactoryPolicyError):
            sample(allowed_external_ai=True, provider_id="mistral", model_id="mistral-small",
                   max_input_tokens=True, max_output_tokens=10)

    def test_policy_snapshot_deterministic_and_separates_job_owners(self) -> None:
        first = sample()
        self.assertEqual(first.digest(), sample().digest())
        self.assertNotEqual(first.digest(), sample(source_id="book-18").digest())
        self.assertEqual(first.snapshot()["selection"], {"kind": "all", "ranges": []})

    def test_duplicate_output_and_unapproved_format_rejected(self) -> None:
        with self.assertRaises(FactoryPolicyError):
            sample(output_formats=("pgn", "pgn"))
        with self.assertRaises(FactoryPolicyError):
            sample(output_formats=("braille",))


if __name__ == "__main__":
    unittest.main()

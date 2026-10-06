from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_policy import normalize_search_result
from acs.search_service import GameSearchQuery


class SearchResultFilterPolicyTests(unittest.TestCase):
    def test_exact_builtin_result_tokens_and_none_are_preserved(self) -> None:
        for token in (None, "1-0", "0-1", "1/2-1/2", "*"):
            with self.subTest(token=token):
                self.assertIs(normalize_search_result(token), token)

    def test_unknown_builtin_result_token_remains_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported chess result"):
            normalize_search_result("draw")

    def test_text_subclass_is_rejected_before_hashing_at_all_public_ingress(self) -> None:
        class HashForbiddenString(str):
            def __hash__(self):
                raise AssertionError("untrusted string subclass must not be hashed")

        hostile = HashForbiddenString("1-0")
        with self.assertRaisesRegex(TypeError, "result must be text"):
            normalize_search_result(hostile)

        with self.assertRaisesRegex(TypeError, "result must be text"):
            GameSearchQuery(result=hostile).normalized()  # type: ignore[arg-type]

        with AcsDatabase() as database:
            with self.assertRaisesRegex(TypeError, "result must be text"):
                database.search_games(result=hostile)

    def test_non_text_object_is_rejected_before_hash_or_string_coercion(self) -> None:
        class HostileScalar:
            def __hash__(self):
                raise AssertionError("untrusted scalar must not be hashed")

            def __str__(self):
                raise AssertionError("untrusted scalar must not be stringified")

        hostile = HostileScalar()
        with self.assertRaisesRegex(TypeError, "result must be text"):
            normalize_search_result(hostile)

        with self.assertRaisesRegex(TypeError, "result must be text"):
            GameSearchQuery(result=hostile).normalized()  # type: ignore[arg-type]

        with AcsDatabase() as database:
            with self.assertRaisesRegex(TypeError, "result must be text"):
                database.search_games(result=hostile)


if __name__ == "__main__":
    unittest.main()

import hashlib
import unittest
from dataclasses import replace

from acs.chessbase_cbg_payload_evidence import ClassicCbgMovePayloadEvidence
from acs.chessbase_cbg_tokens import (
    MAX_CLASSIC_CBG_TOKEN_FRAMES,
    MAX_CLASSIC_CBG_VARIATION_DEPTH,
    CbgTokenFramingCode,
    CbgTokenFramingError,
    frame_cbg_move_payload_evidence,
)


def _evidence(
    payload: bytes,
    *,
    game_offset: int = 8,
    payload_start_offset: int = 40,
    custom: bool = True,
) -> ClassicCbgMovePayloadEvidence:
    return ClassicCbgMovePayloadEvidence(
        game_offset=game_offset,
        payload_start_offset=payload_start_offset,
        game_end_offset=payload_start_offset + len(payload),
        payload_bytes=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        custom_setup_prefix_consumed=custom,
    )


class ClassicCbgTokenFramingTests(unittest.TestCase):
    def assert_code(self, expected, callable_, *args, **kwargs):
        with self.assertRaises(CbgTokenFramingError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)

    def test_mixed_stream_preserves_exact_frames_and_counter_rules(self):
        # Decoded values at successive counters:
        # 84, DC, AA, 0C, 9F, 29(A295), 0C(final).
        payload = bytes.fromhex("84 dd ab 0e a1 2b 02 03 0f")
        framed = frame_cbg_move_payload_evidence(_evidence(payload))

        self.assertEqual(
            [token.kind for token in framed.tokens],
            [
                "one_byte_candidate",
                "variation_start",
                "null_move_candidate",
                "variation_end",
                "filler",
                "two_byte_candidate",
                "terminal",
            ],
        )
        self.assertEqual(
            [token.payload_offset for token in framed.tokens],
            [0, 1, 2, 3, 4, 5, 8],
        )
        self.assertEqual(
            [token.source_offset for token in framed.tokens],
            [40, 41, 42, 43, 44, 45, 48],
        )
        self.assertEqual(
            [token.processed_counter_before for token in framed.tokens],
            [0, 1, 1, 2, 2, 2, 3],
        )
        self.assertEqual(
            [token.processed_counter_after for token in framed.tokens],
            [1, 1, 2, 2, 2, 3, 3],
        )
        self.assertEqual(
            [token.variation_depth_before for token in framed.tokens],
            [0, 0, 1, 1, 0, 0, 0],
        )
        self.assertEqual(
            [token.variation_depth_after for token in framed.tokens],
            [0, 1, 1, 0, 0, 0, 0],
        )
        two_byte = framed.tokens[5]
        self.assertEqual(two_byte.raw_bytes, bytes.fromhex("2b 02 03"))
        self.assertEqual(two_byte.encoded_size, 3)
        self.assertEqual(two_byte.deobfuscated_code, 0x29)
        self.assertEqual(two_byte.deobfuscated_word, 0xA295)

        self.assertEqual(framed.payload_sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(framed.payload_length, len(payload))
        self.assertEqual(framed.token_count, 7)
        self.assertEqual(framed.observed_max_variation_depth, 1)
        self.assertTrue(framed.framing_complete)
        self.assertFalse(framed.decoder_available)
        self.assertFalse(framed.safe_to_import)

    def test_final_terminator_is_a_complete_zero_move_frame(self):
        framed = frame_cbg_move_payload_evidence(_evidence(b"\x0c"))
        self.assertEqual(framed.token_count, 1)
        self.assertEqual(framed.tokens[0].kind, "terminal")
        self.assertEqual(framed.tokens[0].raw_bytes, b"\x0c")

    def test_processed_counter_wraps_exactly_at_256_candidates(self):
        candidates = bytes((0x84 + counter) & 0xFF for counter in range(256))
        framed = frame_cbg_move_payload_evidence(
            _evidence(candidates + b"\x0c")
        )

        self.assertEqual(framed.token_count, 257)
        self.assertTrue(
            all(
                token.kind == "one_byte_candidate"
                and token.deobfuscated_code == 0x84
                for token in framed.tokens[:-1]
            )
        )
        self.assertEqual(framed.tokens[-2].processed_counter_after, 0)
        self.assertEqual(framed.tokens[-1].kind, "terminal")
        self.assertEqual(framed.tokens[-1].processed_counter_before, 0)

    def test_every_two_byte_substitution_index_survives_every_counter_value(self):
        decoded_table = bytearray()
        for counter in range(256):
            prefix = bytes(
                (0x84 + prior_counter) & 0xFF
                for prior_counter in range(counter)
            )
            marker = bytes(((0x29 + counter) & 0xFF,))
            operand = (counter + counter) & 0xFF
            terminal = bytes(((0x0C + counter + 1) & 0xFF,))
            payload = prefix + marker + bytes((operand, operand)) + terminal

            with self.subTest(counter=counter):
                framed = frame_cbg_move_payload_evidence(_evidence(payload))
                candidate = framed.tokens[-2]
                self.assertEqual(candidate.kind, "two_byte_candidate")
                self.assertEqual(candidate.processed_counter_before, counter)
                self.assertEqual(candidate.processed_counter_after, (counter + 1) & 0xFF)
                high = candidate.deobfuscated_word >> 8
                low = candidate.deobfuscated_word & 0xFF
                self.assertEqual(high, low)
                decoded_table.append(high)

        self.assertEqual(len(set(decoded_table)), 256)
        self.assertEqual(
            hashlib.sha256(decoded_table).hexdigest(),
            "da7a288e3df671e22f4e04384cfc95dd4f19c7e18aa110b7acdc8d8edba328a4",
        )

    def test_two_byte_marker_requires_both_operand_bytes(self):
        for payload in (b"\x29", b"\x29\x00"):
            with self.subTest(payload=payload):
                self.assert_code(
                    CbgTokenFramingCode.TRUNCATED_TWO_BYTE_TOKEN,
                    frame_cbg_move_payload_evidence,
                    _evidence(payload),
                )

    def test_unmatched_and_unterminated_variations_fail_closed(self):
        self.assert_code(
            CbgTokenFramingCode.UNMATCHED_VARIATION_END,
            frame_cbg_move_payload_evidence,
            _evidence(b"\x0c\x0c"),
        )
        self.assert_code(
            CbgTokenFramingCode.UNTERMINATED_VARIATION,
            frame_cbg_move_payload_evidence,
            _evidence(b"\xdc\x0c"),
        )
        self.assert_code(
            CbgTokenFramingCode.UNTERMINATED_VARIATION,
            frame_cbg_move_payload_evidence,
            _evidence(b"\xdc"),
        )

    def test_missing_final_terminator_fails_closed(self):
        for payload in (b"", b"\x84", b"\x29\x00\x01"):
            with self.subTest(payload=payload):
                self.assert_code(
                    CbgTokenFramingCode.MISSING_TERMINATOR,
                    frame_cbg_move_payload_evidence,
                    _evidence(payload),
                )

    def test_token_and_depth_limits_are_hard_and_stable(self):
        self.assert_code(
            CbgTokenFramingCode.TOKEN_LIMIT,
            frame_cbg_move_payload_evidence,
            _evidence(b"\x84\x0d"),
            max_tokens=1,
        )
        self.assert_code(
            CbgTokenFramingCode.VARIATION_DEPTH_LIMIT,
            frame_cbg_move_payload_evidence,
            _evidence(b"\xdc\xdc\x0c\x0c\x0c"),
            max_variation_depth=1,
        )

        invalid_token_limits = (-1, True, 1.5, MAX_CLASSIC_CBG_TOKEN_FRAMES + 1)
        for value in invalid_token_limits:
            with self.subTest(max_tokens=value):
                self.assert_code(
                    CbgTokenFramingCode.INVALID_LIMIT,
                    frame_cbg_move_payload_evidence,
                    _evidence(b"\x0c"),
                    max_tokens=value,
                )

        invalid_depth_limits = (
            -1,
            True,
            1.5,
            MAX_CLASSIC_CBG_VARIATION_DEPTH + 1,
        )
        for value in invalid_depth_limits:
            with self.subTest(max_variation_depth=value):
                self.assert_code(
                    CbgTokenFramingCode.INVALID_LIMIT,
                    frame_cbg_move_payload_evidence,
                    _evidence(b"\x0c"),
                    max_variation_depth=value,
                )

    def test_untrusted_evidence_dto_is_revalidated_before_framing(self):
        valid = _evidence(b"\x0c")
        invalid = (
            object(),
            replace(valid, payload_sha256="0" * 64),
            replace(valid, game_end_offset=valid.game_end_offset + 1),
            replace(valid, payload_bytes=bytearray(b"\x0c")),
            replace(valid, payload_start_offset=True),
            replace(valid, custom_setup_prefix_consumed=1),
            replace(valid, custom_setup_prefix_consumed=False),
            replace(valid, payload_sha256=object()),
        )
        for evidence in invalid:
            with self.subTest(evidence=evidence):
                self.assert_code(
                    CbgTokenFramingCode.INVALID_EVIDENCE,
                    frame_cbg_move_payload_evidence,
                    evidence,
                )

    def test_framing_does_not_expose_chess_or_import_semantics(self):
        framed = frame_cbg_move_payload_evidence(_evidence(b"\x84\x0d"))
        candidate = framed.tokens[0]

        for forbidden in (
            "move",
            "source_square",
            "destination_square",
            "position",
            "fen",
            "legality",
            "annotations",
            "game_tree",
        ):
            self.assertFalse(hasattr(candidate, forbidden), forbidden)
        self.assertFalse(framed.decoder_available)
        self.assertFalse(framed.safe_to_import)


if __name__ == "__main__":
    unittest.main()

import unittest

from acs.sound_events import MoveSoundFacts, SoundEvent, SoundEventPolicy


class SoundEventPolicyTests(unittest.TestCase):
    def test_game_boundary_events_are_explicit(self):
        self.assertEqual(SoundEventPolicy.game_start(), (SoundEvent.START,))
        self.assertEqual(SoundEventPolicy.game_end(), (SoundEvent.END,))
        self.assertEqual(SoundEventPolicy.illegal(), (SoundEvent.ILLEGAL,))

    def test_plain_move_emits_move_only(self):
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts()),
            (SoundEvent.MOVE,),
        )

    def test_capture_emits_capture_as_primary_event(self):
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(capture=True)),
            (SoundEvent.CAPTURE,),
        )

    def test_check_is_additional_to_primary_move_event(self):
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(check=True)),
            (SoundEvent.MOVE, SoundEvent.CHECK),
        )
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(capture=True, check=True)),
            (SoundEvent.CAPTURE, SoundEvent.CHECK),
        )

    def test_castling_and_promotion_have_specific_primary_events(self):
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(castle=True)),
            (SoundEvent.CASTLE,),
        )
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(promotion=True)),
            (SoundEvent.PROMOTION,),
        )

    def test_capturing_promotion_uses_promotion_without_duplicate_primary_sound(self):
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(capture=True, promotion=True)),
            (SoundEvent.PROMOTION,),
        )

    def test_terminal_move_appends_end_after_check(self):
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(check=True, game_ended=True)),
            (SoundEvent.MOVE, SoundEvent.CHECK, SoundEvent.END),
        )
        self.assertEqual(
            SoundEventPolicy.for_move(
                MoveSoundFacts(capture=True, check=True, game_ended=True)
            ),
            (SoundEvent.CAPTURE, SoundEvent.CHECK, SoundEvent.END),
        )

    def test_illegal_move_is_standalone(self):
        self.assertEqual(
            SoundEventPolicy.for_move(MoveSoundFacts(legal=False)),
            (SoundEvent.ILLEGAL,),
        )

    def test_impossible_fact_combinations_are_rejected(self):
        with self.assertRaises(ValueError):
            MoveSoundFacts(legal=False, check=True)
        with self.assertRaises(ValueError):
            MoveSoundFacts(castle=True, capture=True)
        with self.assertRaises(ValueError):
            MoveSoundFacts(castle=True, promotion=True)


if __name__ == "__main__":
    unittest.main()

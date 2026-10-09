from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import unittest

from acs.format_factory_tokens import (
    FactoryTokenGovernor, FactoryTokenLimitError, FactoryTokenUsage,
)


class Section54FactoryTokenGovernorTests(unittest.TestCase):
    def test_hard_input_output_reservation_and_actual_usage(self) -> None:
        governor = FactoryTokenGovernor(max_input_tokens=100, max_output_tokens=50)
        first = governor.reserve(
            request_id="r1", model_id="provider/model", predicted_input_tokens=60,
            max_output_tokens=30, provider_enforces_output_cap=True,
        )
        with self.assertRaises(FactoryTokenLimitError):
            governor.reserve(
                request_id="r2", model_id="provider/model", predicted_input_tokens=41,
                max_output_tokens=10, provider_enforces_output_cap=True,
            )
        self.assertEqual(governor.snapshot().reserved_input_tokens, 60)
        governor.settle(
            first, actual_input_tokens=35, actual_output_tokens=10,
            cached_input_tokens=5, reasoning_output_tokens=2,
        )
        snap = governor.snapshot()
        self.assertEqual(snap.committed_input_tokens, 35)
        self.assertEqual(snap.committed_output_tokens, 10)
        self.assertEqual(snap.reserved_output_tokens, 0)
        self.assertEqual(governor.usage_by_model()["provider/model"], FactoryTokenUsage(35, 10, 5, 2))

    def test_no_paid_call_without_enforceable_output_ceiling(self) -> None:
        governor = FactoryTokenGovernor(max_input_tokens=100, max_output_tokens=50)
        with self.assertRaises(FactoryTokenLimitError):
            governor.reserve(
                request_id="x1", model_id="m", predicted_input_tokens=2,
                max_output_tokens=3, provider_enforces_output_cap=False,
            )
        self.assertEqual(governor.snapshot().reserved_input_tokens, 0)

    def test_output_envelopes_hold_across_parallel_inflight_calls(self) -> None:
        governor = FactoryTokenGovernor(max_input_tokens=100, max_output_tokens=50)
        def take(i: int) -> bool:
            try:
                governor.reserve(
                    request_id=f"r{i}", model_id="m", predicted_input_tokens=10,
                    max_output_tokens=10, provider_enforces_output_cap=True,
                )
                return True
            except FactoryTokenLimitError:
                return False
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(take, range(10)))
        self.assertEqual(sum(results), 5)
        self.assertEqual(governor.snapshot().reserved_output_tokens, 50)

    def test_unknown_billed_tokens_prevent_retry(self) -> None:
        governor = FactoryTokenGovernor(max_input_tokens=100, max_output_tokens=50)
        item = governor.reserve(
            request_id="r1", model_id="m", predicted_input_tokens=10,
            max_output_tokens=10, provider_enforces_output_cap=True,
        )
        governor.fail_after_dispatch(item)
        self.assertEqual(governor.snapshot().blocked_reason, "UNKNOWN_PROVIDER_USAGE")
        with self.assertRaises(FactoryTokenLimitError):
            governor.reserve(
                request_id="r2", model_id="m", predicted_input_tokens=10,
                max_output_tokens=10, provider_enforces_output_cap=True,
            )

    def test_duplicate_calls_and_double_settlement_blocked(self) -> None:
        governor = FactoryTokenGovernor(max_input_tokens=100, max_output_tokens=50)
        reservation = governor.reserve(
            request_id="r1", model_id="m", predicted_input_tokens=10,
            max_output_tokens=10, provider_enforces_output_cap=True,
        )
        with self.assertRaises(FactoryTokenLimitError):
            governor.reserve(
                request_id="r1", model_id="m", predicted_input_tokens=10,
                max_output_tokens=10, provider_enforces_output_cap=True,
            )
        governor.settle(reservation, actual_input_tokens=8, actual_output_tokens=9)
        with self.assertRaises(FactoryTokenLimitError):
            governor.settle(reservation, actual_input_tokens=8, actual_output_tokens=9)

    def test_usage_over_reservation_blocks_later_calls(self) -> None:
        governor = FactoryTokenGovernor(max_input_tokens=100, max_output_tokens=50)
        reservation = governor.reserve(
            request_id="r1", model_id="m", predicted_input_tokens=10,
            max_output_tokens=10, provider_enforces_output_cap=True,
        )
        with self.assertRaises(FactoryTokenLimitError):
            governor.settle(reservation, actual_input_tokens=11, actual_output_tokens=8)
        self.assertEqual(governor.snapshot().blocked_reason, "REPORTED_OVER_ENVELOPE")

    def test_only_pre_dispatch_cancel_refunds(self) -> None:
        governor = FactoryTokenGovernor(max_input_tokens=10, max_output_tokens=10)
        reservation = governor.reserve(
            request_id="a", model_id="m", predicted_input_tokens=10,
            max_output_tokens=10, provider_enforces_output_cap=True,
        )
        governor.cancel_before_dispatch(reservation)
        self.assertEqual(governor.snapshot().remaining_input_tokens, 10)

    def test_validation_rejects_bool_negative_and_cached_overreport(self) -> None:
        with self.assertRaises(FactoryTokenLimitError):
            FactoryTokenGovernor(max_input_tokens=True, max_output_tokens=10)
        governor = FactoryTokenGovernor(max_input_tokens=100, max_output_tokens=100)
        reservation = governor.reserve(
            request_id="x", model_id="m", predicted_input_tokens=20,
            max_output_tokens=10, provider_enforces_output_cap=True,
        )
        with self.assertRaises(FactoryTokenLimitError):
            governor.settle(
                reservation, actual_input_tokens=10, actual_output_tokens=3,
                cached_input_tokens=11,
            )
        self.assertEqual(governor.snapshot().reserved_input_tokens, 20)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import asyncio
import unittest
from decimal import Decimal

from acs.agent_accessibility import format_agent_status, format_media_status
from acs.agent_budget import AgentBudgetLedger
from acs.keyed_async_lock import KeyedAsyncLock
from acs.public_errors import PublicApplicationError


class CrossRepoSafetyReuseTests(unittest.TestCase):
    def test_budget_reserve_settle_and_reconcile(self):
        ledger = AgentBudgetLedger("10.00")
        ledger.reserve("req-1", "3.00")
        self.assertEqual(ledger.snapshot().available, Decimal("7.00"))
        ledger.settle("req-1", incurred="1.50", estimated_unbilled="0.50")
        snap = ledger.snapshot()
        self.assertEqual(snap.incurred, Decimal("1.50"))
        self.assertEqual(snap.estimated_unbilled, Decimal("0.50"))
        self.assertEqual(snap.available, Decimal("8.00"))
        ledger.reconcile_unbilled(
            billing_id="bill-1",
            request_id="req-1",
            billed="0.40",
        )
        snap = ledger.snapshot()
        self.assertEqual(snap.incurred, Decimal("1.90"))
        self.assertEqual(snap.estimated_unbilled, Decimal("0.10"))

    def test_budget_rejects_over_reservation_and_conflict(self):
        ledger = AgentBudgetLedger("1.00")
        ledger.reserve("req-1", "0.75")
        with self.assertRaises(ValueError):
            ledger.reserve("req-2", "0.50")
        with self.assertRaises(ValueError):
            ledger.reserve("req-1", "0.50")

    def test_accessible_agent_status_is_plain_and_complete(self):
        text = format_agent_status(
            {
                "state": "running",
                "task_id": "review-1",
                "provider_id": "local",
                "model": "coach",
                "tool_id": "board.square",
                "steps": 4,
            }
        )
        self.assertIn("Accessible Chess agent status", text)
        self.assertIn("State: running", text)
        self.assertIn("Current tool: board.square", text)
        self.assertNotIn("\x1b", text)

    def test_accessible_media_status_exposes_restore(self):
        text = format_media_status(
            {
                "playback_state": "paused",
                "current_ms": 42000,
                "reconciliation_status": "verified",
                "position_id": "p42",
                "move_id": "Nf3",
                "analysis_detached": True,
            }
        )
        self.assertIn("Restore Media Position is available", text)

    def test_public_error_strips_unsafe_metadata(self):
        err = PublicApplicationError(
            "Bad request",
            status=400,
            code="bad_request",
            details={
                "field": "position_id",
                "path": "C:\\private\\secret",
                "reason": "invalid_state",
            },
        )
        payload = err.public_payload("request-1")
        self.assertEqual(payload["error"]["details"]["field"], "position_id")
        self.assertNotIn("path", payload["error"]["details"])

    def test_public_error_fails_closed_on_header_injection(self):
        err = PublicApplicationError(
            "bad\r\nInjected: yes",
            status=400,
            code="bad_request",
        )
        self.assertEqual(err.status, 500)
        self.assertEqual(err.code, "internal_error")
        self.assertEqual(err.message, "Internal server error")

    def test_keyed_lock_serializes_same_key(self):
        async def scenario():
            lock = KeyedAsyncLock()
            order: list[str] = []

            async def op(name: str, delay: float):
                async def body():
                    order.append(name + ":start")
                    await asyncio.sleep(delay)
                    order.append(name + ":end")
                await lock.run("media-1", body)

            await asyncio.gather(op("a", 0.01), op("b", 0.0))
            return order, await lock.active_keys()

        order, active = asyncio.run(scenario())
        self.assertEqual(order, ["a:start", "a:end", "b:start", "b:end"])
        self.assertEqual(active, ())

    def test_keyed_lock_allows_different_keys(self):
        async def scenario():
            lock = KeyedAsyncLock()
            started = asyncio.Event()
            release = asyncio.Event()
            second_started = asyncio.Event()

            async def first():
                async def body():
                    started.set()
                    await release.wait()
                await lock.run("a", body)

            async def second():
                await started.wait()
                async def body():
                    second_started.set()
                await lock.run("b", body)
                release.set()

            await asyncio.wait_for(asyncio.gather(first(), second()), timeout=1.0)
            return second_started.is_set()

        self.assertTrue(asyncio.run(scenario()))


if __name__ == "__main__":
    unittest.main()

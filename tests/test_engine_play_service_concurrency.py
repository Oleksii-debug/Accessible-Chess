import threading
import unittest

from acs.engine_play_service import EnginePlayService
from acs.engine_ports import EngineContractError, EngineContractErrorCode, EngineMoveRequest


class BlockingMoveEngine:
    def __init__(self):
        self._state_lock = threading.Lock()
        self.entered = threading.Event()
        self.second_entered = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()
        self.calls = 0
        self.inflight = 0
        self.max_inflight = 0
        self.close_calls = 0

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        with self._state_lock:
            self.calls += 1
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            if self.calls == 1:
                self.entered.set()
            else:
                self.second_entered.set()
        self.release.wait(2)
        with self._state_lock:
            self.inflight -= 1
        return 'e2e4'

    def close(self):
        with self._state_lock:
            self.close_calls += 1
        self.closed.set()


class FlakyCloseMoveEngine(BlockingMoveEngine):
    def close(self):
        with self._state_lock:
            self.close_calls += 1
            close_calls = self.close_calls
        if close_calls == 1:
            raise RuntimeError('temporary close failure')
        self.closed.set()


class EnginePlayServiceConcurrencyTests(unittest.TestCase):
    def test_close_is_terminal_and_factory_never_runs_after_close(self):
        calls = []
        service = EnginePlayService(lambda: calls.append(1) or BlockingMoveEngine())

        service.close()
        service.close()

        with self.assertRaises(EngineContractError) as caught:
            service.choose_move(EngineMoveRequest('fen'))
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_SESSION)
        self.assertEqual(calls, [])

    def test_close_is_idempotent_and_closes_owned_provider_once(self):
        engine = BlockingMoveEngine()
        engine.release.set()
        service = EnginePlayService(lambda: engine)
        service.choose_move(EngineMoveRequest('fen'))

        service.close()
        service.close()

        self.assertEqual(engine.close_calls, 1)
        self.assertTrue(engine.closed.is_set())

    def test_concurrent_requests_share_one_factory_and_serialize_provider_access(self):
        engine = BlockingMoveEngine()
        factory_calls = []
        service = EnginePlayService(lambda: factory_calls.append(1) or engine)
        results = []
        errors = []

        def choose(fen):
            try:
                results.append(service.choose_move(EngineMoveRequest(fen)).move)
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        first = threading.Thread(target=choose, args=('fen-1',))
        second = threading.Thread(target=choose, args=('fen-2',))
        first.start()
        self.assertTrue(engine.entered.wait(1))
        second.start()

        # The second call cannot enter the stateful provider while the first is
        # blocked. In an unlocked implementation second_entered becomes set.
        self.assertFalse(engine.second_entered.wait(0.1))
        engine.release.set()
        first.join(2)
        second.join(2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(factory_calls, [1])
        self.assertEqual(engine.calls, 2)
        self.assertEqual(engine.max_inflight, 1)

    def test_close_waits_for_inflight_request_then_prevents_reopen(self):
        engine = BlockingMoveEngine()
        service = EnginePlayService(lambda: engine)
        results = []

        worker = threading.Thread(
            target=lambda: results.append(service.choose_move(EngineMoveRequest('fen')).move)
        )
        worker.start()
        self.assertTrue(engine.entered.wait(1))

        closer = threading.Thread(target=service.close)
        closer.start()
        self.assertFalse(engine.closed.wait(0.1))

        engine.release.set()
        worker.join(2)
        closer.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertEqual(results, ['e2e4'])
        self.assertTrue(engine.closed.is_set())
        self.assertEqual(engine.close_calls, 1)

        with self.assertRaises(EngineContractError) as caught:
            service.choose_move(EngineMoveRequest('fen-2'))
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_SESSION)

    def test_borrowed_provider_is_not_closed_but_service_is_still_terminal(self):
        engine = BlockingMoveEngine()
        engine.release.set()
        service = EnginePlayService(lambda: engine, owns_engine=False)
        service.choose_move(EngineMoveRequest('fen'))

        service.close()

        self.assertEqual(engine.close_calls, 0)
        with self.assertRaises(EngineContractError):
            service.choose_move(EngineMoveRequest('fen-2'))

    def test_failed_owned_close_is_retryable_without_reopening_service(self):
        engine = FlakyCloseMoveEngine()
        engine.release.set()
        factory_calls = []
        service = EnginePlayService(
            lambda: factory_calls.append(1) or engine,
        )
        service.choose_move(EngineMoveRequest('fen'))

        with self.assertRaises(EngineContractError) as caught:
            service.close()
        self.assertEqual(
            caught.exception.code,
            EngineContractErrorCode.INVALID_PROVIDER,
        )
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertEqual(str(caught.exception.__cause__), 'temporary close failure')

        with self.assertRaises(EngineContractError) as terminal:
            service.choose_move(EngineMoveRequest('fen-2'))
        self.assertEqual(
            terminal.exception.code,
            EngineContractErrorCode.INVALID_SESSION,
        )

        service.close()
        service.close()

        self.assertEqual(factory_calls, [1])
        self.assertEqual(engine.close_calls, 2)
        self.assertTrue(engine.closed.is_set())


if __name__ == '__main__':
    unittest.main()

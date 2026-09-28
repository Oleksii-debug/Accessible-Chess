from __future__ import annotations

import threading
import unittest

from acs.version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime


class _Delegate:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, action_id: str, payload) -> object:
        self.calls.append((action_id, dict(payload)))
        return "ok"


class Version2WindowsActionUiThreadAffinityTests(unittest.TestCase):
    def _runtime_without_forms(self) -> tuple[Version2WindowsFileWorkflowRuntime, _Delegate]:
        runtime = Version2WindowsFileWorkflowRuntime.__new__(Version2WindowsFileWorkflowRuntime)
        runtime._ui_thread_id = threading.get_ident()
        runtime._lock = threading.RLock()
        runtime._closed = False
        delegate = _Delegate()
        runtime._file_delegate = delegate
        return runtime, delegate

    def test_ui_thread_action_still_reaches_delegate(self) -> None:
        runtime, delegate = self._runtime_without_forms()

        result = runtime("pgn.open", {})

        self.assertEqual(result, "ok")
        self.assertEqual(delegate.calls, [("pgn.open", {})])

    def test_background_action_fails_closed_before_native_workflow_delegate(self) -> None:
        runtime, delegate = self._runtime_without_forms()
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                runtime("pgn.open", {})
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker, name="w3-background-file-action")
        thread.start()
        thread.join(5.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("UI thread", str(errors[0]))
        self.assertEqual(delegate.calls, [])


if __name__ == "__main__":
    unittest.main()

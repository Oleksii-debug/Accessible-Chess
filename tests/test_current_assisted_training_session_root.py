from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisService
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.engine_ports import EngineContractError, EngineContractErrorCode
from acs.training import ExerciseSession


class CurrentAssistedTrainingSessionRootTests(unittest.TestCase):
    def test_training_rejects_session_subclass_before_snapshot_hook(self) -> None:
        class HostileSession(ExerciseSession):
            touched = False

            def snapshot(self):
                type(self).touched = True
                raise AssertionError("rejected Training session snapshot hook must not execute")

        hostile = HostileSession.__new__(HostileSession)
        HostileSession.touched = False

        analysis = AnalysisService(
            lambda: (_ for _ in ()).throw(
                AssertionError("rejected Training session must not construct an engine")
            )
        )
        self.addCleanup(analysis.close)
        service = EngineAssistedWorkflowService(analysis)

        with self.assertRaises(EngineContractError) as caught:
            service.analyze_training(hostile, Board.START)

        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_REQUEST)
        self.assertFalse(HostileSession.touched)


if __name__ == "__main__":
    unittest.main()

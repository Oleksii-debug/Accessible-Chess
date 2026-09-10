from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.engine_game_session import EngineTurnState
from acs.pgn_document import PgnDocumentSession
from acs.version2_application import Version2Application
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


PRODUCT_SHA = "2c981d33189870e7f1e2bbbf5b1835d0953fd525"
PGN = '[Event "W6 recovery oracle"]\n[Result "*"]\n\n1. d4 d5 2. c4 e6 *\n'


class _ProbeSession:
    def __init__(self) -> None:
        self.resume_calls = 0
        self.other_calls: dict[str, int] = {}

    def _call(self, name: str):
        self.other_calls[name] = self.other_calls.get(name, 0) + 1
        return None

    def resume(self) -> None:
        self.resume_calls += 1

    def stop(self):
        return self._call("stop")

    def takeback(self):
        return self._call("takeback")

    def offer_draw(self):
        return self._call("offer_draw")

    def resign(self):
        return self._call("resign")

    def snapshot(self):
        # ENGINE is intentional: if retry crosses the external-review guard,
        # Product reaches the real engine-reply boundary after session.resume().
        return SimpleNamespace(
            config=SimpleNamespace(
                engine_side="b",
                level=SimpleNamespace(level=5),
                time_control=SimpleNamespace(
                    initial_ms=0,
                    increment_ms=0,
                    untimed=True,
                ),
            ),
            turn_state=EngineTurnState.ENGINE,
            clock=SimpleNamespace(white_ms=0, black_ms=0),
        )


def _history_records(api: Version2ReleaseAccessibleChessAPI):
    return tuple(
        (
            record.node_id,
            record.parent_id,
            record.snapshot.fen,
            record.snapshot.san,
            record.snapshot.side,
            record.snapshot.last_move,
        )
        for record in api.review_history.tree_nodes()
    )


def _history_digest(records) -> str:
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Version2ReviewEngineRecoveryOracle(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        actual = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
        if actual != PRODUCT_SHA:
            raise AssertionError(
                f"oracle must execute on exact Product SHA {PRODUCT_SHA}; got {actual}"
            )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "review.pgn"
        self.source.write_text(PGN, encoding="utf-8")
        self.book = self.root / "review.md"
        self.book.write_text(
            "# Review\n\nText\n\n```pgn\n" + PGN + "```\n\nAfter\n",
            encoding="utf-8",
        )
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.api = Version2ReleaseAccessibleChessAPI(
            keymap_path=self.root / "keymap.json"
        )
        self.addCleanup(self.api.close_analysis)
        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=self.api.v2_board_dispatch,
            board_position_projector=self.api.project_review_fen,
        )
        self.api.bind_version2_application(self.app)

    def _live(self):
        records = _history_records(self.api)
        return {
            "fen": self.api.board.fen(),
            "sans": tuple(self.api.sans),
            "live_history_node": self.api.live_history_node,
            "history_digest": _history_digest(records),
            "history_owner_identity": id(self.api.review_history),
        }

    def _display(self):
        state = self.api.get_state()
        return {
            "fen": state["fen"],
            "historyLength": state["historyLength"],
            "reviewCursor": state["reviewCursor"],
            "reviewStatus": state["reviewStatus"],
            "atHistoryEnd": state["atHistoryEnd"],
            "moves": state["moves"],
            "lastMove": state["lastMove"],
        }

    def _open_review(self, owner: str):
        played = self.api.make_move("e4")
        self.assertTrue(played["ok"])
        live = self._live()
        self.assertEqual(live["sans"], ("e4",))

        if owner == "pgn":
            self.app.set_document(PgnDocumentSession.open(self.source))
            reviewed_fen = self.app.pgn_commands.current_fen()
            opened = self.app.browser_command("review", "pgn.open_on_board")
            self.assertEqual(opened["kind"], "review")
            self.assertTrue(self.app.pgn_board_active)
        elif owner == "book":
            self.app.open_book(self.book)
            moved = self.app.browser_command("books", "book.next_game")
            self.assertNotEqual(moved["kind"], "error")
            opened = self.app.browser_command("books", "book.open_position")
            self.assertNotEqual(opened["kind"], "error")
            self.assertTrue(self.app.book_workflow.active)
            reviewed_fen = self.app.book_delegate.view().current_fen
        else:
            raise AssertionError(owner)

        display = self._display()
        self.assertEqual(display["fen"], reviewed_fen)
        self.assertNotEqual(display["fen"], live["fen"])
        self.assertEqual(display["historyLength"], 0)
        self.assertFalse(display["atHistoryEnd"])
        self.assertTrue(self.api._external_review_owned())
        return live, display

    def _assert_live_exact(self, expected) -> None:
        actual = self._live()
        self.assertEqual(actual["fen"], expected["fen"])
        self.assertEqual(actual["sans"], expected["sans"])
        self.assertEqual(
            actual["live_history_node"],
            expected["live_history_node"],
            "live history node identity changed",
        )
        self.assertEqual(actual["history_digest"], expected["history_digest"])
        self.assertEqual(
            actual["history_owner_identity"],
            expected["history_owner_identity"],
            "ReviewHistory owner object was replaced",
        )

    def _exercise(self, owner: str) -> None:
        live, displayed = self._open_review(owner)

        probe = _ProbeSession()
        self.api._engine_session = probe
        self.api._engine_game_phase = "error"
        self.api._engine_game_error = "simulated paused/error engine"

        engine_request_calls = 0

        def request_engine_reply():
            nonlocal engine_request_calls
            engine_request_calls += 1
            return True, "probe engine reply"

        self.api._request_engine_reply = request_engine_reply

        # Prove aliases themselves are routed, not hard-coded only to the default
        # "s". A user-remapped standard-position alias must still hit new_game().
        self.api.keymap_service.editor.registry.set_alias(
            "move.standard", "standard-again"
        )

        commands = (
            ("retry", self.api.retry_engine_move),
            ("stop", self.api.stop_engine_game),
            ("takeback", self.api.engine_takeback),
            ("draw", self.api.offer_draw_engine_game),
            ("resign", self.api.resign_engine_game),
            ("new_game_direct", self.api.new_game),
            ("new_game_default_alias_s", lambda: self.api.make_move("s")),
            (
                "new_game_custom_alias",
                lambda: self.api.make_move("standard-again"),
            ),
            ("clear_alias_c", lambda: self.api.make_move("c")),
            ("empty_alias_e", lambda: self.api.make_move("e")),
        )

        counts = {
            "harmless_rejected_commands": 0,
            "session_resume_side_effects": 0,
            "real_engine_requests": 0,
            "session_other_side_effects": 0,
            "live_fen_mutations": 0,
            "san_mutations": 0,
            "history_node_mutations": 0,
            "history_tree_mutations": 0,
            "displayed_review_mutations": 0,
            "review_owner_releases": 0,
        }
        command_reports = []

        for name, command in commands:
            before_live = self._live()
            before_display = self._display()
            before_resume = probe.resume_calls
            before_requests = engine_request_calls
            before_other = sum(probe.other_calls.values())
            before_owned = self.api._external_review_owned()

            result = command()

            after_live = self._live()
            after_display = self._display()
            after_owned = self.api._external_review_owned()
            resume_delta = probe.resume_calls - before_resume
            request_delta = engine_request_calls - before_requests
            other_delta = sum(probe.other_calls.values()) - before_other

            if before_live["fen"] != after_live["fen"]:
                counts["live_fen_mutations"] += 1
            if before_live["sans"] != after_live["sans"]:
                counts["san_mutations"] += 1
            if before_live["live_history_node"] != after_live["live_history_node"]:
                counts["history_node_mutations"] += 1
            if before_live["history_digest"] != after_live["history_digest"]:
                counts["history_tree_mutations"] += 1
            if before_display != after_display:
                counts["displayed_review_mutations"] += 1
            if before_owned and not after_owned:
                counts["review_owner_releases"] += 1

            counts["session_resume_side_effects"] += resume_delta
            counts["real_engine_requests"] += request_delta
            counts["session_other_side_effects"] += other_delta

            rejected = isinstance(result, dict) and result.get("ok") is False
            clean = (
                rejected
                and resume_delta == 0
                and request_delta == 0
                and other_delta == 0
                and before_live == after_live
                and before_display == after_display
                and before_owned
                and after_owned
            )
            if clean:
                counts["harmless_rejected_commands"] += 1

            command_reports.append(
                {
                    "command": name,
                    "rejected": rejected,
                    "resume_delta": resume_delta,
                    "engine_request_delta": request_delta,
                    "session_other_delta": other_delta,
                    "live_fen_unchanged": before_live["fen"] == after_live["fen"],
                    "san_unchanged": before_live["sans"] == after_live["sans"],
                    "history_node_unchanged": before_live["live_history_node"]
                    == after_live["live_history_node"],
                    "history_tree_unchanged": before_live["history_digest"]
                    == after_live["history_digest"],
                    "displayed_review_unchanged": before_display == after_display,
                    "review_owner_retained": after_owned,
                }
            )

            self.assertTrue(rejected, f"{owner}:{name} was not rejected")
            self.assertEqual(resume_delta, 0, f"{owner}:{name} called session.resume()")
            self.assertEqual(
                request_delta, 0, f"{owner}:{name} reached engine request boundary"
            )
            self.assertEqual(
                other_delta, 0, f"{owner}:{name} mutated engine session"
            )
            self.assertEqual(before_live, after_live, f"{owner}:{name} mutated live state")
            self.assertEqual(
                before_display,
                after_display,
                f"{owner}:{name} changed displayed review state",
            )
            self.assertTrue(after_owned, f"{owner}:{name} released review ownership")

        self.assertEqual(counts["harmless_rejected_commands"], len(commands))
        self.assertEqual(counts["session_resume_side_effects"], 0)
        self.assertEqual(counts["real_engine_requests"], 0)
        self.assertEqual(counts["session_other_side_effects"], 0)
        self.assertEqual(counts["live_fen_mutations"], 0)
        self.assertEqual(counts["san_mutations"], 0)
        self.assertEqual(counts["history_node_mutations"], 0)
        self.assertEqual(counts["history_tree_mutations"], 0)
        self.assertEqual(counts["displayed_review_mutations"], 0)
        self.assertEqual(counts["review_owner_releases"], 0)
        self._assert_live_exact(live)

        # Cleanup is the only permitted ownership release. It must reveal the
        # untouched hidden live board/history, not reset or replay it.
        if owner == "pgn":
            cleanup = self.app.browser_command("review", "pgn.return")
        else:
            cleanup = self.app.browser_command("review", "book.return")
        self.assertEqual(cleanup["kind"], "review")
        self.assertFalse(self.api._external_review_owned())
        counts["review_owner_releases"] += 1
        self._assert_live_exact(live)
        after_cleanup = self._display()
        self.assertEqual(after_cleanup["fen"], live["fen"])

        report = {
            "oracle": "W6_V2_REVIEW_ENGINE_RECOVERY_SIDE_EFFECT_ORACLE",
            "product_sha": PRODUCT_SHA,
            "review_owner": owner,
            "before": {
                "live_fen": live["fen"],
                "san": list(live["sans"]),
                "live_history_node": live["live_history_node"],
                "history_sha256": live["history_digest"],
                "displayed_review": displayed,
            },
            "commands": command_reports,
            "counts": counts,
            "cleanup": {
                "review_owner_released": True,
                "displayed_fen_after_return": after_cleanup["fen"],
                "live_fen_after_return": self.api.board.fen(),
                "san_after_return": list(self.api.sans),
                "live_history_node_after_return": self.api.live_history_node,
                "history_sha256_after_return": _history_digest(
                    _history_records(self.api)
                ),
            },
            "nvda_verified": False,
            "version2_windows_zip": False,
        }
        print("W6_ORACLE_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True))

    def test_pgn_external_review_recovery_matrix(self) -> None:
        self._exercise("pgn")

    def test_book_external_review_recovery_matrix(self) -> None:
        self._exercise("book")


if __name__ == "__main__":
    unittest.main(verbosity=2)

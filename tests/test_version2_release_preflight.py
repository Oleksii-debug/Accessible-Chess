from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile

from acs.release_preflight import ReleasePreflightError, inspect_release_package
from acs.version2_release_preflight import (
    VERSION2_NATIVE_MENU_NAME,
    VERSION2_RELEASE_PROFILE,
    VERSION2_TOP_MENU_IDS,
    inspect_version2_release_package,
)


EVENTS = (
    "move",
    "capture",
    "check",
    "castle",
    "promotion",
    "illegal",
    "start",
    "end",
    "tick",
)


class Version2ReleasePreflightTests(unittest.TestCase):
    def make_package(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name) / "v2 пакет"
        product = root / "AccessibleChess"
        sounds = product / "assets" / "sounds"
        engine = product / "engines" / "stockfish"
        notices = root / "THIRD_PARTY_NOTICES"
        sounds.mkdir(parents=True)
        engine.mkdir(parents=True)
        notices.mkdir(parents=True)

        (product / "AccessibleChess.exe").write_bytes(b"MZ-accessible-chess-v2")
        (engine / "stockfish.exe").write_bytes(b"MZ-stockfish-18")
        for index, event in enumerate(EVENTS, start=1):
            with wave.open(str(sounds / f"{event}.wav"), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(8000)
                wav.writeframes((index.to_bytes(2, "little", signed=True)) * 80)
        (sounds / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "files": {event: f"{event}.wav" for event in EVENTS},
                }
            ),
            encoding="utf-8",
        )

        with zipfile.ZipFile(notices / "Stockfish-18-source.zip", "w") as archive:
            archive.writestr(
                "Stockfish-sf_18/Copying.txt",
                "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007",
            )
            archive.writestr("Stockfish-sf_18/src/main.cpp", "int main(){}")
        (notices / "NOTICE.txt").write_text(
            "Stockfish 18 GPLv3 complete corresponding source included",
            encoding="utf-8",
        )
        (notices / "README.txt").write_text(
            "Stockfish source included",
            encoding="utf-8",
        )

        (root / "native-menu-self-diagnostic.json").write_text(
            json.dumps(
                {
                    "host_exists": True,
                    "menu_exists": True,
                    "host_top_level": True,
                    "parent_is_host": True,
                    "main_menu_strip_is_menu": True,
                    "installed": True,
                    "menu_name": VERSION2_NATIVE_MENU_NAME,
                    "accessible_role": "MenuBar",
                    "menu_ids": list(VERSION2_TOP_MENU_IDS),
                    "commands": [
                        "Файл",
                        "Гра",
                        "Позиція",
                        "PGN",
                        "Бібліотека",
                        "Імпорт",
                        "Експорт",
                        "Stockfish",
                        "Аналіз",
                        "Книги",
                        "Налаштування",
                        "Довідка",
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "packaged-uia-strict-summary.json").write_text(
            json.dumps(
                {
                    "product_sha": "1" * 40,
                    "app_pid": 4242,
                    "classification": "A",
                    "evidence_complete": True,
                    "move_runtime_id": "42.1.2.3",
                    "e4_fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                    "invalid_e9_fen_unchanged": True,
                    "clipboard": "e9",
                    "semantic_square_count": 64,
                    "board_focus_continuity": True,
                    "black_e5_fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
                    "raw_exception_noise": False,
                }
            ),
            encoding="utf-8",
        )
        (root / "RELEASE_MANIFEST.json").write_text(
            json.dumps(
                {
                    "product": "Accessible Chess",
                    "release_profile": VERSION2_RELEASE_PROFILE,
                    "label": "NVDA TEST CANDIDATE — WAITING FOR USER TEST",
                    "integration_sha": "1" * 40,
                    "qa_commit": "2" * 40,
                    "stockfish": "18",
                    "nvda_verified": False,
                    "strict_cross_process_uia": "PASS",
                    "packaged_e4_e9_clipboard_board_focus": "PASS",
                    "packaged_sound": "PASS",
                    "stockfish_runtime_lifecycle": "PASS",
                    "native_menu_automated_self_diagnostic": "PASS",
                    "native_menu_alt_arrows_enter_esc": "HUMAN-ONLY UNPROVEN",
                    "nvda_menu_usability": "HUMAN-ONLY UNPROVEN",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.rewrite_checksums(root)
        return root

    def rewrite_checksums(self, root: Path) -> None:
        files = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.name != "SHA256SUMS.txt"
            ),
            key=lambda path: path.relative_to(root).as_posix().casefold(),
        )
        rows = [
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(root).as_posix()}"
            for path in files
        ]
        (root / "SHA256SUMS.txt").write_text(
            "\n".join(rows) + "\n",
            encoding="utf-8",
        )

    def rejected(self, root: Path, fragment: str) -> None:
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_version2_release_package(root)
        self.assertIn(fragment, str(caught.exception))

    def test_exact_v2_profile_passes_with_shared_stage1_board_evidence(self) -> None:
        root = self.make_package()
        report = inspect_version2_release_package(root)
        self.assertEqual(report.integration_sha, "1" * 40)
        self.assertEqual(report.qa_commit, "2" * 40)
        self.assertEqual(report.checksums_verified, len(report.inventory) - 1)

    def test_release_profile_is_mandatory_and_exact(self) -> None:
        for value in (None, "stage1", "Version2", "full-product"):
            with self.subTest(value=value):
                root = self.make_package()
                path = root / "RELEASE_MANIFEST.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                if value is None:
                    data.pop("release_profile")
                else:
                    data["release_profile"] = value
                path.write_text(json.dumps(data), encoding="utf-8")
                self.rewrite_checksums(root)
                self.rejected(root, "release_profile=version2")

    def test_stage1_menu_cannot_masquerade_as_v2_candidate(self) -> None:
        root = self.make_package()
        path = root / "native-menu-self-diagnostic.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["menu_name"] = "AccessibleChessMainMenu"
        data.pop("menu_ids")
        data["commands"] = ["File", "Game", "Board", "Analysis", "Settings", "Help"]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.rewrite_checksums(root)
        self.rejected(root, "Version 2 native menu diagnostic menu identity mismatch")

    def test_v2_menu_ids_are_canonical_ordered_and_complete(self) -> None:
        root = self.make_package()
        path = root / "native-menu-self-diagnostic.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["menu_ids"] = list(reversed(VERSION2_TOP_MENU_IDS))
        path.write_text(json.dumps(data), encoding="utf-8")
        self.rewrite_checksums(root)
        self.rejected(root, "Version 2 native menu id inventory mismatch")

        root = self.make_package()
        path = root / "native-menu-self-diagnostic.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["commands"] = data["commands"][:-1]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.rewrite_checksums(root)
        self.rejected(root, "Version 2 native menu command inventory mismatch")

    def test_human_nvda_gates_remain_unproven(self) -> None:
        root = self.make_package()
        path = root / "RELEASE_MANIFEST.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["nvda_verified"] = True
        path.write_text(json.dumps(data), encoding="utf-8")
        self.rewrite_checksums(root)
        self.rejected(root, "nvda_verified=false")

        root = self.make_package()
        path = root / "RELEASE_MANIFEST.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["nvda_menu_usability"] = "PASS"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.rewrite_checksums(root)
        self.rejected(root, "HUMAN-ONLY UNPROVEN")

    def test_stage1_preflight_does_not_silently_accept_v2_menu_evidence(self) -> None:
        root = self.make_package()
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        self.assertIn("menu identity mismatch", str(caught.exception))

    def test_v2_preflight_keeps_checksum_fail_closed(self) -> None:
        root = self.make_package()
        (root / "AccessibleChess/AccessibleChess.exe").write_bytes(b"tampered")
        self.rejected(root, "checksum mismatch")


if __name__ == "__main__":
    unittest.main()

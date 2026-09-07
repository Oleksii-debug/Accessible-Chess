from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

from acs import version2_release_payload as payload
from acs.sound_events import SoundEvent
from acs.sound_windows import PackagedSoundAssetResolver
from acs.stockfish_runtime import StockfishRuntimeConfig, resolve_stockfish_path


class Version2ReleasePayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.standalone = self.root / "standalone"
        (self.standalone / "web").mkdir(parents=True)
        (self.standalone / "AccessibleChess.exe").write_bytes(b"MZ\0v2-standalone")
        (self.standalone / "web" / "index.html").write_text(
            "<main>Accessible Chess</main>\n", encoding="utf-8"
        )
        self.sounds = self.root / "sounds"
        self.sounds.mkdir()
        files: dict[str, str] = {}
        for index, event in enumerate(SoundEvent, start=1):
            name = f"{event.value}.wav"
            files[event.value] = name
            self._write_wav(self.sounds / name, sample=index * 100)
        (self.sounds / "manifest.json").write_text(
            json.dumps({"schema_version": 1, "files": files}, sort_keys=True),
            encoding="utf-8",
        )
        self.stockfish = self.root / "stockfish.zip"
        self._write_stockfish_archive(self.stockfish)

    @staticmethod
    def _write_wav(path: Path, *, sample: int) -> None:
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            writer.writeframes(struct.pack("<h", sample) * 8)

    @staticmethod
    def _write_stockfish_archive(
        path: Path,
        *,
        include_source: bool = True,
        extra_member: tuple[str, bytes] | None = None,
    ) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("stockfish/stockfish-windows-x86-64.exe", b"MZ\0stockfish18")
            archive.writestr("stockfish/Copying.txt", b"GNU GENERAL PUBLIC LICENSE\n")
            if include_source:
                archive.writestr("stockfish/src/uci.cpp", b"// corresponding source\n")
            if extra_member is not None:
                archive.writestr(extra_member[0], extra_member[1])

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _prepare(self, output: Path | None = None):
        destination = output or (self.root / "payload")
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            return payload.prepare_version2_release_payload(
                self.standalone,
                self.stockfish,
                self.sounds,
                destination,
            )

    def test_stages_canonical_stockfish_sounds_and_notices_atomically(self) -> None:
        result = self._prepare()

        self.assertEqual(result.root, self.root / "payload")
        self.assertTrue((result.product_dir / "AccessibleChess.exe").is_file())
        self.assertTrue((result.product_dir / "web" / "index.html").is_file())
        self.assertEqual(result.stockfish_executable.read_bytes(), b"MZ\0stockfish18")
        self.assertEqual(
            resolve_stockfish_path(StockfishRuntimeConfig(application_dir=result.product_dir)),
            result.stockfish_executable.resolve(),
        )
        manifest = PackagedSoundAssetResolver(result.product_dir).load_manifest()
        self.assertEqual(set(manifest.files), set(SoundEvent))
        for wav in manifest.files.values():
            with wave.open(str(wav), "rb") as reader:
                self.assertEqual(reader.getsampwidth(), 2)
                self.assertGreater(reader.getnframes(), 0)

        notices = result.notices_dir
        self.assertEqual(
            (notices / "Stockfish-18-windows-x86-64.zip").read_bytes(),
            self.stockfish.read_bytes(),
        )
        self.assertIn("GNU GENERAL PUBLIC LICENSE", (notices / "Stockfish-COPYING.txt").read_text())
        provenance = json.loads((notices / "STOCKFISH_PROVENANCE.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["tag"], payload.OFFICIAL_STOCKFISH_18_TAG)
        self.assertEqual(provenance["upstream_commit"], payload.OFFICIAL_STOCKFISH_18_COMMIT)
        self.assertEqual(provenance["release_asset_sha256"], self._digest(self.stockfish))
        self.assertEqual(
            provenance["packaged_executable_sha256"],
            hashlib.sha256(b"MZ\0stockfish18").hexdigest(),
        )

    def test_wrong_stockfish_digest_fails_without_output(self) -> None:
        output = self.root / "payload"
        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "SHA-256 mismatch"):
            payload.prepare_version2_release_payload(
                self.standalone,
                self.stockfish,
                self.sounds,
                output,
            )
        self.assertFalse(output.exists())

    def test_stockfish_archive_requires_corresponding_source(self) -> None:
        self._write_stockfish_archive(self.stockfish, include_source=False)
        output = self.root / "payload"
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "corresponding source"):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self.assertFalse(output.exists())

    def test_stockfish_archive_traversal_fails_closed(self) -> None:
        self._write_stockfish_archive(
            self.stockfish,
            extra_member=("../escape.txt", b"no"),
        )
        output = self.root / "payload"
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "path traversal"):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self.assertFalse(output.exists())
        self.assertFalse((self.root / "escape.txt").exists())

    def test_missing_sound_event_fails_without_output(self) -> None:
        manifest_path = self.sounds / "manifest.json"
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw["files"].pop(next(iter(SoundEvent)).value)
        manifest_path.write_text(json.dumps(raw), encoding="utf-8")
        output = self.root / "payload"

        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "sound pack"):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self.assertFalse(output.exists())

    def test_non_pcm_or_empty_wav_fails_without_output(self) -> None:
        target = self.sounds / f"{next(iter(SoundEvent)).value}.wav"
        target.write_bytes(b"not-a-wave")
        output = self.root / "payload"

        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "WAV"):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self.assertFalse(output.exists())

    def test_raw_python_source_in_standalone_is_rejected_atomically(self) -> None:
        (self.standalone / "leak.py").write_text("secret = True\n", encoding="utf-8")
        output = self.root / "payload"
        with patch.object(
            payload,
            "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
            self._digest(self.stockfish),
        ):
            with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "raw Python source"):
                payload.prepare_version2_release_payload(
                    self.standalone,
                    self.stockfish,
                    self.sounds,
                    output,
                )
        self.assertFalse(output.exists())

    def test_existing_output_is_never_overwritten(self) -> None:
        output = self.root / "payload"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(payload.Version2ReleasePayloadError, "already exists"):
            self._prepare(output)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()

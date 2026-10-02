from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.sound_profile_composition import (
    _local_pack_resolver,
    _playable_installed_packs,
    _windows_pack_is_playable,
    create_local_sound_composition,
)
from acs.sound_profile_store import SoundProfileWriteBlockedError
from acs.sound_profiles import CORE_SOUND_EVENTS, SoundPackManifest
from acs.sound_runtime import SoundAssetRequest


def _pack_manifest(pack_id: str, suffix: str = ".wav") -> SoundPackManifest:
    return SoundPackManifest(
        pack_id=pack_id,
        version="1.0.0",
        title=pack_id,
        license_id="CC0-1.0",
        files={event: f"audio/{event}{suffix}" for event in CORE_SOUND_EVENTS},
        author="Accessible Chess tests",
        provenance="tests-only generated assets",
    )


class _InstalledStore:
    def __init__(self, manifests):
        self._manifests = {item.pack_id: item for item in manifests}

    def installed(self):
        return dict(self._manifests)


class _Playback:
    def __init__(self) -> None:
        self.requests: list[SoundAssetRequest] = []

    def play_sound(self, request: SoundAssetRequest) -> None:
        self.requests.append(request)


class _LegacyPlayback:
    def __init__(self) -> None:
        self.calls = []

    def play(self, event, *, volume: int) -> None:
        self.calls.append((event, volume))


class LocalSoundCompositionTests(unittest.TestCase):
    def test_first_run_migrates_legacy_sound_toggle_and_volume_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-migrate-") as raw:
            root = Path(raw)
            playback = _Playback()
            first = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                legacy_settings={"sounds": False, "volume": 37},
                asset_playback=playback,
            )
            self.assertFalse(first.profile_manager.current.master_enabled)
            self.assertEqual(37, first.profile_manager.current.master_volume_percent)
            profile_path = root / "data" / "sound-profile.json"
            self.assertTrue(profile_path.is_file())

            # A later legacy-setting change cannot overwrite the new single authority.
            second = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                legacy_settings={"sounds": True, "volume": 99},
                asset_playback=_Playback(),
            )
            self.assertFalse(second.profile_manager.current.master_enabled)
            self.assertEqual(37, second.profile_manager.current.master_volume_percent)

    def test_settings_mutation_persists_and_is_visible_after_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-restart-") as raw:
            root = Path(raw)
            first = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
            )
            first.settings.set_master(enabled=True, volume_percent=64)
            first.settings.set_event("check", volume_percent=45, sound_id="check.soft")

            second = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
            )
            self.assertEqual(64, second.profile_manager.current.master_volume_percent)
            self.assertEqual(45, second.profile_manager.current.preference_for("check").volume_percent)
            self.assertEqual("check.soft", second.profile_manager.current.preference_for("check").sound_id)

    def test_classroom_runtime_reuses_exact_profile_and_playback_authorities(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-classroom-") as raw:
            root = Path(raw)
            playback = _Playback()
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=playback,
            )

            self.assertIs(
                composition.classroom_runtime._playback,
                composition.profiled_runtime._asset_playback,
            )
            composition.settings.set_master(enabled=False)
            result = composition.classroom_runtime.dispatch("classroom.join")
            self.assertTrue(result.ok)
            self.assertFalse(result.delivered)
            self.assertEqual([], playback.requests)

    def test_preview_runs_through_composed_profiled_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-preview-") as raw:
            root = Path(raw)
            playback = _Playback()
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=playback,
            )
            composition.settings.set_master(volume_percent=50)
            composition.settings.set_event("capture", volume_percent=60, sound_id="capture.soft")
            composition.settings.preview("capture", language="en")

            self.assertEqual(1, len(playback.requests))
            request = playback.requests[0]
            self.assertEqual("classic", request.pack_id)
            self.assertEqual("capture", request.event_id)
            self.assertEqual("capture.soft", request.sound_id)
            self.assertEqual(30, request.volume)
            self.assertTrue(request.preview)

    def test_retained_legacy_injection_is_adapted_without_second_profile_owner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-legacy-port-") as raw:
            root = Path(raw)
            playback = _LegacyPlayback()
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=playback,
            )
            composition.settings.set_master(volume_percent=55)
            composition.settings.preview("move", language="en")

            self.assertEqual(1, len(playback.calls))
            event, volume = playback.calls[0]
            self.assertEqual("move", event.value)
            self.assertEqual(55, volume)

    def test_legacy_injection_low_time_is_preview_only_and_maps_to_tick(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-legacy-low-time-") as raw:
            root = Path(raw)
            playback = _LegacyPlayback()
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=playback,
            )
            composition.settings.preview("low_time")

            self.assertEqual(1, len(playback.calls))
            event, _volume = playback.calls[0]
            self.assertEqual("tick", event.value)

    def test_missing_selected_custom_pack_recovers_to_classic_on_load(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-fallback-") as raw:
            root = Path(raw)
            data = root / "data"
            data.mkdir(parents=True)
            (data / "sound-profile.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "pack_id": "missing.pack",
                        "master_enabled": True,
                        "master_volume_percent": 80,
                        "events": {},
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=data,
                asset_playback=_Playback(),
            )
            self.assertEqual("classic", composition.profile_manager.current.pack_id)
            persisted = json.loads((data / "sound-profile.json").read_text(encoding="utf-8"))
            self.assertEqual("classic", persisted["pack_id"])

    def test_future_profile_schema_is_preserved_and_ui_writes_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-future-") as raw:
            root = Path(raw)
            data = root / "data"
            data.mkdir(parents=True)
            future = {"schema_version": 999, "pack_id": "future.pack", "future": {"x": 1}}
            path = data / "sound-profile.json"
            path.write_text(json.dumps(future), encoding="utf-8")

            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=data,
                legacy_settings={"sounds": False, "volume": 1},
                asset_playback=_Playback(),
            )
            self.assertTrue(composition.profile_manager.writes_blocked)
            with self.assertRaises(SoundProfileWriteBlockedError):
                composition.settings.set_master(enabled=False)
            self.assertEqual(future, json.loads(path.read_text(encoding="utf-8")))

    def test_windows_incompatible_installed_pack_is_never_resolved_or_exposed(self) -> None:
        wav = _pack_manifest("local.wav")
        ogg = _pack_manifest("local.ogg", ".ogg")
        store = _InstalledStore([wav, ogg])

        self.assertTrue(_windows_pack_is_playable(wav))
        self.assertFalse(_windows_pack_is_playable(ogg))
        self.assertEqual("local.wav", _local_pack_resolver(store)("local.wav"))
        self.assertEqual("classic", _local_pack_resolver(store)("local.ogg"))
        self.assertEqual({"local.wav": wav}, _playable_installed_packs(store))

    def test_composition_binds_settings_to_filtered_local_pack_provider(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-local-pack-provider-") as raw:
            root = Path(raw)
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=root / "data",
                asset_playback=_Playback(),
            )
            provider = composition.settings._installed_pack_provider
            self.assertTrue(callable(provider))
            self.assertEqual({}, provider())

    def test_composition_creates_dedicated_profile_pack_and_cache_roots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sound-compose-layout-") as raw:
            root = Path(raw)
            data = root / "data"
            composition = create_local_sound_composition(
                application_dir=root / "app",
                data_root=data,
                asset_playback=_Playback(),
            )
            self.assertEqual(data / "sound-packs", composition.pack_store.root)
            self.assertEqual(data / "sound-profile.json", composition.profile_manager._storage.path)


if __name__ == "__main__":
    unittest.main()

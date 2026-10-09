"""Gameplay -> actual PCM WAV -> Windows adapter. Never proves audible/NVDA output."""
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from acs.sound_events import SoundEvent
from acs.version2_upgrade_status_release import create_version2_release_application
from tests.test_stage1_release_composition_ui import _FakeRuntime


class OwnerGameplayWavDeliveryTests(unittest.TestCase):
    def _run(self, *, native=False):
        with tempfile.TemporaryDirectory(prefix='Шахи WAV ') as directory:
            root = Path(directory)
            assets = root / 'assets' / 'sounds'
            assets.mkdir(parents=True)
            files = {}
            for event in SoundEvent:
                name = event.value + '.wav'
                files[event.value] = name
                # Test-only PCM bytes; never substituted for the owner's sound pack.
                with wave.open(str(assets / name), 'wb') as output:
                    output.setnchannels(1); output.setsampwidth(2); output.setframerate(8000)
                    output.writeframes(struct.pack('<h', 1200) * 160)
            (assets / 'manifest.json').write_text(json.dumps({'schema_version':1,'files':files}))
            calls = []
            if native:
                import winsound
                native_play = winsound.PlaySound
            else:
                native_play = None
            def observe_play(filename, flags):
                if filename is not None:
                    path = Path(filename)
                    self.assertTrue(path.is_file())
                    with wave.open(str(path),'rb') as source:
                        self.assertEqual(source.getsampwidth(),2)
                        self.assertGreater(source.getnframes(),0)
                        self.assertTrue(any(source.readframes(source.getnframes())))
                    calls.append((path.name,flags))
                if native_play is not None:
                    native_play(filename,flags)
            port = SimpleNamespace(SND_FILENAME=0x20000,SND_NODEFAULT=2,SND_ASYNC=1,PlaySound=observe_play)
            api=app=runtime=None
            with patch.dict(sys.modules, {'winsound':port}), patch('acs.sound_windows.sys', SimpleNamespace(platform='win32')):
                try:
                    api,app,runtime,_=create_version2_release_application(
                        application_dir=root, data_root=root/'дані програми', runtime_factory=_FakeRuntime)
                    self.assertTrue(api.new_game()['ok'])
                    for text in ('e4','e5','nf3'):
                        self.assertTrue(api.make_move(text)['ok'])
                    self.assertEqual(len(calls),4, 'every action must reach the platform audio API')
                    self.assertTrue(calls[0][0].startswith('start-v80-'))
                    self.assertTrue(calls[0][1]&port.SND_ASYNC)
                    self.assertTrue(all(name.startswith('move-v80-') for name,_ in calls[1:]))
                    self.assertTrue(all(flags&port.SND_NODEFAULT for _,flags in calls))
                    before=len(calls)
                    self.assertTrue(api.set_sound_enabled(False)['ok'])
                    self.assertTrue(api.make_move('nc6')['ok'])
                    self.assertEqual(len(calls),before)
                    self.assertTrue(api.set_sound_enabled(True)['ok'])
                    self.assertTrue(api.make_move('bc4')['ok'])
                    self.assertEqual(len(calls),before+1)
                finally:
                    if app is not None: app.shutdown()
                    if api is not None: api.close_analysis()
                    if runtime is not None: runtime.close()

    def test_production_composition_delivers_real_wav_files_for_game_actions(self):
        self._run()

    @unittest.skipUnless(sys.platform == 'win32', 'requires the real Windows PlaySound API')
    def test_windows_plays_gameplay_wavs_through_native_audio_api(self):
        self._run(native=True)

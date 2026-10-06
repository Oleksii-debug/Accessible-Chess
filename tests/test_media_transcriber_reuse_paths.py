from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from acs.media_transcription import ModelDescriptor, TranscriptionRequest
from acs.media_transcribers import FasterWhisperTranscriber


class TranscriberReusePathTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix='Шахи media ')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.audio = self.root / 'Урок один.wav'
        with wave.open(str(self.audio), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b'\0\0' * 16000)

    def test_platform_concrete_path_reaches_faster_whisper_and_keeps_offsets(self):
        calls = []
        def model_factory(path, **kwargs):
            calls.append((path, kwargs))
            def transcribe(path, **kwargs):
                calls.append((path, kwargs))
                return iter([SimpleNamespace(start=0.1, end=0.8, text=' Хід конем. ')]), SimpleNamespace(language='uk')
            return SimpleNamespace(transcribe=transcribe)
        descriptor = ModelDescriptor('local-model', 'faster-whisper', 'fixture-v1', 'fixture license')
        with patch('acs.media_transcribers.importlib.metadata.version', return_value='fixture'), \
             patch('acs.media_transcribers.importlib.import_module', return_value=SimpleNamespace(WhisperModel=model_factory)):
            adapter = FasterWhisperTranscriber(model_path=self.root, model=descriptor)
            result = adapter.transcribe(TranscriptionRequest('chunk-1', self.audio, offset_ms=30000))
        self.assertEqual(result.segments[0].start_ms, 30100)
        self.assertEqual(result.segments[0].end_ms, 30800)
        self.assertEqual(result.segments[0].text, 'Хід конем.')
        self.assertTrue(calls[0][1]['local_files_only'])
        self.assertEqual(calls[0][1]['device'], 'cpu')
        self.assertEqual(calls[0][1]['compute_type'], 'int8')
        self.assertEqual(calls[1][0], str(self.audio.resolve()))

    def test_path_text_is_not_accepted_as_a_host_path(self):
        with self.assertRaises(TypeError):
            TranscriptionRequest('chunk-1', str(self.audio))


if __name__ == '__main__':
    unittest.main()

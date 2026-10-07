from __future__ import annotations

from pathlib import Path

from acs.media_audio import AudioExtractionPolicy, FFmpegAudioExtractor


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, argv, **kwargs):
        partial = Path(argv[-1])
        partial.write_bytes(b"RIFFfixture")
        self.calls.append({"argv": tuple(argv), **kwargs})

        class _Result:
            returncode = 0

        return _Result()


def test_ffmpeg_extractor_bounds_partial_output_during_process(tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"fixture")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture video")
    destination = tmp_path / "normalized.wav"
    runner = _FakeRunner()

    result = FFmpegAudioExtractor(
        ffmpeg_path=ffmpeg,
        runner=runner,
    ).extract(
        source_path=source,
        destination_path=destination,
        allowed_root=tmp_path,
        policy=AudioExtractionPolicy(max_output_bytes=1234),
    )

    assert result.path == destination
    assert destination.read_bytes() == b"RIFFfixture"
    assert len(runner.calls) == 1
    call = runner.calls[0]
    expected_partial = destination.with_suffix(".wav.partial")
    assert call["watched_paths"] == (expected_partial,)
    assert call["max_watched_file_bytes"] == 1234

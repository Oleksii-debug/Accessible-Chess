from __future__ import annotations

import asyncio
from hashlib import sha256
import unittest
from unittest.mock import patch

from acs.agent_tools import ToolCall, ToolExecutor
from acs.media_errors import MediaError, MediaErrorCode
from acs.media_subtitles import parse_subtitle_context, register_speech_context_tool

SRT = ('1\n00:00:01,000 --> 00:00:03,000\n<b>Хід конем.</b>\nДруга лінія.\n\n'
       '2\n00:00:06,000 --> 00:00:09,000\nCompare e4 and d4.\n').encode('utf-8')
VTT = ('WEBVTT\n\n00:01.000 --> 00:03.000\n<b>Хід конем.</b>\nДруга лінія.\n\n'
       '00:06.000 --> 00:09.000\nCompare e4 and d4.\n').encode('utf-8')


def context(raw=SRT, format='srt', **kwargs):
    return parse_subtitle_context(raw, format=format, source_id='lesson',
        source_revision='revision-1', language='uk', **kwargs)


class ActiveTuple(tuple):
    def __iter__(self):
        raise AssertionError("active tuple subclass must not be iterated")


class ActiveText(str):
    def __eq__(self, other):
        raise AssertionError("active text subclass must not be compared")


class ActiveFloat(float):
    def __float__(self):
        raise AssertionError("active numeric subclass must not execute")


class SubtitleReuseTests(unittest.TestCase):
    def test_real_pysubs2_srt_webvtt_same_unicode_timestamps_and_identity(self):
        first, second = context(), context(VTT, 'vtt')
        self.assertEqual(first.segments, second.segments)
        self.assertEqual(first.source_sha256, sha256(SRT).hexdigest())
        self.assertNotEqual(first.source_sha256, second.source_sha256)
        self.assertEqual(first.segments[0].text, 'Хід конем.\nДруга лінія.')
        self.assertEqual(first.segments[1].start_ms, 6000)
        self.assertEqual(first, context())

    def test_real_pysubs2_ass_discards_comments_and_preserves_dialogue(self):
        import pysubs2
        source = pysubs2.SSAFile()
        source.append(pysubs2.SSAEvent(start=1000, end=2000, text='Шахи\\NChess'))
        source.append(pysubs2.SSAEvent(start=2000, end=3000, text='Editor note', type='Comment'))
        for format in ('ass', 'ssa'):
            with self.subTest(format=format):
                opened = context(source.to_string(format).encode(), format)
                self.assertEqual(len(opened.segments), 1)
                self.assertEqual(opened.segments[0].text, 'Шахи\nChess')

    def test_seek_backward_and_pause_use_current_cursor_without_mutation(self):
        opened = context()
        late = opened.around(6500, before_ms=0, after_ms=0)
        early = opened.around(1500, before_ms=0, after_ms=0)
        self.assertEqual(late['segments'][0]['text'], 'Compare e4 and d4.')
        self.assertEqual(early['segments'][0]['text'], 'Хід конем.\nДруга лінія.')
        self.assertEqual(early, opened.around(1500, before_ms=0, after_ms=0))
        self.assertEqual(opened.around(3000, before_ms=0, after_ms=0)['segments'], [])
        self.assertFalse(early['chessAuthority'])

    def test_output_truncation_is_explicit_and_leaves_track_unchanged(self):
        opened = context()
        with patch('acs.media_subtitles.MAX_CONTEXT_SEGMENTS', 1):
            result = opened.around(5000)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['segments']), 1)
        self.assertEqual(len(opened.segments), 2)

    def test_reject_empty_bad_encoding_invalid_order_and_zero_duration(self):
        sources = [b'not subtitles', b'1\n00:00:01,000 --> 00:00:02,000\n\xff',
                   SRT.replace(b'00:00:03,000', b'00:00:01,000'),
                   SRT.replace(b'00:00:06,000', b'00:00:00,000')]
        for raw in sources:
            with self.subTest(raw=raw[:15]), self.assertRaises(MediaError) as raised:
                context(raw)
            self.assertIs(raised.exception.code, MediaErrorCode.INVALID_SUBTITLE)

    def test_missing_optional_codec_reports_component_missing(self):
        with patch.dict('sys.modules', {'pysubs2': None}), self.assertRaises(MediaError) as raised:
            context()
        self.assertIs(raised.exception.code, MediaErrorCode.COMPONENT_MISSING)

    def test_bounded_source_and_context(self):
        with patch('acs.media_subtitles.MAX_SUBTITLE_BYTES', 10), self.assertRaises(MediaError):
            context()
        for kwargs in ({'before_ms': True}, {'after_ms': -1}, {'before_ms': 60001}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                context().around(1000, **kwargs)

    def test_same_executor_reads_context_and_rejects_stale_video(self):
        executor = ToolExecutor()
        current = ['lesson', 'revision-1', 6500]
        register_speech_context_tool(executor, context=context(), current_media=lambda: tuple(current))
        call = ToolCall('call-1', 'speech_context.around_current_time', {'before_ms': 0, 'after_ms': 0})
        result = asyncio.run(executor.execute(call))
        self.assertTrue(result.ok)
        self.assertEqual(result.output['segments'][0]['text'], 'Compare e4 and d4.')
        current[1] = 'revision-2'
        stale = asyncio.run(executor.execute(call))
        self.assertFalse(stale.ok)
        self.assertIsNone(stale.output)

    def test_registered_tool_detaches_context_from_later_dto_mutation(self):
        opened = context()
        original_text = opened.segments[0].text
        executor = ToolExecutor()
        register_speech_context_tool(
            executor,
            context=opened,
            current_media=lambda: ('lesson', 'revision-1', 1500),
        )

        object.__setattr__(opened.segments[0], 'text', 'MUTATED AFTER BIND')
        object.__setattr__(opened, 'source_revision', 'mutated-revision')

        result = asyncio.run(
            executor.execute(
                ToolCall(
                    'call-detached',
                    'speech_context.around_current_time',
                    {'before_ms': 0, 'after_ms': 0},
                )
            )
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output['sourceRevision'], 'revision-1')
        self.assertEqual(result.output['segments'][0]['text'], original_text)
        self.assertNotIn('MUTATED AFTER BIND', repr(result.output))

    def test_current_media_snapshot_requires_exact_passive_tuple_and_scalars(self):
        cases = (
            ActiveTuple(('lesson', 'revision-1', 1000)),
            (ActiveText('lesson'), 'revision-1', 1000),
            ('lesson', ActiveText('revision-1'), 1000),
            ('lesson', 'revision-1', True),
            ('lesson', 'revision-1'),
        )
        for index, snapshot in enumerate(cases):
            with self.subTest(index=index):
                executor = ToolExecutor()
                register_speech_context_tool(
                    executor,
                    context=context(),
                    current_media=lambda snapshot=snapshot: snapshot,
                )
                result = asyncio.run(
                    executor.execute(
                        ToolCall(
                            f'call-passive-{index}',
                            'speech_context.around_current_time',
                            {},
                        )
                    )
                )
                self.assertFalse(result.ok)
                self.assertIsNone(result.output)

    def test_registration_rejects_active_tampered_segment_confidence(self):
        opened = context()
        object.__setattr__(opened.segments[0], 'confidence', ActiveFloat(0.5))
        executor = ToolExecutor()

        with self.assertRaises(TypeError):
            register_speech_context_tool(
                executor,
                context=opened,
                current_media=lambda: ('lesson', 'revision-1', 1000),
            )

        self.assertNotIn(
            'speech_context.around_current_time',
            {spec.tool_id for spec in executor.specs()},
        )

    def test_unknown_tool_argument_is_rejected(self):
        executor = ToolExecutor()
        register_speech_context_tool(executor, context=context(),
            current_media=lambda: ('lesson', 'revision-1', 1000))
        result = asyncio.run(executor.execute(ToolCall('call-1',
            'speech_context.around_current_time', {'source_id': 'different'})))
        self.assertFalse(result.ok)


if __name__ == '__main__':
    unittest.main()

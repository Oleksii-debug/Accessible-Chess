from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from acs.agent_model_contracts import ModelErrorCode, ModelGatewayError, ModelMessage, ModelRequest
from acs.agent_model_gateway import ModelGateway
from acs.agent_ollama_provider import OllamaProvider
from acs.agent_tools import ToolExecutor
from acs.media_subtitles import parse_subtitle_context, register_speech_context_tool
from acs.universal_chess_agent import UniversalChessAgentRuntime


def response(text='Вітаю', **extra):
    return {'model': 'qwen3:8b', 'done': True,
            'message': {'role': 'assistant', 'content': text},
            'prompt_eval_count': 10, 'eval_count': 4, **extra}


class OllamaReuseTests(unittest.TestCase):
    def provider(self, handler):
        self.requests = []
        def wrapped(request):
            self.requests.append(request)
            return handler(request)
        def factory(**kwargs):
            self.assertIs(kwargs['trust_env'], False)
            self.assertIs(kwargs['follow_redirects'], False)
            return httpx.AsyncClient(transport=httpx.MockTransport(wrapped), **kwargs)
        return OllamaProvider(client_factory=factory)

    def request(self):
        return ModelRequest('request-1', (ModelMessage('user', 'Яка позиція?'),), model='qwen3:8b')

    def test_actual_httpx_transport_native_payload_and_gateway_response(self):
        provider = self.provider(lambda _: httpx.Response(200, json=response()))
        gateway = ModelGateway()
        gateway.register(provider, default=True)
        from dataclasses import replace
        result = asyncio.run(gateway.complete(replace(self.request(), provider_id='ollama')))
        self.assertEqual(result.text, 'Вітаю')
        self.assertEqual(result.request_id, 'request-1')
        self.assertEqual(result.usage.total_tokens, 14)
        sent = json.loads(self.requests[0].content)
        self.assertEqual(str(self.requests[0].url), 'http://localhost:11434/api/chat')
        self.assertIs(sent['stream'], False)
        self.assertIs(sent['think'], False)
        self.assertEqual(sent['model'], 'qwen3:8b')
        self.assertEqual(sent['messages'][0]['content'], 'Яка позиція?')
        self.assertFalse(provider.capabilities.supports_hard_cancellation)

    def test_complete_agent_subtitles_tool_roundtrip_uses_existing_runtime(self):
        answers = [json.dumps({'type': 'tool', 'tool_id': 'speech_context.around_current_time',
                              'arguments': {'before_ms': 0, 'after_ms': 0}}),
                   json.dumps({'type': 'final', 'text': 'Коментатор сказав: хід конем.'})]
        provider = self.provider(lambda _: httpx.Response(200, json=response(answers.pop(0))))
        gateway, executor = ModelGateway(), ToolExecutor()
        gateway.register(provider)
        subtitles = parse_subtitle_context(
            '1\n00:00:01,000 --> 00:00:03,000\nХід конем.\n'.encode(),
            format='srt', source_id='video', source_revision='v1', language='uk')
        register_speech_context_tool(
            executor,
            context=subtitles,
            context_allowed=lambda: True,
            current_media=lambda: ('video', 'v1', 1500),
        )
        runtime = UniversalChessAgentRuntime(gateway=gateway, tools=executor,
            provider_id='ollama', model='qwen3:8b', product_instruction='Відповідай українською.')
        result = asyncio.run(runtime.run(run_id='run-1', user_text='Що сказав коментатор?'))
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(result.model_calls, 2)
        self.assertEqual(result.text, 'Коментатор сказав: хід конем.')
        second = json.loads(self.requests[1].content)
        tool = json.loads(second['messages'][-1]['content'])
        self.assertIn('Хід конем.', json.dumps(tool, ensure_ascii=False))
        self.assertIn('"chessAuthority": false', json.dumps(tool))

    def test_incomplete_model_mismatch_and_bad_usage_rejected(self):
        for body in (response(done=False), response(model='different'),
                     response(eval_count=True), response(eval_count=-1)):
            with self.subTest(body=body):
                provider = self.provider(lambda _: httpx.Response(200, json=body))
                with self.assertRaises(ModelGatewayError) as raised:
                    asyncio.run(provider.complete(self.request()))
                self.assertIs(raised.exception.code, ModelErrorCode.PROVIDER_ERROR)

    def test_http_errors_do_not_leak_body_or_enable_retry(self):
        for status in (401, 404, 429, 500):
            with self.subTest(status=status):
                provider = self.provider(lambda _: httpx.Response(status, text='private data'))
                with self.assertRaises(ModelGatewayError) as raised:
                    asyncio.run(provider.complete(self.request()))
                self.assertNotIn('private', str(raised.exception))
                self.assertFalse(raised.exception.retryable)

    def test_limits_apply_to_request_and_response(self):
        provider = self.provider(lambda _: httpx.Response(200, json=response()))
        with patch('acs.agent_ollama_provider.MAX_OLLAMA_REQUEST_CHARS', 1):
            with self.assertRaises(ModelGatewayError) as raised:
                asyncio.run(provider.complete(self.request()))
        self.assertEqual(self.requests, [])
        self.assertIs(raised.exception.code, ModelErrorCode.RESOURCE_LIMIT)
        with patch('acs.agent_ollama_provider.MAX_OLLAMA_RESPONSE_BYTES', 1):
            with self.assertRaises(ModelGatewayError) as raised:
                asyncio.run(provider.complete(self.request()))
        self.assertIs(raised.exception.code, ModelErrorCode.RESOURCE_LIMIT)

    def test_endpoint_is_local_and_cloud_model_is_not_routed_as_private(self):
        for endpoint in ('https://example.org', 'http://localhost:11434/api/chat',
                         'http://user:secret@localhost:11434'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                OllamaProvider(base_url=endpoint)
        with self.assertRaises(ValueError):
            OllamaProvider(default_model='model:cloud')

    def test_cancellation_propagates_and_closes_http_client(self):
        started = asyncio.Event()
        async def handler(request):
            started.set()
            await asyncio.Future()
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OllamaProvider(client_factory=lambda **_: client)
        async def scenario():
            task = asyncio.create_task(provider.complete(self.request()))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(scenario())
        self.assertTrue(client.is_closed)

    def test_real_loopback_http_roundtrip(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                observed.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                raw = json.dumps(response('Локальна відповідь'), ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            provider = OllamaProvider(base_url=f'http://127.0.0.1:{server.server_port}')
            result = asyncio.run(provider.complete(self.request()))
            self.assertEqual(result.text, 'Локальна відповідь')
            self.assertEqual(observed[0][0], '/api/chat')
            self.assertFalse(observed[0][1]['stream'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(5)


if __name__ == '__main__':
    unittest.main()

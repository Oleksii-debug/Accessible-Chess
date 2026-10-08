from __future__ import annotations

import asyncio
import json
from pathlib import Path
import unittest

from acs.web_client_gateway import (
    CanonicalWebGateway,
    WebClientContractError,
    WebPrincipal,
)
from acs.web_client_http import AccessibleChessWebAsgi


class Section34WebClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.principal = WebPrincipal(
            "user-1", "workspace-1", "session-private", ("student",)
        )

        def snapshot(principal: WebPrincipal):
            self.calls.append(("snapshot", principal))
            return {
                "document": {"lang": "uk"},
                "screen": {
                    "route_id": "board",
                    "heading": "Дошка",
                    "description": "Канонічна позиція",
                },
                "board": {
                    "cells": [
                        {"square": f"square-{index}", "label": f"Square {index}"}
                        for index in range(64)
                    ]
                },
                "media": {"status": "paused"},
                "education": {"status": "ready"},
                "online": {"status": "connected"},
            }

        def command(principal, area, command, payload):
            self.calls.append(("command", principal, area, command, dict(payload)))
            return {"kind": "accepted", "area": area, "command": command}

        self.gateway = CanonicalWebGateway(snapshot=snapshot, command=command)

    def test_gateway_preserves_authenticated_workspace_and_hides_session(self) -> None:
        value = self.gateway.snapshot(self.principal)
        self.assertEqual(value["context"]["user_id"], "user-1")
        self.assertEqual(value["context"]["workspace_id"], "workspace-1")
        self.assertNotIn("session_id", value["context"])
        self.assertNotIn("session-private", json.dumps(value, ensure_ascii=False))

    def test_all_section34_product_areas_delegate_without_chess_semantics(self) -> None:
        areas = (
            "board", "pgn", "gametree", "library", "books", "training",
            "media", "teacher", "classroom", "online", "spectator",
        )
        for area in areas:
            with self.subTest(area=area):
                result = self.gateway.command(
                    self.principal,
                    area=area,
                    command=f"{area}.test",
                    payload={"value": "opaque"},
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["result"]["area"], area)
        delegated = [call[2] for call in self.calls if call[0] == "command"]
        self.assertEqual(list(areas), delegated)

    def test_browser_cannot_supply_identity_or_unknown_area(self) -> None:
        with self.assertRaises(WebClientContractError):
            self.gateway.command(
                self.principal,
                area="billing-admin",
                command="billing-admin.test",
                payload={},
            )
        with self.assertRaises(WebClientContractError):
            WebPrincipal("../user", "workspace", "session")

    def test_payload_bounds_and_non_finite_values_fail_closed(self) -> None:
        with self.assertRaises(WebClientContractError):
            self.gateway.command(
                self.principal,
                area="library",
                command="library.search",
                payload={"q": "x" * 20_000},
            )
        with self.assertRaises(WebClientContractError):
            self.gateway.command(
                self.principal,
                area="media",
                command="media.seek",
                payload={"position": float("nan")},
            )

    def _asgi(self, method, path, *, principal=True, headers=(), body=b"", query=b""):
        async def run():
            app = AccessibleChessWebAsgi(
                self.gateway,
                html=b"<html>client</html>",
                javascript=b"console.log('client')",
            )
            sent = []
            queue = [
                {"type": "http.request", "body": body, "more_body": False}
            ]

            async def receive():
                return queue.pop(0)

            async def send(message):
                sent.append(message)

            state = {}
            if principal:
                state["accessible_chess_principal"] = self.principal
            scope = {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": query,
                "headers": list(headers),
                "state": state,
            }
            await app(scope, receive, send)
            return sent

        return asyncio.run(run())

    def test_snapshot_requires_authenticated_server_context(self) -> None:
        denied = self._asgi("GET", "/v1/snapshot", principal=False)
        self.assertEqual(denied[0]["status"], 401)
        accepted = self._asgi("GET", "/v1/snapshot")
        self.assertEqual(accepted[0]["status"], 200)
        value = json.loads(accepted[1]["body"].decode("utf-8"))
        self.assertEqual(value["context"]["workspace_id"], "workspace-1")

    def test_command_rejects_identity_smuggling_and_delegates_valid_request(self) -> None:
        smuggled = json.dumps(
            {
                "area": "library",
                "command": "library.search",
                "payload": {},
                "user_id": "attacker",
            }
        ).encode("utf-8")
        rejected = self._asgi(
            "POST",
            "/v1/command",
            headers=((b"content-type", b"application/json"),),
            body=smuggled,
        )
        self.assertEqual(rejected[0]["status"], 400)

        valid = json.dumps(
            {
                "area": "library",
                "command": "library.search",
                "payload": {"query": "Kasparov"},
            }
        ).encode("utf-8")
        accepted = self._asgi(
            "POST",
            "/v1/command",
            headers=((b"content-type", b"application/json; charset=utf-8"),),
            body=valid,
        )
        self.assertEqual(accepted[0]["status"], 200)
        result = json.loads(accepted[1]["body"].decode("utf-8"))
        self.assertEqual(result["result"]["command"], "library.search")

    def test_transport_rejects_query_strings_duplicate_json_and_oversize(self) -> None:
        query = self._asgi("GET", "/v1/snapshot", query=b"user=attacker")
        self.assertEqual(query[0]["status"], 400)
        duplicate = b'{"area":"library","area":"media","command":"x","payload":{}}'
        dup_result = self._asgi(
            "POST",
            "/v1/command",
            headers=((b"content-type", b"application/json"),),
            body=duplicate,
        )
        self.assertEqual(dup_result[0]["status"], 400)
        large = self._asgi(
            "POST",
            "/v1/command",
            headers=((b"content-type", b"application/json"),),
            body=b"x" * 70_000,
        )
        self.assertEqual(large[0]["status"], 413)

    def test_semantic_document_and_script_are_browser_native(self) -> None:
        root = Path(__file__).resolve().parent.parent
        html = (root / "web" / "accessible_chess_web.html").read_text(encoding="utf-8")
        js = (root / "web" / "accessible_chess_web.js").read_text(encoding="utf-8")
        for token in (
            "<main", "<nav", 'role="status"', 'role="alert"', "<progress",
            'role="grid"', 'data-route="media"', 'data-route="classes"',
            'data-route="online"', 'data-route="spectator"',
        ):
            self.assertIn(token, html)
        self.assertIn('event.key === "ArrowRight"', js)
        self.assertIn('credentials: "same-origin"', js)
        self.assertIn('redirect: "error"', js)
        self.assertIn("textContent", js)
        self.assertNotIn("window.pywebview", html + js)
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("remote desktop", (html + js).lower())

    def test_web_boundary_does_not_import_chess_or_duplicate_domain_logic(self) -> None:
        root = Path(__file__).resolve().parent.parent
        source = "\n".join(
            (root / path).read_text(encoding="utf-8")
            for path in ("acs/web_client_gateway.py", "acs/web_client_http.py")
        )
        forbidden = (
            "from .chesscore", "import chesscore", "from .gametree",
            "from .notation", "from .pgn", "parse_fen", "legal_moves(",
        )
        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()

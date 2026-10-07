from __future__ import annotations

import unittest

from acs.network_security import (
    ConsentContext,
    DataClass,
    DEFAULT_SECTION29_POLICY,
    NetworkSurface,
    SecurityContractError,
    SecurityRequest,
)


class _Limiter:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    def consume(self, **kwargs):
        self.calls.append(kwargs)
        return self.allowed


class Section29SecurityContractTests(unittest.TestCase):
    def setUp(self):
        self.policy = DEFAULT_SECTION29_POLICY

    def _request(self, **changes):
        values = dict(
            surface=NetworkSurface.SERVER,
            operation="server.application.command",
            purpose="product",
            actor_role="teacher",
            required_permission="app.write",
            granted_permissions=frozenset({"app.write"}),
            data_classes=frozenset(),
            mutates=True,
        )
        values.update(changes)
        return SecurityRequest(**values)

    def test_production_gate_is_deterministic_and_verifiable(self):
        one = self.policy.gate()
        two = self.policy.gate()
        self.assertEqual(one, two)
        self.policy.verify_gate(one)
        self.assertEqual(len(one.policy_digest), 64)

    def test_every_required_network_surface_is_threat_modelled(self):
        self.assertEqual({entry.surface for entry in self.policy.threats}, set(NetworkSurface))

    def test_state_change_requires_server_side_permission(self):
        self.policy.authorize(self._request())
        with self.assertRaises(SecurityContractError):
            self.policy.authorize(self._request(granted_permissions=frozenset()))

    def test_minor_data_fails_closed_without_guardian_and_org_policy(self):
        weak = ConsentContext(True, "child-v1", True, False)
        with self.assertRaises(SecurityContractError):
            self.policy.authorize(self._request(
                surface=NetworkSurface.CLASSROOM,
                operation="classroom.assignment.save",
                data_classes=frozenset({DataClass.CHILD, DataClass.CLASSROOM_STATE}),
                consent=weak,
                requested_retention_days=30,
            ))
        strong = ConsentContext(True, "child-v1", True, True)
        self.policy.authorize(self._request(
            surface=NetworkSurface.CLASSROOM,
            operation="classroom.assignment.save",
            data_classes=frozenset({DataClass.CHILD, DataClass.CLASSROOM_STATE}),
            consent=strong,
            requested_retention_days=30,
        ))

    def test_sensitive_network_data_requires_bounded_retention(self):
        with self.assertRaises(SecurityContractError):
            self.policy.authorize(self._request(
                surface=NetworkSurface.CLASSROOM,
                operation="classroom.chat.send",
                data_classes=frozenset({DataClass.CHAT}),
            ))
        with self.assertRaises(SecurityContractError):
            self.policy.authorize(self._request(
                surface=NetworkSurface.CLASSROOM,
                operation="classroom.chat.send",
                data_classes=frozenset({DataClass.CHAT}),
                requested_retention_days=366,
            ))
        self.policy.authorize(self._request(
            surface=NetworkSurface.CLASSROOM,
            operation="classroom.chat.send",
            data_classes=frozenset({DataClass.CHAT}),
            requested_retention_days=30,
        ))

    def test_raw_content_is_never_ordinary_analytics(self):
        for data_class in (
            DataClass.CHESS_CONTENT, DataClass.BOOK_CONTENT, DataClass.CHAT,
            DataClass.FILE, DataClass.AUDIO_VIDEO, DataClass.CLIPBOARD,
        ):
            with self.subTest(data_class=data_class):
                kwargs = dict(
                    purpose="analytics",
                    data_classes=frozenset({data_class}),
                    requested_retention_days=30 if data_class in {
                        DataClass.CHAT, DataClass.FILE, DataClass.AUDIO_VIDEO
                    } else None,
                )
                if data_class is DataClass.FILE:
                    kwargs.update(
                        surface=NetworkSurface.FILE_UPLOAD,
                        operation="file.upload",
                        malware_scan_required=True,
                    )
                with self.assertRaises(SecurityContractError):
                    self.policy.authorize(self._request(**kwargs))

    def test_persistent_file_upload_requires_scanning_and_classification(self):
        with self.assertRaises(SecurityContractError):
            self.policy.authorize(self._request(
                surface=NetworkSurface.FILE_UPLOAD,
                operation="file.upload",
                data_classes=frozenset({DataClass.FILE}),
                requested_retention_days=30,
                malware_scan_required=False,
            ))
        self.policy.authorize(self._request(
            surface=NetworkSurface.FILE_UPLOAD,
            operation="file.upload",
            data_classes=frozenset({DataClass.FILE}),
            requested_retention_days=30,
            malware_scan_required=True,
        ))

    def test_moderation_is_role_bounded(self):
        self.policy.authorize(self._request(
            surface=NetworkSurface.CLASSROOM,
            operation="classroom.moderate",
            moderation=True,
        ))
        with self.assertRaises(SecurityContractError):
            self.policy.authorize(self._request(
                surface=NetworkSurface.CLASSROOM,
                operation="classroom.moderate",
                moderation=True,
                actor_role="student",
            ))

    def test_rate_limit_policy_is_fail_closed(self):
        limiter = _Limiter()
        self.policy.consume_rate_limit(
            limiter,
            operation="server.application.command",
            key="workspace:w1:actor:a1",
        )
        self.assertEqual(limiter.calls[0]["limit"], 600)
        with self.assertRaises(SecurityContractError):
            self.policy.consume_rate_limit(
                _Limiter(False),
                operation="server.application.command",
                key="workspace:w1:actor:a1",
            )
        with self.assertRaises(SecurityContractError):
            self.policy.rate_rule_for("unknown.operation")

    def test_logs_redact_secrets_and_raw_payloads(self):
        safe = self.policy.redact_log_fields({
            "workspace_id": "w1",
            "Authorization": "Bearer secret-value",
            "nested": {
                "join_token": "live-secret",
                "chat_body": "private classroom message",
                "count": 2,
            },
            "file_bytes": b"private",
        })
        text = repr(safe)
        self.assertNotIn("secret-value", text)
        self.assertNotIn("live-secret", text)
        self.assertNotIn("private classroom message", text)
        self.assertNotIn("b'private'", text)
        self.assertEqual(safe["workspace_id"], "w1")
        self.assertEqual(safe["nested"]["count"], 2)


if __name__ == "__main__":
    unittest.main()

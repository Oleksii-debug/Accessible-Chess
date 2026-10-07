from __future__ import annotations

import unittest

from acs.entitlements import EntitlementState
from acs.licensing_privacy import (
    LicensingMetadata,
    LicensingPrivacyError,
    OptionalTelemetryConsent,
    build_licensing_payload,
    build_optional_telemetry_payload,
    licensing_payload_keys,
)


class LicensingPrivacyTests(unittest.TestCase):
    def test_licensing_payload_is_exactly_the_minimal_allowlist(self) -> None:
        metadata = LicensingMetadata(
            account_id="acct-42",
            installation_id="install-7",
            session_id="session-9",
            app_version="2.0.0-beta.3",
            entitlement_state=EntitlementState.FREE_BETA,
        )
        payload = build_licensing_payload(metadata)
        self.assertEqual(set(payload), set(licensing_payload_keys()))
        self.assertEqual(
            payload,
            {
                "account_id": "acct-42",
                "installation_id": "install-7",
                "session_id": "session-9",
                "app_version": "2.0.0-beta.3",
                "entitlement_state": "free_beta",
            },
        )
        for forbidden in (
            "pgn",
            "fen",
            "game",
            "database",
            "book",
            "document",
            "path",
            "token",
            "email",
            "diagnostic",
        ):
            self.assertNotIn(forbidden, payload)

    def test_entitlement_state_reuses_the_canonical_enum(self) -> None:
        for state in EntitlementState:
            with self.subTest(state=state):
                metadata = LicensingMetadata(
                    account_id="acct",
                    installation_id="installation",
                    session_id="session",
                    app_version="2.0.0",
                    entitlement_state=state.value,
                )
                self.assertIs(metadata.entitlement_state, state)
        with self.assertRaisesRegex(LicensingPrivacyError, "unsupported"):
            LicensingMetadata(
                account_id="acct",
                installation_id="installation",
                session_id="session",
                app_version="2.0.0",
                entitlement_state="future_paid_magic",
            )

    def test_arbitrary_mapping_cannot_be_used_as_licensing_payload(self) -> None:
        with self.assertRaisesRegex(LicensingPrivacyError, "requires LicensingMetadata"):
            build_licensing_payload(  # type: ignore[arg-type]
                {"account_id": "acct", "pgn": "1. e4 e5"}
            )

    def test_identifiers_and_versions_are_bounded_plain_text(self) -> None:
        cases = (
            {"account_id": "../database.acsdb"},
            {"installation_id": "install\nsecret"},
            {"session_id": ""},
            {"app_version": "2.0.0\r\nAuthorization: Bearer secret"},
        )
        base = {
            "account_id": "acct",
            "installation_id": "installation",
            "session_id": "session",
            "app_version": "2.0.0",
            "entitlement_state": EntitlementState.TRIAL,
        }
        for replacement in cases:
            with self.subTest(replacement=replacement):
                with self.assertRaises(LicensingPrivacyError):
                    LicensingMetadata(**{**base, **replacement})

    def test_optional_telemetry_is_disabled_by_default(self) -> None:
        values = {
            "event": "screen_opened",
            "app_version": "2.0.0",
            "platform": "windows",
            "locale": "uk-UA",
        }
        self.assertIsNone(build_optional_telemetry_payload(values))
        self.assertIsNone(
            build_optional_telemetry_payload(
                {"pgn": "sensitive game"},
                consent=OptionalTelemetryConsent.DISABLED,
            )
        )

    def test_explicit_analytics_consent_still_uses_a_closed_non_user_data_allowlist(self) -> None:
        values = {
            "event": "screen_opened",
            "app_version": "2.0.0",
            "platform": "windows",
            "locale": "uk-UA",
        }
        self.assertEqual(
            build_optional_telemetry_payload(
                values,
                consent=OptionalTelemetryConsent.ENABLED,
            ),
            values,
        )
        for forbidden in (
            "pgn",
            "fen",
            "database",
            "book",
            "document",
            "account_id",
            "installation_id",
            "session_id",
            "authorization",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaisesRegex(LicensingPrivacyError, "non-allowlisted"):
                    build_optional_telemetry_payload(
                        {"event": "test", forbidden: "secret"},
                        consent=OptionalTelemetryConsent.ENABLED,
                    )

    def test_telemetry_consent_must_be_explicit_enum_not_truthy_flag(self) -> None:
        with self.assertRaisesRegex(LicensingPrivacyError, "consent must be explicit"):
            build_optional_telemetry_payload(  # type: ignore[arg-type]
                {"event": "test"}, consent=True
            )

    def test_optional_telemetry_rejects_nested_or_control_character_values(self) -> None:
        for values in (
            {"event": {"nested": "value"}},
            {"event": "line1\nline2"},
            {"event": "x" * 257},
        ):
            with self.subTest(values=values):
                with self.assertRaises(LicensingPrivacyError):
                    build_optional_telemetry_payload(
                        values, consent=OptionalTelemetryConsent.ENABLED
                    )


if __name__ == "__main__":
    unittest.main()

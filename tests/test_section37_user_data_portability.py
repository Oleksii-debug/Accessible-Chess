from __future__ import annotations

import json
import unittest

from acs.full_product_actions import build_full_product_action_registry
from acs.user_data_portability import (
    BundleKind,
    DomainAdapter,
    DomainSnapshot,
    UserDataPortabilityCoordinator,
    UserDataPortabilityError,
)


class _Owner:
    def __init__(self, domain: str, schema: int, payload: bytes, *, fail_on: bytes | None = None):
        self.domain = domain
        self.schema = schema
        self.payload = payload
        self.fail_on = fail_on
        self.revision = 0

    def snapshot(self) -> DomainSnapshot:
        return DomainSnapshot(
            self.domain,
            self.schema,
            self.payload,
            f"r{self.revision}",
        )

    def prepare(self, snapshot: DomainSnapshot) -> DomainSnapshot:
        if snapshot.domain != self.domain:
            raise ValueError("wrong domain")
        # Test one explicit cross-version migration: schema 1 -> schema 2.
        if self.schema == 2 and snapshot.schema_version == 1:
            return DomainSnapshot(self.domain, 2, b"v2:" + snapshot.payload)
        if snapshot.schema_version != self.schema:
            raise ValueError("unsupported schema")
        return DomainSnapshot(self.domain, self.schema, snapshot.payload)

    def restore(self, snapshot: DomainSnapshot) -> None:
        if self.fail_on is not None and snapshot.payload == self.fail_on:
            raise RuntimeError("injected owner failure")
        self.schema = snapshot.schema_version
        self.payload = snapshot.payload
        self.revision += 1

    def adapter(self, *, portable: bool = True) -> DomainAdapter:
        return DomainAdapter(
            self.domain,
            self.snapshot,
            self.prepare,
            self.restore,
            portable=portable,
        )


class Section37PortabilityTests(unittest.TestCase):
    def test_backup_is_deterministic_sorted_and_checksummed(self):
        settings = _Owner("settings", 2, b'{"language":"uk"}')
        library = _Owner("library", 5, b"acsdb-snapshot")
        coordinator = UserDataPortabilityCoordinator(
            (settings.adapter(), library.adapter())
        )

        first, receipt = coordinator.create_backup()
        second, second_receipt = coordinator.create_backup()

        self.assertEqual(first, second)
        self.assertEqual(receipt, second_receipt)
        self.assertEqual(receipt.kind, BundleKind.BACKUP)
        self.assertEqual(receipt.domains, ("library", "settings"))
        parsed = json.loads(first)
        self.assertEqual(
            [item["domain"] for item in parsed["entries"]],
            ["library", "settings"],
        )

    def test_portable_export_excludes_nonportable_domain(self):
        settings = _Owner("settings", 2, b"settings")
        account_cache = _Owner("account-cache", 1, b"opaque")
        coordinator = UserDataPortabilityCoordinator(
            (settings.adapter(), account_cache.adapter(portable=False))
        )

        raw, receipt = coordinator.export_user_data()

        self.assertEqual(receipt.domains, ("settings",))
        self.assertEqual(coordinator.inspect(raw).kind, BundleKind.PORTABLE)

    def test_import_preflights_and_migrates_before_mutation(self):
        source = _Owner("settings", 1, b"legacy")
        export = UserDataPortabilityCoordinator((source.adapter(),))
        raw, _ = export.export_user_data()

        target = _Owner("settings", 2, b"current")
        coordinator = UserDataPortabilityCoordinator((target.adapter(),))

        receipt = coordinator.import_user_data(raw)

        self.assertEqual(receipt.domains, ("settings",))
        self.assertEqual(target.schema, 2)
        self.assertEqual(target.payload, b"v2:legacy")

    def test_corrupt_digest_fails_before_any_owner_mutation(self):
        first = _Owner("library", 5, b"library")
        second = _Owner("settings", 2, b"settings")
        coordinator = UserDataPortabilityCoordinator(
            (first.adapter(), second.adapter())
        )
        raw, _ = coordinator.create_backup()
        value = json.loads(raw)
        value["entries"][0]["sha256"] = "0" * 64
        corrupt = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()

        with self.assertRaisesRegex(UserDataPortabilityError, "checksum"):
            coordinator.restore_backup(corrupt)

        self.assertEqual(first.payload, b"library")
        self.assertEqual(second.payload, b"settings")

    def test_mid_restore_failure_rolls_back_already_applied_domains(self):
        source_a = _Owner("a", 1, b"new-a")
        source_b = _Owner("b", 1, b"new-b")
        raw, _ = UserDataPortabilityCoordinator(
            (source_a.adapter(), source_b.adapter())
        ).create_backup()

        target_a = _Owner("a", 1, b"old-a")
        target_b = _Owner("b", 1, b"old-b", fail_on=b"new-b")
        coordinator = UserDataPortabilityCoordinator(
            (target_a.adapter(), target_b.adapter())
        )

        with self.assertRaisesRegex(UserDataPortabilityError, "prior state was restored"):
            coordinator.restore_backup(raw)

        self.assertEqual(target_a.payload, b"old-a")
        self.assertEqual(target_b.payload, b"old-b")

    def test_unknown_domain_fails_closed_before_mutation(self):
        source = _Owner("unknown", 1, b"payload")
        raw, _ = UserDataPortabilityCoordinator((source.adapter(),)).export_user_data()
        existing = _Owner("settings", 2, b"safe")
        coordinator = UserDataPortabilityCoordinator((existing.adapter(),))

        with self.assertRaisesRegex(UserDataPortabilityError, "unavailable"):
            coordinator.import_user_data(raw)

        self.assertEqual(existing.payload, b"safe")

    def test_secret_material_cannot_be_registered(self):
        owner = _Owner("credentials", 1, b"token")
        with self.assertRaisesRegex(UserDataPortabilityError, "secret material"):
            DomainAdapter(
                "credentials",
                owner.snapshot,
                owner.prepare,
                owner.restore,
                contains_secret_material=True,
            )

    def test_accessible_action_registry_exposes_all_portability_operations(self):
        ids = {item.action_id for item in build_full_product_action_registry().actions}
        self.assertTrue(
            {"data.backup", "data.restore", "data.export", "data.import"}.issubset(ids)
        )

    def test_kind_mismatch_is_rejected(self):
        owner = _Owner("settings", 2, b"x")
        coordinator = UserDataPortabilityCoordinator((owner.adapter(),))
        portable, _ = coordinator.export_user_data()

        with self.assertRaisesRegex(UserDataPortabilityError, "kind"):
            coordinator.restore_backup(portable)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

"""Accessible V2 local-profile bridge over the canonical LocalProfileStore."""

from typing import Any

from .local_profile import (
    LocalProfile,
    LocalProfileConflict,
    LocalProfileDurabilityUnknownError,
    LocalProfileError,
    LocalProfileStore,
)
from .version2_release_ui import Version2ReleaseAccessibleChessAPI


class Version2ProfileAccessibleChessAPI(Version2ReleaseAccessibleChessAPI):
    """Expose only privacy-bounded profile presentation/actions to WebView."""

    def __init__(
        self,
        *args: Any,
        profile_store: LocalProfileStore | None = None,
        **kwargs: Any,
    ) -> None:
        self._local_profile_store = profile_store
        super().__init__(*args, **kwargs)

    def _profile_error_message(self) -> str:
        return (
            "Local profile is unavailable. Existing profile data was not changed."
            if self.lang == "en"
            else "Локальний профіль недоступний. Наявні дані профілю не змінено."
        )

    def _profile_payload(
        self,
        profile: LocalProfile | None,
        *,
        announcement: str = "",
        recovery_required: bool = False,
    ) -> dict[str, object]:
        if profile is None:
            return {
                "ok": True,
                "exists": False,
                "displayName": "",
                "generatedAlias": False,
                "recoveryRequired": False,
                "announcement": announcement,
            }
        # profile_id is intentionally not exposed to browser presentation.
        return {
            "ok": True,
            "exists": True,
            "displayName": profile.display_name,
            "generatedAlias": profile.generated_alias,
            "recoveryRequired": recovery_required,
            "revision": profile.revision,
            "announcement": announcement,
        }

    def _profile_store(self) -> LocalProfileStore:
        store = self._local_profile_store
        if not isinstance(store, LocalProfileStore):
            raise LocalProfileError("local profile store is unavailable")
        return store

    def _load_profile_state(
        self,
        store: LocalProfileStore,
    ) -> tuple[LocalProfile | None, bool]:
        profile = store.load()
        recovery_required = False
        if profile is not None:
            primary_exists = store.path.exists() or store.path.is_symlink()
            if not primary_exists:
                recovery_required = True
            else:
                try:
                    store._read_profile(store.path)
                except LocalProfileError:
                    recovery_required = True
        return profile, recovery_required

    def _profile_snapshot_ui(self) -> dict[str, object]:
        try:
            store = self._profile_store()
            profile, recovery_required = self._load_profile_state(store)
            return self._profile_payload(profile, recovery_required=recovery_required)
        except LocalProfileError:
            return {
                "ok": False,
                "exists": False,
                "displayName": "",
                "generatedAlias": False,
                "recoveryRequired": False,
                "announcement": self._profile_error_message(),
            }

    def profile_snapshot(self) -> dict[str, object]:
        return self._invoke_ui(self._profile_snapshot_ui)

    def _profile_durability_unknown_payload(
        self,
        store: LocalProfileStore,
    ) -> dict[str, object]:
        try:
            profile, recovery_required = self._load_profile_state(store)
        except LocalProfileError:
            return {
                "ok": False,
                "exists": False,
                "displayName": "",
                "generatedAlias": False,
                "recoveryRequired": False,
                "durabilityUncertain": True,
                "stateChanged": True,
                "announcement": (
                    "Profile storage may have changed, but durable state could not be confirmed."
                    if self.lang == "en"
                    else "Стан профілю міг змінитися, але підтвердити надійне збереження не вдалося."
                ),
            }

        payload = self._profile_payload(
            profile,
            recovery_required=recovery_required,
            announcement=(
                "Profile storage may have changed, but durable state could not be confirmed. The current visible profile was reloaded."
                if self.lang == "en"
                else "Стан профілю міг змінитися, але підтвердити надійне збереження не вдалося. Поточний видимий профіль перечитано."
            ),
        )
        payload["ok"] = False
        payload["durabilityUncertain"] = True
        payload["stateChanged"] = True
        return payload

    def _profile_create_ui(self, display_name: object, skip: object) -> dict[str, object]:
        if (
            type(skip) is not bool
            or not isinstance(display_name, str)
            or (not skip and not display_name.strip())
        ):
            return {
                "ok": False,
                "exists": False,
                "announcement": (
                    "Enter a profile name or choose Skip."
                    if self.lang == "en"
                    else "Введіть ім’я профілю або виберіть «Пропустити»."
                ),
            }
        try:
            store = self._profile_store()
            profile = store.create(None if skip else display_name)
        except LocalProfileDurabilityUnknownError:
            return self._profile_durability_unknown_payload(store)
        except LocalProfileConflict:
            try:
                profile, recovery_required = self._load_profile_state(store)
            except LocalProfileError:
                return {
                    "ok": False,
                    "exists": False,
                    "announcement": self._profile_error_message(),
                }
            if profile is None:
                return {
                    "ok": False,
                    "exists": False,
                    "announcement": self._profile_error_message(),
                }
            announcement = (
                "A local profile already exists. The current profile was loaded."
                if self.lang == "en"
                else "Локальний профіль уже існує. Завантажено поточний профіль."
            )
            return self._profile_payload(
                profile,
                announcement=announcement,
                recovery_required=recovery_required,
            )
        except LocalProfileError:
            return {
                "ok": False,
                "exists": False,
                "announcement": self._profile_error_message(),
            }
        announcement = (
            f"Profile saved as {profile.display_name}."
            if self.lang == "en"
            else f"Профіль збережено як {profile.display_name}."
        )
        return self._profile_payload(profile, announcement=announcement)

    def profile_create(self, display_name: str, skip: bool = False) -> dict[str, object]:
        return self._invoke_ui(lambda: self._profile_create_ui(display_name, skip))

    def _profile_repair_ui(self) -> dict[str, object]:
        try:
            store = self._profile_store()
            profile = store.repair_from_backup()
        except LocalProfileDurabilityUnknownError:
            return self._profile_durability_unknown_payload(store)
        except LocalProfileError:
            return {
                "ok": False,
                "exists": True,
                "announcement": self._profile_error_message(),
            }
        announcement = (
            "Local profile recovery check completed. The current profile is ready."
            if self.lang == "en"
            else "Перевірку відновлення завершено. Поточний профіль готовий до роботи."
        )
        return self._profile_payload(profile, announcement=announcement)

    def profile_repair(self) -> dict[str, object]:
        return self._invoke_ui(self._profile_repair_ui)

    def _profile_rename_ui(self, display_name: object) -> dict[str, object]:
        if not isinstance(display_name, str) or not display_name.strip():
            return {
                "ok": False,
                "exists": True,
                "announcement": (
                    "Enter a profile name."
                    if self.lang == "en"
                    else "Введіть ім’я профілю."
                ),
            }
        try:
            store = self._profile_store()
            current, recovery_required = self._load_profile_state(store)
            if current is None:
                return {
                    "ok": False,
                    "exists": False,
                    "announcement": (
                        "Create a profile first."
                        if self.lang == "en"
                        else "Спочатку створіть профіль."
                    ),
                }
            if recovery_required:
                blocked = self._profile_payload(
                    current,
                    recovery_required=True,
                    announcement=(
                        "Recover the local profile before renaming it."
                        if self.lang == "en"
                        else "Відновіть локальний профіль перед зміною імені."
                    ),
                )
                blocked["ok"] = False
                return blocked
            profile = store.rename(current, display_name)
        except LocalProfileDurabilityUnknownError:
            return self._profile_durability_unknown_payload(store)
        except LocalProfileConflict:
            try:
                current, recovery_required = self._load_profile_state(store)
            except LocalProfileError:
                return {
                    "ok": False,
                    "exists": True,
                    "announcement": self._profile_error_message(),
                }
            if current is None:
                return {
                    "ok": False,
                    "exists": False,
                    "displayName": "",
                    "generatedAlias": False,
                    "recoveryRequired": False,
                    "stateChanged": True,
                    "announcement": (
                        "The local profile changed in another window. No current profile remains."
                        if self.lang == "en"
                        else "Локальний профіль змінено в іншому вікні. Поточного профілю більше немає."
                    ),
                }
            conflict = self._profile_payload(
                current,
                recovery_required=recovery_required,
                announcement=(
                    "The local profile changed in another window. The current profile was reloaded."
                    if self.lang == "en"
                    else "Локальний профіль змінено в іншому вікні. Завантажено поточний профіль."
                ),
            )
            conflict["ok"] = False
            conflict["stateChanged"] = True
            return conflict
        except LocalProfileError:
            return {
                "ok": False,
                "exists": True,
                "announcement": self._profile_error_message(),
            }
        announcement = (
            f"Profile name changed to {profile.display_name}."
            if self.lang == "en"
            else f"Ім’я профілю змінено на {profile.display_name}."
        )
        return self._profile_payload(profile, announcement=announcement)

    def profile_rename(self, display_name: str) -> dict[str, object]:
        return self._invoke_ui(lambda: self._profile_rename_ui(display_name))


__all__ = ["Version2ProfileAccessibleChessAPI"]

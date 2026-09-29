from __future__ import annotations

"""Accessible V2 local-profile bridge over the canonical LocalProfileStore."""

from typing import Any

from .local_profile import LocalProfile, LocalProfileError, LocalProfileStore
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
                "recoveryRequired": recovery_required,
                "announcement": announcement,
            }
        # profile_id is intentionally not exposed to browser presentation.
        return {
            "ok": True,
            "exists": True,
            "displayName": profile.display_name,
            "generatedAlias": profile.generated_alias,
            "revision": profile.revision,
            "recoveryRequired": recovery_required,
            "announcement": announcement,
        }

    def _profile_store(self) -> LocalProfileStore:
        store = self._local_profile_store
        if not isinstance(store, LocalProfileStore):
            raise LocalProfileError("local profile store is unavailable")
        return store

    def _profile_snapshot_ui(self) -> dict[str, object]:
        try:
            store = self._profile_store()
            profile = store.load()
            return self._profile_payload(
                profile,
                recovery_required=store.recovery_required(),
            )
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
            profile = self._profile_store().create(None if skip else display_name)
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
            if not store.recovery_required():
                return self._profile_payload(store.load())
            profile = store.repair_from_backup()
        except LocalProfileError:
            return {
                "ok": False,
                "exists": True,
                "recoveryRequired": True,
                "announcement": self._profile_error_message(),
            }
        announcement = (
            "Local profile recovered from the verified backup."
            if self.lang == "en"
            else "Локальний профіль відновлено з перевіреної резервної копії."
        )
        return self._profile_payload(profile, announcement=announcement)

    def profile_repair(self) -> dict[str, object]:
        return self._invoke_ui(self._profile_repair_ui)

    def _profile_rename_ui(self, display_name: object) -> dict[str, object]:
        if not isinstance(display_name, str):
            return {
                "ok": False,
                "exists": True,
                "announcement": self._profile_error_message(),
            }
        try:
            store = self._profile_store()
            current = store.load()
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
            profile = store.rename(current, display_name)
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

from __future__ import annotations

"""Accessible presentation projection for licensing / entitlement state.

This module intentionally knows nothing about payment providers, network clients,
OAuth implementation, or chess rules.  It converts the neutral entitlement
contract required by issue #11 into concise keyboard/NVDA-friendly state that a
WebView or native shell can render with ordinary document semantics.
"""

from dataclasses import dataclass
from typing import Any, Mapping


_ALLOWED_STATES = frozenset({
    "free_beta",
    "trial",
    "paid_monthly",
    "paid_yearly",
    "organization",
    "grace_period",
    "expired",
    "revoked",
    "update_required",
})

_BLOCKING_STATES = frozenset({"expired", "revoked", "update_required"})


@dataclass(frozen=True)
class EntitlementView:
    state: str
    active: bool
    blocking: bool
    heading: str
    summary: str
    action_label: str | None
    action_id: str | None
    preserve_user_data: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "active": self.active,
            "blocking": self.blocking,
            "heading": self.heading,
            "summary": self.summary,
            "actionLabel": self.action_label,
            "actionId": self.action_id,
            "preserveUserData": self.preserve_user_data,
        }


_UK: dict[str, tuple[str, str, str | None, str | None]] = {
    "free_beta": (
        "Доступ до Accessible Chess",
        "Безкоштовний бета-доступ активний.",
        None,
        None,
    ),
    "trial": (
        "Пробний доступ",
        "Пробний доступ активний.",
        "Переглянути стан облікового запису",
        "account.status",
    ),
    "paid_monthly": (
        "Підписка активна",
        "Місячна підписка активна.",
        "Переглянути стан облікового запису",
        "account.status",
    ),
    "paid_yearly": (
        "Підписка активна",
        "Річна підписка активна.",
        "Переглянути стан облікового запису",
        "account.status",
    ),
    "organization": (
        "Організаційний доступ",
        "Доступ через організацію активний.",
        "Переглянути стан облікового запису",
        "account.status",
    ),
    "grace_period": (
        "Тимчасовий офлайн-доступ",
        "Сервер ліцензування зараз недоступний. Програма працює в дозволеному пільговому періоді; ваші локальні шахові дані не змінюються.",
        "Повторити перевірку доступу",
        "entitlement.refresh",
    ),
    "expired": (
        "Доступ завершився",
        "Термін доступу завершився. Ваші локальні партії, бази, книги та інші користувацькі дані збережено.",
        "Увійти або відновити доступ",
        "account.login",
    ),
    "revoked": (
        "Доступ відкликано",
        "Цю активацію відкликано. Ваші локальні партії, бази, книги та інші користувацькі дані збережено.",
        "Увійти або відновити доступ",
        "account.login",
    ),
    "update_required": (
        "Потрібне оновлення",
        "Ця версія Accessible Chess більше не підтримується для захищених функцій. Ваші локальні дані збережено.",
        "Перевірити оновлення",
        "app.update",
    ),
}

_EN: dict[str, tuple[str, str, str | None, str | None]] = {
    "free_beta": ("Accessible Chess access", "Free beta access is active.", None, None),
    "trial": ("Trial access", "Trial access is active.", "View account status", "account.status"),
    "paid_monthly": ("Subscription active", "Monthly subscription is active.", "View account status", "account.status"),
    "paid_yearly": ("Subscription active", "Yearly subscription is active.", "View account status", "account.status"),
    "organization": ("Organization access", "Organization access is active.", "View account status", "account.status"),
    "grace_period": (
        "Temporary offline access",
        "The licensing service is currently unavailable. Accessible Chess remains available during the permitted grace period; your local chess data is unchanged.",
        "Retry access check",
        "entitlement.refresh",
    ),
    "expired": (
        "Access expired",
        "Your access period has ended. Local games, databases, books, and other user-created data are preserved.",
        "Sign in or restore access",
        "account.login",
    ),
    "revoked": (
        "Access revoked",
        "This activation has been revoked. Local games, databases, books, and other user-created data are preserved.",
        "Sign in or restore access",
        "account.login",
    ),
    "update_required": (
        "Update required",
        "This Accessible Chess version is no longer supported for protected features. Your local data is preserved.",
        "Check for updates",
        "app.update",
    ),
}


def project_entitlement(payload: Mapping[str, Any] | None, *, lang: str = "uk") -> EntitlementView:
    """Project a neutral entitlement payload into accessible UI state.

    Unknown or malformed state fails closed for protected functionality but does
    not imply data deletion.  This is deliberate: UI must explain the problem
    before asking the user to recover access.
    """

    raw_state = str((payload or {}).get("state", "")).strip().lower()
    language = "en" if lang == "en" else "uk"
    if raw_state not in _ALLOWED_STATES:
        if language == "en":
            return EntitlementView(
                state="unknown",
                active=False,
                blocking=True,
                heading="Access status unavailable",
                summary="Accessible Chess could not verify the current access state. Your local user data is preserved.",
                action_label="Retry access check",
                action_id="entitlement.refresh",
            )
        return EntitlementView(
            state="unknown",
            active=False,
            blocking=True,
            heading="Стан доступу недоступний",
            summary="Accessible Chess не вдалося перевірити поточний стан доступу. Ваші локальні користувацькі дані збережено.",
            action_label="Повторити перевірку доступу",
            action_id="entitlement.refresh",
        )

    heading, summary, action_label, action_id = (_EN if language == "en" else _UK)[raw_state]
    blocking = raw_state in _BLOCKING_STATES
    return EntitlementView(
        state=raw_state,
        active=not blocking,
        blocking=blocking,
        heading=heading,
        summary=summary,
        action_label=action_label,
        action_id=action_id,
    )


def semantic_contract(view: EntitlementView) -> dict[str, Any]:
    """JSON-friendly rendering contract for semantic WebView/native UI.

    Presentation should render ``heading`` as a normal heading in document order,
    ``summary`` as ordinary text/status, and the optional action as a native
    button.  No whole-page ``role=application`` or inaccessible modal is needed.
    """

    return {
        **view.as_dict(),
        "headingRole": "heading",
        "statusRole": "status",
        "statusLive": "polite",
        "actionControl": "button" if view.action_id else None,
        "modalRequired": False,
        "destructiveAction": False,
    }

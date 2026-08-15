from pathlib import Path

from acs.webapp_keymap import KeymapAwareAccessibleChessAPI


def _api(tmp_path: Path, payload, lang: str = "uk") -> KeymapAwareAccessibleChessAPI:
    return KeymapAwareAccessibleChessAPI(
        keymap_path=tmp_path / "keymap.json",
        entitlement_payload=payload,
        lang=lang,
    )


def test_free_beta_is_visible_in_semantic_game_information(tmp_path: Path) -> None:
    state = _api(tmp_path, {"state": "free_beta"}).get_state()

    assert state["entitlement"]["state"] == "free_beta"
    assert state["entitlement"]["blocking"] is False
    assert state["entitlement"]["preserveUserData"] is True
    assert "Безкоштовний бета-доступ активний" in state["gameInfo"]


def test_expired_access_fails_closed_but_never_claims_data_deletion(tmp_path: Path) -> None:
    state = _api(tmp_path, {"state": "expired"}, lang="en").get_state()

    assert state["entitlement"]["blocking"] is True
    assert state["entitlement"]["active"] is False
    assert state["entitlement"]["actionId"] == "account.login"
    assert state["entitlement"]["destructiveAction"] is False
    assert state["entitlement"]["preserveUserData"] is True
    assert "preserved" in state["gameInfo"]


def test_unknown_access_state_is_fail_closed_and_accessible(tmp_path: Path) -> None:
    state = _api(tmp_path, {"state": "provider_specific_unknown"}).get_state()

    assert state["entitlement"]["state"] == "unknown"
    assert state["entitlement"]["blocking"] is True
    assert state["entitlement"]["statusRole"] == "status"
    assert state["entitlement"]["statusLive"] == "polite"
    assert state["entitlement"]["modalRequired"] is False
    assert "збережено" in state["gameInfo"]


def test_language_switch_reprojects_access_status_without_provider_logic(tmp_path: Path) -> None:
    api = _api(tmp_path, {"state": "grace_period"}, lang="uk")
    assert "Тимчасовий офлайн-доступ" in api.get_state()["gameInfo"]

    changed = api.set_language("en")

    assert changed["ok"] is True
    assert changed["entitlement"]["state"] == "grace_period"
    assert changed["entitlement"]["blocking"] is False
    assert "Temporary offline access" in changed["gameInfo"]

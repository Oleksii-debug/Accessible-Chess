from acs.ui_entitlement import project_entitlement, semantic_contract


def test_free_beta_is_active_and_non_blocking():
    view = project_entitlement({"state": "free_beta"}, lang="uk")

    assert view.state == "free_beta"
    assert view.active is True
    assert view.blocking is False
    assert view.preserve_user_data is True
    assert view.action_id is None


def test_revoked_and_expired_preserve_local_data_and_offer_recovery():
    for state in ("expired", "revoked"):
        view = project_entitlement({"state": state}, lang="en")

        assert view.active is False
        assert view.blocking is True
        assert view.preserve_user_data is True
        assert view.action_id == "account.login"
        assert "preserved" in view.summary


def test_grace_period_is_accessible_non_blocking_recovery_state():
    view = project_entitlement({"state": "grace_period"}, lang="uk")
    contract = semantic_contract(view)

    assert view.active is True
    assert view.blocking is False
    assert view.action_id == "entitlement.refresh"
    assert contract["statusRole"] == "status"
    assert contract["statusLive"] == "polite"
    assert contract["actionControl"] == "button"
    assert contract["modalRequired"] is False
    assert contract["destructiveAction"] is False


def test_update_required_blocks_protected_features_without_destructive_action():
    view = project_entitlement({"state": "update_required"}, lang="en")
    contract = semantic_contract(view)

    assert view.blocking is True
    assert view.action_id == "app.update"
    assert view.preserve_user_data is True
    assert contract["destructiveAction"] is False


def test_unknown_or_malformed_state_fails_closed_but_keeps_recovery_path():
    for payload in (None, {}, {"state": "unexpected-provider-specific-value"}):
        view = project_entitlement(payload, lang="uk")

        assert view.state == "unknown"
        assert view.active is False
        assert view.blocking is True
        assert view.preserve_user_data is True
        assert view.action_id == "entitlement.refresh"
        assert "збережено" in view.summary


def test_all_stable_issue_11_states_have_semantic_projection():
    states = {
        "free_beta",
        "trial",
        "paid_monthly",
        "paid_yearly",
        "organization",
        "grace_period",
        "expired",
        "revoked",
        "update_required",
    }

    for state in states:
        contract = semantic_contract(project_entitlement({"state": state}, lang="en"))
        assert contract["state"] == state
        assert contract["heading"]
        assert contract["summary"]
        assert contract["headingRole"] == "heading"
        assert contract["statusRole"] == "status"
        assert contract["modalRequired"] is False

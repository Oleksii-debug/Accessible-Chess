from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from acs.agent_checkpoint import (
    AgentCheckpointHead,
    CheckpointError,
    RewindStatus,
    assess_rewind,
    create_checkpoint,
    verify_checkpoint,
)


NOW = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)


def _checkpoint():
    return create_checkpoint(
        checkpoint_id="checkpoint-1",
        agent_id="chess-agent",
        run_id="run-1",
        plan_revision=2,
        internal_state_revision=5,
        effect_ledger_revision=3,
        policy_revision_id="policy-7",
        snapshot_utf8='{"state":"fixture"}',
        evidence_ids=("evidence-1",),
        created_at=NOW,
    )


def _head(**changes):
    base = AgentCheckpointHead(
        agent_id="chess-agent",
        run_id="run-1",
        plan_revision=3,
        internal_state_revision=7,
        effect_ledger_revision=3,
        policy_revision_id="policy-8",
        unresolved_effect_ids=(),
        observed_at=NOW + timedelta(seconds=10),
    )
    return replace(base, **changes)


def test_checkpoint_binds_exact_snapshot_bytes() -> None:
    checkpoint = _checkpoint()
    verify_checkpoint(checkpoint, '{"state":"fixture"}')
    with pytest.raises(CheckpointError, match="snapshot"):
        verify_checkpoint(checkpoint, '{"state":"changed"}')


def test_rewind_is_only_ready_for_reconciliation_not_auto_restore() -> None:
    assessment = assess_rewind(
        checkpoint=_checkpoint(),
        current=_head(),
        snapshot_utf8='{"state":"fixture"}',
    )
    assert assessment.status is RewindStatus.READY_FOR_RECONCILIATION
    assert assessment.restore_authorized is False
    assert assessment.requires_fresh_policy_evaluation is True
    assert assessment.requires_fresh_reconciliation is True
    assert assessment.target_plan_revision == 2
    assert assessment.target_internal_state_revision == 5


def test_rewind_blocks_if_external_effects_happened_after_checkpoint() -> None:
    assessment = assess_rewind(
        checkpoint=_checkpoint(),
        current=_head(effect_ledger_revision=4),
        snapshot_utf8='{"state":"fixture"}',
    )
    assert assessment.status is RewindStatus.BLOCKED
    assert assessment.reason_code == "EXTERNAL_EFFECTS_AFTER_CHECKPOINT"
    assert assessment.restore_authorized is False


def test_rewind_blocks_unresolved_external_effect() -> None:
    assessment = assess_rewind(
        checkpoint=_checkpoint(),
        current=_head(unresolved_effect_ids=("tool-effect-9",)),
        snapshot_utf8='{"state":"fixture"}',
    )
    assert assessment.status is RewindStatus.BLOCKED
    assert assessment.reason_code == "UNRESOLVED_EXTERNAL_EFFECTS"


def test_rewind_is_noop_when_internal_revisions_already_match() -> None:
    assessment = assess_rewind(
        checkpoint=_checkpoint(),
        current=_head(plan_revision=2, internal_state_revision=5),
        snapshot_utf8='{"state":"fixture"}',
    )
    assert assessment.status is RewindStatus.NOOP


def test_rewind_rejects_identity_or_revision_regression() -> None:
    with pytest.raises(CheckpointError):
        assess_rewind(
            checkpoint=_checkpoint(),
            current=_head(run_id="other-run"),
            snapshot_utf8='{"state":"fixture"}',
        )
    with pytest.raises(CheckpointError):
        assess_rewind(
            checkpoint=_checkpoint(),
            current=_head(effect_ledger_revision=2),
            snapshot_utf8='{"state":"fixture"}',
        )

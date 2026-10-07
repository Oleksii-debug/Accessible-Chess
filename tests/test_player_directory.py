import pytest

from acs.player_directory import (
    DirectoryPresenceSnapshot,
    DirectoryPresenceState,
    FriendIntentKind,
    FriendListSnapshot,
    FriendListSnapshotTracker,
    FriendRelationIntent,
    FriendRequestIntent,
    FriendshipSnapshot,
    FriendshipSnapshotTracker,
    FriendshipState,
    PlayerDirectoryContractError,
    PlayerDirectoryEntry,
    PlayerDirectorySnapshot,
    PlayerDirectorySnapshotTracker,
    validate_friend_intent,
)


def player(player_id: str, name: str, revision: int = 0, **kwargs):
    return PlayerDirectoryEntry(
        player_id=player_id,
        display_name=name,
        revision=revision,
        **kwargs,
    )


def test_public_directory_entry_normalizes_public_metadata_without_auth_fields():
    entry = player(
        "oleksii",
        "Oleksii",
        country_code="sk",
        language_tag="uk-UA",
        fide_rating=1800,
        national_rating=1850,
        app_rating=1725,
        chess_title="CM",
    )
    assert entry.country_code == "SK"
    assert entry.language_tag == "uk-UA"
    assert entry.to_record() == {
        "version": 1,
        "player_id": "oleksii",
        "display_name": "Oleksii",
        "revision": 0,
        "country_code": "SK",
        "language_tag": "uk-UA",
        "fide_rating": 1800,
        "national_rating": 1850,
        "app_rating": 1725,
        "chess_title": "CM",
    }
    assert "email" not in entry.to_record()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"player_id": "Bad ID", "display_name": "Name"},
        {"player_id": "ok", "display_name": " Name"},
        {"player_id": "ok", "display_name": "Name\nInjected"},
        {"player_id": "ok", "display_name": "Name", "country_code": "SVK"},
        {"player_id": "ok", "display_name": "Name", "language_tag": "u"},
        {"player_id": "ok", "display_name": "Name", "fide_rating": True},
    ],
)
def test_directory_entry_rejects_noncanonical_or_unbounded_public_values(kwargs):
    with pytest.raises(PlayerDirectoryContractError):
        PlayerDirectoryEntry(**kwargs)


def test_directory_snapshot_round_trip_presence_default_and_deterministic_search():
    snapshot = PlayerDirectorySnapshot(
        revision=7,
        players=(
            player("zeta", "Žaneta", country_code="SK", language_tag="sk"),
            player("anna", "Anna Chess", country_code="UA", language_tag="uk"),
            player("andrii", "Andrii", country_code="UA", language_tag="uk", chess_title="FM"),
        ),
        presences=(
            DirectoryPresenceSnapshot("anna", DirectoryPresenceState.AVAILABLE, 3),
            DirectoryPresenceSnapshot("andrii", DirectoryPresenceState.IN_GAME, 4),
        ),
    )
    restored = PlayerDirectorySnapshot.from_record(snapshot.to_record())
    assert restored == snapshot
    assert restored.presence("zeta").state is DirectoryPresenceState.OFFLINE
    assert [entry.player_id for entry in restored.search("chess")] == ["anna"]
    assert [entry.player_id for entry in restored.search("", country_code="ua")] == [
        "andrii",
        "anna",
    ]
    assert [entry.player_id for entry in restored.search("fm", language_tag="uk")] == [
        "andrii"
    ]
    assert restored.search("", exclude_player_ids=("andrii",), limit=2) == (
        restored.player("anna"),
        restored.player("zeta"),
    )


def test_directory_snapshot_rejects_duplicate_and_orphan_presence():
    a = player("a", "A")
    with pytest.raises(PlayerDirectoryContractError, match="duplicate player id"):
        PlayerDirectorySnapshot(revision=1, players=(a, a))
    with pytest.raises(PlayerDirectoryContractError, match="outside the snapshot"):
        PlayerDirectorySnapshot(
            revision=1,
            players=(a,),
            presences=(DirectoryPresenceSnapshot("b"),),
        )


def test_directory_tracker_is_monotonic_and_rejects_component_revision_regression():
    first = PlayerDirectorySnapshot(
        revision=4,
        players=(player("a", "Alpha", revision=3),),
        presences=(DirectoryPresenceSnapshot("a", DirectoryPresenceState.AVAILABLE, 2),),
    )
    tracker = PlayerDirectorySnapshotTracker(first)
    assert tracker.apply(first) is False
    with pytest.raises(PlayerDirectoryContractError, match="stale"):
        tracker.apply(PlayerDirectorySnapshot(revision=3))
    with pytest.raises(PlayerDirectoryContractError, match="conflicting"):
        tracker.apply(PlayerDirectorySnapshot(revision=4))
    with pytest.raises(PlayerDirectoryContractError, match="player entry revision regressed"):
        tracker.apply(
            PlayerDirectorySnapshot(
                revision=5,
                players=(player("a", "Alpha", revision=2),),
            )
        )
    newer = PlayerDirectorySnapshot(
        revision=5,
        players=(player("a", "Alpha Prime", revision=4),),
        presences=(DirectoryPresenceSnapshot("a", DirectoryPresenceState.BUSY, 3),),
    )
    assert tracker.apply(newer) is True
    assert tracker.snapshot == newer


def pending(revision: int = 0):
    return FriendshipSnapshot(
        relation_id="friend:a:b",
        requester_id="a",
        addressee_id="b",
        revision=revision,
    )


def intent(actor: str, kind: FriendIntentKind, revision: int = 0):
    return FriendRelationIntent(
        relation_id="friend:a:b",
        actor_id=actor,
        expected_revision=revision,
        kind=kind,
    )


def test_friend_intent_identity_is_deterministic_and_permissions_are_fail_closed():
    first = intent("b", FriendIntentKind.ACCEPT)
    second = intent("b", FriendIntentKind.ACCEPT)
    assert first.intent_id == second.intent_id
    assert len(first.intent_id) == 64
    validate_friend_intent(pending(), first)
    validate_friend_intent(pending(), intent("a", FriendIntentKind.CANCEL))
    validate_friend_intent(pending(), intent("a", FriendIntentKind.BLOCK))
    with pytest.raises(PlayerDirectoryContractError, match="addressee"):
        validate_friend_intent(pending(), intent("a", FriendIntentKind.ACCEPT))
    with pytest.raises(PlayerDirectoryContractError, match="sender"):
        validate_friend_intent(pending(), intent("b", FriendIntentKind.CANCEL))
    with pytest.raises(PlayerDirectoryContractError, match="stale"):
        validate_friend_intent(pending(revision=1), intent("b", FriendIntentKind.ACCEPT))


def test_blocked_relation_identifies_blocker_and_only_blocker_can_unblock():
    with pytest.raises(PlayerDirectoryContractError, match="blocker"):
        FriendshipSnapshot(
            relation_id="friend:a:b",
            requester_id="a",
            addressee_id="b",
            state=FriendshipState.BLOCKED,
        )
    blocked = FriendshipSnapshot(
        relation_id="friend:a:b",
        requester_id="a",
        addressee_id="b",
        revision=2,
        state=FriendshipState.BLOCKED,
        blocked_by_id="b",
    )
    validate_friend_intent(blocked, intent("b", FriendIntentKind.UNBLOCK, revision=2))
    with pytest.raises(PlayerDirectoryContractError, match="participant who blocked"):
        validate_friend_intent(blocked, intent("a", FriendIntentKind.UNBLOCK, revision=2))


def test_friendship_tracker_allows_only_server_authoritative_monotonic_transitions():
    tracker = FriendshipSnapshotTracker(pending())
    accepted = FriendshipSnapshot(
        relation_id="friend:a:b",
        requester_id="a",
        addressee_id="b",
        revision=1,
        state=FriendshipState.ACCEPTED,
    )
    assert tracker.apply(accepted) is True
    with pytest.raises(PlayerDirectoryContractError, match="without a state transition"):
        tracker.apply(
            FriendshipSnapshot(
                relation_id="friend:a:b",
                requester_id="a",
                addressee_id="b",
                revision=2,
                state=FriendshipState.ACCEPTED,
            )
        )
    blocked = FriendshipSnapshot(
        relation_id="friend:a:b",
        requester_id="a",
        addressee_id="b",
        revision=2,
        state=FriendshipState.BLOCKED,
        blocked_by_id="a",
    )
    assert tracker.apply(blocked) is True
    removed = FriendshipSnapshot(
        relation_id="friend:a:b",
        requester_id="a",
        addressee_id="b",
        revision=3,
        state=FriendshipState.REMOVED,
    )
    assert tracker.apply(removed) is True
    with pytest.raises(PlayerDirectoryContractError, match="terminal"):
        tracker.apply(
            FriendshipSnapshot(
                relation_id="friend:a:b",
                requester_id="a",
                addressee_id="b",
                revision=4,
                state=FriendshipState.ACCEPTED,
            )
        )


def test_friendship_tracker_rejects_skipped_revision_and_direction_change():
    tracker = FriendshipSnapshotTracker(pending(revision=2))
    with pytest.raises(PlayerDirectoryContractError, match="advance by one"):
        tracker.apply(
            FriendshipSnapshot(
                relation_id="friend:a:b",
                requester_id="a",
                addressee_id="b",
                revision=4,
                state=FriendshipState.ACCEPTED,
            )
        )
    with pytest.raises(PlayerDirectoryContractError, match="request direction changed"):
        tracker.apply(
            FriendshipSnapshot(
                relation_id="friend:a:b",
                requester_id="b",
                addressee_id="a",
                revision=3,
                state=FriendshipState.ACCEPTED,
            )
        )


def test_friend_list_is_owner_scoped_unique_and_reports_only_accepted_friends():
    accepted = FriendshipSnapshot(
        relation_id="r1",
        requester_id="owner",
        addressee_id="friend2",
        revision=1,
        state=FriendshipState.ACCEPTED,
    )
    pending_relation = FriendshipSnapshot(
        relation_id="r2",
        requester_id="friend1",
        addressee_id="owner",
    )
    snapshot = FriendListSnapshot(
        owner_id="owner", revision=9, relationships=(pending_relation, accepted)
    )
    assert snapshot.accepted_friend_ids() == ("friend2",)
    assert FriendListSnapshot.from_record(snapshot.to_record()) == snapshot
    with pytest.raises(PlayerDirectoryContractError, match="does not involve"):
        FriendListSnapshot(
            owner_id="owner",
            revision=1,
            relationships=(
                FriendshipSnapshot(
                    relation_id="other",
                    requester_id="a",
                    addressee_id="b",
                ),
            ),
        )


def test_wire_decoders_reject_unknown_fields_instead_of_silently_accepting_drift():
    record = player("a", "A").to_record()
    record["email"] = "should-not-be-public@example.test"
    with pytest.raises(PlayerDirectoryContractError, match="extra=email"):
        PlayerDirectoryEntry.from_record(record)

    relation = pending().to_record()
    relation.pop("blocked_by_id")
    with pytest.raises(PlayerDirectoryContractError, match="missing=blocked_by_id"):
        FriendshipSnapshot.from_record(relation)


def test_friend_request_creation_intent_is_idempotent_and_has_no_server_relation_id():
    first = FriendRequestIntent(
        requester_id="a", addressee_id="b", client_nonce="request-001"
    )
    second = FriendRequestIntent(
        requester_id="a", addressee_id="b", client_nonce="request-001"
    )
    assert first.intent_id == second.intent_id
    assert len(first.intent_id) == 64
    assert not hasattr(first, "relation_id")
    with pytest.raises(PlayerDirectoryContractError, match="distinct"):
        FriendRequestIntent(
            requester_id="a", addressee_id="a", client_nonce="request-002"
        )


def test_friend_list_tracker_is_owner_scoped_and_rejects_relation_regression():
    relation = FriendshipSnapshot(
        relation_id="r1",
        requester_id="owner",
        addressee_id="friend",
        revision=2,
        state=FriendshipState.ACCEPTED,
    )
    first = FriendListSnapshot(owner_id="owner", revision=7, relationships=(relation,))
    tracker = FriendListSnapshotTracker(first)
    assert tracker.apply(first) is False
    with pytest.raises(PlayerDirectoryContractError, match="different owner"):
        tracker.apply(FriendListSnapshot(owner_id="other", revision=8))
    with pytest.raises(PlayerDirectoryContractError, match="relation revision regressed"):
        tracker.apply(
            FriendListSnapshot(
                owner_id="owner",
                revision=8,
                relationships=(
                    FriendshipSnapshot(
                        relation_id="r1",
                        requester_id="owner",
                        addressee_id="friend",
                        revision=1,
                        state=FriendshipState.ACCEPTED,
                    ),
                ),
            )
        )
    newer = FriendListSnapshot(owner_id="owner", revision=8, relationships=())
    assert tracker.apply(newer) is True
    assert tracker.snapshot == newer

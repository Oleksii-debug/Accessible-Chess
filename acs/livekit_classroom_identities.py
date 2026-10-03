from __future__ import annotations

"""Provider namespace reserved for trusted Accessible Chess service identities.

These identifiers are LiveKit transport identities, not classroom membership,
authentication, roster, role, or chess authority. Member token issuance must
never allocate a reserved service identity.
"""


MODERATION_SERVICE_PARTICIPANT_IDENTITY = "moderation-service"
RESERVED_MEMBER_PARTICIPANT_IDENTITIES = frozenset(
    {MODERATION_SERVICE_PARTICIPANT_IDENTITY}
)


__all__ = [
    "MODERATION_SERVICE_PARTICIPANT_IDENTITY",
    "RESERVED_MEMBER_PARTICIPANT_IDENTITIES",
]

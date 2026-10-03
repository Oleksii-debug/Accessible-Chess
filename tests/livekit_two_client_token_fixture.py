from __future__ import annotations

"""Generate short-lived real-provider smoke credentials through the canonical issuer."""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from acs.classroom_join_credentials import ClassroomJoinGrant
from acs.classroom_realtime_media import MediaSource
from acs.livekit_join_token_issuer import LiveKitJoinTokenIssuer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--api-secret", required=True)
    parser.add_argument("--room", default="accessible-chess-media-smoke")
    parser.add_argument("--output", required=True)
    return parser


async def _issue(args: argparse.Namespace) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=2)
    issuer = LiveKitJoinTokenIssuer(
        api_key=args.api_key,
        api_secret=args.api_secret,
    )

    publisher = ClassroomJoinGrant(
        room_id=args.room,
        participant_id="publisher-1",
        publish_sources=(MediaSource.MICROPHONE, MediaSource.CAMERA),
    )
    subscriber = ClassroomJoinGrant(
        room_id=args.room,
        participant_id="subscriber-1",
        publish_sources=(),
    )

    publisher_token = await issuer.issue_join_token(
        grant=publisher,
        issued_at=now - timedelta(seconds=1),
        expires_at=expires,
    )
    subscriber_token = await issuer.issue_join_token(
        grant=subscriber,
        issued_at=now - timedelta(seconds=1),
        expires_at=expires,
    )
    return {
        "schema_version": 1,
        "room_id": args.room,
        "publisher": {
            "participant_id": publisher.participant_id,
            "token": publisher_token,
        },
        "subscriber": {
            "participant_id": subscriber.participant_id,
            "token": subscriber_token,
        },
    }


def main() -> int:
    args = _parser().parse_args()
    payload = asyncio.run(_issue(args))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    output.chmod(0o600)
    print(
        "LIVEKIT_TWO_CLIENT_TOKEN_FIXTURE=PASS "
        f"room={payload['room_id']} participants=2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

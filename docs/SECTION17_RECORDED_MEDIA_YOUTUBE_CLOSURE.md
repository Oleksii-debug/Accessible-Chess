# Section 17 closure candidate — Recorded Media and YouTube playback

Canonical plan scope:

- 17.1 Local/user-owned recorded-media preprocessing.
- 17.2 YouTube IFrame documented playback adapter.
- 17.3 Permitted provider metadata through documented APIs.
- 17.4 No prohibited media download/cache/undocumented stream extraction.
- 17.5 Persisted recorded timeline for repeated playback.

## Accepted dependency

Section 16 is terminally DONE in `SEQUENTIAL_CLOSURE_STATE.md`.
This candidate descends from the accepted Section 16 source candidate
`7bf0a28dc65d5ceef45f78af0a5f023503b79a28`.

## Acceptance mapping

### 17.1 Local/user-owned preprocessing

- `acs/media_preprocess.py` defines the bounded preprocessing plan and passive evidence DTOs.
- `acs/media_preprocess_executor.py` executes injected local preprocessing ports without owning chess legality.
- `acs/recorded_media_sync.py` publishes only through the canonical Media Core / canonical chess application boundary.
- `tests/test_media_preprocess.py`, `tests/test_media_preprocess_executor.py`, and
  `tests/test_recorded_media_sync.py` qualify cancellation, retry, revision binding, ambiguity,
  fail-closed behavior and deterministic timeline publication.

### 17.2 Documented YouTube playback

- `web/youtube_iframe_playback_adapter.js` uses the documented YouTube IFrame Player API surface.
- `tests/js/youtube_iframe_playback_adapter_test.js` qualifies source parsing, player commands,
  event-driven clock snapshots, origin binding and provider error handling.
- The adapter does not resolve or request raw audio/video stream URLs.

### 17.3 Documented provider metadata

- `web/youtube_provider_metadata.js` uses only the documented YouTube Data API v3
  `videos.list` endpoint at `https://www.googleapis.com/youtube/v3/videos`.
- The request is read-only, redirect-fail-closed, credential-omitting and `cache: no-store`.
- Returned browser-facing data is a bounded metadata DTO and excludes descriptions,
  thumbnails, API credentials and any media URL.
- `tests/js/youtube_provider_metadata_adapter_test.js` verifies host/path/query constraints,
  response bounds, malformed-result rejection and absence of undocumented media surfaces.

Official provider documentation checked for this closure:
- https://developers.google.com/youtube/iframe_api_reference
- https://developers.google.com/youtube/v3/docs/videos/list

### 17.4 Prohibited surfaces remain absent

The Section 17 whole-contract gate rejects known raw/undocumented YouTube media surfaces such
as `googlevideo`, `videoplayback`, `get_video_info`, `player_response`, HLS manifests and
DASH manifests in the provider adapters. Recorded preprocessing remains local/injected and does
not add a provider-network authority.

### 17.5 Persisted timeline and repeated playback

`acs/recorded_media_sync.py` reuses canonical Media Core serialization for a bounded,
versioned recorded-media state. Its tests cover deterministic replay, seek resolution,
serialization/deserialization round-trip, saved media position, source/cache/revision binding and
stale/tampered-state rejection.

## Closure rule

This document is not itself a DONE claim. Section 17 becomes terminally DONE only after the exact
frozen candidate passes the Section 17 whole-contract workflow on the available Ubuntu and Windows
runners, is integrated into the canonical Section 17 finisher lineage, receives post-merge readback,
and the durable closure registry is updated. Once DONE, ordinary workers must skip Section 17 unless
the repository records a demonstrated regression, invalid closure evidence, materially changed
acceptance contract or later integration break.

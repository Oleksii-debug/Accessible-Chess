# Accessible Chess — Sections 47 and 48: real-video qualification

## Scope, not a DONE claim
Current canonical plan: ACCESSIBLE CHESS — SECTION PLAN ДО ПОВНІСТЮ ЗАВЕРШЕНОГО ПРОДУКТУ (Google Drive, 2026-10-08).
Reuses accepted Section 17 YouTube IFrame adapter and recorded media engine and Sections 19/20 MediaPositionTimeline/MediaSession, without new chess authority.

## Implemented in this candidate
- web/real_media_workbench.html: semantically labeled, keyboard and NVDA-oriented separate local video and remote YouTube surfaces.
- web/real_media_workbench.js: actual HTML5 local-file MP4/WebM selection and native play/pause/seek, 10-second rewind/forward, speed and volume, source reopening and blob URL revocation, accessible error status. Does not contact YouTube for local video.
- The same workbench uses the documented existing IFrame Player API adapter for video ID/HTTPS URLs, play/pause/seek/event/current time, visible third-party player, and offline/provider error states. Never downloads YouTube streams.
- For both providers chess state is explicitly UNLINKED until existing canonical Media Core supplies independently verified board/PGN/FEN evidence. A callback is not an integrated Windows MediaSession.

## Lawful real ORIGINAL source pages, NOT yet downloaded in this work
Documented metadata and licenses in docs/SECTION47_48_REAL_MEDIA_CATALOG.json:
1. Byrne vs Fischer - The Game of the Century.webm — Tamuz Hasan, CC BY-SA 4.0, 108s, original Wikimedia SHA1 022b2c55b284c9586c5bee695d82af3a582b2adc.
2. Joaquin Perkins blitz chess vs USCF expert.webm — Keleperkins, CC BY-SA 3.0, ~20s, original Wikimedia SHA1 910919c9c3f442c85d1388f85576956ee4ffa320.
3. Youth chess tournament.webm — Samson Ssemakadde, CC0 1.0, ~26s.
4. Youth chess championships.webm — Samson Ssemakadde, CC0 1.0, ~12s.

Rights remain asset-specific. Before any public release retain original attribution/license, source and changes. Source-page checked != bytes downloaded: missing SHA256 and download_verified=false are deliberate. To produce private real-original SHA256 receipts and verify complete ffmpeg decoding:
    python tools/section47_download_commons_corpus.py --output PRIVATE_EMPTY_DIRECTORY --decode
Requires online access; output directory must be empty to protect existing data; ffmpeg and ffprobe must be installed. Originals do not belong in the public git tree by default. The emitted RECEIPT.json contains measured SHA-256 and full decoder outcomes.

## YouTube source registry
- https://www.youtube.com/watch?v=M7lc1UVf-VE — Google Developers IFrame API example; technical smoke only, NOT a chess video.
- https://www.youtube.com/watch?v=k4BS-4O1iI0 — Saint Louis Chess Club, 2025 Sinquefield Cup Round 1; chess publisher video; embed permission UNKNOWN.
- https://www.youtube.com/watch?v=sMsExxmQ8gQ — Saint Louis Chess Club, 2025 Sinquefield Cup Round 6; chess publisher video; embed permission UNKNOWN.
Actual embed result and embeddable status cannot be inferred from a public watch page; must independently verify via permitted official provider metadata and an actual live IFrame run. No cache/download/bypass/hidden controls or branding.

## Qualification — distinct evidence classes
- SIMULATED contract: node tests/js/youtube_iframe_playback_adapter_test.js and node tests/js/section47_48_real_media_workbench_test.js; plus Python adversarial integrity tests. This does NOT prove live provider or physical playback.
- EXTERNAL ORIGINAL BYTES: real Commons API fingerprint, streaming SHA1+measured SHA256, ffprobe/ffmpeg decode, preserved source and license. CI independent job, may fail due network.
- WINDOWS BROWSER REAL PLAYBACK: MP4/WebM loaded into real packaged Windows WebView, seek/pause/rewind/restart and codec rejection confirmed. Not proved by ffmpeg.
- CANONICAL CHESS: timecode-to-board observations, actual PGN/FEN validation and MediaSession restore by existing canonical chess application; uncertainty never promoted to confirmed.
- LIVE YOUTUBE: real chess-channel IFrame embed/current time/events, private/unavailable/embeddable/autoplay/network failure and NVDA feedback. Mock passes are not live passes.

## Terminal state
Section 47: IN_PROGRESS — NOT DONE until source-byte SHA256 receipts, actual Windows playback, board/PGN/FEN matching, MediaSession restore and packaged readback.
Section 48: IN_PROGRESS — NOT DONE until real chess publisher embed, independently labeled live smoke/negative cases, provider clock-to-timeline integration, and Windows/accessible readback.
Existing Section 17 remains terminally DONE and not reopened. No manual user/NVDA acceptance is demanded before the final whole-product release stage under AGENTS.md v3.

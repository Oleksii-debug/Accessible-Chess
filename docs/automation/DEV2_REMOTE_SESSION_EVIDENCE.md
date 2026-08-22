# DEV2 full-product validation marker

Validation-only branch. DO NOT MERGE.

Canonical Product source under test: `auto/dev2-full-product-core-20260822 @ 7d525dd34f6ae1a2083a79e25638cbc101e9beaf`.

Current DEV2 delta extends the already-GREEN remote/shared-session package with bounded presentation-state exchange: highlights, arrows, and student pointer history now have explicit finite v1 limits; in-process iterables are consumed only through limit + 1; oversized JSON arrays fail before per-entry parsing. Existing chess, GameTree, FEN, UI and remote-session semantics are unchanged.

This branch continues to overlay only the accepted DEV1 rank/file/keybinding/WebView compatibility blobs for aggregate validation. They are evidence-only and are not canonical DEV2 Product changes.

Retrigger marker: bounded presentation-state canonical source validation.

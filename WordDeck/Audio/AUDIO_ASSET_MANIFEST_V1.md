# WordDeck Audio Asset Manifest v1

This document defines the presentation-neutral metadata contract for local WordDeck audio assets. It does not generate audio, authorize redistribution, or replace the accepted Oxford pronunciation pack. Existing lexical playback remains compatible while future word, sentence, dialogue, story and listening-passage packs can share one integrity/provenance model.

## Schema identity

`schema` is fixed to `worddeck-audio-assets-v1` for this version. A manifest also has a stable `pack_id`, a `pack_version`, and an `assets` array. Every asset repeats `pack_version` so flattened audit exports cannot silently mix files from different releases.

## Required asset fields

- `asset_id`: stable identifier for the audio object. It identifies the recording/rendering, not merely its text.
- `text_id`: stable identifier of the canonical text/content being spoken. For Oxford words this can be the lexical entry ID; sentence/dialogue/story/listening systems should use their own canonical stable content IDs.
- `content_type`: exactly one of `word`, `sentence`, `dialogue`, `story`, `listening-passage`.
- `speaker`: stable human speaker, TTS voice, narrator, or cast identifier. A multi-speaker dialogue may use a stable cast ID; per-turn speaker metadata belongs to the dialogue/text model and should not be duplicated here.
- `accent`: declared accent/locale, for example `en-GB`. The current Oxford pronunciation contract remains British English.
- `production`: exactly `human` or `tts`.
- `speed`: playback/rendering speed multiplier. v1 accepts 0.25 through 4.0; normal-speed WordDeck production is 1.0 unless a future approved pack says otherwise.
- `level`: pedagogical level metadata such as A1/A2/B1/B2/C1 or another explicit nonblank level label owned by the content pack. This field does not create an Oxford C2 scope.
- `license`: explicit redistribution/use license descriptor. Blank or unknown license metadata is rejected; the manifest does not itself grant rights.
- `source`: provenance descriptor for the recording or generation source. Runtime treats it as metadata and never downloads it.
- `hash`: `sha256:` followed by exactly 64 hexadecimal characters, computed over the local asset bytes.
- `duration_ms`: positive duration in milliseconds.
- `pack_version`: must exactly equal the manifest-level `pack_version`.
- `relative_path`: required local path beneath the pack root. Absolute paths, drive-qualified paths and `..` traversal are rejected.

`relative_path` is intentionally additional to the requested identity/provenance fields: IDs tell WordDeck what an asset is; the path tells the offline runtime where its bytes are. Paths are relative so packs remain portable across Windows installations, spaces and Cyrillic user paths without embedding personal machine locations.

## Example shape

The following is illustrative metadata only, not a production pack and not a licensing claim:

```json
{
  "schema": "worddeck-audio-assets-v1",
  "pack_id": "example-non-production",
  "pack_version": "0.0-test",
  "assets": [
    {
      "asset_id": "asset-word-example",
      "text_id": "lexical-entry-stable-id",
      "content_type": "word",
      "speaker": "example-en-gb-voice",
      "accent": "en-GB",
      "production": "tts",
      "speed": 1.0,
      "level": "A1",
      "license": "example-only-not-for-release",
      "source": "non-production-example",
      "hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
      "duration_ms": 900,
      "pack_version": "0.0-test",
      "relative_path": "word/asset-word-example.mp3"
    }
  ]
}
```

The runtime validator will reject this example against a real file unless the file's SHA-256 actually matches the shown value.

## Runtime API

`AudioAssetManifestJson` loads/serializes strict JSON. Unknown JSON properties are rejected so typos do not silently discard provenance.

`AudioAssetManifestValidator` validates schema, required metadata, unique asset IDs, supported content types, human/TTS declaration, speed/duration, pack-version consistency, safe relative paths and SHA-256 syntax. `VerifyAllFiles` additionally proves that every listed local file exists and matches its declared hash.

`AudioAssetCatalog` provides deterministic lookup by `asset_id` and by `(content_type, text_id)`. Multiple assets may share a text ID, allowing alternate speakers or approved variants without changing canonical text identity.

`WordDeck.exe --validate-audio-asset-manifest <manifest.json> <pack-root>` is a read-only offline validation command. It performs schema/path/hash checks and prints counts by content type. It never calls a network service.

## Compatibility and migration

The accepted lexical AudioPack currently has a legacy stable-ID file layout and a development/release `worddeck-audiopack-v1` builder. This new schema does not force conversion or regeneration of those accepted MP3 files. An integrator can later create metadata for existing bytes and adopt the universal catalog only when provenance/license/duration fields are known truthfully.

No credentials, API keys, TTS service secrets or machine-specific absolute paths belong in a manifest. Generation systems remain development tooling; production playback remains local/offline.

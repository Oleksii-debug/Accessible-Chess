# Optional CBV extraction backend

Accessible Chess can import an unencrypted ChessBase `.cbv` archive through an
optional external `uncbv` executable, then decode the extracted classic `.cbh`
family through the separately configured `libcbh` bridge.  Neither GPL backend
is bundled in the default package.

Evidence pins:

- `antoyo/uncbv` commit `3c18e8a7c6a30c21f945a1ab5462521c306dca57`
  (`GPL-3.0`);
- `rolandlo/libcbh` commit
  `9641c5c3949d8fb210b17dd9aa54455645843696` (`GPL-2.0`).

The trusted host must configure `ExternalCbvExtractorConfig` with the exact
SHA-256 of the built `uncbv` executable and configure
`ExternalChessBaseDecoderConfig` with the exact expected `libcbh` commit.

The extraction boundary:

1. fingerprints the immutable `.cbv` source and pinned executable;
2. lists every archive entry before extraction;
3. rejects absolute paths, drive paths, traversal, duplicate/case-colliding
   names, excessive entry counts and excessive source/output sizes;
4. extracts only to a new empty temporary directory with bounded time and
   process output;
5. rejects symlink/reparse/non-regular or unexpected output;
6. requires exactly one extracted `.cbh` primary;
7. re-verifies the archive and extractor bytes before accepting output;
8. decodes the temporary CBH family to canonical `GameTree` objects and
   publishes them atomically to ACSDB under the original CBV provenance;
9. deletes the temporary family after decoding and never writes to the source.

Encrypted `.cbz`, legacy `.cbf`, `.2cbh` and `.cbone` are not enabled by this
path.  They remain blocked until an independently licensed, fixture-backed,
fail-closed decoder exists.

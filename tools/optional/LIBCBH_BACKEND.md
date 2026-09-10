# Optional libcbh ChessBase backend

Accessible Chess keeps ChessBase semantic decoding behind an external process boundary.
The core application does not import, embed, or copy the libcbh decoder implementation.

Current reference evidence is pinned to:

- repository: `rolandlo/libcbh`
- commit: `9641c5c3949d8fb210b17dd9aa54455645843696`
- repository license: GPL-2.0
- protocol: `accessible-chess-libcbh-v1`

`tools/optional/libcbh_json_bridge.cpp` is Accessible Chess adapter code that uses the
public libcbh API and emits bounded neutral JSON. A binary linked with libcbh is a
separately licensed component. It is not part of the default Accessible Chess package
and must not be redistributed as part of a release until the release/license review
explicitly approves the exact binary, source/version provenance, notices and obligations.

The Python Product boundary `acs/chessbase_decoder.py` is decoder-neutral. It:

- starts one exact configured executable without a shell;
- bounds time and stdout/stderr;
- rejects ambiguous JSON and untrusted backend identity;
- fingerprints the complete classic CBH source family before execution and verifies it
  again afterwards;
- re-validates every decoded ordinary move using the canonical Accessible Chess board;
- converts the backend result into the canonical GameTree rather than maintaining a
  second chess model.

The external backend currently enables only classic `.cbh` component families. CBV,
CBF, 2CBH and CBONE remain unsupported by this backend until independent format/backend
evidence exists. The capability must therefore be reported dynamically from an actually
configured and validated backend, never from filename recognition alone.

Upstream fixture databases used by CI remain in the upstream repository. They are fetched
at the pinned commit for evidence and are not copied into this repository or release
artifacts.

# V2 Starter Content Discovery UX

The packaged corpus is not acceptable if users must inspect installation folders to find it.

The Windows application must expose an accessible route such as Starter Library / Included Content / Sample Content (final naming may follow existing navigation conventions) that lets a keyboard/NVDA user discover and open bundled books, training material, games and the sample Library/database.

Requirements:

- reachable through normal keyboard navigation and Help/menu discoverability;
- concise accessible names and current selection/state;
- no absolute installation-path knowledge required;
- bundled content identities remain stable after extraction to a different folder;
- opening supplied content follows the same canonical Books/Training/PGN/Library services as imported user content;
- missing/corrupt packaged content fails with a concise user-facing message, not traceback/path leakage.
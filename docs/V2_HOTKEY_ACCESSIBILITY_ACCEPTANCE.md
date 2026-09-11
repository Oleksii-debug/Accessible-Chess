# V2 Hotkey Accessibility Acceptance

For every critical user-facing keyboard shortcut, verify:

1. the shortcut is reachable without a mouse;
2. the intended command is the one actually mapped in the live keymap;
3. the action occurs against the correct canonical/review state;
4. the resulting user-relevant value/state/result is exposed accessibly;
5. NVDA can read that result immediately without requiring visual inspection;
6. focus remains logical;
7. repeated use does not create unsolicited/background speech spam;
8. Help/keymap text matches actual behavior;
9. no raw UCI, traceback, local path, provider/debug internals or secrets are exposed.

A shortcut fails acceptance if it changes state silently.

Oleksii's `Alt+1` / `Alt+2` report is the triggering user finding, not permission to hard-code an assumed mapping. Verify the current mapping first and then audit all critical shortcuts for the same defect class.
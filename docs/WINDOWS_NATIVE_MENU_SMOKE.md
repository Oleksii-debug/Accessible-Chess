# Windows native menu packaged acceptance smoke

This is the release-facing acceptance contract for the Accessible Chess application menu. Source-level composition tests are necessary but are not sufficient.

The test target is the actual packaged Windows EXE and its actual top-level process window.

1. Start the packaged application with the production WebView2/WinForms composition.
2. Confirm the application window contains a discoverable Windows UI Automation descendant with `ControlType.MenuBar`. The menu must be the native `AccessibleChessMainMenu`; an HTML/WebView imitation is not an acceptable substitute.
3. Press `Alt`. The application menu must receive normal Windows menu focus without requiring WebView browse-mode navigation.
4. Use `ArrowRight`/`ArrowLeft` between top-level menus and `ArrowDown`/`ArrowUp` inside a submenu.
5. Press `Enter` on one safe, reversible command and verify that the command activates through the application action path.
6. Press `Esc` to close the menu and return to the application without trapping keyboard focus.
7. Repeat the keyboard journey with NVDA running. This remains HUMAN-ONLY UNPROVEN until Oleksii personally completes the Windows+NVDA test.

For structural diagnostics in Python.NET, do not compare CLR objects with Python `is`. Repeated CLR property access may be represented by different Python proxies for the same managed object. Use `acs.ui_native_menu.native_menu_attachment_state`, which performs proxy-safe managed-object identity checks for MenuStrip parent and `MainMenuStrip` ownership.

A failed packaged structural check blocks release. A hosted environment that cannot prove its own WinForms baseline does not by itself justify changing product menu semantics.
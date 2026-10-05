from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact replacement, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "acs/full_product_actions.py",
    '''    _action("pgn.previous_item", BindingContext.PGN_TREE, "Previous GameTree item", "Up"),
    _action("pgn.next_item", BindingContext.PGN_TREE, "Next GameTree item", "Down"),
    _action("pgn.parent_variation", BindingContext.PGN_TREE, "Return to parent variation", "Left"),
''',
    '''    _action("pgn.previous_item", BindingContext.PGN_TREE, "Previous GameTree item", "Up"),
    _action("pgn.next_item", BindingContext.PGN_TREE, "Next GameTree item", "Down"),
    _action("pgn.parent_variation", BindingContext.PGN_TREE, "Return to parent variation", "Left"),
    _action("pgn.first_child", BindingContext.PGN_TREE, "First child GameTree item", "Right"),
    _action("pgn.first_item", BindingContext.PGN_TREE, "First GameTree item", "Home"),
    _action("pgn.last_item", BindingContext.PGN_TREE, "Last GameTree item", "End"),
''',
)

replace_once(
    "web/full_product_pgn.js",
    '''          if (event.key === "ArrowUp") actionId = "pgn.previous_item";
          else if (event.key === "ArrowDown") actionId = "pgn.next_item";
          else if (event.key === "ArrowLeft") actionId = "pgn.parent_variation";
''',
    '''          if (event.key === "ArrowUp") actionId = "pgn.previous_item";
          else if (event.key === "ArrowDown") actionId = "pgn.next_item";
          else if (event.key === "ArrowLeft") actionId = "pgn.parent_variation";
          else if (event.key === "ArrowRight") actionId = "pgn.first_child";
          else if (event.key === "Home") actionId = "pgn.first_item";
          else if (event.key === "End") actionId = "pgn.last_item";
''',
)

replace_once(
    "web/full_product_pgn.js",
    '''        } else if (
          !event.altKey && !event.ctrlKey && !event.shiftKey && !event.metaKey &&
          event.key === "ArrowRight"
        ) {
          handled = true;
          if (hasChild) {
            command = "pgn.select";
            payload = { node_id: snapshot.tree[itemIndex + 1].node_id };
          }
        } else if (
          !event.altKey && !event.ctrlKey && !event.shiftKey && !event.metaKey &&
          event.key === "Home"
        ) {
          handled = true;
          if (itemIndex > 0 && snapshot.tree.length) {
            command = "pgn.select";
            payload = { node_id: snapshot.tree[0].node_id };
          }
        } else if (
          !event.altKey && !event.ctrlKey && !event.shiftKey && !event.metaKey &&
          event.key === "End"
        ) {
          handled = true;
          if (itemIndex + 1 < snapshot.tree.length) {
            command = "pgn.select";
            payload = {
              node_id: snapshot.tree[snapshot.tree.length - 1].node_id
            };
          }
        }
''',
    '''        } else if (actionId === "pgn.first_child") {
          handled = true;
          if (hasChild) {
            command = "pgn.select";
            payload = { node_id: snapshot.tree[itemIndex + 1].node_id };
          }
        } else if (actionId === "pgn.first_item") {
          handled = true;
          if (itemIndex > 0 && snapshot.tree.length) {
            command = "pgn.select";
            payload = { node_id: snapshot.tree[0].node_id };
          }
        } else if (actionId === "pgn.last_item") {
          handled = true;
          if (itemIndex + 1 < snapshot.tree.length) {
            command = "pgn.select";
            payload = {
              node_id: snapshot.tree[snapshot.tree.length - 1].node_id
            };
          }
        }
''',
)

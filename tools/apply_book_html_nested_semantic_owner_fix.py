from __future__ import annotations

"""Apply the bounded nested-semantic owner fix to acs/book_html_import.py.

This is an execution helper for the stacked regression PR. It fails closed if the
expected live parser snippets drift, so it cannot silently patch a different
implementation shape.
"""

from pathlib import Path


TARGET = Path("acs/book_html_import.py")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one live snippet, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    text = _replace_once(
        text,
        '''    def _nearest_structural_owner_capture(self) -> _Capture | None:\n        """Return the nearest capture whose text may need semantic splitting."""\n        for capture in reversed(self._captures):\n            if capture.kind in {"paragraph", "heading"}:\n                return capture\n        return None\n''',
        '''    def _nearest_structural_owner_capture(self) -> _Capture | None:\n        """Return the nearest capture that owns flattened readable text."""\n        for capture in reversed(self._captures):\n            if capture.kind in {"paragraph", "heading", "list_item", "table_row", "pre"}:\n                return capture\n        return None\n\n    @staticmethod\n    def _needs_flat_nested_projection(capture: _Capture) -> bool:\n        """Whether nested blocks must be removed from an ancestor's flat text."""\n        current: _Capture | None = capture\n        while current is not None:\n            if current.kind in {"list_item", "table_row", "pre"}:\n                return True\n            current = current.parent_inline_owner\n        return False\n''',
        "parent-owner binding",
    )

    text = _replace_once(
        text,
        '''        """Flatten one rich list item without reordering its semantic blocks."""\n        events = [event for event in capture.inline_semantics if not event.structural]\n        if not events:\n            return\n''',
        '''        """Flatten one rich list item without reordering its semantic blocks."""\n        if not any(not event.structural for event in capture.inline_semantics):\n            return\n        # Structural child captures are ordering boundaries too. Once any direct\n        # semantic event makes this item fall back from canonical ListBlock, walk\n        # every boundary so nested child text is not duplicated in flat item text.\n        events = capture.inline_semantics\n''',
        "list structural-boundary projection",
    )

    text = _replace_once(
        text,
        '''        # Anchor the nested semantic subtree at its source start. The boundary is\n        # structural only: without a direct inline image/position event on the\n        # parent, legacy nested-only projection remains unchanged.\n        self._record_inline_semantic(\n            self.blocks[capture.block_start_index],\n            owner=parent,\n            part_index=part_index,\n            structural=True,\n            resume_part_index=(\n                len(parent.parts) if capture.kind == "heading" else None\n            ),\n        )\n''',
        '''        flat_projection = self._needs_flat_nested_projection(parent)\n        nested_semantic = any(\n            not event.structural for event in capture.inline_semantics\n        ) or any(\n            isinstance(block, _PgnSlot)\n            for block in self.blocks[capture.block_start_index:]\n        )\n        promote_nested_semantic = flat_projection and nested_semantic\n        # Anchor the nested semantic subtree at its source start. The boundary is\n        # structural unless a list/row/pre flattening ancestor must project this\n        # semantic subtree in place. Outside those flat owners, legacy nested-only\n        # paragraph/heading projection remains unchanged.\n        self._record_inline_semantic(\n            self.blocks[capture.block_start_index],\n            owner=parent,\n            part_index=part_index,\n            structural=not promote_nested_semantic,\n            resume_part_index=(\n                len(parent.parts)\n                if flat_projection or capture.kind == "heading"\n                else None\n            ),\n        )\n''',
        "nested semantic propagation",
    )

    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"patched {TARGET}")


if __name__ == "__main__":
    main()

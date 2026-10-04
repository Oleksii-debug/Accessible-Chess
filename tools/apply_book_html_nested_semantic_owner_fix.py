from __future__ import annotations

"""Apply the bounded nested-semantic owner fix to acs/book_html_import.py.

This execution helper is deliberately idempotent and fails closed if neither the
expected live snippet nor the exact repaired snippet is present once. It exists so
the stacked PR can prove the same parser delta on Linux and Windows before the
verified source change is published.
"""

from pathlib import Path


TARGET = Path("acs/book_html_import.py")


def _replace_or_confirm(text: str, old: str, new: str, label: str) -> str:
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 1 and new_count == 0:
        return text.replace(old, new, 1)
    if old_count == 0 and new_count == 1:
        print(f"{label}: already repaired")
        return text
    raise SystemExit(
        f"{label}: unexpected parser shape old={old_count} repaired={new_count}"
    )


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    text = _replace_or_confirm(
        text,
        '''    def _nearest_structural_owner_capture(self) -> _Capture | None:\n        """Return the nearest capture whose text may need semantic splitting."""\n        for capture in reversed(self._captures):\n            if capture.kind in {"paragraph", "heading"}:\n                return capture\n        return None\n''',
        '''    def _nearest_structural_owner_capture(self) -> _Capture | None:\n        """Return the nearest capture that owns flattened readable text."""\n        for capture in reversed(self._captures):\n            if capture.kind in {"paragraph", "heading", "list_item", "table_row", "pre"}:\n                return capture\n        return None\n\n    @staticmethod\n    def _needs_flat_nested_projection(capture: _Capture) -> bool:\n        """Whether nested blocks must be removed from an ancestor's flat text."""\n        current: _Capture | None = capture\n        while current is not None:\n            if current.kind in {"list_item", "table_row", "pre"}:\n                return True\n            current = current.parent_inline_owner\n        return False\n''',
        "parent-owner binding",
    )

    text = _replace_or_confirm(
        text,
        '''        """Flatten one rich list item without reordering its semantic blocks."""\n        events = [event for event in capture.inline_semantics if not event.structural]\n        if not events:\n            return\n''',
        '''        """Flatten one rich list item without reordering its semantic blocks."""\n        if not any(not event.structural for event in capture.inline_semantics):\n            return\n        # Structural child captures are ordering boundaries too. Once any direct\n        # semantic event makes this item fall back from canonical ListBlock, walk\n        # every boundary so nested child text is not duplicated in flat item text.\n        events = capture.inline_semantics\n''',
        "list structural-boundary projection",
    )

    text = _replace_or_confirm(
        text,
        '''        # Anchor the nested semantic subtree at its source start. The boundary is\n        # structural only: without a direct inline image/position event on the\n        # parent, legacy nested-only projection remains unchanged.\n        self._record_inline_semantic(\n            self.blocks[capture.block_start_index],\n            owner=parent,\n            part_index=part_index,\n            structural=True,\n            resume_part_index=(\n                len(parent.parts) if capture.kind == "heading" else None\n            ),\n        )\n''',
        '''        flat_projection = self._needs_flat_nested_projection(parent)\n        nested_semantic = any(\n            not event.structural for event in capture.inline_semantics\n        ) or any(\n            isinstance(block, _PgnSlot)\n            for block in self.blocks[capture.block_start_index:]\n        )\n        promote_nested_semantic = flat_projection and nested_semantic\n        # Anchor the nested semantic subtree at its source start. The boundary is\n        # structural unless a list/row/pre flattening ancestor must project this\n        # semantic subtree in place. Outside those flat owners, legacy nested-only\n        # paragraph/heading projection remains unchanged.\n        self._record_inline_semantic(\n            self.blocks[capture.block_start_index],\n            owner=parent,\n            part_index=part_index,\n            structural=not promote_nested_semantic,\n            resume_part_index=(\n                len(parent.parts)\n                if flat_projection or capture.kind == "heading"\n                else None\n            ),\n        )\n''',
        "nested semantic propagation",
    )

    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"prepared {TARGET}")


if __name__ == "__main__":
    main()

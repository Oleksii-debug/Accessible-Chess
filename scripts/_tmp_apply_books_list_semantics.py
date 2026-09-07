from __future__ import annotations

from pathlib import Path


TARGET = Path("acs/book_html_import.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .bookdocument import BookDocument, Diagram, Game, Heading, Note, Paragraph, Position\n",
        "from .bookdocument import (\n    BookDocument,\n    Diagram,\n    Game,\n    Heading,\n    ListBlock,\n    Note,\n    Paragraph,\n    Position,\n)\n",
        "ListBlock import",
    )
    text = replace_once(
        text,
        '''@dataclass(slots=True)\nclass _Capture:\n    tag: str\n    kind: str\n    attrs: dict[str, str]\n    parts: list[str]\n\n\n_BLOCK_BOUNDARY_TAGS''',
        '''@dataclass(slots=True)\nclass _Capture:\n    tag: str\n    kind: str\n    attrs: dict[str, str]\n    parts: list[str]\n    list_depth: int = 0\n\n\n@dataclass(slots=True)\nclass _ListCapture:\n    tag: str\n    ordered: bool\n    start: int | None\n    source_anchor: str | None\n    items: list[str]\n\n\n_BLOCK_BOUNDARY_TAGS''',
        "list state",
    )
    text = replace_once(
        text,
        '''        self._captures: list[_Capture] = []\n        self._suppressed_depth = 0\n''',
        '''        self._captures: list[_Capture] = []\n        self._lists: list[_ListCapture] = []\n        self._suppressed_depth = 0\n''',
        "list stack",
    )
    text = replace_once(
        text,
        '''        self._warned_table_flatten = False\n        self._warned_list_flatten = False\n''',
        '''        self._warned_table_flatten = False\n        self._warned_nested_list = False\n''',
        "obsolete list warning state",
    )
    text = replace_once(
        text,
        '''        if self._suppressed_depth:\n            return\n        if tag in _BLOCK_BOUNDARY_TAGS:\n''',
        '''        if self._suppressed_depth:\n            return\n        if tag in {"ol", "ul"}:\n            ordered = tag == "ol"\n            start_value = None\n            if ordered:\n                raw_start = attrs.get("start", "").strip()\n                if raw_start:\n                    try:\n                        candidate = int(raw_start, 10)\n                    except ValueError:\n                        self._warning("HTML ordered list start is invalid; default numbering was used")\n                    else:\n                        if candidate >= 1:\n                            start_value = candidate\n                        else:\n                            self._warning("HTML ordered list start is outside the canonical positive range; default numbering was used")\n            if self._lists and not self._warned_nested_list:\n                self._warning("nested HTML list hierarchy is preserved as adjacent semantic lists because BookDocument lists are not recursive")\n                self._warned_nested_list = True\n            self._lists.append(\n                _ListCapture(\n                    tag=tag,\n                    ordered=ordered,\n                    start=start_value,\n                    source_anchor=attrs.get("id") or None,\n                    items=[],\n                )\n            )\n        if tag in _BLOCK_BOUNDARY_TAGS:\n''',
        "list open",
    )
    text = replace_once(
        text,
        '''        kind = _CAPTURE_KINDS.get(tag)\n        if kind is not None:\n            self._captures.append(_Capture(tag=tag, kind=kind, attrs=attrs, parts=[]))\n''',
        '''        kind = _CAPTURE_KINDS.get(tag)\n        if kind is not None:\n            self._captures.append(\n                _Capture(\n                    tag=tag,\n                    kind=kind,\n                    attrs=attrs,\n                    parts=[],\n                    list_depth=len(self._lists),\n                )\n            )\n''',
        "capture list depth",
    )
    text = replace_once(
        text,
        '''        if self._captures and self._captures[-1].tag == tag:\n            capture = self._captures.pop()\n            self._finish_capture(capture)\n        if tag in _BLOCK_BOUNDARY_TAGS:\n''',
        '''        if self._captures and self._captures[-1].tag == tag:\n            capture = self._captures.pop()\n            self._finish_capture(capture)\n        if tag in {"ol", "ul"}:\n            self._finish_list(tag)\n        if tag in _BLOCK_BOUNDARY_TAGS:\n''',
        "list close",
    )
    text = replace_once(
        text,
        '''        self._append_visible(data)\n        for capture in self._captures:\n            capture.parts.append(data)\n\n    def _finish_capture''',
        '''        self._append_visible(data)\n        current_list_depth = len(self._lists)\n        for capture in self._captures:\n            if capture.kind != "list_item" or capture.list_depth == current_list_depth:\n                capture.parts.append(data)\n\n    def _finish_list(self, tag: str, *, recovered: bool = False) -> None:\n        if not self._lists:\n            return\n        state = self._lists[-1]\n        if state.tag != tag:\n            self._warning("malformed HTML list nesting was recovered without inventing list membership")\n            return\n        self._lists.pop()\n        if recovered:\n            self._warning(f"malformed HTML left an unclosed {state.tag} list; readable items were recovered")\n        if not state.items:\n            return\n        payload = (\n            ("ordered" if state.ordered else "unordered")\n            + "\\0"\n            + (str(state.start) if state.start is not None else "")\n            + "\\0"\n            + "\\0".join(state.items)\n        )\n        self._append_block(\n            ListBlock(\n                items=list(state.items),\n                ordered=state.ordered,\n                start=state.start,\n                block_id=self._block_id("List", payload),\n                source_anchor=state.source_anchor,\n            )\n        )\n\n    def _finish_capture''',
        "list finish helper",
    )
    text = replace_once(
        text,
        '''        if capture.kind == "list_item":\n            if not self._warned_list_flatten:\n                self._warning("HTML list structure is preserved as ordered reading text because BookDocument has no list block kind")\n                self._warned_list_flatten = True\n            text = "• " + text\n        elif capture.kind == "table_row":\n''',
        '''        if capture.kind == "list_item":\n            if self._lists:\n                self._lists[-1].items.append(text)\n                return\n            self._warning("HTML list item appeared outside a list; readable text was preserved as a paragraph")\n        elif capture.kind == "table_row":\n''',
        "list item projection",
    )
    text = replace_once(
        text,
        '''    def close(self) -> None:\n        super().close()\n        while self._captures:\n            self._finish_capture(self._captures.pop(), recovered=True)\n''',
        '''    def close(self) -> None:\n        super().close()\n        while self._captures:\n            self._finish_capture(self._captures.pop(), recovered=True)\n        while self._lists:\n            self._finish_list(self._lists[-1].tag, recovered=True)\n''',
        "unclosed list recovery",
    )
    text = replace_once(
        text,
        '''            "Heading",\n            "Paragraph",\n            "Note(image)",\n''',
        '''            "Heading",\n            "Paragraph",\n            "List",\n            "Note(image)",\n''',
        "HTML capability",
    )
    TARGET.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

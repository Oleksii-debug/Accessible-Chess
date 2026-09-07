from __future__ import annotations

from pathlib import Path


HTML = Path("acs/book_html_import.py")
TEXT = Path("acs/book_text_import.py")
TEXT_TEST = Path("tests/test_v2_book_text_import.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_html() -> None:
    text = HTML.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .bookdocument import BookDocument, Diagram, Game, Heading, Note, Paragraph, Position\n",
        "from .bookdocument import (\n    BookDocument,\n    Diagram,\n    Game,\n    Heading,\n    ListBlock,\n    Note,\n    Paragraph,\n    Position,\n)\n",
        "HTML ListBlock import",
    )
    text = replace_once(
        text,
        '''@dataclass(slots=True)\nclass _Capture:\n    tag: str\n    kind: str\n    attrs: dict[str, str]\n    parts: list[str]\n\n\n_BLOCK_BOUNDARY_TAGS''',
        '''@dataclass(slots=True)\nclass _Capture:\n    tag: str\n    kind: str\n    attrs: dict[str, str]\n    parts: list[str]\n    list_depth: int = 0\n\n\n@dataclass(slots=True)\nclass _ListCapture:\n    tag: str\n    ordered: bool\n    start: int | None\n    source_anchor: str | None\n    items: list[str]\n\n\n_BLOCK_BOUNDARY_TAGS''',
        "HTML list state",
    )
    text = replace_once(
        text,
        '''        self._captures: list[_Capture] = []\n        self._suppressed_depth = 0\n''',
        '''        self._captures: list[_Capture] = []\n        self._lists: list[_ListCapture] = []\n        self._suppressed_depth = 0\n''',
        "HTML list stack",
    )
    text = replace_once(
        text,
        '''        self._warned_table_flatten = False\n        self._warned_list_flatten = False\n''',
        '''        self._warned_table_flatten = False\n        self._warned_nested_list = False\n''',
        "HTML obsolete list warning state",
    )
    text = replace_once(
        text,
        '''        if self._suppressed_depth:\n            return\n        if tag in _BLOCK_BOUNDARY_TAGS:\n''',
        '''        if self._suppressed_depth:\n            return\n        if tag in {"ol", "ul"}:\n            ordered = tag == "ol"\n            start_value = None\n            if ordered:\n                raw_start = attrs.get("start", "").strip()\n                if raw_start:\n                    try:\n                        candidate = int(raw_start, 10)\n                    except ValueError:\n                        self._warning("HTML ordered list start is invalid; default numbering was used")\n                    else:\n                        if candidate >= 1:\n                            start_value = candidate\n                        else:\n                            self._warning("HTML ordered list start is outside the canonical positive range; default numbering was used")\n            if self._lists and not self._warned_nested_list:\n                self._warning("nested HTML list hierarchy is preserved as adjacent semantic lists because BookDocument lists are not recursive")\n                self._warned_nested_list = True\n            self._lists.append(\n                _ListCapture(\n                    tag=tag,\n                    ordered=ordered,\n                    start=start_value,\n                    source_anchor=attrs.get("id") or None,\n                    items=[],\n                )\n            )\n        if tag in _BLOCK_BOUNDARY_TAGS:\n''',
        "HTML list open",
    )
    text = replace_once(
        text,
        '''        kind = _CAPTURE_KINDS.get(tag)\n        if kind is not None:\n            self._captures.append(_Capture(tag=tag, kind=kind, attrs=attrs, parts=[]))\n''',
        '''        kind = _CAPTURE_KINDS.get(tag)\n        if kind is not None:\n            self._captures.append(\n                _Capture(\n                    tag=tag,\n                    kind=kind,\n                    attrs=attrs,\n                    parts=[],\n                    list_depth=len(self._lists),\n                )\n            )\n''',
        "HTML capture depth",
    )
    text = replace_once(
        text,
        '''        if self._captures and self._captures[-1].tag == tag:\n            capture = self._captures.pop()\n            self._finish_capture(capture)\n        if tag in _BLOCK_BOUNDARY_TAGS:\n''',
        '''        if self._captures and self._captures[-1].tag == tag:\n            capture = self._captures.pop()\n            self._finish_capture(capture)\n        if tag in {"ol", "ul"}:\n            self._finish_list(tag)\n        if tag in _BLOCK_BOUNDARY_TAGS:\n''',
        "HTML list close",
    )
    text = replace_once(
        text,
        '''        self._append_visible(data)\n        for capture in self._captures:\n            capture.parts.append(data)\n\n    def _finish_capture''',
        '''        self._append_visible(data)\n        current_list_depth = len(self._lists)\n        for capture in self._captures:\n            if capture.kind != "list_item" or capture.list_depth == current_list_depth:\n                capture.parts.append(data)\n\n    def _finish_list(self, tag: str, *, recovered: bool = False) -> None:\n        if not self._lists:\n            return\n        state = self._lists[-1]\n        if state.tag != tag:\n            self._warning("malformed HTML list nesting was recovered without inventing list membership")\n            return\n        self._lists.pop()\n        if recovered:\n            self._warning(f"malformed HTML left an unclosed {state.tag} list; readable items were recovered")\n        if not state.items:\n            return\n        payload = (\n            ("ordered" if state.ordered else "unordered")\n            + "\\0"\n            + (str(state.start) if state.start is not None else "")\n            + "\\0"\n            + "\\0".join(state.items)\n        )\n        self._append_block(\n            ListBlock(\n                items=list(state.items),\n                ordered=state.ordered,\n                start=state.start,\n                block_id=self._block_id("List", payload),\n                source_anchor=state.source_anchor,\n            )\n        )\n\n    def _finish_capture''',
        "HTML list finish helper",
    )
    text = replace_once(
        text,
        '''        if capture.kind == "list_item":\n            if not self._warned_list_flatten:\n                self._warning("HTML list structure is preserved as ordered reading text because BookDocument has no list block kind")\n                self._warned_list_flatten = True\n            text = "• " + text\n        elif capture.kind == "table_row":\n''',
        '''        if capture.kind == "list_item":\n            if self._lists:\n                self._lists[-1].items.append(text)\n                return\n            self._warning("HTML list item appeared outside a list; readable text was preserved as a paragraph")\n        elif capture.kind == "table_row":\n''',
        "HTML list item projection",
    )
    text = replace_once(
        text,
        '''    def close(self) -> None:\n        super().close()\n        while self._captures:\n            self._finish_capture(self._captures.pop(), recovered=True)\n''',
        '''    def close(self) -> None:\n        super().close()\n        while self._captures:\n            self._finish_capture(self._captures.pop(), recovered=True)\n        while self._lists:\n            self._finish_list(self._lists[-1].tag, recovered=True)\n''',
        "HTML unclosed list recovery",
    )
    text = replace_once(
        text,
        '''            "Heading",\n            "Paragraph",\n            "Note(image)",\n''',
        '''            "Heading",\n            "Paragraph",\n            "List",\n            "Note(image)",\n''',
        "HTML capability",
    )
    HTML.write_text(text, encoding="utf-8", newline="\n")


def patch_text() -> None:
    text = TEXT.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .bookdocument import BookDocument, Diagram, Game, Heading, Note, Paragraph, Position\n",
        "from .bookdocument import (\n    BookDocument,\n    Diagram,\n    Game,\n    Heading,\n    ListBlock,\n    Note,\n    Paragraph,\n    Position,\n)\n",
        "Markdown ListBlock import",
    )
    text = replace_once(
        text,
        '''    def heading(self, text: str, level: int, line: int) -> None:\n        text = text.strip()\n        if not text:\n            return\n        self._append(\n            Heading(\n                text=text,\n                level=level,\n                block_id=self._id("Heading", f"{level}\\0{text}"),\n                source_anchor=f"line:{line}",\n            )\n        )\n\n    def code_note''',
        '''    def heading(self, text: str, level: int, line: int) -> None:\n        text = text.strip()\n        if not text:\n            return\n        self._append(\n            Heading(\n                text=text,\n                level=level,\n                block_id=self._id("Heading", f"{level}\\0{text}"),\n                source_anchor=f"line:{line}",\n            )\n        )\n\n    def list_block(\n        self,\n        items: list[str],\n        *,\n        ordered: bool,\n        start: int | None,\n        line: int,\n    ) -> None:\n        cleaned = [item.strip() for item in items if item.strip()]\n        if not cleaned:\n            return\n        payload = (\n            ("ordered" if ordered else "unordered")\n            + "\\0"\n            + (str(start) if start is not None else "")\n            + "\\0"\n            + "\\0".join(cleaned)\n        )\n        self._append(\n            ListBlock(\n                items=cleaned,\n                ordered=ordered,\n                start=start,\n                block_id=self._id("List", payload),\n                source_anchor=f"line:{line}",\n            )\n        )\n\n    def code_note''',
        "Markdown builder list",
    )
    text = replace_once(
        text,
        '''_LIST_RE = re.compile(r"^\\s*(?:[-+*]|\\d+[.)])\\s+(.+)$")\n''',
        '''_LIST_RE = re.compile(r"^\\s*([-+*]|\\d+[.)])\\s+(.+)$")\n''',
        "Markdown list regex",
    )
    text = replace_once(
        text,
        '''    visible = 0\n    index = 0\n\n    def flush() -> None:\n        nonlocal paragraph\n        if paragraph:\n            builder.paragraph(_compact_paragraph(paragraph), paragraph_start)\n            paragraph = []\n\n    while index < len(lines):\n''',
        '''    visible = 0\n    index = 0\n    list_items: list[str] = []\n    list_ordered: bool | None = None\n    list_start: int | None = None\n    list_line = 1\n\n    def flush() -> None:\n        nonlocal paragraph\n        if paragraph:\n            builder.paragraph(_compact_paragraph(paragraph), paragraph_start)\n            paragraph = []\n\n    def flush_list() -> None:\n        nonlocal list_items, list_ordered, list_start, list_line\n        if list_items:\n            assert list_ordered is not None\n            builder.list_block(\n                list_items,\n                ordered=list_ordered,\n                start=list_start,\n                line=list_line,\n            )\n        list_items = []\n        list_ordered = None\n        list_start = None\n        list_line = 1\n\n    while index < len(lines):\n''',
        "Markdown pending list state",
    )
    text = replace_once(
        text,
        '''        if visible > MAX_TEXT_VISIBLE_CHARS:\n            raise BookTextImportError(\n                "Markdown book visible text exceeds the supported size",\n                code=BookTextImportErrorCode.RESOURCE_LIMIT,\n            )\n        fence = _FENCE_RE.match(line)\n''',
        '''        if visible > MAX_TEXT_VISIBLE_CHARS:\n            raise BookTextImportError(\n                "Markdown book visible text exceeds the supported size",\n                code=BookTextImportErrorCode.RESOURCE_LIMIT,\n            )\n\n        list_match = _LIST_RE.match(line)\n        if list_match:\n            flush()\n            marker = list_match.group(1)\n            item = list_match.group(2).strip()\n            ordered = marker[0].isdigit()\n            start_value = int(re.match(r"\\d+", marker).group(0)) if ordered else None\n            if list_items and list_ordered != ordered:\n                flush_list()\n            if not list_items:\n                list_ordered = ordered\n                list_start = start_value\n                list_line = number\n            if item:\n                list_items.append(item)\n            index += 1\n            continue\n\n        flush_list()\n        fence = _FENCE_RE.match(line)\n''',
        "Markdown list grouping",
    )
    text = replace_once(
        text,
        '''        list_match = _LIST_RE.match(line)\n        quote_match = _QUOTE_RE.match(line)\n        if list_match:\n            flush()\n            builder.paragraph("• " + list_match.group(1).strip(), number)\n            builder.warning("Markdown list structure was preserved as ordered reading text because the current BookDocument has no list block kind")\n            index += 1\n            continue\n        if quote_match:\n''',
        '''        quote_match = _QUOTE_RE.match(line)\n        if quote_match:\n''',
        "Markdown obsolete list flattening",
    )
    text = replace_once(
        text,
        '''        index += 1\n\n    flush()\n\n\ndef import_text_book''',
        '''        index += 1\n\n    flush_list()\n    flush()\n\n\ndef import_text_book''',
        "Markdown final list flush",
    )
    text = replace_once(
        text,
        '''                "Heading",\n                "Paragraph",\n                "Note(image/code)",\n''',
        '''                "Heading",\n                "Paragraph",\n                "List",\n                "Note(image/code)",\n''',
        "Markdown capability",
    )
    TEXT.write_text(text, encoding="utf-8", newline="\n")


def patch_existing_test() -> None:
    text = TEXT_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from acs.bookdocument import Diagram, Game, Heading, Note, Paragraph, Position\n",
        "from acs.bookdocument import Diagram, Game, Heading, ListBlock, Note, Paragraph, Position\n",
        "existing test ListBlock import",
    )
    text = replace_once(
        text,
        '''    def test_markdown_lists_quotes_are_readable_but_structure_loss_is_explicit(self) -> None:\n        source = ''' + "'''# Notes\n\n- First item\n- Second item\n\n> Quoted advice\n'''" + '''\n        result = import_text_book(source, source_name="notes.md", source_format="markdown")\n        paragraphs = [block.text for block in result.document.blocks if isinstance(block, Paragraph)]\n        self.assertIn("• First item", paragraphs)\n        self.assertIn("• Second item", paragraphs)\n        self.assertIn("Quoted advice", paragraphs)\n        self.assertTrue(any("list structure" in warning for warning in result.warnings))\n        self.assertTrue(any("block quote" in warning for warning in result.warnings))\n''',
        '''    def test_markdown_lists_are_semantic_while_quotes_keep_explicit_loss_warning(self) -> None:\n        source = ''' + "'''# Notes\n\n- First item\n- Second item\n\n> Quoted advice\n'''" + '''\n        result = import_text_book(source, source_name="notes.md", source_format="markdown")\n        lists = [block for block in result.document.blocks if isinstance(block, ListBlock)]\n        self.assertEqual(len(lists), 1)\n        self.assertEqual(lists[0].items, ["First item", "Second item"])\n        self.assertFalse(lists[0].ordered)\n        paragraphs = [block.text for block in result.document.blocks if isinstance(block, Paragraph)]\n        self.assertIn("Quoted advice", paragraphs)\n        self.assertFalse(any("BookDocument has no list block kind" in warning for warning in result.warnings))\n        self.assertTrue(any("block quote" in warning for warning in result.warnings))\n''',
        "existing Markdown list expectation",
    )
    TEXT_TEST.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    patch_html()
    patch_text()
    patch_existing_test()


if __name__ == "__main__":
    main()

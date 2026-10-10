from __future__ import annotations

"""Section 54 bounded private accessible HTML/TXT preview from canonical BookDocument.

The validated document schema is the sole semantic authority. This is an output
adapter, not a PDF/DOCX/EPUB/PGN exporter or a rights-to-publish decision.
Output bytes remain private to the caller until a separate rights/release gate.
"""

from dataclasses import dataclass
from hashlib import sha256
from html import escape
import re

from .bookdocument import BookDocument


class FactoryExportError(ValueError):
    """Unsupported conversion; no partially emitted output is returned."""


@dataclass(frozen=True, slots=True)
class FactoryExportResult:
    output_format: str
    output_bytes: bytes
    source_sha256: str
    output_sha256: str
    losses: tuple[str, ...]
    warnings: tuple[str, ...]
    public_release_approved: bool = False


def _source_digest(text: str) -> str:
    if type(text) is not str or re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise FactoryExportError("Verified source SHA-256 required")
    return text


def _block_lines(block: dict[str, object]) -> tuple[str, str, str | None]:
    """Return safe text, safe semantic HTML, optional documented fidelity loss."""
    kind = block["kind"]
    if kind == "Heading":
        level = block["level"]
        value = block["text"]
        return f"Heading {level}: {value}", f"<h{level}>{escape(value)}</h{level}>", "TEXT_STRUCTURE_NOT_MACHINE_NAVIGABLE"
    if kind == "Paragraph":
        value = block["text"]
        return value, f"<p>{escape(value)}</p>", None
    if kind == "List":
        items = block["items"]
        numbered = block.get("ordered", False)
        start = block.get("start") or 1
        lines = [f"{start + i}. {value}" if numbered else f"- {value}" for i, value in enumerate(items)]
        tag = "ol" if numbered else "ul"
        start_attr = f' start="{start}"' if numbered and start != 1 else ""
        content = "".join(f"<li>{escape(value)}</li>" for value in items)
        return "\n".join(lines), f"<{tag}{start_attr}>{content}</{tag}>", "TEXT_STRUCTURE_NOT_MACHINE_NAVIGABLE"
    if kind == "Note":
        value = block["text"]
        note_type = block.get("note_type", "note")
        return f"{note_type}: {value}", f'<aside role="note"><strong>{escape(note_type)}:</strong> {escape(value)}</aside>', None
    if kind in ("Position", "Diagram"):
        fen = block["fen"]
        caption = block.get("caption") or ("Chess diagram" if kind == "Diagram" else "Chess position")
        alt = block.get("alt_text") if kind == "Diagram" else None
        description = f"{caption}. FEN: {fen}"
        if alt:
            description += f". {alt}"
        html = (f'<figure role="group" aria-label="{escape(str(caption), quote=True)}">'
                f'<figcaption>{escape(str(caption))}</figcaption>'
                f'<p>{escape(str(alt))}</p>' if alt else
                f'<figure role="group" aria-label="{escape(str(caption), quote=True)}">'
                f'<figcaption>{escape(str(caption))}</figcaption>')
        html += f'<pre><code>{escape(fen)}</code></pre></figure>'
        return description, html, "ORIGINAL_DIAGRAM_GRAPHICS_NOT_REPRODUCED" if kind == "Diagram" else None
    if kind == "Game":
        pgn = block.get("pgn")
        if not pgn:
            raise FactoryExportError("Linked game requires canonical PGN materialization")
        title = block.get("title") or "Chess game"
        return f"{title}\n{pgn}", f'<section aria-label="{escape(title, quote=True)}"><h2>{escape(title)}</h2><pre>{escape(pgn)}</pre></section>', None
    if kind == "VariationTree":
        pgn, fen = block["pgn"], block["root_fen"]
        title = block.get("title") or "Chess variations"
        return f"{title}\nStarting FEN: {fen}\n{pgn}", f'<section><h2>{escape(title)}</h2><p>Starting FEN: {escape(fen)}</p><pre>{escape(pgn)}</pre></section>', None
    if kind == "Exercise":
        fen, prompt = block["fen"], block["prompt"]
        solution = block.get("solution_pgn") or block.get("answer_text")
        if not solution:
            raise FactoryExportError("Exercise has no verified answer")
        plain = f"Exercise: {prompt}\nFEN: {fen}\nSolution: {solution}"
        html = ('<section><h2>Exercise</h2>' + f'<p>{escape(prompt)}</p>' +
                f'<p>FEN: {escape(fen)}</p><details><summary>Solution</summary>' +
                f'<pre>{escape(solution)}</pre></details></section>')
        return plain, html, None
    raise FactoryExportError("Unsupported canonical block kind")


def export_factory_preview(document: BookDocument, *, source_sha256: str,
                           output_format: str = "html", allow_semantic_loss: bool = False) -> FactoryExportResult:
    """Render only bounded verified content; report structural/graphic losses."""
    digest = _source_digest(source_sha256)
    if type(document) is not BookDocument:
        raise FactoryExportError("Canonical BookDocument required")
    if output_format not in ("html", "txt") or type(output_format) is not str:
        raise FactoryExportError("Requested output format has no qualified renderer")
    if type(allow_semantic_loss) is not bool:
        raise FactoryExportError("Loss policy must be explicitly boolean")
    wire = document.as_dict()
    blocks = wire["blocks"]
    losses: list[str] = []
    text: list[str] = [wire["title"]]
    html: list[str] = []
    for block in blocks:
        plain, semantic, loss = _block_lines(block)
        text.append(plain)
        html.append(semantic)
        if loss and (output_format == "txt" or loss != "TEXT_STRUCTURE_NOT_MACHINE_NAVIGABLE"):
            losses.append(loss)
    losses = list(dict.fromkeys(losses))
    if losses and not allow_semantic_loss:
        raise FactoryExportError("Output loses declared source semantics; explicit loss approval required")
    if output_format == "txt":
        output = ("\n\n".join(text) + "\n").encode("utf-8")
    else:
        title = escape(wire["title"])
        language = escape(wire["language"] or "und", quote=True)
        markup = (f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
                  f'<title>{title}</title></head><body><main><h1>{title}</h1>' +
                  "\n".join(html) + "</main></body></html>")
        output = markup.encode("utf-8")
    return FactoryExportResult(output_format, output, digest, sha256(output).hexdigest(),
                               tuple(losses), tuple(wire["warnings"]), False)

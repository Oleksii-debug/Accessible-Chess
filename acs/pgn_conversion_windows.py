from __future__ import annotations

"""Native keyboard conversion dialog; all parsing and writes stay in D06.

BackgroundWorker keeps the UI thread available for cancel/close. Only its
completion event updates controls. No browser content supplies a file path.
"""

import os
import logging
from pathlib import Path
import threading

from .pgn_conversion import (
    ENCODINGS, PgnConversionError, convert_pgn, format_conversion_review, preview_conversion,
)

NATIVE_CONVERSION_MAX_BYTES = 8 * 1024 * 1024
_LOG = logging.getLogger(__name__)


def run_conversion_job(source: Path, encoding: str, destination: Path | None, plan, cancel_check):
    """Headless-testable job used by the native worker without reading controls."""
    if destination is None:
        return preview_conversion(source, encoding=encoding, max_bytes=NATIVE_CONVERSION_MAX_BYTES, cancel_check=cancel_check)
    return convert_pgn(source, destination, reviewed_plan=plan, max_bytes=NATIVE_CONVERSION_MAX_BYTES, cancel_check=cancel_check)


_TEXT = {
    "uk": {
        "title": "Перекодувати PGN у UTF-8", "source": "Джерело PGN", "browse": "Вибрати джерело",
        "encoding": "Кодування джерела", "preview": "Перевірити й переглянути", "review": "Звіт і перегляд тексту",
        "convert": "Зберегти новий UTF-8 PGN", "close": "Закрити", "cancel": "Скасувати операцію",
        "ready": "Виберіть джерело. Інструмент працює з PGN до 8 МіБ; оригінал не змінюється.",
        "busy": "Виконується перевірка. Операцію можна скасувати.", "reviewed": "Перегляд готовий. Перевірте текст і виберіть збереження нового файлу.",
        "saved": "Новий UTF-8 PGN збережено. Оригінал не змінено.", "error": "Операція не виконана. Перевірте джерело, кодування та папку призначення.",
        "open": "Вибрати PGN для перекодування", "save": "Зберегти перекодовану копію PGN", "filter": "Файли PGN (*.pgn)|*.pgn",
        "cancelled": "Операцію скасовано. Новий файл не опубліковано.",
        "auto": "Автоматично (UTF-8, BOM UTF-16, Windows-1251)",
        "source_changed": "Джерело змінилося після перегляду. Перевірте й перегляньте його знову.",
        "destination_exists": "Файл призначення вже існує. Виберіть інше ім’я; наявний файл збережено.",
        "same_source": "Виберіть інший файл для нової копії. Оригінал не перезаписується.",
        "source_unavailable": "Джерело недоступне, змінилося або перевищує ліміт 8 МіБ.",
        "encoding_error": "Не вдалося прочитати це кодування. Виберіть правильне кодування й виконайте перегляд.",
        "pgn_error": "PGN не пройшов перевірку структури. Цей інструмент не виправляє пошкоджені партії.",
    },
    "en": {
        "title": "Convert PGN to UTF-8", "source": "PGN source", "browse": "Choose source",
        "encoding": "Source encoding", "preview": "Check and preview", "review": "Report and text preview",
        "convert": "Save new UTF-8 PGN", "close": "Close", "cancel": "Cancel operation",
        "ready": "Choose a source. This tool accepts PGN up to 8 MiB and keeps the original.",
        "busy": "Checking. You can cancel the operation.", "reviewed": "Preview ready. Check the text, then save a new file.",
        "saved": "New UTF-8 PGN saved. The original is unchanged.", "error": "Operation failed. Check the source, encoding and destination folder.",
        "open": "Choose PGN to convert", "save": "Save converted PGN copy", "filter": "PGN files (*.pgn)|*.pgn",
        "cancelled": "Operation cancelled. No new file was published.",
        "auto": "Automatic (UTF-8, BOM UTF-16, Windows-1251)",
        "source_changed": "The source changed after preview. Check and preview it again.",
        "destination_exists": "The destination already exists. Choose a different name; the existing file is kept.",
        "same_source": "Choose another file for the new copy. The original cannot be overwritten.",
        "source_unavailable": "The source is unavailable, changed or exceeds the 8 MiB limit.",
        "encoding_error": "This encoding could not be read. Choose the correct source encoding and preview again.",
        "pgn_error": "PGN structure validation failed. This tool does not repair damaged games.",
    },
}


def show_pgn_conversion_dialog(*, language: str = "uk", owner=None) -> None:
    if type(language) is not str:
        raise TypeError("conversion dialog language must be text")
    if os.name != "nt":
        raise RuntimeError("native PGN conversion requires Windows")
    import clr  # type: ignore
    clr.AddReference("System")
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.ComponentModel import BackgroundWorker  # type: ignore
    from System.Drawing import Size  # type: ignore
    from System.Windows.Forms import (  # type: ignore
        Button, ComboBox, ComboBoxStyle, DialogResult, DockStyle, FlowLayoutPanel,
        Form, FormStartPosition, Label, OpenFileDialog, RowStyle, SaveFileDialog,
        ScrollBars, SizeType, TableLayoutPanel, TextBox,
    )

    text = _TEXT["en" if language == "en" else "uk"]
    form = Form()
    form.Text = text["title"]
    form.AccessibleName = text["title"]
    form.Size = Size(740, 620)
    form.MinimumSize = Size(540, 430)
    form.StartPosition = FormStartPosition.CenterParent
    table = TableLayoutPanel()
    table.Dock = DockStyle.Fill
    table.ColumnCount = 1
    table.RowCount = 7
    for index in range(7):
        table.RowStyles.Add(RowStyle(SizeType.Percent, 100) if index == 4 else RowStyle(SizeType.AutoSize))
    form.Controls.Add(table)

    source_label = Label()
    source_label.Text = text["source"]
    source_label.AutoSize = True
    table.Controls.Add(source_label, 0, 0)
    source_row = FlowLayoutPanel()
    source_row.AutoSize = True
    source_row.Dock = DockStyle.Fill
    source_field = TextBox()
    source_field.ReadOnly = True
    source_field.Width = 470
    source_field.AccessibleName = text["source"]
    source_field.TabIndex = 0
    browse = Button()
    browse.Text = text["browse"]
    browse.AutoSize = True
    browse.TabIndex = 1
    source_row.Controls.Add(source_field)
    source_row.Controls.Add(browse)
    table.Controls.Add(source_row, 0, 1)

    encoding_row = FlowLayoutPanel()
    encoding_row.AutoSize = True
    encoding_row.Dock = DockStyle.Fill
    encoding_label = Label()
    encoding_label.Text = text["encoding"]
    encoding_label.AutoSize = True
    encoding = ComboBox()
    encoding.DropDownStyle = ComboBoxStyle.DropDownList
    encoding.AccessibleName = text["encoding"]
    encoding.TabIndex = 0
    for value in ENCODINGS:
        encoding.Items.Add(text["auto"] if value == "auto" else value)
    encoding.SelectedIndex = 0
    preview = Button()
    preview.Text = text["preview"]
    preview.AutoSize = True
    preview.Enabled = False
    preview.TabIndex = 1
    for control in (encoding_label, encoding, preview):
        encoding_row.Controls.Add(control)
    table.Controls.Add(encoding_row, 0, 2)
    review_label = Label()
    review_label.Text = text["review"]
    review_label.AutoSize = True
    table.Controls.Add(review_label, 0, 3)
    review = TextBox()
    review.Multiline = True
    review.ReadOnly = True
    review.ScrollBars = ScrollBars.Vertical
    review.Dock = DockStyle.Fill
    review.AccessibleName = text["review"]
    table.Controls.Add(review, 0, 4)
    status = Label()
    status.Text = text["ready"]
    status.AutoSize = True
    status.AccessibleName = text["ready"]
    table.Controls.Add(status, 0, 5)
    buttons = FlowLayoutPanel()
    buttons.AutoSize = True
    buttons.Dock = DockStyle.Fill
    save = Button()
    save.Text = text["convert"]
    save.AutoSize = True
    save.Enabled = False
    save.TabIndex = 0
    close = Button()
    close.Text = text["close"]
    close.AutoSize = True
    close.TabIndex = 1
    buttons.Controls.Add(save)
    buttons.Controls.Add(close)
    table.Controls.Add(buttons, 0, 6)
    for index, control in enumerate((source_row, encoding_row, review, buttons)):
        control.TabIndex = index
    form.AcceptButton = preview
    form.CancelButton = close
    close.DialogResult = getattr(DialogResult, "None")
    state = {"source": None, "plan": None, "task": None, "close_requested": False}
    cancel = threading.Event()
    worker = BackgroundWorker()

    def set_status(message):
        status.Text = message
        status.AccessibleName = message

    def reset_plan(sender=None, event=None):
        state["plan"] = None
        save.Enabled = False
        form.AcceptButton = preview
        review.Text = ""
        set_status(text["ready"])

    def choose_source(sender, event):
        dialog = OpenFileDialog()
        try:
            dialog.Title = text["open"]
            dialog.Filter = text["filter"]
            dialog.CheckFileExists = True
            dialog.Multiselect = False
            if dialog.ShowDialog(form) == DialogResult.OK:
                state["source"] = Path(str(dialog.FileName))
                source_field.Text = str(dialog.FileName)
                reset_plan()
                preview.Enabled = True
                encoding.Focus()
        finally:
            dialog.Dispose()

    def begin(destination=None):
        if worker.IsBusy or state["source"] is None:
            return
        state["task"] = (state["source"], ENCODINGS[int(encoding.SelectedIndex)], destination, state["plan"])
        cancel.clear()
        for control in (browse, encoding, preview, save):
            control.Enabled = False
        close.Text = text["cancel"]
        set_status(text["busy"])
        # Preview/save controls are disabled while the worker runs. Move keyboard
        # focus to the one remaining action so screen-reader users do not stay
        # stranded on a disabled control and can cancel immediately with Enter.
        close.Focus()
        worker.RunWorkerAsync()

    def do_work(sender, event):
        try:
            event.Result = ("ok", run_conversion_job(*state["task"], cancel.is_set))
        except PgnConversionError as exc:
            _LOG.warning("PGN conversion failed: %s", exc.code)
            event.Result = ("error", exc.code)
        except Exception:
            # Never display filesystem paths or raw provider exceptions.
            _LOG.warning("PGN conversion failed: operation_failed")
            event.Result = ("error", "operation_failed")

    def completed(sender, event):
        destination = state["task"][2]
        result = ("error", "operation_failed") if event.Error is not None else event.Result
        browse.Enabled = encoding.Enabled = preview.Enabled = True
        close.Text = text["close"]
        if result[0] == "ok" and destination is None:
            state["plan"] = result[1]
            review.Text = format_conversion_review(result[1], language)
            save.Enabled = True
            form.AcceptButton = save
            set_status(text["reviewed"])
        elif result[0] == "ok":
            set_status(text["saved"])
            review.Text += "\r\n\r\n" + text["saved"]
            save.Enabled = True
        else:
            state["plan"] = None
            form.AcceptButton = preview
            code = result[1]
            message = (text["encoding_error"] if code == "encoding" else
                       text["pgn_error"] if code.startswith("pgn_") else text.get(code, text["error"]))
            set_status(message)
            review.Text = message
            save.Enabled = False
        review.Focus()
        if state["close_requested"]:
            form.Close()

    def choose_destination(sender, event):
        if worker.IsBusy or state["plan"] is None:
            return
        dialog = SaveFileDialog()
        try:
            dialog.Title = text["save"]
            dialog.Filter = text["filter"]
            dialog.DefaultExt = "pgn"
            dialog.AddExtension = True
            dialog.CheckPathExists = True
            # Conversion is deliberately no-clobber. Do not let the native
            # Save dialog promise an overwrite that the canonical writer will
            # (correctly) refuse after the user confirms it.
            dialog.OverwritePrompt = False
            dialog.FileName = state["source"].stem + "-utf8.pgn"
            if dialog.ShowDialog(form) == DialogResult.OK:
                begin(Path(str(dialog.FileName)))
        finally:
            dialog.Dispose()

    def close_click(sender, event):
        if worker.IsBusy:
            cancel.set()
        else:
            form.Close()

    def closing(sender, event):
        if worker.IsBusy:
            state["close_requested"] = True
            cancel.set()
            event.Cancel = True

    browse.Click += choose_source
    encoding.SelectedIndexChanged += reset_plan
    preview.Click += lambda sender, event: begin()
    save.Click += choose_destination
    close.Click += close_click
    form.FormClosing += closing
    worker.DoWork += do_work
    worker.RunWorkerCompleted += completed
    try:
        form.ShowDialog(owner) if owner is not None else form.ShowDialog()
    finally:
        worker.Dispose()
        form.Dispose()

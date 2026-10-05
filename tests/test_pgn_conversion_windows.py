from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from acs import pgn_conversion_windows as native


class Hook:
    def __init__(self):
        self.handlers = []
    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self
    def fire(self, event=None):
        for handler in self.handlers:
            handler(None, event)


class Collection(list):
    def Add(self, value, *position):
        self.append(value)


class Control:
    def __init__(self):
        self.Controls = Collection()
        self.Items = Collection()
        self.RowStyles = Collection()
        self.Click = Hook()
        self.SelectedIndexChanged = Hook()
        self.FormClosing = Hook()
        self.Enabled = True
        self.Text = ""
        self.AccessibleName = ""
        self.focused = False
        self.disposed = False
        self._index = -1
    def Focus(self):
        self.focused = True
    def Dispose(self):
        self.disposed = True
    def Close(self):
        event = SimpleNamespace(Cancel=False)
        self.FormClosing.fire(event)
        self.closed = not event.Cancel
    @property
    def SelectedIndex(self):
        return self._index
    @SelectedIndex.setter
    def SelectedIndex(self, value):
        self._index = value
        self.SelectedIndexChanged.fire()
    @property
    def SelectedItem(self):
        return self.Items[self._index]


@contextmanager
def fake_forms(driver, source, destination, *, deferred=False):
    workers = []
    dialogs = []
    class Worker:
        def __init__(self):
            self.DoWork = Hook()
            self.RunWorkerCompleted = Hook()
            self.IsBusy = False
            self.disposed = False
            workers.append(self)
        def RunWorkerAsync(self):
            self.IsBusy = True
            if not deferred:
                self.finish()
        def finish(self):
            event = SimpleNamespace(Result=None)
            self.DoWork.fire(event)
            self.IsBusy = False
            self.RunWorkerCompleted.fire(SimpleNamespace(Error=None, Result=event.Result))
        def Dispose(self):
            self.disposed = True
    class Form(Control):
        def ShowDialog(self, owner=None):
            driver(self, workers)
    class OpenDialog(Control):
        def ShowDialog(self, owner=None):
            self.FileName = str(source)
            dialogs.append(self)
            return "ok"
    class SaveDialog(Control):
        def ShowDialog(self, owner=None):
            self.FileName = str(destination)
            dialogs.append(self)
            return "ok"
    modules = {name: ModuleType(name) for name in ("clr", "System.ComponentModel", "System.Drawing", "System.Windows.Forms")}
    modules["clr"].AddReference = lambda name: None
    modules["System.ComponentModel"].BackgroundWorker = Worker
    modules["System.Drawing"].Size = lambda *args: args
    forms = modules["System.Windows.Forms"]
    for name in ("Button", "ComboBox", "FlowLayoutPanel", "Label", "TableLayoutPanel", "TextBox"):
        setattr(forms, name, Control)
    forms.Form = Form
    forms.OpenFileDialog = OpenDialog
    forms.SaveFileDialog = SaveDialog
    forms.RowStyle = lambda *args: args
    forms.DialogResult = SimpleNamespace(OK="ok", **{"None": "none"})
    forms.DockStyle = SimpleNamespace(Fill="fill")
    forms.ComboBoxStyle = SimpleNamespace(DropDownList="list")
    forms.SizeType = SimpleNamespace(Percent="percent", AutoSize="auto")
    forms.ScrollBars = SimpleNamespace(Vertical="vertical")
    forms.FormStartPosition = SimpleNamespace(CenterParent="parent")
    with patch.dict(sys.modules, modules), patch.object(native, "os", SimpleNamespace(name="nt")):
        yield workers, dialogs


def controls(form):
    table = form.Controls[0]
    source = table.Controls[1]
    encoding = table.Controls[2]
    buttons = table.Controls[6]
    return SimpleNamespace(browse=source.Controls[1], source=source.Controls[0], encoding=encoding.Controls[1], preview=encoding.Controls[2], review=table.Controls[4], status=table.Controls[5], save=buttons.Controls[0], close=buttons.Controls[1])


class PgnConversionNativeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / "Шахова книга.pgn"
        self.destination = Path(self.tmp.name) / "Нова копія.pgn"
        self.raw = '[Event "Шахова книга"]\n[Result "*"]\n\n1. e4 {Пояснення} *\n'.encode("cp1251")
        self.source.write_bytes(self.raw)

    def test_preview_focus_encoding_invalidation_and_native_new_copy(self):
        def driver(form, workers):
            c = controls(form)
            self.assertFalse(c.save.Enabled)
            c.browse.Click.fire()
            self.assertTrue(c.encoding.focused)
            c.preview.Click.fire()
            self.assertIn("Шахова книга", c.review.Text)
            self.assertTrue(c.review.ReadOnly)
            self.assertTrue(c.review.focused)
            self.assertTrue(c.save.Enabled)
            c.encoding.SelectedIndex = 3  # explicit Windows-1251
            self.assertFalse(c.save.Enabled)
            self.assertEqual(c.review.Text, "")
            self.assertIs(form.AcceptButton, c.preview)
            c.preview.Click.fire()
            c.save.Click.fire()
            self.assertIn("збережено", c.status.Text)
            self.assertTrue(c.review.focused)
            c.close.Click.fire()
        with fake_forms(driver, self.source, self.destination) as (workers, dialogs):
            native.show_pgn_conversion_dialog(language="uk")
        self.assertFalse(dialogs[-1].OverwritePrompt)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertIn("Шахова книга", self.destination.read_text(encoding="utf-8"))
        self.assertTrue(all(d.disposed for d in dialogs))
        self.assertTrue(workers[0].disposed)

    def test_busy_close_is_deferred_and_cancel_does_not_publish(self):
        def driver(form, workers):
            c = controls(form)
            c.browse.Click.fire()
            c.preview.Click.fire()
            self.assertFalse(c.browse.Enabled)
            self.assertFalse(c.encoding.Enabled)
            self.assertTrue(c.close.focused)
            self.assertIn("Скасувати", c.close.Text)
            form.Close()
            self.assertFalse(form.closed)
            self.assertTrue(workers[0].IsBusy)
            workers[0].finish()
            self.assertTrue(form.closed)
            self.assertIn("скасовано", c.review.Text)
        with fake_forms(driver, self.source, self.destination, deferred=True):
            native.show_pgn_conversion_dialog()
        self.assertFalse(self.destination.exists())

    def test_english_dialog_handles_source_change_without_raw_exception(self):
        def driver(form, workers):
            c = controls(form)
            c.browse.Click.fire()
            c.preview.Click.fire()
            self.source.write_bytes(self.raw.replace(b"e4", b"d4"))
            c.save.Click.fire()
            self.assertIn("source changed after preview", c.review.Text)
            self.assertNotIn(str(self.source), c.review.Text)
            self.assertFalse(c.save.Enabled)
        with fake_forms(driver, self.source, self.destination):
            native.show_pgn_conversion_dialog(language="en")
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()

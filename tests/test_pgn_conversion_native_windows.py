from __future__ import annotations

import os
import unittest


@unittest.skipUnless(os.name == "nt", "real native dialog requires Windows and pythonnet")
class PgnConversionRealWindowsTests(unittest.TestCase):
    def test_real_sta_dialog_controls_and_modal_close_in_both_languages(self):
        import clr  # type: ignore
        clr.AddReference("System")
        clr.AddReference("System.Windows.Forms")
        from System.Threading import ApartmentState, Thread, ThreadStart  # type: ignore
        from System.Windows.Forms import Application, ComboBox, ComboBoxStyle, TextBox, Timer  # type: ignore
        from acs.pgn_conversion_windows import show_pgn_conversion_dialog

        for language, title, source_name, review_name in (
            ("uk", "Перекодувати PGN у UTF-8", "Джерело PGN", "Звіт і перегляд тексту"),
            ("en", "Convert PGN to UTF-8", "PGN source", "Report and text preview"),
        ):
            with self.subTest(language=language):
                failures = []
                inspected = []

                def run():
                    timer = Timer()
                    timer.Interval = 200
                    ticks = 0

                    def tick(sender, event):
                        nonlocal ticks
                        ticks += 1
                        form = next((Application.OpenForms[index] for index in range(Application.OpenForms.Count)
                                     if str(Application.OpenForms[index].Text) == title), None)
                        if form is None:
                            if ticks >= 25:
                                failures.append("native dialog never became visible")
                                timer.Stop()
                                Application.ExitThread()
                            return
                        timer.Stop()
                        try:
                            self.assertEqual(str(form.AccessibleName), title)
                            pending = list(form.Controls)
                            descendants = []
                            while pending:
                                control = pending.pop()
                                descendants.append(control)
                                pending.extend(list(control.Controls))
                            source = next(c for c in descendants if isinstance(c, TextBox) and str(c.AccessibleName) == source_name)
                            review = next(c for c in descendants if isinstance(c, TextBox) and str(c.AccessibleName) == review_name)
                            encoding = next(c for c in descendants if isinstance(c, ComboBox))
                            self.assertTrue(source.ReadOnly and source.TabStop)
                            self.assertTrue(review.ReadOnly and review.Multiline and review.TabStop)
                            self.assertEqual(encoding.DropDownStyle, ComboBoxStyle.DropDownList)
                            self.assertEqual(encoding.Items.Count, 9)
                            self.assertEqual(encoding.SelectedIndex, 0)
                            self.assertIn("UTF-8", str(encoding.SelectedItem))
                            self.assertFalse(form.AcceptButton.Enabled)
                            self.assertTrue(form.CancelButton.Enabled)
                            inspected.append(language)
                        except BaseException as exc:
                            failures.append(str(exc))
                        finally:
                            form.Close()

                    timer.Tick += tick
                    timer.Start()
                    try:
                        show_pgn_conversion_dialog(language=language)
                    except BaseException as exc:
                        failures.append(type(exc).__name__ + ": " + str(exc))
                    finally:
                        timer.Stop()
                        timer.Dispose()

                thread = Thread(ThreadStart(run))
                thread.IsBackground = True
                thread.SetApartmentState(ApartmentState.STA)
                thread.Start()
                self.assertTrue(thread.Join(10000), "native modal dialog did not close")
                self.assertEqual(failures, [])
                self.assertEqual(inspected, [language])


if __name__ == "__main__":
    unittest.main()

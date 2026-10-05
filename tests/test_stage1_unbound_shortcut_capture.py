from __future__ import annotations

import unittest
from pathlib import Path

from acs.keybindings import ActionRegistry
from acs.ui_keymap_adapter import build_web_keymap
from acs.ui_keymap_editor import KeymapEditorModel


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


class Stage1UnboundShortcutCaptureTests(unittest.TestCase):
    def test_board_material_remains_an_unbound_shortcut_not_an_alias(self) -> None:
        registry = ActionRegistry()
        actions = {
            item["id"]: item
            for item in build_web_keymap(registry)["actions"]
        }
        material = actions["board.material"]
        self.assertIsNone(material["binding"])
        self.assertIsNone(material["defaultBinding"])
        self.assertIsNone(material["alias"])
        self.assertIsNone(material["defaultAlias"])

        editor_rows = {
            row.action_id: row
            for row in KeymapEditorModel(registry, lang="en").rows()
        }
        self.assertEqual(editor_rows["board.material"].value_kind, "shortcut")
        self.assertEqual(editor_rows["board.material"].value, "")

        alias = actions["move.undo"]
        self.assertIsNone(alias["binding"])
        self.assertIsNone(alias["defaultBinding"])
        self.assertEqual(alias["alias"], "u")
        self.assertEqual(alias["defaultAlias"], "u")
        self.assertEqual(editor_rows["move.undo"].value_kind, "alias")

    def test_web_editor_matches_backend_shortcut_classification_when_unbound(self) -> None:
        self.assertIn(
            "const shortcut=item.binding!=null||item.defaultBinding!=null||item.defaultAlias==null;",
            HTML,
        )
        self.assertIn(
            "inp.value=shortcut?(item.binding||''):(item.alias||'')",
            HTML,
        )
        self.assertIn("if(shortcut)inp.readOnly=true", HTML)
        self.assertIn("if(shortcut){const b=document.createElement('button')", HTML)
        self.assertNotIn("if(item.binding){const b=document.createElement('button')", HTML)

    def test_keymap_editor_controls_have_action_specific_accessible_names(self) -> None:
        self.assertIn(
            "const token=String(item.id).replace(/[^A-Za-z0-9_-]/g,'-')",
            HTML,
        )
        self.assertIn("h.id='binding-label-'+token", HTML)
        self.assertIn("inp.setAttribute('aria-labelledby',h.id)", HTML)
        self.assertIn("status.id='binding-status-'+token", HTML)
        self.assertIn(
            "b.setAttribute('aria-label',(en?'New shortcut for ':'Нова комбінація для ')+h.textContent)",
            HTML,
        )
        self.assertIn(
            "save.setAttribute('aria-label',(en?'Save ':'Зберегти ')+h.textContent)",
            HTML,
        )
        self.assertIn(
            "reset.setAttribute('aria-label',(en?'Restore default for ':'Відновити за замовчуванням для ')+h.textContent)",
            HTML,
        )

    def test_context_default_metadata_covers_current_terminal_contexts(self) -> None:
        self.assertIn("function keymapContextLabel(ctx)", HTML)
        for token in (
            "pgn_tree:'PGN tree'",
            "library_results:'Library results'",
            "education_list:'Education list'",
            "pgn_tree:'Дерево PGN'",
            "library_results:'Результати бібліотеки'",
            "education_list:'Навчальний список'",
        ):
            self.assertIn(token, HTML)
        self.assertIn(
            "all.textContent=document.documentElement.lang==='en'?'All':'Усі'",
            HTML,
        )
        self.assertIn("o.textContent=keymapContextLabel(ctx)", HTML)
        self.assertIn(
            "document.documentElement.lang==='en'?(x.labelEn||x.labelUk||''):(x.labelUk||x.labelEn||'')",
            HTML,
        )
        self.assertIn(
            "+' '+keymapContextLabel(x.registryContext||x.context)+' '+(x.binding||x.alias||'')+' '+(x.defaultBinding||x.defaultAlias||'')",
            HTML,
        )
        self.assertIn("meta.id='binding-meta-'+token", HTML)
        self.assertIn("meta.className='binding-meta'", HTML)
        self.assertIn(
            "meta.textContent=(en?'Context: ':'Контекст: ')+keymapContextLabel(item.registryContext||item.context)+(en?'; Default: ':'; За замовчуванням: ')+defaultValue",
            HTML,
        )
        self.assertIn(
            "inp.setAttribute('aria-describedby',meta.id+' '+status.id)",
            HTML,
        )
        self.assertIn(
            "const next=lang==='en'?'en':'uk',changed=document.documentElement.lang!==next",
            HTML,
        )
        self.assertIn("if(changed&&keymap.length)renderKeymap();renderHelp()", HTML)
        self.assertNotIn("if(keymap.length)renderKeymap();renderHelp()", HTML)

    def test_shortcut_capture_remains_keyboard_first_and_backend_validated(self) -> None:
        self.assertIn("b.textContent=en?'New shortcut':'Нова комбінація'", HTML)
        self.assertIn("save.textContent=en?'Save':'Зберегти'", HTML)
        self.assertIn("reset.textContent=en?'Restore default':'За замовчуванням'", HTML)
        self.assertIn("b.setAttribute('aria-pressed','false')", HTML)
        self.assertIn(
            "b.addEventListener('click',()=>beginCapture(item,inp,status,b))",
            HTML,
        )
        self.assertIn("typeof a.keymap_capture_shortcut==='function'", HTML)
        self.assertIn("typeof a.keymap_preview==='function'", HTML)


    def test_keymap_mutations_restore_row_focus_and_async_capture_is_transactional(self) -> None:
        self.assertIn(
            "const active=document.activeElement,listNode=el('key-list'),focusId=active&&listNode.contains(active)?active.id:''",
            HTML,
        )
        for token in (
            "inp.id='binding-value-'+token",
            "b.id='binding-capture-'+token",
            "save.id='binding-save-'+token",
            "reset.id='binding-reset-'+token",
        ):
            self.assertIn(token, HTML)
        self.assertIn(
            "if(focusId){const next=el(focusId);if(next&&typeof next.focus==='function')next.focus();else el('key-search').focus()}",
            HTML,
        )
        self.assertIn("if(e.key==='Tab'){stopCapture(false);return}", HTML)
        self.assertIn("if(capture!==c)return", HTML)
        self.assertIn("Shortcut capture unavailable.", HTML)
        self.assertIn("Захоплення комбінації недоступне.", HTML)
        self.assertIn(
            "if(version!==previewVersion||inp.value!==value)return",
            HTML,
        )
        self.assertIn(
            "if(inp.value!==value){const message=en?'Value changed; review and save again.':'Значення змінено; перевірте та збережіть ще раз.'",
            HTML,
        )

    def test_capture_announcements_follow_active_ui_language(self) -> None:
        self.assertIn(
            "c.button.textContent=en?'New shortcut':'Нова комбінація'",
            HTML,
        )
        self.assertIn(
            "button.textContent=en?'Press shortcut':'Натисніть комбінацію'",
            HTML,
        )
        self.assertIn("announce(en?'Cancelled.':'Скасовано.')", HTML)
        self.assertIn(
            "announce(en?'Waiting for shortcut.':'Очікую комбінацію.')",
            HTML,
        )


    def test_keymap_dialog_chrome_and_failure_feedback_are_localized(self) -> None:
        self.assertIn("function applyKeymapLanguage()", HTML)
        for token in (
            "setText('h-settings',en?'Settings':'Налаштування')",
            "setText('language-label',en?'Language':'Мова')",
            "setText('open-keymap',en?'Keyboard and commands':'Клавіатура і команди')",
            "setText('key-search-label',en?'Search':'Пошук')",
            "setText('key-context-label',en?'Section':'Розділ')",
            "setText('key-reset-all',en?'Restore all':'Відновити всі')",
            "setText('key-import-label',en?'Import':'Імпорт')",
            "setText('close-keymap',en?'Close':'Закрити')",
            "applyKeymapLanguage();applyCoreUiLanguage(next==='en')",
            "renderKeymapRecovery(keymapBase,false);if(changed&&keymap.length)renderKeymap()",
        ):
            self.assertIn(token, HTML)
        self.assertIn(
            "announce(result&&result.message|| (en?'Keyboard settings could not be changed.':'Не вдалося змінити налаштування клавіш.'))",
            HTML,
        )
        self.assertIn(
            "announce(en?'Select a section first.':'Спочатку виберіть розділ.')",
            HTML,
        )
        self.assertIn("Keyboard profile exported.", HTML)
        self.assertIn("Профіль клавіш експортовано.", HTML)
        self.assertIn("Keyboard settings could not be imported.", HTML)
        self.assertIn("Не вдалося імпортувати налаштування.", HTML)


    def test_keymap_mutation_refresh_is_fail_closed_and_recoverable(self) -> None:
        self.assertIn(
            "installKeymapSnapshot(nextBase,nextCentral);renderKeymapRecovery(nextBase,true);return true",
            HTML,
        )
        self.assertNotIn("Keyboard settings restored.", HTML)
        self.assertNotIn("Налаштування клавіш відновлено.", HTML)
        self.assertIn(
            "announce(document.documentElement.lang==='en'?'Keyboard settings unavailable.':'Налаштування клавіш недоступні.');return false",
            HTML,
        )
        self.assertIn(
            "if(result.snapshot){try{installKeymapSnapshot(result.snapshot,true);refreshed=true}catch(e){refreshed=await loadKeymap()}}else refreshed=await loadKeymap()",
            HTML,
        )
        self.assertIn("if(!refreshed)return false", HTML)
        self.assertNotIn(
            "else await loadKeymap()}catch(e){announce(en?'Keyboard settings could not be refreshed.'",
            HTML,
        )


if __name__ == "__main__":
    unittest.main()

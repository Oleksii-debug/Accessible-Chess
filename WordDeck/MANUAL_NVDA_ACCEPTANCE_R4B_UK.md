# WordDeck Round 4b — ручна перевірка NVDA

Цей список виконує людина на Windows 11 з NVDA на ТОЧНІЙ збірці-кандидаті. Автоматичний UI Automation PASS не є ручним NVDA PASS.

1. Запустити WordDeck без прав адміністратора. NVDA має оголосити вікно WordDeck і поточне англійське слово; фокус має бути корисним для початку навчання.
2. Tab / Shift+Tab: пройти Dictionary, Recall study scope, Active Recall deck, Current English word, Ukrainian translation та доступні команди. Назви мають бути зрозумілими, без mouse-only кроків.
3. На Current English word натиснути Down кілька разів, потім Up. Down = наступна картка; Up = реально попередня показана картка.
4. Відкрити переклад Ctrl+T. У Ukrainian translation перевірити Up/Down/Left/Right/Home/End/PageUp/PageDown. NVDA/курсор читає текст, Recall-картка не змінюється.
5. Окремо на Dictionary, Recall study scope і Active Recall deck багато разів натиснути Up/Down без Enter. Значення змінюється й оголошується; фокус не перескакує на картку.
6. Відкрити меню клавіатурою й пройти його стрілками. Стрілки меню не повинні перемикати Recall-картки.
7. F1: довідка має правдиво описувати поточні клавіші, Recall Up/Down тільки на English word і Alt+F4 для закриття тренувальних вікон.
8. Ctrl+K: Shortcut settings. Список дій має отримати фокус. Enter відкриває capture; Esc скасовує capture. Після скасування settings лишається доступним.
9. Переконатися, що Alt+F4, Ctrl+Alt+Delete та звичайні Left/Right/Home/End не можна призначити як довільний shortcut; повідомлення про відмову має бути читабельним.
10. Відкрити Spelling. Перевірити Spelling study scope і Active spelling deck через повторні Up/Down без Enter. У полі відповіді стрілки/Home/End працюють як редагування тексту.
11. У Spelling перевірити неправильну/правильну відповідь, Show Answer, підказку/аудіо, Adaptive Coach/undo, доступний текстовий статус. Закрити Alt+F4 без втрати прогресу.
12. Відкрити Sentence Spelling. Перевірити Sentence pack, deck/scope, target count, поле відповіді, diagnostics/show/repeat. Стрілки в полі відповіді мають бути нативними; закриття Alt+F4 — безпечним.
13. Відкрити Export profile та Import profile клавіатурою. Стандартні Open/Save dialogs повинні бути повністю доступними. Для реального round-trip використати копію профілю, не єдиний оригінал.
14. Відкрити Reset learning data, прочитати підтвердження NVDA та натиснути No/Cancel. Потім, лише на disposable test profile, окремо перевірити реальний reset+recovery.
15. Перезапустити WordDeck. Recall/Spelling/Sentence state, scopes/decks, shortcuts і налаштування мають зберегтися відповідно до профільного контракту.
16. Перевірити помилки: відсутнє аудіо, відсутній SentencePack, некоректний імпорт. Має бути текстове читабельне повідомлення без тихого стирання прогресу.
17. Зафіксувати версію Windows, версію NVDA, точну identity збірки та PASS/FAIL для кожного пункту. Будь-який P0 дефект клавіатури/фокусу блокує ручне прийняття.

Машинні перевірки доводять кодову/Windows/UIA поведінку. Остаточну якість озвучення, порядок читання NVDA та реальні announcement-и підтверджує тільки користувач на точній фінальній збірці.

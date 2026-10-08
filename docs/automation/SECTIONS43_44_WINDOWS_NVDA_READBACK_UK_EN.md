# Windows/NVDA readback — Sections 43 and 44 (UA / EN)

**This is an executable acceptance script, not evidence that it has run.**
Use a genuine Windows 11 build of the exact PR #2499 shipping candidate with
NVDA 2026.1+ and Edge WebView2. Record the candidate SHA, screenshot hashes,
Windows build, display scaling, NVDA version and actual outcome. Never report
PASS merely because the source or a fake DOM fixture worked.

## Українська — послідовність перевірки

1. Запустіть зібраний EXE звичайним способом. Перевірте, що NVDA називає
   вікно Accessible Chess, основні заголовки та шахову дошку; клавіші
   `H`, `Shift+H`, `Tab` і `Shift+Tab` проходять справжні елементи.
2. На шаховій робочій області дійдіть `Tab` до «Колонки» і «Щільність».
   Оберіть одну колонку й компактний вигляд. Спробуйте «Згорнути» біля
   розділу ходів, потім «Розгорнути». Кнопка має оголошувати стан і не
   переносити фокус до прихованого поля.
3. Кнопкою «Висота» змініть висоту панелі двічі. Закрийте програму та
   запустіть новий процес. Переконайтеся, що вбудований нативний Settings
   відновив розмір, макет, щільність і стан панелей у приватному WebView2.
   Не приймайте успіх, отриманий лише всередині тієї самої сесії браузера.
4. Перевірте введення ходу та керування аналізом Stockfish без перехоплення
   звичайних комбінацій `Ctrl+C`, `Ctrl+A`, `Home` і `End` у полях.
   Виділення тексту в історії ходів і його копіювання мають працювати.
5. Через наявну канонічну навігацію відкрийте PGN, Бібліотеку, Книги,
   Тренування, Викладача та Класи (лише якщо функція доступна у збірці).
   На кожному екрані перевірте заголовки, фокус після переходу, вибір елемента,
   текст помилки та відновлення фокуса після дії.
6. У V2-розділі виберіть «Великий текст і читання». Перейдіть до іншого
   V2-розділу, оберіть компактний вигляд, закрийте EXE й перевірте,
   що окремі режими кожного розділу відновлюються після нового запуску.
7. У бібліотеці перевірте фільтри, результати та PGN-дерево. У книгах —
   метадані, заголовки, семантичні діаграми і повернення до дошки.
   У тренуванні — завдання, відповідь, підказку, розв'язок, прогрес.
   У класі — доступний список, авторизовану дію та видимий стан помилки.
8. У Web-клієнті пройдіть Board, PGN, Library, Books, Training, Media,
   Teacher, Classes, Online і Spectator, не вигадуючи доступних сервісів.
   Перевірте навігаційні кнопки, повідомлення `status`/`alert` і
   відсутність перекриття нативних відеокнопок стороннім шаром.
9. Повторіть пункти 1–8 при 200% і 400% збільшенні браузера, 125% і 200%
   масштабуванні Windows, вузькому вікні, темній і висококонтрастній темах.
   Додайте незалежні скриншоти й UIA-дерева як окремі докази.
10. Заблокуйте запис нативного Settings або підставте некоректний
    layout JSON через ізольований тестовий профіль. Перевірте fail-closed,
    повідомлення для NVDA та відсутність «Успішно збережено», якщо на диску
    нічого не збереглося. Не тестуйте на реальному обліковому профілі.

## English — independent acceptance checklist

1. Launch the exact packaged Windows EXE and use NVDA heading/Tab navigation
   to verify semantic board, move history and toolbar accessibility.
2. Collapse/expand a board panel; check aria-expanded, keyboard focus,
   reset, and natural text selection/copy.
3. Change width/density/panel height, close the entire executable, restart
   in a fresh private WebView2 profile, and prove native Settings readback.
4. Navigate existing PGN, Library, Book Reader, Training, Teacher and Classes
   services; verify live focus, errors, headings, selection and full
   keyboard navigation without duplicating application/engine authority.
5. Preserve separate Books reading and Teacher compact preferences across
   a real process restart.
6. In Web/Media/Online/Spectator, check semantic navigation, status and
   media-player controls without visual-only overlays.
7. Run 200%/400% zoom, Windows DPI changes, dark/high-contrast mode, 320px
   responsive width, error/recovery and capture evidence from genuine
   Windows UIA and NVDA.
8. Report exact SHA, PASS/FAIL/INCONCLUSIVE per step and attach raw evidence.
   Any unavailable external media/provider is NOT_CONFIGURED, never fake PASS.

## Evidence receipt template

- Candidate source SHA:
- Packaged binary SHA256:
- Windows / WebView2 / NVDA versions:
- Browser zoom / display scale / color theme:
- Tested module & specific keyboard actions:
- Actual NVDA speech/focus result:
- Screenshot/UIA/CI artifact:
- Outcome: PASS | FAIL | INCONCLUSIVE | NOT_CONFIGURED
- Regression/recovery notes:
- Reviewer and timestamp:

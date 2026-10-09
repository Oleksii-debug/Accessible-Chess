# Accessible Chess — Section 43: Windows workspace convergence and release qualification

Дата перевірки: 2026-10-09. **Статус: IMPLEMENTED CANDIDATE / NOT TERMINAL DONE.**

## Авторитетні джерела

- Технічний план: Section 43.1–43.6, «Повний редизайн Windows-вікон і робочих областей».
- Поточна інтеграція: [PR #2525](https://github.com/Oleksii-debug/Accessible-Chess/pull/2525), гілка `section43/windows-workspace-main-convergence-20261009-gpt6`.
- Попередня розробка: [PR #2499](https://github.com/Oleksii-debug/Accessible-Chess/pull/2499), лише джерело вибіркового перенесення, не кандидат прямого злиття.
- Розділи 41 (офлайновий Tabler дизайн) та 44 (реальні стилі сервісних панелей) вже включені двома контрольованими двобатьківськими інтеграційними комітами. Збережено їх авторитет і зміни в `main`.

## Інтегроване (реальний код, не макети)

1. **43.1:** продовжено чинний `web/index.html`, `web/design_system.css`, офлайнову основу Tabler Section 41. Збережено Python chess/domain core, WebView2, WinForms меню, існуючі ID і елементи введення.
2. **43.2:** п'ятнадцять наявних панелей Stage1 — шахівниця, ходи, Stockfish, відомості, форми, гра проти рушія, допомога, Media та AI. Кнопки згортання, перемикання висоти, вибір щільності/колонок, відновлення. Вмістом і шаховою позицією як раніше керує канонічна програма.
3. **43.3:** робочі області PGN, Library, Books, Training, Teacher, Classes отримали індивідуальні режими normal/compact/reading, згортання, зміну висоти, reset та відновлення. Native persistence: `get_presentation_layout` / `save_presentation_layout` через атомарний, upgrade-locked `acs.settings.Settings`. Резервна копія браузера є локальним fallback, а не авторитетом Windows.
4. **43.4:** реальні модальні діалоги keymap, help, Stockfish game повертають фокус до ініціатора і не перехоплюють фокус, який був свідомо перенесений. Збережено існуючі native dialogs, меню, прогрес/імпорт/експорт.
5. **43.5:** збережено native editable fields, text-selection/copy, поточний keyboard owner, NVDA live-region ownership. Після зміни мови у чинних заголовках початкові кнопки контролю панелей перепід'єднуються без дублювання слухачів.
6. **43.6:** додані source-bound DOM/native-контракти, негативні/відновлювальні native Settings тести, реальний Edge headless DOM та screenshots (DPI 100%, 125%, 150%, 200%), незалежний process-scoped WinForms UIA oracle, exact SHA multi-OS workflow.

## Точні виконані перевірки

- **160/160** асерцій Section43 у V8 із фактичними GitHub-байтами `web/index.html`, `web/version2_final_product_bootstrap.js` і `web/design_system.css`. Включено асинхронну симуляцію WebView2 private-mode bridge, контроль 15 панелей, фокусу, resize/reset, poisoning, restart, три справжні обробники `dialog.close`.
- **84/84** додаткових асерцій Section44 service CSS/source-contract на тих самих GitHub-байтах та реальних Book/Library/Training/Teacher/Classroom/PGN модулях. **Сумарно 244/244.**
- Ці виконання здійснено у V8-середовищі з адаптацією Node built-in `fs`, `vm`, `path`, `assert`. Не називати їх Hosted Node PASS, Windows UIA PASS або NVDA PASS.
- GitHub Actions нових комітів перебувають у черзі: `QUEUED`, `conclusion=null`, без доказів успішного прогону Windows або Linux. Окремий `section43-windows-workspace.yml` тепер запускає також Section44 contract у справжньому Node.

## Фінальна перевірка Windows/NVDA (після отримання exact-SHA збірки)

1. З Windows 11/NVDA відкрити збірку саме з того SHA, який є в майбутньому фінальному CI-рецепті. Перевірити назву головного вікна, native меню через Alt/стрілки/Enter та доступну дошку.
2. Обійти клавішею Tab Stage1 controls панелей: назви повинні містити заголовок; кнопка згортання має назву й стан `aria-expanded`. Згорнути панель з активним фокусом у її вмісті: фокус має перейти на кнопку, прихований вміст не повинен звучати в NVDA. Розгорнути й прочитати статичний текст/скопіювати його.
3. Змінити розміри та макет, перезапустити програму, перевірити ті самі панелі. Перевірити зламаний JSON та stale settings writer; має бути безпечне відновлення без зміни chess state.
4. Перемикати PGN, Library, Books, Training, Teacher, Classes; окремо для кожного змінити normal/compact/reading, висоту, згортання; перезапустити; переконатися, що фокус і клавіатурні команди поточних реальних модулів працюють.
5. Відкрити/закрити клавіатурний діалог, довідку та Stockfish game; перевірити повернення фокусу. Для нової партії після успішної дії переконатися, що відновлення фокусу діалогу не перехоплює вже встановлений фокус вводу ходу.
6. Перевірити масштаб 100%, 125%, 150%, 200%, висококонтрастний режим, reduced motion, довгі UA/EN рядки, розміри вікна, збереження selection-copy, доступність video controls YouTube.
7. Реальні external UIA, screenshot artifacts, packaged restart, NVDA human feedback прив'язати до exact source SHA; не прирівнювати source fixture до реальної фізичної перевірки.

## Терміни статусів / правило DONE

`CODE_CANDIDATE` = зміни на гілці; `V8_PASS` = фактично виконаний JS-контракт; `HOSTED_PASS` = відповідний завершений hosted run для exact head; `WINDOWS_UIA_PASS` = реально виконаний зовнішній UIA; `DONE` = прийнято source, host/GUI кваліфікацію, після цього інтеграцію в актуальний `main` і зафіксовано фінальний статус.

**Наразі 43.1–43.3 є кандидатом реалізації; 43.4–43.5 потребують реального Windows прийняття; 43.6 очікує hosted Windows/Ubuntu і UIA кваліфікації. SECTION 43 = PARTIAL / NOT TERMINAL DONE.** Програмне злиття не є підставою автоматично ставити DONE. За архітектурним планом власник проводить остаточний human NVDA acceptance на релізному етапі.

Для наступного виконавця: продовжувати PR #2525, зафіксувати actual logs/tests, усунути конкретні помилки, провести релізні перевірки. Не дублювати планові записи і не перезаписувати приналежні Section 41/44 реалізації.

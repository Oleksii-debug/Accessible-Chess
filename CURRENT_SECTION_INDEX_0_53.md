# Accessible Chess — єдина чинна ідентичність Sections 0–53

**ОБОВ'ЯЗКОВИЙ ІНДЕКС ДЛЯ ВСІХ ВОРКЕРІВ.** Цей файл відображає нумеровані назви з поточного канонічного Google Drive документа «ACCESSIBLE CHESS — SECTION PLAN ДО ПОВНІСТЮ ЗАВЕРШЕНОГО ПРОДУКТУ». Існує лише **одна** допустима відповідність номер → назва → поточні вимоги. Номери не є вільними ярликами: Section 39 завжди має саме той scope, який зазначений для Section 39 нижче та в поточному Drive документі.

**Правила:**
- Для завдань, реалізації, тестів, називання PR, реєстру DONE, звітів і вибору наступної роботи використовувати виключно наведений нижче поточний перелік Sections **0–53**. Ніяких альтернативних трактувань номерів, історичних зіставлень, порівнянь версій переліку або коментарів про зміну порядку.
- Відомості про попередні коміти або PR можна читати **тільки** як технічні докази для відповідної поточної функції, ніколи як джерело вимог чи іншої ідентичності Section. Не переносити жоден DONE із чужої ідентичності або непов'язаного історичного запису.
- Точний scope і acceptance для кожного рядка визначає **поточний** Drive план; реальний завершений стан — live `main/SEQUENTIAL_CLOSURE_STATE.md`. Історичні цитати, робочі PR, інші документи та чати не змінюють цей перелік.
- Не змінювати номери, назви або кількість рядків без окремої явної вказівки власника. Не перескакувати перший ACTIONABLE Section. За запуск — один батьківський Section; завершені підрозділи не переробляти.

## Зафіксований поточний перелік

- **Section 0 — Канонічні контракти форматів і єдина модель даних**
- **Section 1 — FEN, позиції, SAN і позиційний interchange**
- **Section 2 — PGN і повний GameTree**
- **Section 3 — ACSDB, Library, Search і великі бази партій**
- **Section 4 — ChessBase family: CBH, CBV, CBF та related formats**
- **Section 5 — Книжкові формати і semantic BookDocument**
- **Section 6 — Books, Training, Exercises і готовий навчальний контент**
- **Section 7 — Форматна кваліфікація на реальних корпусах**
- **Section 8 — Refreshable Tactile Graphics Core**
- **Section 9 — TactileFrame і реальний hardware adapter**
- **Section 10 — Тактильна синхронізація з Formats, Books і Training**
- **Section 11 — Tactile input, routing і device profiles**
- **Section 12 — Повний локальний chess workflow**
- **Section 13 — Stockfish, analysis і гра проти engine**
- **Section 14 — Windows application, keyboard, menu, settings, languages, sounds і clocks**
- **Section 15 — Візуальна дошка для зрячих користувачів**
- **Section 16 — Media Core: MediaSession, MediaClock і MediaPositionTimeline**
- **Section 17 — Recorded Media і YouTube playback**
- **Section 18 — Live Broadcast synchronization**
- **Section 19 — Board Vision, Speech Context і Media Intelligence**
- **Section 20 — Повний Media user workflow**
- **Section 21 — Universal Chess Agent runtime і tool gateway**
- **Section 22 — Agent tools для вже завершених доменів**
- **Section 23 — AI Coach, game review, research і training workflows**
- **Section 24 — Agent reliability, voice, privacy і resource policy**
- **Section 25 — Blind Coach Pointer, “мишка”, highlights і arrows**
- **Section 26 — Local Teacher/Classroom core**
- **Section 27 — Зворотний канал від учня і teaching interaction modes**
- **Section 28 — Students, classes, courses, assignments, progress і child UX**
- **Section 29 — Privacy і security foundation для мережевих/дитячих функцій**
- **Section 30 — Server application boundary і authenticated API foundation**
- **Section 31 — Accounts, authentication, workspaces і cloud synchronization**
- **Section 32 — Remote Classroom: sync, audio, chat, files, video і lesson recording**
- **Section 33 — Online Game, multiplayer, spectator і social play**
- **Section 34 — Повноцінний Web client**
- **Section 35 — Entitlements, subscriptions, billing і organization plans**
- **Section 36 — Late cross-product integration: Agent, Tactile, Classroom, Media, Web**
- **Section 37 — Законні джерела книг, партій, позицій і шахових баз**
- **Section 38 — Завантаження реальних корпусів та інтеграція всіх форматів**
- **Section 39 — Практичне тестування всіх форматів і варіацій**
- **Section 40 — Наповнення програми готовою офлайновою бібліотекою**
- **Section 41 — Професійна дизайн-система та інтеграція безкоштовних бібліотек**
- **Section 42 — Преміальні шахівниці, фігури, масштабування й графічні ефекти**
- **Section 43 — Повний редизайн Windows-вікон і робочих областей**
- **Section 44 — Єдиний преміальний стиль бібліотеки, навчання, класів, Web і медіа**
- **Section 45 — Студія налаштувань дизайну й персональні профілі**
- **Section 46 — Візуальне доведення, usability та accessibility quality gate**
- **Section 47 — Завантаження реальних шахових відеофайлів з інтернету та автономний аналіз**
- **Section 48 — YouTube IFrame: реальні посилання, плеєр і дозволені інтеграційні тести**
- **Section 49 — Безпечне підключення Mistral та інших наявних безкоштовних ШІ-провайдерів**
- **Section 50 — Наскрізне реальне тестування відео, YouTube і ШІ-агента**
- **Section 51 — Persistence, backup, restore, migrations і user-data portability**
- **Section 52 — Packaging, updates, signing, SBOM, licensing і commercial release infrastructure**
- **Section 53 — Whole-Product Final Convergence**

## Контроль

У таблиці наведені всі номери від **0 до 53 включно** (54 нумеровані позиції, зокрема Section 0). **Останній номер — 53.** Ніяких додаткових Sections не створювати. DONE визначається окремо, а не за наявністю рядка в цьому індексі.

**Канонічний Drive-план:** https://docs.google.com/document/d/1ITsUBFwwETRICctcOWLd6atuMcCFZg6v5-wVFumIyxE/edit

# Sections 45–46 — незалежне оцінювання вигляду та NVDA на Windows

**Стан:** протокол для реального тестування. Ніякого PASS, підпису тестувальника чи погодженого baseline тут ще немає. Код із PR #2503 не можна назвати Section 46 DONE лише за цим документом.

## Тестова комплектація та ідентичність

Перед початком зафіксуйте точний Git commit SHA, SHA-256 ZIP/EXE, версію Windows, масштаб DPI, версію NVDA, версію WebView2 і походження всіх локальних графічних файлів. Доступні лише фактично зібрані артефакти; не використовуйте випадковий старий EXE. Всі screenshot і записи зберігайте без приватних шляхів, імен студентів, ключів і справжніх матеріалів користувача.

## NVDA та клавіатурна перевірка

1. Відкрийте існуючий Windows Accessible Chess. Без миші перейдіть Tab до «Відкрити студію». NVDA має оголосити кнопку та її стан «згорнуто».
2. Натисніть Enter. NVDA має оголосити розгорнутий стан та фокус на виборі профілю. Tab повинен перейти до «Тема інтерфейсу»; усі поля мусять мати зрозумілі назви.
3. Виберіть Low Vision, перегляньте 64-польову декоративну дошку. Не повинно існувати ще однієї шахової дошки для скринрідера: приклад позначений aria-hidden. Справжня позиція FEN, список ходів і статус не змінюються.
4. Перевірте Classic, Tournament, Coach, Classroom Presentation, Low Vision, High Contrast. Для кожного протестуйте Apply / Cancel / Reset, зміну розміру, орієнтації, кольору, фігур, координат та підсвічування. Виконуйте ті самі кроки для української й англійської локалізації.
5. Збережіть новий профіль через клавіатуру, назвіть його, експортуйте JSON, імпортуйте назад, закрийте програму і відкрийте повторно. Попередньо збережені партії, книги, бібліотеки, гарячі клавіші та звуки не повинні губитися.
6. Введіть назву профілю, виконайте Ctrl+A і Ctrl+C. Скопійований текст має бути доступний як звичайний виділений текст. Перевірте Esc, Shift+Tab, утримання фокуса після зміни теми й відновлення зіпсованих параметрів.
7. У Web повторіть профілі та перевірте, що зображення фігур і стилі впливають на дійсну поточну дошку, але не змінюють FEN, історію чи перехід між ходами. Web-профілі є локальними; перенесення потребує явного імпорту/експорту.

## Фактична візуальна оцінка зрячих тестувальників

Щонайменше двом незалежним зрячим тестувальникам запропонуйте пройти **кожен реальний продуктовий модуль**: дошка, PGN, бібліотека, книги, тренування, викладач, клас, медіа, онлайн/глядач, налаштування, діалоги клавіш і запуск Stockfish. Зіставляйте три теми (light/dark/high contrast), усі шість профілів, вузьке/широке вікно, DPI 100/125/150/200%, Windows forced-colors і reduced motion.

Кожен тестувальник незалежно виставляє оцінку **1–5** за: цілісність стилю; читабельність; професійний вигляд; зрозумілість організації; контраст та фокус; відсутність обрізання тексту/елементів. Для оцінки 1–3 обов'язково додається конкретний відтворюваний дефект та screenshot (без приватних даних). Окремо фіксується PASS/FAIL фізичних keyboard/NVDA маршрутів: позитивна оцінка зовнішнього вигляду **не замінює** автоматичний або нативний accessibility PASS.

## Approved screenshot baselines: як підписувати

Автоматичний сценарій tools/section46_visual_quality_browser.py формує PNG та quality-manifest.json із SHA-256 кожного PNG і exact-source SHA. Це ще **не** погоджені еталони. Після реальної перевірки зрячим тестувальником зберігайте окремий approved-baselines.json зі строгою схемою:

- schema_version = 1, approved = true, human_reviewed = true;
- reviewer = реальна ідентифікація незалежного тестувальника;
- reviewed_at = фактичний UTC час YYYY-MM-DDTHH:MM:SSZ;
- baseline_source_sha = точний SHA знімків-еталонів;
- screenshots = масив об'єктів name та sha256 для кожного погодженого PNG.

Після цього tools/section46_baseline_diff.py може порівняти поточні PNG з погодженим набором; він відхиляє відсутні підписи, дубльовані назви, інший SHA-256 або нечітку source provenance. Без фізичної оцінки і погоджених еталонів SECTION46_VISUAL_APPROVAL=NOT_QUALIFIED.

## Evidence і термінальне рішення

Результат має містити: exact source SHA; реальні двоплатформні CI запуски та логи; підтверджену інтеграцію у поточний Product; Windows EXE clean-machine запуск; фактичні NVDA/UIA/keyboard/selection-copy; скриншоти і оцінки зрячих; реальні performance на великих базах і Media; права на всі зображення/шрифти; постінтеграційний readback. Якщо будь-яка обов'язкова частина відсутня, залишайте OPEN, не ставте DONE.

---

## English — independent tester quick reference

Use the exact qualified Windows build and record its SHA, environment, screenshot checksums and license notices. Test all six design profiles with keyboard and NVDA, every real product route, three colour themes, 100–200% DPI, forced colours and reduced motion. Verify preserved focus, selectable text, unchanged chess FEN/move history, profile export/import and restart recovery. Score legibility, cohesion, clarity and professional quality from 1 to 5, recording reproducible defects. Do not sign visual baselines or mark Section 46 DONE until actual human review and native/automated evidence exist.

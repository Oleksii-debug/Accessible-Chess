# Accessible Chess — advanced test corpus / Інструкція для тестувальників

**Version:** Revised Section 37 source branch (NOT final product release).  
**Audience:** Ukrainian and English readers at or above first chess category / candidate master, aspiring to master/GM-level calculation.  
**Rights:** Original instructional explanations created for this project using genuine Lichess **CC0** chess positions. Historical Réti study (1921) with newly authored bilingual prose. No pirated chess books or third-party proprietary CBH/CBV/CBF/2CBH/CBONE databases are included.

## Українською — як перевірити

1. Завантажуйте тільки збірки, які реально пройшли GitHub Actions: `section37-uk-en-advanced-tactics-positional-endgame-books-ubuntu-24.04` або `...-windows-2025` із **цього ж точного коміту**. Якщо задача `queued` чи `failed`, готового перевіреного архіву немає. Не вважайте PR або commit доказом зібраного продукту.
2. Кожна кваліфікована збірка має **10 текстових і книжкових версій**: українські та англійські TXT, Markdown, HTML, EPUB3, DOCX. Додатково мають бути **два оригінальні PGN** (чотири реальні анотовані партії Lichess 2200+ за онлайн-рейтингами гравців; справжній історичний етюд Реті 1921) і **один FEN** із 12 вихідними шаховими позиціями. Разом **13 файлів плюс SHA256-маніфест**.
3. **TXT**: перевірте озвучення української/англійської мови, пошук заголовків як тексту. Не вимагайте, щоб звичайний TXT сам створив шахові об’єкти з тексту.
4. **Markdown**: для кожного завдання є окремий блок `fen`; він повинен відкритися як семантична позиція через Books/BookReader, із переходами між заголовками та позиціями.
5. **HTML та EPUB3**: кожне з 12 завдань має власний стабільний заголовок/якір; EPUB3 містить 12 посилань на глави. Перевірте навігацію клавіатурою та озвучення NVDA.
6. **DOCX**: власне текстове джерело українською позначене `uk-UA`, англійське — `en-US`. Перевірте читання заголовків та описів позицій. На цей момент DOCX підтримує текстову семантику, але не повинен домислювати шахову FEN-позицію із звичайного абзацу.
7. **PGN**: завантажуйте через відповідний маршрут імпорту партій/бібліотеки, не через Books як нібито книгу. Перевірте оригінальні коментарі, варіанти, історичну FEN та повторне відкриття бібліотеки; етюд Реті не називайте турнірною партією.
8. **FEN**: збережені позиції є станом **до останнього ходу суперника**. У навчальному режимі цей хід потрібно виконати на єдиній канонічній шаховій дошці до того, як користувач робитиме власне рішення. Не показуйте готовий розв’язок завчасно.
9. **PDF**: окреме завдання GitHub Actions лише тимчасово створює та перевіряє PDF; до користувацького ZIP або публічного набору ці файли **не додаються**, бо поточна програма не має кваліфікованого імпорту PDF. Зберігається тільки технічний JSON-звіт.
10. **Доступність NVDA**: користуйтеся стандартною клавіатурною навігацією за заголовками й абзацами. Перевірте читання кирилиці, порядок FEN, перехід між розділами, відновлення після закриття. Фактичне ручне тестування NVDA на Windows ще має бути виконане користувачем або незалежним тестувальником — CI не може цього засвідчити.

## English — how to test

1. Download **only GitHub Actions artifacts from a passing run on the exact source SHA**, not an unverified or queued workflow. The advanced bookpack is labeled `section37-uk-en-advanced-tactics-positional-endgame-books-[platform]`.
2. The main artifact is **10 books** (two languages × five formats: TXT, Markdown, HTML, EPUB3 and DOCX), **two real PGN sources** (four CC0 annotated Lichess games; the historical 1921 Réti study with our original bilingual commentary), **one 12-position FEN source**, and a source-digest manifest.
3. Test native `Version2Application` Books open/heading/position/progress-restart on each of the five book formats, rather than merely checking ZIP validity or file extensions. In TXT and DOCX, plain FEN prose is **not** inferred as a playable position. Markdown, HTML and EPUB3 use explicit FEN semantics.
4. The 12 EPUB3 chapter links must resolve to the corresponding XHTML headings. DOCX should expose actual headings and English `en-US` or Ukrainian `uk-UA` reading languages for assistive technology.
5. The source FEN is **before the opponent's preceding UCI move**. Apply that first move using the existing canonical chess engine before presenting the learner with the position to solve.
6. The advanced materials are **not beginner chess tutorials**. Lichess puzzle ratings 2200–3166 are not FIDE ratings or proof of grandmaster title. The historical composed study is separately attributed to Richard Réti, not mislabeled as a practical game.
7. PDF source files are rendered and tested **temporarily only**, never distributed as a reader-ready Accessible Chess user book. Native PDF ingress is **NOT_QUALIFIED**; only a metadata receipt can be uploaded until the app itself opens PDFs.
8. ChessBase proprietary families, English premium publisher books and third-party tournament PGNs not licensed for redistribution are deliberately excluded. Source/reference links may be included in the bibliography; **references are not imported book content**.

## Source and integration evidence / Докази

- Machine-readable source and bilingual tasks: `tests/real_corpus/advanced_training/section37_master_workbook_bilingual.json`.
- Original annotated CC0 games and 1921 genuine composed endgame study: `tests/real_corpus/advanced_training/*.pgn`.
- High-level English publisher bibliography + Ukrainian original parallel material and format status: `docs/corpus/SECTION37_UK_EN_HIGH_LEVEL_REFERENCE_MATRIX.json`.
- Actual parser/book contracts: `tests/test_revised_section37_bilingual_advanced_formats.py`.
- Actual product-route and restart contracts: `tests/test_revised_section37_bilingual_in_application.py`.
- Historical study to ACSDB import: `tests/test_revised_section37_genuine_advanced_study_readback.py`.
- Exact source and distribution license registry: `docs/corpus/revised_sections37_40_sources.json`.

**Terminal status:** Section 37 is **NOT DONE** until exact-head passing test evidence, licensed broad real-format acquisition, full format/provenance/packaging readback and independent accessibility evidence are recorded. **Current-shipping is not advanced by this PR alone.**


## Вимога власника: лише те, що реально відкривається у програмі / Native-reader-only policy

- Книги Івана Хабінця та інші придбані сторонні видання, яких немає як правомірно отриманих і реально імпортованих файлів, **не входять до користувацького тестового набору**. Посилання на магазин або видавця не вважається бібліотечною книгою Accessible Chess.
- Фінальна команда збірки передбачає `python -m tools.revised_section37_bilingual_workbook_pack --output-dir section37-bilingual-shareable-advanced-books --zip-output section37-advanced-uk-en-tested-corpus.zip`. Перед перейменуванням тимчасового ZIP вона перевіряє всі оригінальні SHA-256, заборонені сторонні вихідні файли і повторно читає архів. У ZIP 10 справжніх двомовних файлів книг у підтримуваних форматах, два вихідні PGN, 12-позиційний FEN і маніфест.
- PDF **НЕ публікується як доступний у Accessible Chess користувацький навчальний файл**; окремий PDF-тест у CI може генерувати PDF тимчасово, однак як артефакт віддає **лише технічний JSON-звіт**, поки канонічний PDF Book importer не зможе відкрити його сам.
- Розділ 38 має окремий `tests/test_revised_section38_real_advanced_source_crossroute.py` для фактичного readback того самого ZIP через `Version2Application`, `LibraryImportService`, `AcsDatabase` і канонічну модель шахів. Вимога DONE — тільки **успішний незалежний запуск** цих тестів на тому самому Git SHA. Якщо GitHub Actions стоїть `queued`, тест ще не підтверджений.

**English:** No full book is included merely because a retailer link exists. Only actual legally shareable content with a native Accessible Chess reading/import path is published to the owner. PDFs are source QA only until the product can natively read them, and external paid publications are not part of the real corpus. The complete user ZIP is generated only after source SHA checks, an excluded-material leakage audit and complete ZIP readback; a queued CI run is not a PASS.

# Accessible Chess — майстерська бібліотека й тестування форматів 38–39

**Вікно застосування:** від I розряду / КМС до IM/GM, **без** вступних підручників,
елементарних матів, вправ для початківців і заяв, що Lichess puzzle rating = FIDE Elo.

**EN scope:** Candidate Master and above, IM/GM training objectives. Exclude
beginner textbooks and training below the owner-designated level. Lichess puzzle
ratings are **difficulty estimates**, never proof of a player's title.

**Source of truth:** `docs/corpus/SECTION38_39_ADVANCED_BILINGUAL_QA_CATALOG.json`;
єдиний чинний план Accessible Chess 0–53, Sections 38–39. Це НЕ новий план.
Літературні посилання — **бібліографія**, а не завантажені, перевірені або
дозволені до перепоширення копії платних книг.

## Що вже є як шаховий зміст і як ним користуватися

- У встановленій актуальній версії продукту з відповідним комітом:
  **Books** → матеріал `Advanced Lichess tactics 2200+` або
  `Складна тактика Lichess 2200+` залежно від мови; містить **16** оригінальних
  Lichess CC0 вправ із рейтингом задачі від 2200. Окремий матеріал **Extreme
  Lichess puzzles 3000–3166** — **4** вправи. Український та англійський тексти
  ведуть на **ті самі 20 шахових позицій і рішення**, без нових шахових правил.
- Під час тесту NVDA працюйте лише клавіатурою: відкрийте Books, оберіть
  матеріал, перейдіть до вправи, відкрийте шахівницю, поверніться до книги,
  запустіть Training та перевірте збереження прогресу. Фізичний тест на
  встановленій EXE **ще не підтверджений**; не підміняйте його unittest.
- PGN для імпорту в штатну **Library/PGN Open**: workflow
  `Revised Sections 38-39 Bilingual Advanced Chess QA`, артефакт
  `section38-39-real-cc0-advanced-pgn-windows-2025`, файл
  `advanced-cc0-20-master-puzzles.pgn`. Артефакт з'являється тільки коли
  GitHub Actions виконав експорт; якщо job `queued`, файла для завантаження
  **поки немає**. Поряд із PGN є
  `advanced-cc0-20-master-puzzles-manifest.json` з SHA256.
- PGN містить **20 вихідних CC0 задач, перетворених** на 20 позиційних записів
  SetUp/FEN/SAN. Це **НЕ** оригінальні турнірні PGN, не FIDE-рейтинг і не
  перепаковані захищені книги. Зафіксовані FEN/відповідь мають зберігатися при
  відкритті й повторному імпорті.

## Професійні книги — українська навігація / English references

| Тема / Area | Український маршрут тесту | Професійне англомовне джерело — лише законний опис |
| --- | --- | --- |
| Складна тактика / tactics | Власний український текст 20 оригінальних CC0 задач; М. Боднар, «Тактика для всіх» — **лише розділ 200 задач КМС/МС/ММ**, не решта книги; мова друкованого видання ще не підтверджена | Jacob Aagaard, *Grandmaster Preparation: Attack & Defence*, [official excerpt](https://qualitychess.co.uk/wp-content/uploads/2024/02/AttackDefence-excerpt.pdf) |
| Розрахунок / calculation | Кандидатні ходи, захист, довгі варіанти, власні UA задачі Lichess 2200+ | Jacob Aagaard, *Grandmaster Preparation: Calculation*, [publisher catalogue/excerpt](https://qualitychess.co.uk/ebooks/CALCULATION-excerpt.pdf) |
| Етюди / composed studies | Власні UA картки складних етюдів, однак **справжні авторські оригінали ще не імпортовані** | Mark Dvoretsky & Oleg Pervakov, *Studies for Practical Players*; Jan Timman, *The Art of The Endgame* |
| Позиційна гра / structures | UA картки планів, профілактики, типових слабкостей, оригінальні ECO метадані | Mauricio Flores Rios, *Chess Structures: A Grandmaster Guide*, [publisher page](https://www.simonandschuster.com/books/Chess-Structures/Mauricio-Flores-Rios/9781784830007) |
| Дебют / opening theory | UA практикум із справжніх ECO A–E, тільки глибокі RAV і майстерські партії проходять експертне приймання | Andrei Volokitin & Vladimir Grabinsky, *Perfect Your Chess*, [publisher page](https://www.newinchess.com/perfect-your-chess) |
| Мітельшпіль / annotated master games | UA складні позиції й чотири авторизовані анотовані Lichess ігри | Volokitin & Grabinsky, *Perfect Your Chess*, [publisher page](https://www.newinchess.com/perfect-your-chess) |
| Практичний ендшпіль / endgames | UA задачі із цугцвангом, ладейними й пішаковими закінченнями | Mark Dvoretsky, *Dvoretsky's Endgame Manual*, [publisher page](https://www.newinchess.com/dvoretsky-s-endgame-manual-6270); Jesús de la Villa, *100 Endgame Patterns You Must Know* |
| Оборона / defensive resourcefulness | UA тихі ресурси, контргра й помилкові кандидати | Aagaard, *Grandmaster Preparation: Attack & Defence*, [official excerpt](https://qualitychess.co.uk/wp-content/uploads/2024/02/AttackDefence-excerpt.pdf) |

**EN testers:** the Ukrainian descriptions are separately authored QA instructions, not
claimed authorized translations of commercial books. Use the original publisher
pages to obtain licensed copies; verify format and right to test before private
ingestion. Never put a commercial book inside public GitHub/ZIP.

## Усі шістнадцять форматів / Sixteen format gates

| Формат | Вхідний матеріал і обов'язкова перевірка | Truth boundary |
| --- | --- | --- |
| FEN | Майстерські позиції, parse→canonical FEN→reimport | Local verified slice; not all positions |
| SAN | Реальний запис ходів, canonical Board, розгалуження | Embedded original/derived SAN only |
| EPD | Оригінальні EPD задачі, operations + FEN, restart | External source qualification incomplete |
| PGN | Справжні анотовані партії, RAV/NAG/Chess960 та 20 CC0 derived tests | Not every original corpus qualified |
| ACSDB | Партії в Library, SHA, пошук, reopen SQLite | Derived database is not external ACSDB |
| EPUB3 | Оригінальна професійна книга з дозволом, розділи/діаграми/повернення | Not yet all externally qualified |
| HTML | Оригінальний авторський аналіз, heading/image/position semantics | Incomplete external source coverage |
| TXT | Текст із перевіреним hash/rights, stable reading | Technical Capablanca sample not CM-only course |
| Markdown | Оригінальний ліцензований розділ із PGN/FEN fences | Original source qualification pending |
| DOCX | Справжній OPC Word, heading, text/alt, restart | Partial; genuine external CM book missing |
| PDF | Оригінальна PDF книга/етюди, доступний текст+діаграми | PDF/OCR semantic importer unsupported |
| CBH | Повна оригінальна сім'я companions, RAV/NAG і decoder | Conditional external backend, not full |
| CBV | Правомірний оригінальний архів, індекси, коментарі | Conditional external backend |
| CBF | Справжня пара CBF+CBI | Unsupported / missing licensed sample |
| 2CBH | Справжня повна база 2CBH | Unsupported / missing licensed sample |
| CBONE | Справжня повна база CBONE | Unsupported / missing licensed sample |

Testers must report **original source URL, expected SHA256, observed SHA256, import
count, actual semantic readback, warnings, lost comments/variations, restart,
keyboard/UI result, CI source SHA, and actual PASS/PARTIAL/UNSUPPORTED/BLOCKED**.
Never mark a source PASS on the basis of an extension, link, synthetic document,
partial ChessBase import, or queued workflow.

## Термінальна готовність

Викладені матеріали — **робочі вихідні тексти, тестові контракти і рецепти**.
Вони не є доказом інтегрованої Windows EXE, законності всіх сучасних видань,
виконання зовнішнього CI або людського тесту NVDA. Нові Section 38 і Section 39
позначати DONE можна **лише** після всього обсягу відповідно до єдиного
канонічного плану і фактичного post-integration readback.

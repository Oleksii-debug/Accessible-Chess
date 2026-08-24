# WordDeck R4c — ручна NVDA-перевірка точної збірки

Статус: **HUMAN TEST REQUIRED / PASS НЕ ЗАЯВЛЕНО**.

Цей список застосовується лише до точної інтегрованої/релізної збірки, яку перевіряє користувач у Windows 11 з NVDA. Автоматичний UIA та self-test не є заміною ручної NVDA-перевірки.

## 1. Запуск і стартовий фокус
- Запустити `WordDeck.exe` лише клавіатурою.
- Переконатися, що NVDA оголошує вікно WordDeck і доступні стандартні елементи.
- Перейти Tab/Shift+Tab через Dictionary, Study Scope, Deck, Current English word, Ukrainian translation та інші доступні елементи без тупика або миші.
- Пасивне оновлення статусу не повинно красти фокус.

## 2. Recall — критичний Natalia regression
- На `Current English word`: Down показує наступну картку; Up повертає реально попередню показану картку.
- Відкрити переклад Ctrl+T. У `Ukrainian translation` Up/Down/Left/Right/Home/End/PageUp/PageDown повинні залишатися звичайною навігацією текстом і не міняти картку.
- У Dictionary, Recall study scope та Active Recall deck багаторазово натискати Up/Down без Enter. Значення повинно змінюватися штатно, а фокус залишатися в тому самому selector.
- Відкрити File menu та користуватися стрілками. Стрілки меню не повинні перемикати Recall-картку.

## 3. F1 та shortcuts
- F1 має пояснювати, що швидкі Up/Down працюють лише на англійському слові, а переклад/selector мають стандартні стрілки.
- F1 має містити актуальні дії Spelling і Sentence та стандартне закриття Alt+F4.
- Ctrl+K відкриває Keyboard shortcuts; стартовий фокус має бути на списку дій.
- Enter на дії відкриває capture; Escape скасовує capture без закриття settings.
- Перевірити одну безпечну переназначену комбінацію: нове призначення діє відразу та зберігається після перезапуску.
- Alt+F4 та Ctrl+Alt+Delete не повинні прийматися як навчальні shortcuts.

## 4. Spelling
- Ctrl+Shift+S відкриває Spelling.
- NVDA читає український prompt, scope/deck selectors, поле англійської відповіді та текстовий статус.
- У scope/deck багаторазовий Up/Down не переводить фокус у поле відповіді.
- У полі відповіді стрілки/Home/End працюють як редагування тексту, а не як навчальна навігація.
- Перевірити неправильну відповідь, правильну відповідь, Show Answer, hint/audio та Adaptive Coach keyboard paths, якщо вони доступні в точній збірці.
- Alt+F4 стандартно закриває Spelling і повертає до корисного контексту WordDeck.

## 5. Sentence Spelling
- Ctrl+Shift+E відкриває Sentence Spelling навіть якщо production SentencePack не встановлено; відсутність pack має пояснюватися текстом, без падіння.
- NVDA читає доступні selectors, поле відповіді, diagnostics/status та import/help controls.
- Up/Down у selector не краде фокус; стрілки у полі відповіді залишаються звичайним редагуванням.
- Перевірити import/cancel/error шлях лише клавіатурою.
- Alt+F4 стандартно закриває Sentence вікно.

## 6. Профіль, відновлення та reset
- Ctrl+Alt+E відкриває export повного персонального профілю; Cancel/Escape не змінює поточну картку.
- Ctrl+Shift+I відкриває import повного профілю; Cancel/Escape не змінює дані.
- File → Reset Recall learning data: діалог має бути читабельним NVDA; Cancel не повинен скидати дані.
- Hide/restore слова, backup/recovery та помилки повинні повідомлятися текстом.

## 7. Стабільність фокусу
- Виконати не менше 30–50 повторних змін scope/deck у Recall і Spelling.
- Кілька разів відкрити/закрити F1, shortcuts, Spelling, Sentence і профільні діалоги.
- Після закриття modal/trainer вікон фокус має повертатися до логічного доступного елемента, без mouse-only recovery.

## 8. Що фіксувати при помилці
Для кожної проблеми записати: точну збірку, режим, елемент/accessible name, клавіші, що NVDA сказав, очікуваний результат, фактичний результат і чи відновився фокус.

## Майбутні режими
Grammar, Dictation, Story/Reading і Book Import не проходять ручний PASS у цьому Foundation циклі, бо повні модулі ще не активуються тут. Їхні accessibility contracts визначені окремо та повинні бути використані в майбутніх стадіях.

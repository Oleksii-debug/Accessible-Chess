STRINGS = {
'uk': {
'app':'Accessible Chess — Етап 1', 'ready':'Готово. Стандартна позиція. Хід білих.',
'game_info':'Інформація про гру','moves':'Список ходів','white_pieces':'Білі фігури','black_pieces':'Чорні фігури',
'game_status':'Стан гри','last_move':'Останній хід','move_input':'Введення ходу','engine_analysis':'Аналіз Stockfish','board':'Дошка','actions':'Дії',
'enter_move':'Введіть хід: e4, Nf3, Bc4, O-O. Однолітерні команди: u, y, l, w, b, c, s, t, o, e, v, p.',
'make_move':'Зробити хід','standard_position':'Стандартна позиція','empty_board':'Порожня дошка','position_editor':'Редактор позиції',
'load_fen':'Відкрити FEN','engine_toggle':'Stockfish увімкнути / вимкнути','play_engine':'Грати проти комп’ютера',
'takeback':'Повернути хід','draw':'Нічия','resign':'Здатися','settings':'Налаштування',
'white_to_move':'Хід білих','black_to_move':'Хід чорних','no_moves':'Ходів ще немає','no_last':'Останнього ходу немає',
'empty':'порожньо','selected':'Вибрано','cancelled':'Вибір скасовано','illegal':'Неможливий хід',
'engine_off':'Stockfish вимкнено','engine_missing':'Stockfish не знайдено. Виберіть stockfish.exe у меню Аналіз.',
'analysis_wait':'Аналіз для поточної позиції ще не виконано','depth':'Глибина','score':'оцінка','line':'Лінія',
'new_game':'Нова партія. Хід білих.','mate':'Мат','stalemate':'Пат. Нічия.','check':'Шах',
'file':'Файл','game':'Гра','board_menu':'Дошка','analysis':'Аналіз','help':'Довідка','exit':'Вихід','choose_engine':'Вибрати Stockfish.exe',
'language':'Мова','notation':'Нотація','sound':'Звуки','volume':'Гучність','tick':'Тикання годинника','save':'Зберегти','cancel':'Скасувати',
'ukrainian':'Українська','english':'English','short_san':'Коротка SAN','uk_literal':'Українська літеральна','en_literal':'English literal',
'none':'Вимкнено','my_turn':'Тільки мій хід','opponent_turn':'Тільки хід суперника','always':'Завжди',
'color':'Колір','white':'Білі','black':'Чорні','random':'Випадково','level':'Рівень','time_control':'Контроль часу','start_game':'Почати гру','no_clock':'Без часу','custom':'Власний',
'user_time':'Ваш час','opponent_time':'Час суперника','engine_thinking':'Stockfish думає','game_over':'Гру завершено','resigned':'Ви здалися','analyze_game':'Аналізувати поточну партію','minutes':'Хвилини','increment_seconds':'Додавання секунд',
},
'en': {
'app':'Accessible Chess — Stage 1','ready':'Ready. Standard position. White to move.',
'game_info':'Game information','moves':'Move list','white_pieces':'White pieces','black_pieces':'Black pieces','game_status':'Game status','last_move':'Last move','move_input':'Move input','engine_analysis':'Stockfish analysis','board':'Board','actions':'Actions',
'enter_move':'Enter a move: e4, Nf3, Bc4, O-O. One-letter commands: u, y, l, w, b, c, s, t, o, e, v, p.',
'make_move':'Make move','standard_position':'Standard position','empty_board':'Empty board','position_editor':'Position editor','load_fen':'Open FEN','engine_toggle':'Toggle Stockfish','play_engine':'Play computer','takeback':'Take back','draw':'Draw','resign':'Resign','settings':'Settings',
'white_to_move':'White to move','black_to_move':'Black to move','no_moves':'No moves yet','no_last':'No last move','empty':'empty','selected':'Selected','cancelled':'Selection cancelled','illegal':'Illegal move',
'engine_off':'Stockfish off','engine_missing':'Stockfish not found. Choose stockfish.exe from the Analysis menu.','analysis_wait':'Analysis for the current position has not been run yet','depth':'Depth','score':'score','line':'Line','new_game':'New game. White to move.','mate':'Checkmate','stalemate':'Stalemate. Draw.','check':'Check',
'file':'File','game':'Game','board_menu':'Board','analysis':'Analysis','help':'Help','exit':'Exit','choose_engine':'Choose Stockfish.exe','language':'Language','notation':'Notation','sound':'Sounds','volume':'Volume','tick':'Clock ticking','save':'Save','cancel':'Cancel','ukrainian':'Українська','english':'English','short_san':'Short SAN','uk_literal':'Ukrainian literal','en_literal':'English literal','none':'Off','my_turn':'My turn only','opponent_turn':'Opponent turn only','always':'Always',
'color':'Color','white':'White','black':'Black','random':'Random','level':'Level','time_control':'Time control','start_game':'Start game','no_clock':'No clock','custom':'Custom','user_time':'Your time','opponent_time':'Opponent time','engine_thinking':'Stockfish is thinking','game_over':'Game over','resigned':'You resigned','analyze_game':'Analyze current game','minutes':'Minutes','increment_seconds':'Increment seconds',
}}

def tr(lang, key): return STRINGS.get(lang, STRINGS['uk']).get(key, key)

# Child Chess Coaching Research — design input for Accessible Chess

Research date: 2026-08-16.

Purpose: convert observed teaching practice from established chess-education programs into product requirements for individual and group lessons, especially for ages 4–10 and complete beginners.

## Sources reviewed

Primary/official sources used for the synthesis:

- FIDE Chess in Education Commission: https://edu.fide.com/introduction
- FIDE Chess in Education history / early-years methodology: https://edu.fide.com/history
- FIDE/ECU certified strategy-games course: https://edu.fide.com/non-fide-courses/certified-courses
- Chess in Schools and Communities curriculum: https://www.chessinschools.co.uk/csc-curriculum-lessons
- CSC Lesson 1 PDF (Pawn, board, coordinates, Capture the Flag): https://www.chessinschools.co.uk/s/CSC-Curriculum-Lesson-1.pdf
- CSC Lesson 5 PDF (Queen): https://www.chessinschools.co.uk/s/CSC-Curriculum-Lesson-5.pdf
- CSC Lesson 6 PDF (Knight): https://www.chessinschools.co.uk/s/CSC-Curriculum-Lesson-6.pdf
- CSC Lesson 9 PDF (Stalemate and draw): https://www.chessinschools.co.uk/s/CSC-Curriculum-Lesson-9.pdf
- ChessKid Classroom Planner: https://www.chesskid.com/learn/articles/how-to-use-the-chesskid-classroom-planner
- ChessKid coaching guide: https://www.chesskid.com/learn/articles/chess-coaching-for-kids
- ChessKid kindergarten case: https://www.chesskid.com/learn/articles/teach-your-kindergarten-class-to-play-chess
- ChessKid Live Classroom: https://www.chesskid.com/learn/articles/how-to-use-the-chesskid-live-classroom-tool
- Chess.com Classroom help: https://support.chess.com/en/articles/8708915-how-do-i-use-classroom-on-chess-com
- Chess.com online teaching guide: https://www.chess.com/article/view/how-can-i-teach-using-chess-com
- Chess.com Classroom release/features: https://www.chess.com/news/view/chesscom-releases-new-classroom-feature
- Silver Knights Chess Academy online program: https://chessacademy.com/pages/online-chess-academy
- Silver Knights class format: https://chessacademy.com/products/heartland-charter-school-chess-classes
- Ukraine: Chess Leader packages: https://www.chessleader.com.ua/paketi-navchannya/
- Ukraine: Chess Leader trial/lesson description: https://www.chessleader.com.ua/chess-lesson/
- Ukraine: Chess Leader age programs: https://www.chessleader.com.ua/
- Ukraine: Lviv Chess Academy training information: https://chessclub.lviv.ua/zapys-na-probne-zaniattia/
- Ukraine: Lviv Chess Academy coaches: https://chessclub.lviv.ua/trener/

## What consistently appears across strong programs

### 1. Teach progressively, not by dumping all rules at once

FIDE EDU explicitly frames chess education as game-based learning. Its early-years history describes preschool “pre-chess” as play with board/pieces plus stories, songs, movement, drama and other age-appropriate activities. FIDE/ECU teacher training also explicitly uses mini-games, chess variants and logic/strategy games to keep children motivated.

CSC’s 30-week school curriculum assumes no chess knowledge and introduces the game progressively. Its first lesson does not ask children to play complete chess. It teaches the board, coordinates and pawn movement, then immediately uses a pawn-only mini-game called Capture the Flag. Later lessons introduce new pieces and use piece-versus-pawn mini-games before full-game complexity.

Product implication: Accessible Chess teaching mode must support partial positions and mini-games as first-class lesson objects rather than assuming that every beginner lesson is a full legal starting-position game.

### 2. A lesson repeatedly cycles: recall → show → ask → practise → play → recap

CSC lesson plans visibly repeat the same structure:

- learning objective;
- starter/recall;
- explanation on a demonstration board;
- questions to pupils and volunteers manipulating the demo board;
- activity/worksheet;
- mini-game or game in pairs;
- coach circulates/observes and corrects;
- plenary/recap;
- assessment and sometimes homework.

Chess Leader in Ukraine describes a normal lesson similarly: repeat the previous lesson, learn a new topic, reinforce through exercises, play games, discuss what was remembered, and receive homework. ChessKid’s planner is likewise a structured weekly guide with a topic, lesson/video, classroom materials and extra practice.

Product implication: the lesson UI should have explicit teaching phases and one-action transitions between prepared material rather than forcing the coach to reconstruct positions and tools manually.

### 3. Demonstration board and student participation are essential

CSC specifically requires a demonstration board visible to the group and individual sets for pairs. The teacher points to pieces/squares, asks children to name squares, asks volunteers to reproduce moves on the demo board, then asks everyone to reproduce the position on their own boards.

Chess.com’s coaching tools emphasize a shared analysis board, position setup, FEN/PGN loading, arrows/highlights and permission controls. ChessKid Live Classroom gives teachers saved positions/game history and lets them give students board control.

Product implication for a blind coach: keyboard-controlled pointer/highlight/arrow tools and student-pointer feedback are not extras; they are accessibility equivalents of the sighted coach’s ordinary pointing and board demonstration.

### 4. Ask the child to do and explain, not just listen

In CSC Lesson 1, children repeatedly identify squares, reproduce moves and play a mini-game. In the queen and knight lessons, they predict what will happen, compare piece strength, find moves and demonstrate answers. In Lesson 9, the coach asks children to distinguish check, checkmate and stalemate, then has them solve examples before playing.

For individual lessons this means guided discovery is preferable to a long monologue: ask for candidate moves, threats, square names, plans and reasons; let the student move pieces; then correct the specific misconception.

Product implication: the coach must be able to grant/revoke board control instantly, see what the student points at, and store quick questions/tasks attached to positions.

### 5. Play is not a reward after teaching; it is part of teaching

CSC repeatedly follows explanation with a constrained game that forces the new skill. Silver Knights’ 55-minute online classes advertise roughly 25 minutes of lesson content followed by play. ChessKid programs pair structured lessons with puzzles, workouts and games.

Product implication: lesson plans need `mini-game`, `exercise`, `pair-play` and `full-game` blocks, with easy transition from the demonstration position to student practice boards.

### 6. Match the child’s age and level

Ukraine’s Chess Leader separates programs into 4–6, 7–8, 9–12 and 13+ groups. For ages 4–6 it advertises 30-minute lessons, bright visual material, repeated practice and game-like instruction. Lviv Chess Academy groups learners by chess level, from beginners upward. Silver Knights separates learners into levels and uses small-group classes.

Product implication: lesson plans need both age band and skill band. A four-year-old beginner should not receive the same density, notation requirements or session length as a ten-year-old fourth-category player.

## Recommended teaching model by age

These are product-design recommendations synthesized from the sources, not rigid universal rules.

### Ages 4–5, complete beginner

Recommended core lesson duration: about 25–30 minutes. Longer meetings should be split by movement/game breaks rather than becoming one continuous chess lecture.

Typical flow:

1. 2–3 min — greeting, simple story/game and one previous concept.
2. 5 min — introduce one concrete object or movement: board colors, rook, pawn, king, etc.
3. 5 min — coach demonstrates and child points/copies.
4. 8–10 min — mini-game with very few pieces.
5. 3–5 min — success recap: “show me where the rook can go”, one tiny home challenge.

Do not require notation at the start. Coordinate learning can be optional and playful. Use large, clear pieces and optional coordinate overlays.

### Ages 6–7, beginner

Recommended lesson: 35–45 minutes depending on attention and prior experience.

Typical flow:

1. 3–5 min — warm-up/recall.
2. 8–10 min — one new concept with demonstration.
3. 5–8 min — student reproduces or solves guided examples.
4. 12–15 min — mini-game or short game focused on the concept.
5. 5 min — correction and recap/home task.

Begin notation gradually: files/ranks, square names, then move notation only after board orientation is secure.

### Ages 8–10, beginner to fourth-category range

45–60 minutes works well for a standard lesson. A representative commercial small-group format is 55 minutes, with about 25 minutes of lesson content followed by games.

Typical 60-minute flow:

1. 5–7 min — 2–4 warm-up puzzles or recall questions.
2. 5 min — review prior homework/game mistake.
3. 12–15 min — new topic, demonstration and questions.
4. 10 min — guided positions; student explains candidate moves/threats.
5. 15–18 min — themed game, pair game or practical position.
6. 5 min — recap, one measurable next step and homework.

For a fourth-category student, shift more time toward tactical recognition, blunder prevention, forcing moves, basic endings, opening principles and analysis of the student’s own games rather than piece-movement rules.

### 90-minute lesson

For children around 8–10+, treat 90 minutes as two learning blocks rather than one uninterrupted lecture:

- Block A: warm-up + new concept + guided examples.
- Short break/change of activity.
- Block B: practical games/positions + analysis + recap.

For preschool beginners, 90 minutes of continuous chess instruction is not an appropriate default product template.

## Individual lesson model

A strong one-to-one lesson should use the student’s actual decisions as data.

Recommended flow:

1. Quick check-in and one success from the previous week.
2. 2–5 diagnostic puzzles/positions.
3. Review one important fragment from the student’s game, not every move equally.
4. Ask the student what they saw, what they feared, and which candidate moves they considered.
5. Extract one teachable theme from the mistake or missed opportunity.
6. Show 2–4 related positions.
7. Let the student control the board and solve/practise.
8. Finish with a practical game or starting position that reinforces the theme.
9. Set small homework and a measurable target.

Accessible Chess feature consequences:

- student game/position library;
- planned positions and tags;
- hidden teacher notes;
- student board-control permission;
- coach pointer/arrow/highlight from keyboard;
- quick “student pointed at square X” feedback for the blind coach;
- one-key load of the next prepared position;
- lesson timeline and result notes.

## Group lesson model

The coach needs to manage attention and prevent the fastest children from monopolizing the class.

Recommended flow for 45–60 minutes:

1. Whole-group warm-up.
2. Whole-group demonstration of one idea.
3. Questions distributed across different children.
4. Short individual/pair challenge.
5. Pair play or simultaneous assigned positions.
6. Coach cycles through boards and intervenes selectively.
7. Return everyone to the common demonstration board.
8. Group recap and homework.

If the group has mixed ability, the software should support assigning different prepared positions to different students at the same time. ChessKid explicitly supports skill-based grouping and differentiated learning paths; this is a major product requirement rather than an edge case.

## Beginner curriculum sequence recommended for product templates

A practical sequence for complete beginners, consistent with progressive curricula:

1. Board orientation; dark/light squares; files/ranks; optional coordinates.
2. Pawn move and capture; pawn-only mini-game.
3. Rook movement; rook mini-games.
4. Bishop movement; bishop mini-games.
5. Queen movement; queen/pawn mini-games.
6. Knight movement and jumping; knight/pawn mini-games.
7. King movement; attacked squares.
8. Check, ways to escape check, checkmate.
9. Stalemate and simple draw ideas.
10. Starting position and complete-game procedure.
11. Piece values, safe/unsafe pieces, simple exchanges.
12. Opening principles: develop, center, king safety.
13. One-move tactics: hanging piece, fork, pin, skewer.
14. Basic mating patterns.
15. Basic king-and-pawn/endgame concepts.
16. Regular student-game review and tournament habits.

The exact curriculum can evolve, but the software should not hard-code a single course. Templates are data.

## Teaching interactions that the software must support

### Coach shows

- load a prepared FEN/PGN position;
- move pieces in legal mode or demonstration/setup mode;
- point to a square without moving a piece;
- highlight squares;
- draw arrows;
- hide/show coordinates;
- hide/show notation or engine information for students;
- reveal an answer only when ready.

### Coach asks

- “Where can this piece move?”
- “Which piece is attacked?”
- “What is the threat?”
- “Find all checks/captures/threats.”
- “Point to the square.”
- “Make the move.”
- “Explain why.”

### Student responds

- speaks over audio;
- clicks/points at a square;
- draws an annotation if granted permission;
- moves a piece if granted board control;
- submits a move/answer;
- plays an assigned position/game.

### Blind coach receives

- participant name and speaking state;
- square/piece the student pointed to;
- student move in accessible notation;
- concise board changes;
- current student board status on demand;
- participant/microphone/permission state;
- ordered pointer/event history without visual dependence.

## Technical classroom precedents worth matching

Chess.com Classroom already demonstrates several coach-oriented patterns: room creation/joining, individual/group lessons, voice/video, shared boards, loading games/PGNs/FENs, board-control permissions, visibility controls for notation/evaluation/engine lines and student permissions. ChessKid Live Classroom similarly provides real-time audio/video, saved games/positions and the ability to give students board/audio control.

Accessible Chess should match the useful interaction model while differentiating on keyboard-first blind-coach control, accessible event feedback, per-student prepared position deployment and screen-reader-first moderation.

## Product acceptance scenarios derived from pedagogy

### Scenario A — blind coach teaches a 5-year-old rook movement

- coach loads a rook mini-game template;
- coordinates are `every_square` for the child;
- coach types `d4` in pointer input and the child sees the pointer on d4;
- coach types successive target squares without clearing manually;
- child clicks a square and coach hears/reads `Оля: d 8`;
- coach grants move control;
- child moves rook; accessible coach history reports move;
- after mini-game, coach deploys next prepared position with one command.

### Scenario B — 10-student group

- teacher creates class and students join by code/name;
- teacher hears/reads join list and can rename/identify participants;
- teacher deploys one demo position to all;
- teacher assigns five pairings with colors and 10+0 or another control;
- five independent games start;
- teacher cycles through boards by keyboard;
- teacher mutes all students and hard-locks microphones during explanation, then restores permission;
- teacher sends different prepared positions to selected students;
- everyone returns to common demo board for recap.

### Scenario C — individual fourth-category lesson

- lesson plan contains three FENs from the student’s recurring tactical weakness;
- coach loads position 1, asks student to verbalize candidates, grants board control;
- coach creates keyboard arrow/highlight without mouse;
- next prepared position loads instantly;
- final block starts a practical game from a planned FEN;
- lesson summary records completed positions, exercise results and game reference.

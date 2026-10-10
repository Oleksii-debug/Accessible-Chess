"""Exact original bilingual Réti 1921 historic chess study used offline.

Verified project-authored annotations and public-domain original composition.
No new game rules, database, chess engine or external copyrighted study book.
"""
from __future__ import annotations

import hashlib

_SOURCE_PGN = "[Event \"Richard Reti - 1921 Historical Endgame Study\"]\n[Site \"Historical composed study, source bibliography: ARVES\"]\n[Date \"1921.??.??\"]\n[White \"Richard Reti (composer, 1889-1929)\"]\n[Black \"Study's imagined defender\"]\n[Result \"1/2-1/2\"]\n[SetUp \"1\"]\n[FEN \"7K/8/k1P5/7p/8/8/8/8 w - - 0 1\"]\n[Annotator \"Accessible Chess original bilingual training commentary\"]\n[Source \"https://www.arves.org/arves/index.php/en/endgamestudies/studies-by-composer/1550-reti-s-study-is-100-years-old\"]\n\n{EN: White to move and draw. Original historic composition by Richard Reti, 1921. Analyze both goals of the king rather than following the shortest path to only one pawn. The following comments are newly authored, not copied from a modern annotated edition.\nUK: Білі починають і досягають нічиєї. Оригінальна історична композиція Ріхарда Реті, 1921. Потрібно поєднати дві цілі короля, а не прямувати тільки до одного пішака. Ці коментарі написано спеціально для Accessible Chess.}\n1. Kg7! {EN: A dual-purpose king move; consider the threat to each pawn. UK: Хід королем створює дві одночасні загрози.}\nh4 2. Kf6! {EN: Threatening to assist c6 while approaching h-file defence. UK: Король одночасно підтримує пішака c6 та наближається до протидії на лінії h.}\nKb6 3. Ke5! {EN: Calculate the defender's alternative pawn advance before declaring a draw. UK: Перевірте відповідь із просуванням чорного пішака, перш ніж оцінювати результат.}\nh3 4. Kd6 h2 5. c7 Kb7 6. Kd7\n{EN: Model study endpoint; the composition's objective is a draw, not a competitive played game result.\nUK: Кінцева позиція модельного варіанта; ціль етюду — нічия, а не результат зіграної турнірної партії.}\n1/2-1/2\n"
SOURCE_SHA256 = "f0bb51066fde9d103406773666100977d6e2d2fc48ff71887dacbbb3ad0e8c83"
SOURCE_ID = "historical_reti_1921_original_bilingual_study_pgn"


def original_reti_source_bytes() -> bytes:
    content = _SOURCE_PGN.encode("utf-8")
    if hashlib.sha256(content).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("historic Reti bilingual PGN source checksum changed")
    return content

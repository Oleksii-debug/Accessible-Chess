import tempfile
from pathlib import Path
from .chesscore import Board,parse_sq,sq_name
from .storage import Library
from . import pgn

def run():
    b=Board(); assert len(b.legal_moves())==20
    for m in ['e4','e5','Nf3','Nc6','Bb5','a6','Ba4','Nf6','O-O']:
        b.push_text(m)
    assert b.turn=='b'; Board(b.fen())
    b=Board(); b.push_text('e4'); b.push_text('d5'); assert b.push_text('exd5')=='exd5'
    b=Board('4k3/P7/8/8/8/8/8/4K3 w - - 0 1'); assert b.push_text('a8=Q+')=='a8=Q+'
    b=Board(); assert [sq_name(x) for x in b.attacks_from(parse_sq('e2'))]==['d3','f3']
    with tempfile.TemporaryDirectory() as td:
        db=Path(td)/'data'/'library.acsdb'; lib=Library(db); assert db.exists(); lib.db.close()
        src=Path(td)/'x.pgn'; src.write_text('[Result "1-0"]\n\n1. e4 e5 1-0',encoding='utf-8')
        tags,board,sans=pgn.load_pgn(src); out=Path(td)/'out.pgn'; pgn.save_pgn(out,tags,Board.START,sans); assert '[Result "1-0"]' in out.read_text(encoding='utf-8')
    print('SELFTEST PASS')
if __name__=='__main__': run()

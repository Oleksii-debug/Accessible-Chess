from dataclasses import dataclass
import re, copy
from .squares import FILES, parse_square, square_name

PIECE_UA={'P':'білий пішак','N':'білий кінь','B':'білий слон','R':'біла тура','Q':'білий ферзь','K':'білий король',
          'p':'чорний пішак','n':'чорний кінь','b':'чорний слон','r':'чорна тура','q':'чорний ферзь','k':'чорний король'}

def sq_name(s): return square_name(s)
def parse_sq(t):
    try: return parse_square(t)
    except ValueError as exc: raise ValueError('Неправильне поле: '+repr(t)) from exc

def color_of(p): return 'w' if p and p.isupper() else ('b' if p else None)

def _require_side(value, *, allow_none=False):
    if allow_none and value is None:
        return None
    if type(value) is not str or value not in ('w','b'):
        raise ValueError("Сторона має бути 'w' або 'b'")
    return value

def _require_square_index(value):
    if type(value) is not int or not 0 <= value < 64:
        raise ValueError('Поле має бути цілим індексом від 0 до 63')
    return value

@dataclass(frozen=True)
class Move:
    frm:int; to:int; promotion:str|None=None; en_passant:bool=False; castle:bool=False

    def __post_init__(self):
        _require_square_index(self.frm)
        _require_square_index(self.to)
        if self.promotion is not None and (
            type(self.promotion) is not str
            or len(self.promotion) != 1
            or self.promotion not in 'QRBN'
        ):
            raise ValueError('Перетворення має бути Q, R, B, N або None')
        if type(self.en_passant) is not bool:
            raise ValueError('en_passant має бути логічним значенням')
        if type(self.castle) is not bool:
            raise ValueError('castle має бути логічним значенням')

class Board:
    START='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    def __init__(self, fen=None):
        self.board=[None]*64; self.turn='w'; self.castling='KQkq'; self.ep=None; self.halfmove=0; self.fullmove=1
        self.undo_stack=[]; self.redo_stack=[]; self.last_move=None
        self.set_fen(self.START if fen is None else fen, clear_history=True)
    def clone(self):
        b=Board(self.fen()); b.last_move=self.last_move; return b
    def set_fen(self, fen, clear_history=True):
        """Validate a FEN completely before committing it to canonical state.

        Editor/import input is untrusted.  A rejected FEN must not partially
        replace board, side-to-move, counters or history because callers may
        continue using the same Board instance after reporting the error.
        """
        if type(fen) is not str:
            raise ValueError('FEN має бути текстом')
        if type(clear_history) is not bool:
            raise ValueError('clear_history має бути логічним значенням')
        parts=fen.strip().split()
        if len(parts)<4 or len(parts)>6: raise ValueError('FEN має містити від 4 до 6 полів')
        rows=parts[0].split('/')
        if len(rows)!=8: raise ValueError('FEN: потрібно 8 горизонталей')
        bd=[None]*64
        for rr,row in enumerate(rows):
            rank=7-rr; file=0
            for ch in row:
                if ch in '12345678':
                    file+=int(ch)
                    if file>8: raise ValueError('FEN: забагато полів у горизонталі')
                elif ch.isdigit():
                    raise ValueError('FEN: неправильна кількість порожніх полів')
                elif ch in 'prnbqkPRNBQK':
                    if file>=8: raise ValueError('FEN: зайва фігура')
                    bd[rank*8+file]=ch; file+=1
                else: raise ValueError('FEN: невідомий символ '+ch)
            if file!=8: raise ValueError('FEN: горизонталь не має 8 полів')
        if bd.count('K')!=1 or bd.count('k')!=1: raise ValueError('FEN: має бути по одному королю')
        turn=parts[1]
        if turn not in ('w','b'): raise ValueError('FEN: хід має бути w або b')
        castling='' if parts[2]=='-' else parts[2]
        if any(ch not in 'KQkq' for ch in castling) or len(set(castling))!=len(castling): raise ValueError('FEN: неправильні права рокіровки')
        ep=None if parts[3]=='-' else parse_sq(parts[3])
        if any(not text.isascii() or not text.isdecimal() for text in parts[4:6]):
            raise ValueError('FEN: лічильники мають бути невід’ємними десятковими числами')
        try:
            halfmove=int(parts[4]) if len(parts)>4 else 0
            fullmove=int(parts[5]) if len(parts)>5 else 1
        except ValueError:
            raise ValueError('FEN: лічильники мають бути невід’ємними десятковими числами') from None
        if halfmove<0: raise ValueError('FEN: halfmove не може бути від’ємним')
        if fullmove<1: raise ValueError('FEN: fullmove має бути не менше 1')
        for s,p in enumerate(bd):
            if p and p.upper()=='P' and s//8 in (0,7): raise ValueError('FEN: пішак не може стояти на першій або восьмій горизонталі')
        wk=bd.index('K'); bk=bd.index('k')
        if max(abs(wk%8-bk%8),abs(wk//8-bk//8))<=1: raise ValueError('FEN: королі не можуть стояти поруч')
        required={'K':(4,'K',7,'R'),'Q':(4,'K',0,'R'),'k':(60,'k',63,'r'),'q':(60,'k',56,'r')}
        for right,(ks,kp,rs,rp) in required.items():
            if right in castling and (bd[ks]!=kp or bd[rs]!=rp): raise ValueError('FEN: права рокіровки не відповідають положенню короля/тури')
        if ep is not None:
            er=ep//8
            if er not in (2,5): raise ValueError('FEN: неправильне поле en passant')
            if (turn=='w' and er!=5) or (turn=='b' and er!=2): raise ValueError('FEN: en passant не відповідає стороні ходу')
            if bd[ep] is not None: raise ValueError('FEN: поле en passant має бути порожнім')
            moved_sq=ep-8 if turn=='w' else ep+8
            origin_sq=ep+8 if turn=='w' else ep-8
            moved_pawn='p' if turn=='w' else 'P'
            if bd[moved_sq]!=moved_pawn or bd[origin_sq] is not None:
                raise ValueError('FEN: en passant не відповідає попередньому подвійому ходу пішака')

        # Commit only after every syntactic and structural check has passed.
        self.board=bd; self.turn=turn; self.castling=castling; self.ep=ep
        self.halfmove=halfmove; self.fullmove=fullmove; self.last_move=None
        if clear_history: self.undo_stack=[]; self.redo_stack=[]
    def fen(self):
        rows=[]
        for rank in range(7,-1,-1):
            row=''; empty=0
            for file in range(8):
                p=self.board[rank*8+file]
                if not p: empty+=1
                else:
                    if empty: row+=str(empty); empty=0
                    row+=p
            if empty: row+=str(empty)
            rows.append(row)
        return '/'.join(rows)+f" {self.turn} {self.castling or '-'} {sq_name(self.ep) if self.ep is not None else '-'} {self.halfmove} {self.fullmove}"
    def king_square(self,c):
        c=_require_side(c)
        return self.board.index('K' if c=='w' else 'k')
    def attacked(self,sq,by):
        sq=_require_square_index(sq); by=_require_side(by)
        f=sq%8; r=sq//8
        dr=-1 if by=='w' else 1
        pawn='P' if by=='w' else 'p'
        for df in (-1,1):
            of=f+df; orr=r+dr
            if 0<=of<8 and 0<=orr<8 and self.board[orr*8+of]==pawn: return True
        knight='N' if by=='w' else 'n'
        for df,dr2 in ((1,2),(2,1),(2,-1),(1,-2),(-1,-2),(-2,-1),(-2,1),(-1,2)):
            of=f+df; orr=r+dr2
            if 0<=of<8 and 0<=orr<8 and self.board[orr*8+of]==knight: return True
        king='K' if by=='w' else 'k'
        for df in (-1,0,1):
            for dr2 in (-1,0,1):
                if not df and not dr2: continue
                of=f+df; orr=r+dr2
                if 0<=of<8 and 0<=orr<8 and self.board[orr*8+of]==king: return True
        for dirs,pieces in [(((1,0),(-1,0),(0,1),(0,-1)), ('R','Q') if by=='w' else ('r','q')),
                            (((1,1),(1,-1),(-1,1),(-1,-1)), ('B','Q') if by=='w' else ('b','q'))]:
            for df,dr2 in dirs:
                of=f+df; orr=r+dr2
                while 0<=of<8 and 0<=orr<8:
                    p=self.board[orr*8+of]
                    if p:
                        if p in pieces: return True
                        break
                    of+=df; orr+=dr2
        return False
    def in_check(self,c=None):
        c=self.turn if c is None else _require_side(c)
        return self.attacked(self.king_square(c), 'b' if c=='w' else 'w')
    def pseudo_moves(self,c=None):
        c=self.turn if c is None else _require_side(c)
        for s,p in enumerate(self.board):
            if not p or color_of(p)!=c: continue
            typ=p.upper(); f=s%8; r=s//8
            if typ=='P':
                step=1 if c=='w' else -1; start=1 if c=='w' else 6; promo=7 if c=='w' else 0
                nr=r+step
                if 0<=nr<8:
                    to=nr*8+f
                    if not self.board[to]:
                        if nr==promo:
                            for q in 'QRBN': yield Move(s,to,q)
                        else: yield Move(s,to)
                        if r==start:
                            to2=(r+2*step)*8+f
                            if not self.board[to2]: yield Move(s,to2)
                    for df in (-1,1):
                        nf=f+df
                        if 0<=nf<8:
                            cap=nr*8+nf
                            if self.board[cap] and color_of(self.board[cap])!=c:
                                if nr==promo:
                                    for q in 'QRBN': yield Move(s,cap,q)
                                else: yield Move(s,cap)
                            elif self.ep==cap: yield Move(s,cap,None,True)
            elif typ=='N':
                for df,dr in ((1,2),(2,1),(2,-1),(1,-2),(-1,-2),(-2,-1),(-2,1),(-1,2)):
                    nf=f+df; nr=r+dr
                    if 0<=nf<8 and 0<=nr<8:
                        to=nr*8+nf
                        if not self.board[to] or color_of(self.board[to])!=c: yield Move(s,to)
            elif typ in ('B','R','Q'):
                dirs=[]
                if typ in ('B','Q'): dirs += [(1,1),(1,-1),(-1,1),(-1,-1)]
                if typ in ('R','Q'): dirs += [(1,0),(-1,0),(0,1),(0,-1)]
                for df,dr in dirs:
                    nf=f+df; nr=r+dr
                    while 0<=nf<8 and 0<=nr<8:
                        to=nr*8+nf; q=self.board[to]
                        if not q: yield Move(s,to)
                        else:
                            if color_of(q)!=c: yield Move(s,to)
                            break
                        nf+=df; nr+=dr
            elif typ=='K':
                for df in (-1,0,1):
                    for dr in (-1,0,1):
                        if not df and not dr: continue
                        nf=f+df; nr=r+dr
                        if 0<=nf<8 and 0<=nr<8:
                            to=nr*8+nf
                            if not self.board[to] or color_of(self.board[to])!=c: yield Move(s,to)
                enemy='b' if c=='w' else 'w'
                if c=='w' and s==4 and not self.in_check('w'):
                    if 'K' in self.castling and not self.board[5] and not self.board[6] and self.board[7]=='R' and not self.attacked(5,enemy) and not self.attacked(6,enemy): yield Move(4,6,None,False,True)
                    if 'Q' in self.castling and not self.board[3] and not self.board[2] and not self.board[1] and self.board[0]=='R' and not self.attacked(3,enemy) and not self.attacked(2,enemy): yield Move(4,2,None,False,True)
                if c=='b' and s==60 and not self.in_check('b'):
                    if 'k' in self.castling and not self.board[61] and not self.board[62] and self.board[63]=='r' and not self.attacked(61,enemy) and not self.attacked(62,enemy): yield Move(60,62,None,False,True)
                    if 'q' in self.castling and not self.board[59] and not self.board[58] and not self.board[57] and self.board[56]=='r' and not self.attacked(59,enemy) and not self.attacked(58,enemy): yield Move(60,58,None,False,True)
    def legal_moves(self):
        c=self.turn
        out=[]
        for m in self.pseudo_moves(c):
            b=self.clone(); b._apply(m)
            if not b.in_check(c): out.append(m)
        return out
    def _apply(self,m):
        if type(m) is not Move:
            raise ValueError('Хід має бути canonical Move')
        p=self.board[m.frm]; captured=self.board[m.to]
        if m.en_passant:
            cs=m.to-8 if p=='P' else m.to+8; captured=self.board[cs]; self.board[cs]=None
        self.board[m.to]=p; self.board[m.frm]=None
        if m.promotion: self.board[m.to]=m.promotion if p.isupper() else m.promotion.lower()
        if m.castle:
            if m.to==6: self.board[5]=self.board[7]; self.board[7]=None
            elif m.to==2: self.board[3]=self.board[0]; self.board[0]=None
            elif m.to==62: self.board[61]=self.board[63]; self.board[63]=None
            elif m.to==58: self.board[59]=self.board[56]; self.board[56]=None
        rights=self.castling
        if p=='K': rights=rights.replace('K','').replace('Q','')
        if p=='k': rights=rights.replace('k','').replace('q','')
        for sq,ch in ((0,'Q'),(7,'K'),(56,'q'),(63,'k')):
            if m.frm==sq or (m.to==sq and captured): rights=rights.replace(ch,'')
        self.castling=rights
        self.ep=None
        if p.upper()=='P' and abs(m.to-m.frm)==16: self.ep=(m.to+m.frm)//2
        self.halfmove=0 if p.upper()=='P' or captured else self.halfmove+1
        if self.turn=='b': self.fullmove+=1
        self.turn='b' if self.turn=='w' else 'w'; self.last_move=m
    def san(self,m):
        if type(m) is not Move:
            raise ValueError('Хід має бути canonical Move')
        legal=self.legal_moves()
        if m not in legal: raise ValueError('Нелегальний хід')
        p=self.board[m.frm]; typ=p.upper()
        if m.castle: s='O-O' if m.to>m.frm else 'O-O-O'
        else:
            capture=bool(self.board[m.to]) or m.en_passant
            prefix='' if typ=='P' else typ
            if typ!='P':
                same=[x for x in legal if x!=m and self.board[x.frm] and self.board[x.frm].upper()==typ and x.to==m.to]
                if same:
                    if all(x.frm%8 != m.frm%8 for x in same): prefix+=FILES[m.frm%8]
                    elif all(x.frm//8 != m.frm//8 for x in same): prefix+=str(m.frm//8+1)
                    else: prefix+=sq_name(m.frm)
            elif capture: prefix=FILES[m.frm%8]
            s=prefix+('x' if capture else '')+sq_name(m.to)
            if m.promotion: s+='='+m.promotion.upper()
        b=self.clone(); b._apply(m)
        if b.in_check(b.turn): s += '#' if not b.legal_moves() else '+'
        return s
    @staticmethod
    def norm_san(s):
        if type(s) is not str:
            raise ValueError('Хід має бути текстом')
        return s.strip().replace('0','O').replace('–','-').replace('—','-').replace(' ','').rstrip('!?')
    def parse_move(self,text):
        if type(text) is not str:
            raise ValueError('Хід має бути текстом')
        t=self.norm_san(text)
        if re.fullmatch(r'[a-h][1-8][a-h][1-8][qrbnQRBN]?', t):
            frm=parse_sq(t[:2]); to=parse_sq(t[2:4]); pr=t[4].upper() if len(t)>4 else None
            for m in self.legal_moves():
                if (m.frm,m.to,m.promotion)==(frm,to,pr): return m
            raise ValueError('Нелегальний координатний хід')
        candidates=[]
        for m in self.legal_moves():
            s=self.norm_san(self.san(m)).rstrip('+#')
            target=t.rstrip('+#')
            if s==target: candidates.append(m)
        if len(candidates)==1: return candidates[0]
        if not candidates: raise ValueError('Не вдалося розпізнати або хід нелегальний: '+text)
        raise ValueError('Хід неоднозначний: '+text)
    def push(self,m):
        if type(m) is not Move:
            raise ValueError('Хід має бути canonical Move')
        before=self.fen(); san=self.san(m)
        self.undo_stack.append((before,san)); self.redo_stack.clear(); self._apply(m)
        return san
    def push_text(self,t): return self.push(self.parse_move(t))
    def undo(self):
        if not self.undo_stack: return None
        current=self.fen(); before,san=self.undo_stack.pop(); self.redo_stack.append((current,san)); self.set_fen(before,clear_history=False); return san
    def redo(self):
        if not self.redo_stack: return None
        current=self.fen(); target,san=self.redo_stack.pop(); self.undo_stack.append((current,san)); self.set_fen(target,clear_history=False); return san
    def square_description(self,sq):
        sq=_require_square_index(sq)
        p=self.board[sq]; return f"{sq_name(sq)[0]} {sq_name(sq)[1]}, {PIECE_UA[p] if p else 'порожньо'}"
    def pieces_description(self,color=None):
        color=_require_side(color, allow_none=True)
        arr=[]
        for s,p in enumerate(self.board):
            if p and (color is None or color_of(p)==color): arr.append(f"{PIECE_UA[p]} {sq_name(s)[0]} {sq_name(s)[1]}")
        return '; '.join(arr) if arr else 'фігур немає'
    def attacks_from(self,s):
        """Return squares attacked/defended by the piece on s.

        This is deliberately NOT move generation. Pawns attack diagonally even
        when the target is empty, sliders defend their first occupied blocker,
        and castling/forward pawn pushes are never attacks.
        """
        s=_require_square_index(s)
        p=self.board[s]
        if not p: return []
        c=color_of(p); typ=p.upper(); f=s%8; r=s//8; out=[]
        if typ=='P':
            dr=1 if c=='w' else -1
            for df in (-1,1):
                nf=f+df; nr=r+dr
                if 0<=nf<8 and 0<=nr<8: out.append(nr*8+nf)
        elif typ=='N':
            for df,dr in ((1,2),(2,1),(2,-1),(1,-2),(-1,-2),(-2,-1),(-2,1),(-1,2)):
                nf=f+df; nr=r+dr
                if 0<=nf<8 and 0<=nr<8: out.append(nr*8+nf)
        elif typ in ('B','R','Q'):
            dirs=[]
            if typ in ('B','Q'): dirs += [(1,1),(1,-1),(-1,1),(-1,-1)]
            if typ in ('R','Q'): dirs += [(1,0),(-1,0),(0,1),(0,-1)]
            for df,dr in dirs:
                nf=f+df; nr=r+dr
                while 0<=nf<8 and 0<=nr<8:
                    to=nr*8+nf; out.append(to)
                    if self.board[to]: break
                    nf+=df; nr+=dr
        elif typ=='K':
            for df in (-1,0,1):
                for dr in (-1,0,1):
                    if not df and not dr: continue
                    nf=f+df; nr=r+dr
                    if 0<=nf<8 and 0<=nr<8: out.append(nr*8+nf)
        return sorted(set(out))
    def attackers_of(self,s):
        s=_require_square_index(s)
        return [i for i,p in enumerate(self.board) if p and s in self.attacks_from(i)]

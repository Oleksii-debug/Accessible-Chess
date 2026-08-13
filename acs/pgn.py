import re
from .chesscore import Board

HEADER_RE=re.compile(r'^\[(\w+)\s+"(.*)"\]$')
RESULTS=('1-0','0-1','1/2-1/2','*')
_INTERNAL_PREFIX='__ACS_'

def _first_game_text(txt):
    """Return the first PGN game only, never mix later headers with first moves."""
    lines=txt.splitlines(); out=[]; seen_moves=False
    for line in lines:
        st=line.strip()
        if st.startswith('[') and seen_moves: break
        if st and not st.startswith('['): seen_moves=True
        out.append(line)
    return '\n'.join(out)

def strip_variations(text):
    out=[]; depth=0; in_comment=False; i=0
    while i<len(text):
        c=text[i]
        if in_comment:
            if c=='}': in_comment=False
        elif c=='{': in_comment=True
        elif c==';':
            while i<len(text) and text[i]!='\n': i+=1
            out.append(' ')
        elif c=='(': depth+=1
        elif c==')': depth=max(0,depth-1)
        elif depth==0: out.append(c)
        i+=1
    return ''.join(out)

def load_pgn(path):
    with open(path,'r',encoding='utf-8-sig',errors='replace') as f: raw=f.read()
    txt=_first_game_text(raw); tags={}; movelines=[]; in_headers=True
    for line in txt.splitlines():
        st=line.strip(); m=HEADER_RE.match(st)
        if in_headers and m: tags[m.group(1)]=m.group(2)
        else:
            if st: in_headers=False
            if not m: movelines.append(line)
    movetext='\n'.join(movelines)
    if re.search(r'\{|;|\(|\)|\$\d+',movetext): tags[_INTERNAL_PREFIX+'RICH_PGN']='1'
    board=Board(tags.get('FEN') if tags.get('SetUp')=='1' and tags.get('FEN') else None)
    sans=[]; clean=strip_variations(movetext); clean=re.sub(r'\$\d+',' ',clean)
    toks=clean.replace('\n',' ').split(); found_result=None
    for tok in toks:
        if re.fullmatch(r'\d+\.(\.\.)?',tok) or re.match(r'^\d+\.+$',tok): continue
        tok=re.sub(r'^\d+\.(\.\.)?','',tok)
        if not tok: continue
        if tok in RESULTS: found_result=tok; break
        try: sans.append(board.push_text(tok))
        except Exception as e: raise ValueError(f'PGN: помилка на ході {tok}: {e}')
    if found_result is not None:
        header_result=tags.get('Result')
        if header_result and header_result!=found_result: raise ValueError(f'PGN: Result у заголовку ({header_result}) не збігається з movetext ({found_result})')
        tags['Result']=found_result
    tags.setdefault('Result','*'); return tags, board, sans

def save_pgn(path,tags,start_fen,sans,result=None):
    tags=dict(tags or {})
    if tags.get(_INTERNAL_PREFIX+'RICH_PGN')=='1': raise ValueError('Цей PGN містить коментарі, NAG або варіанти, які ця версія ще не може безпечно перезаписати. Збереження заблоковано, щоб не втратити дані.')
    tags={k:v for k,v in tags.items() if not k.startswith(_INTERNAL_PREFIX)}
    result=result if result is not None else tags.get('Result','*')
    if result not in RESULTS: raise ValueError('PGN: неправильний результат '+str(result))
    tags.setdefault('Event','Accessible Chess Studio'); tags.setdefault('Site','?'); tags.setdefault('Date','????.??.??'); tags.setdefault('Round','?'); tags.setdefault('White','White'); tags.setdefault('Black','Black'); tags['Result']=result
    start=Board(start_fen or Board.START)
    if start_fen and start_fen!=Board.START: tags['SetUp']='1'; tags['FEN']=start_fen
    else: tags.pop('SetUp',None); tags.pop('FEN',None)
    lines=[f'[{k} "{v}"]' for k,v in tags.items()]+['']; moves=[]; side=start.turn; move_no=start.fullmove
    for san in sans:
        if side=='w': moves.append(f'{move_no}. {san}'); side='b'
        else:
            if moves and moves[-1].startswith(f'{move_no}. '): moves[-1]+=' '+san
            else: moves.append(f'{move_no}... {san}')
            side='w'; move_no+=1
    body=(' '.join(moves)+' '+result).strip()
    while len(body)>90:
        cut=body.rfind(' ',0,90)
        if cut<20: cut=90
        lines.append(body[:cut]); body=body[cut:].lstrip()
    lines.append(body)
    with open(path,'w',encoding='utf-8',newline='\n') as f: f.write('\n'.join(lines))

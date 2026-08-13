import re
from .chesscore import parse_sq

def parse_position_text(text, turn='w'):
    """Parse W:/B: piece-coordinate text into a FEN. Requires one king each."""
    text = text.replace('\n', ' ').strip()
    m = re.search(r'(?i)\bW\s*:\s*(.*?)(?=\bB\s*:|$)', text)
    n = re.search(r'(?i)\bB\s*:\s*(.*)$', text)
    if not m or not n: raise ValueError('Потрібні секції W: і B:')
    board=[None]*64
    def fill(chunk, white):
        toks = chunk.replace(',', ' ').split()
        if len(toks)%2: raise ValueError('Кожна фігура повинна мати поле, наприклад N f3')
        for i in range(0,len(toks),2):
            pc=toks[i].upper(); sq=toks[i+1].lower()
            if pc not in 'KQRBNP': raise ValueError('Невідома фігура: '+toks[i])
            s=parse_sq(sq)
            if board[s]: raise ValueError('Поле '+sq+' вказане двічі')
            board[s]=pc if white else pc.lower()
    fill(m.group(1),True); fill(n.group(1),False)
    if board.count('K')!=1 or board.count('k')!=1: raise ValueError('Потрібно рівно по одному королю')
    rows=[]
    for rank in range(7,-1,-1):
        row=''; empty=0
        for file in range(8):
            p=board[rank*8+file]
            if not p: empty+=1
            else:
                if empty: row+=str(empty); empty=0
                row+=p
        if empty: row+=str(empty)
        rows.append(row)
    return '/'.join(rows)+f' {turn} - - 0 1'

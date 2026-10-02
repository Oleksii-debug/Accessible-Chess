import sqlite3, datetime
from pathlib import Path
class Library:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self.db=sqlite3.connect(self.path)
        self.db.execute('CREATE TABLE IF NOT EXISTS games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)'); self.db.commit()
    def add(self,title,pgn): self.db.execute('INSERT INTO games(title,pgn,created_at) VALUES(?,?,?)',(title,pgn,datetime.datetime.now().isoformat(timespec='seconds'))); self.db.commit()
    def list(self): return self.db.execute('SELECT id,title,created_at FROM games ORDER BY id DESC LIMIT 500').fetchall()
    def get(self,id): return self.db.execute('SELECT pgn FROM games WHERE id=?',(id,)).fetchone()[0]

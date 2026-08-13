import subprocess, threading, queue, time, re

class UCIEngine:
    def __init__(self,path):
        self.path=path; self.proc=None; self.q=queue.Queue(); self.reader=None
        self._lock=threading.Lock()
    def start(self):
        if self.proc and self.proc.poll() is None: return
        self.proc=subprocess.Popen([self.path],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def read():
            for line in self.proc.stdout: self.q.put(line.strip())
        self.reader=threading.Thread(target=read,daemon=True); self.reader.start(); self.send('uci'); self._wait('uciok',5); self.send('isready'); self._wait('readyok',5)
    def send(self,s):
        if not self.proc or not self.proc.stdin: raise RuntimeError('Stockfish не запущено')
        self.proc.stdin.write(s+'\n'); self.proc.stdin.flush()
    def _wait(self,token,timeout):
        end=time.time()+timeout
        while time.time()<end:
            try:
                line=self.q.get(timeout=.2)
                if token in line: return line
            except queue.Empty: pass
        raise RuntimeError('Stockfish не відповів: '+token)
    def analyze(self,fen,multipv=3,depth=16):
        if not self._lock.acquire(blocking=False): raise RuntimeError('Аналіз уже виконується')
        try:
            self.start()
            while not self.q.empty():
                try:self.q.get_nowait()
                except queue.Empty:break
            self.send(f'setoption name MultiPV value {multipv}'); self.send('isready'); self._wait('readyok',5)
            self.send('position fen '+fen); self.send(f'go depth {depth}')
            best={}; end=time.time()+60; got_best=False
            while time.time()<end:
                try: line=self.q.get(timeout=.3)
                except queue.Empty: continue
                if line.startswith('bestmove'): got_best=True; break
                if line.startswith('info ') and ' pv ' in line:
                    mp=int(re.search(r' multipv (\d+)',line).group(1)) if ' multipv ' in line else 1
                    dep=int(re.search(r' depth (\d+)',line).group(1)) if ' depth ' in line else 0
                    sm=re.search(r' score (cp|mate) (-?\d+)',line); score=(sm.group(1),int(sm.group(2))) if sm else ('cp',0)
                    pv=line.split(' pv ',1)[1].split(); best[mp]=(dep,score,pv)
            if not got_best:
                try:self.send('stop')
                except Exception:pass
                raise RuntimeError('Stockfish: перевищено час очікування аналізу')
            return [best[k] for k in sorted(best)[:multipv]]
        finally:
            self._lock.release()

    def best_move(self,fen,skill_level=10,movetime_ms=500):
        if not self._lock.acquire(blocking=False): raise RuntimeError('Аналіз уже виконується')
        try:
            self.start()
            while not self.q.empty():
                try:self.q.get_nowait()
                except queue.Empty:break
            skill=max(0,min(20,int(skill_level)))
            self.send(f'setoption name Skill Level value {skill}'); self.send('isready'); self._wait('readyok',5)
            self.send('position fen '+fen); self.send(f'go movetime {max(50,int(movetime_ms))}')
            end=time.time()+max(5,movetime_ms/1000+5)
            while time.time()<end:
                try:line=self.q.get(timeout=.2)
                except queue.Empty:continue
                if line.startswith('bestmove'):
                    parts=line.split(); return parts[1] if len(parts)>1 and parts[1]!='(none)' else None
            try:self.send('stop')
            except Exception:pass
            raise RuntimeError('Stockfish: не отримано bestmove')
        finally:
            self._lock.release()

    def close(self):
        if self.proc:
            try: self.send('quit')
            except: pass

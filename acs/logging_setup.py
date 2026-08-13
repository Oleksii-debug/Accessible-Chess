from pathlib import Path
from datetime import datetime
import traceback, sys, threading, platform

ROOT = Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
REPORTS = ROOT / "ЗВІТИ_ПОМИЛОК"
REPORTS.mkdir(parents=True, exist_ok=True)
VERSION = '0.3.2-stage1-rc2'

def log(name, message):
    REPORTS.mkdir(parents=True, exist_ok=True)
    p=REPORTS/name
    with p.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")

def write_crash(tp, value, tb, context='unhandled'):
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    p=REPORTS/f"crash_{stamp}.log"
    with p.open('w', encoding='utf-8') as f:
        f.write(f'Accessible Chess Studio {VERSION}\n')
        f.write(f'Context: {context}\n')
        f.write(f'Python: {sys.version}\n')
        f.write(f'Platform: {platform.platform()}\n')
        f.write(f'Exception: {tp.__name__}: {value}\n\n')
        traceback.print_exception(tp, value, tb, file=f)
    log('startup.log', f'FATAL; context={context}; {tp.__name__}: {value}; report={p.name}')
    return p

def install_exception_hook():
    def hook(tp, value, tb):
        p=write_crash(tp,value,tb,'sys.excepthook')
        try:
            import tkinter.messagebox as mb
            mb.showerror('Accessible Chess Studio', f'Помилка запуску/роботи. Звіт: {p}')
        except Exception:
            pass
    sys.excepthook=hook
    if hasattr(threading,'excepthook'):
        def thook(args): write_crash(args.exc_type,args.exc_value,args.exc_traceback,'threading.excepthook')
        threading.excepthook=thook

def install_tk_exception_hook(root):
    def report_callback_exception(tp, value, tb):
        p=write_crash(tp,value,tb,'tk.report_callback_exception')
        try:
            import tkinter.messagebox as mb
            mb.showerror('Accessible Chess Studio', f'Помилка команди. Звіт: {p}', parent=root)
        except Exception:
            pass
    root.report_callback_exception=report_callback_exception

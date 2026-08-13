import json
from pathlib import Path

DEFAULTS = {
    'language': 'uk',
    'notation': 'uk_literal',
    'sounds': True,
    'volume': 80,
    'tick_policy': 'my_turn',
    'tick_last_seconds': 0,
    'engine_path': '',
}

class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.data = dict(DEFAULTS)
        self.load()
    def load(self):
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(raw, dict): self.data.update({k:v for k,v in raw.items() if k in DEFAULTS})
        except Exception:
            pass
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
    def get(self, key, default=None): return self.data.get(key, default)
    def set(self, key, value):
        self.data[key] = value; self.save()

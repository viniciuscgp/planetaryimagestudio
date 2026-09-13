"""Persistent per-SOL catalogs; written only after a complete successful read."""
import json
import time
from pathlib import Path


class CatalogCache:
    def __init__(self, root, mission):
        self.folder = Path(root) / '.catalog_cache' / mission

    def read(self, sol, max_age):
        try:
            data = json.loads((self.folder / f'sol_{sol}.json').read_text(encoding='utf-8'))
            if data['version'] != 1 or data['sol'] != sol or not 0 <= time.time() - data['saved_at'] <= max_age:
                return None
            items = data['images']
            if not isinstance(items, list) or any(not isinstance(item, dict) or int(item.get('sol', -1)) != sol for item in items):
                return None
            return items
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def write(self, name, data):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / name
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        temporary.replace(path)

    def save(self, sol, items):
        self.write(f'sol_{sol}.json', dict(version=1, sol=sol, saved_at=time.time(), images=items))

    def complete(self, latest):
        self.write('complete.json', dict(version=1, latest=latest, saved_at=time.time()))

    def clear(self, stopped):
        if not self.folder.exists():
            return
        # Only our own cache files; never traverse image or annotation folders.
        for path in self.folder.iterdir():
            if stopped():
                raise InterruptedError('Limpeza interrompida.')
            if path.is_file() and (path.name == 'complete.json' or
                                   (path.name.startswith('sol_') and path.suffix in ('.json', '.tmp'))):
                path.unlink()

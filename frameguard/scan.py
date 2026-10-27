"""Búsqueda de .blend al arrastrar una carpeta: elige la versión más alta de cada archivo.

La fecha de creación NO sirve (Windows la resetea al copiar), así que manda la versión del nombre
(_RND_V03 > _RND_V02, _v002, -v2...). La fecha de modificación solo desempata."""
import os
from pathlib import Path

from . import util

SKIP_DIRS = {"backup", "backups", "old", "_old", "autosave", "trash", "papelera", "$recycle.bin"}


def scan_folder(root: str, max_depth: int = 4) -> list[dict]:
    root_p = Path(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root_p):
        depth = len(Path(dirpath).relative_to(root_p).parts)
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d.lower() not in SKIP_DIRS)
        for fn in filenames:
            if not fn.lower().endswith(".blend"):  # ignora .blend1, .blend2...
                continue
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            ver, key = util.version_of(p.stem)
            found.append({"path": str(p), "name": p.stem, "version": ver, "mtime": st.st_mtime,
                          "size": st.st_size, "key": str(p.parent).lower() + "|" + key})
    groups: dict[str, list[dict]] = {}
    for b in found:
        groups.setdefault(b["key"], []).append(b)
    result = []
    for items in groups.values():
        items.sort(key=lambda b: (b["version"] if b["version"] is not None else -1, b["mtime"]), reverse=True)
        best = dict(items[0])
        best["older"] = [i["name"] for i in items[1:]]
        result.append(best)
    result.sort(key=lambda b: b["path"].lower())
    return result

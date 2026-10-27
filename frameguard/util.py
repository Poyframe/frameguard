"""Utilidades: JSON atómico, rangos de frames y patrones de archivos de salida."""
import json
import os
import re
import tempfile
import time
from pathlib import Path


def now() -> float:
    return time.time()


def atomic_write_json(path: Path, data) -> None:
    """Escribe a un temporal y lo renombra: si se va la luz a mitad, el archivo anterior sigue sano."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        for i in range(10):  # el antivirus o un lector pueden tener el destino abierto un instante
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05 * (i + 1))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# --- Frames -------------------------------------------------------------------------------

def frame_list(start: int, end: int, step: int = 1) -> list[int]:
    step = max(1, int(step or 1))
    return list(range(int(start), int(end) + 1, step))


def to_ranges(frames, step: int = 1) -> list[list[int]]:
    """[1,2,3,7,8] -> [[1,3],[7,8]] (respetando el step)."""
    out = []
    for f in sorted(set(frames)):
        if out and f == out[-1][1] + step:
            out[-1][1] = f
        else:
            out.append([f, f])
    return out


def from_ranges(ranges) -> list[int]:
    out = []
    for a, b in ranges or []:
        out.extend(range(int(a), int(b) + 1))
    return out


def ranges_label(frames, step: int = 1) -> str:
    return ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in to_ranges(frames, step))


# --- Patrones de salida (ver blender_scripts/fg_common.py) -------------------------------

_HASH_RUN = re.compile(r"#+")


def pattern_path(pattern: str, frame: int) -> str:
    """Reemplaza la ÚLTIMA serie de '#' del nombre de archivo por el frame con ceros."""
    head, tail = os.path.split(pattern)
    runs = list(_HASH_RUN.finditer(tail))
    if not runs:
        return pattern
    m = runs[-1]
    width = m.end() - m.start()
    sign = "-" if frame < 0 else ""
    num = sign + str(abs(frame)).zfill(width)
    return os.path.join(head, tail[:m.start()] + num + tail[m.end():])


def output_patterns(outputs) -> list[str]:
    pats = []
    for o in outputs or []:
        pats.extend(o.get("patterns") or [])
    return pats


def frame_files(outputs, frame: int) -> list[str]:
    return [pattern_path(p, frame) for p in output_patterns(outputs)]


def frame_on_disk(outputs, frame: int) -> bool | None:
    """True si todos los archivos del frame existen y no están vacíos.
    None si no hay patrones verificables (p. ej. salida de video)."""
    files = frame_files(outputs, frame)
    if not files:
        return None
    for f in files:
        try:
            if os.path.getsize(f) <= 0:
                return False
        except OSError:
            return False
    return True


def fmt_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} m"
    if m:
        return f"{m} m {s:02d} s"
    return f"{s} s"


# --- Versiones en el nombre de archivo ------------------------------------------------------

_VERSION = re.compile(r"(?i)(?:^|[_\-. ])v(\d+)(?=$|[_\-. ])")


def version_of(stem: str) -> tuple[int | None, str]:
    """('SH010_RND_V03') -> (3, 'sh010_rnd'). La clave sirve para agrupar versiones."""
    matches = list(_VERSION.finditer(stem))
    if not matches:
        return None, stem.lower()
    m = matches[-1]
    key = (stem[:m.start()] + stem[m.end():]).lower()
    return int(m.group(1)), key

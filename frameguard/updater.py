"""Actualizaciones desde una carpeta compartida (por ejemplo en la red): sin servidor ni internet.

En esa carpeta se dejan los instaladores con este nombre:
    Frameguard-Setup-0.2.0.exe
y, opcionalmente, las novedades de cada versión:
    Frameguard-0.2.0-novedades.txt

El instalador tiene un AppId fijo: instala ENCIMA de la versión existente (no crea otra) y conserva la cola,
los ajustes y los logs, que viven en %APPDATA%\\Frameguard. Para volver a una versión anterior basta con
instalar su instalador, que sigue en la carpeta.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import __version__

SETUP_RE = re.compile(r"^Frameguard-Setup-(\d+)\.(\d+)\.(\d+)\.exe$", re.I)
DETACHED_PROCESS = 0x00000008


def parse_version(text: str) -> tuple[int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", text)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))  # type: ignore[return-value]


CURRENT = parse_version(__version__)


def list_versions(folder: str) -> list[dict]:
    """Instaladores de la carpeta, del más nuevo al más viejo."""
    if not folder or not os.path.isdir(folder):
        return []
    out = []
    for name in os.listdir(folder):
        m = SETUP_RE.match(name)
        if not m:
            continue
        ver = tuple(int(x) for x in m.groups())
        label = ".".join(m.groups())
        notes_path = Path(folder) / f"Frameguard-{label}-novedades.txt"
        notes = ""
        if notes_path.is_file():
            try:
                notes = notes_path.read_text(encoding="utf-8-sig", errors="replace").strip()
            except OSError:
                pass
        out.append({"version": ver, "label": label, "path": str(Path(folder) / name), "notes": notes,
                    "current": ver == CURRENT, "newer": ver > CURRENT})
    out.sort(key=lambda v: v["version"], reverse=True)
    return out


def newest(folder: str) -> dict | None:
    vers = [v for v in list_versions(folder) if v["newer"]]
    return vers[0] if vers else None


def launch_installer(item: dict, silent: bool = True) -> None:
    """Copia el instalador a una carpeta local (que un corte de red no lo interrumpa) y lo ejecuta."""
    tmp = Path(tempfile.gettempdir()) / "Frameguard-update"
    tmp.mkdir(exist_ok=True)
    local = tmp / Path(item["path"]).name
    shutil.copy2(item["path"], local)
    args = [str(local)]
    if silent:
        args += ["/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"]
    subprocess.Popen(args, creationflags=DETACHED_PROCESS, close_fds=True)

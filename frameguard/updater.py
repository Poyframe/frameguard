"""Actualizaciones desde una carpeta compartida (por ejemplo en la red) y, en la edición pública, desde las
Releases de GitHub (github_updates.py).

En la carpeta se dejan los instaladores con este nombre:
    Frameguard-Setup-0.2.0.exe
y, opcionalmente, las novedades de cada versión:
    Frameguard-0.2.0-novedades.txt

En la edición pública, si hay carpeta configurada y tiene la misma versión que GitHub o una más nueva, manda la
carpeta. La edición interna (build.ps1 -SinGitHub) no tiene el código de GitHub: solo usa la carpeta.

El instalador tiene un AppId fijo: instala ENCIMA de la versión existente (no crea otra) y conserva la cola,
los ajustes y los logs, que viven en %APPDATA%\\Frameguard. Para volver a una versión anterior basta con
instalar su instalador, que sigue en la carpeta.
"""
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import __version__

SETUP_RE = re.compile(r"^Frameguard-Setup-(\d+)\.(\d+)\.(\d+)\.exe$", re.I)
DETACHED_PROCESS = 0x00000008

log = logging.getLogger(__name__)


def parse_version(text: str) -> tuple[int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", text)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))  # type: ignore[return-value]


CURRENT = parse_version(__version__)


def update_dir() -> Path:
    """Carpeta local (en %TEMP%) donde se deja el instalador antes de ejecutarlo."""
    return Path(tempfile.gettempdir()) / "Frameguard-update"


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
                    "current": ver == CURRENT, "newer": ver > CURRENT, "source": "folder"})
    out.sort(key=lambda v: v["version"], reverse=True)
    return out


def newest(folder: str) -> dict | None:
    vers = [v for v in list_versions(folder) if v["newer"]]
    return vers[0] if vers else None


def find_update(folder: str, use_github: bool = True) -> dict | None:
    """La versión a la que actualizar, o None. La carpeta manda si tiene la misma versión que GitHub o una más
    nueva; GitHub solo gana si trae algo más nuevo que todo lo que hay en la carpeta. En la edición interna no
    existe el módulo de GitHub y solo se mira la carpeta, diga lo que diga use_github."""
    from .edition import github
    local = list_versions(folder)
    best = local[0] if local else None
    remote = github.latest() if (use_github and github is not None) else None
    if remote and (best is None or remote["version"] > best["version"]):
        best = remote
    return best if best and best["newer"] else None


def launch_installer(item: dict, silent: bool = True) -> None:
    """Ejecuta el instalador desde una carpeta local. Si viene de la carpeta de red, antes lo copia (que un corte
    de red no lo interrumpa); el de GitHub ya está ahí tras download()."""
    tmp = update_dir()
    tmp.mkdir(exist_ok=True)
    local = tmp / Path(item["path"]).name
    if os.path.normcase(os.path.abspath(item["path"])) != os.path.normcase(str(local)):
        shutil.copy2(item["path"], local)
    args = [str(local)]
    if silent:
        args += ["/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"]
    if os.environ.get("FRAMEGUARD_DRY_UPDATE"):  # pruebas: todo menos ejecutar el instalador
        log.info("FRAMEGUARD_DRY_UPDATE: no se ejecuta %s", " ".join(args))
        return
    subprocess.Popen(args, creationflags=DETACHED_PROCESS, close_fds=True)

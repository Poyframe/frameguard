"""Avisos de versiones nuevas desde las Releases de GitHub (solo en la edición pública).

Cada release lleva adjunto Frameguard-Setup-X.Y.Z.exe. Sus notas van en inglés, una línea «---» y luego en español;
de cada parte se toman los puntos («- **Título:** texto»). Se consulta sin token y sin avisar de los errores: sin
red no pasa nada.

La edición interna de un estudio (build.ps1 -SinGitHub) se compila SIN este módulo: ese Frameguard no tiene
ningún código que se conecte a GitHub y solo se actualiza desde su carpeta de la red (ver edition.py).
"""
import hashlib
import json
import logging
import os
import re
import threading
import urllib.request
from pathlib import Path

from . import __version__, i18n
from .i18n import tr
from .updater import CURRENT, SETUP_RE, update_dir

# FRAMEGUARD_GITHUB_API: otra dirección para las pruebas (un servidor local que imita a GitHub)
GITHUB_API = (os.environ.get("FRAMEGUARD_GITHUB_API")
              or "https://api.github.com/repos/Poyframe/frameguard/releases/latest")
RELEASES_PAGE = "https://github.com/Poyframe/frameguard/releases"
HEADERS = {"User-Agent": f"Frameguard/{__version__}", "X-GitHub-Api-Version": "2022-11-28"}

log = logging.getLogger(__name__)


class UpdateError(Exception):
    """Fallo al descargar una actualización (el mensaje ya va traducido para mostrarlo)."""


def release_notes(body: str, language: str) -> str:
    """Los puntos de las notas de una release en el idioma pedido, sin Markdown: «• Título: texto» por línea."""
    parts = re.split(r"(?m)^\s*-{3,}\s*$", body or "", maxsplit=1)
    part = parts[1] if language == "es" and len(parts) > 1 else parts[0]
    out = []
    for line in part.splitlines():
        m = re.match(r"\s*[-*]\s+(.+)", line)
        if m:
            text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", m.group(1))  # [texto](enlace) -> texto
            out.append("• " + re.sub(r"\*\*|`", "", text).strip())
    return "\n".join(out)


def latest(timeout: float = 10) -> dict | None:
    """La última release publicada en GitHub con su instalador, o None (sin red, límite de GitHub, sin .exe...)."""
    try:
        req = urllib.request.Request(GITHUB_API, headers={**HEADERS, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read(2_000_000).decode("utf-8"))
        if data.get("draft") or data.get("prerelease"):
            return None
        for asset in data.get("assets") or []:
            m = SETUP_RE.match(asset.get("name") or "")
            if not m or not str(asset.get("browser_download_url", "")).lower().startswith(("https://", "http://")):
                continue
            ver = tuple(int(x) for x in m.groups())
            digest = str(asset.get("digest") or "")
            return {"version": ver, "label": ".".join(m.groups()), "path": asset["name"],
                    "url": asset["browser_download_url"], "size": int(asset["size"]),
                    "sha256": digest[7:].lower() if digest.lower().startswith("sha256:") else "",
                    "notes": release_notes(data.get("body") or "", i18n.lang()), "page": data.get("html_url", ""),
                    "current": ver == CURRENT, "newer": ver > CURRENT, "source": "github"}
        log.info("GitHub: la última release (%s) no trae Frameguard-Setup-X.Y.Z.exe", data.get("tag_name"))
    except Exception as e:  # noqa: BLE001  sin red, sin DNS, límite de peticiones, JSON raro...: se ignora
        log.info("GitHub: no se pudo consultar la última versión (%s)", e)
    return None


def download(item: dict, progress=None, cancel: threading.Event | None = None, timeout: float = 30) -> Path:
    """Descarga el instalador de GitHub a %TEMP%\\Frameguard-update y comprueba que llegó entero (tamaño y, si
    GitHub la da, la suma SHA-256). progress(bytes, total) se llama durante la descarga. Lanza UpdateError."""
    folder = update_dir()
    folder.mkdir(exist_ok=True)
    final = folder / Path(item["path"]).name
    part = final.with_name(final.name + ".part")
    want = int(item["size"])
    got = 0
    sha = hashlib.sha256()
    try:
        req = urllib.request.Request(item["url"], headers={**HEADERS, "Accept": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
            length = r.headers.get("Content-Length")
            if length and length.isdigit() and int(length) != want:
                raise UpdateError(tr("El instalador de GitHub no tiene el tamaño esperado ({got} de {want} bytes).",
                                     got=int(length), want=want))
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError(tr("Descarga cancelada."))
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if got > want:
                    break
                f.write(chunk)
                sha.update(chunk)
                if progress:
                    progress(got, want)
        if got != want:
            raise UpdateError(tr("El instalador de GitHub no tiene el tamaño esperado ({got} de {want} bytes).",
                                 got=got, want=want))
        if item.get("sha256") and sha.hexdigest() != item["sha256"]:
            raise UpdateError(tr("El instalador descargado no coincide con el publicado en GitHub (SHA-256 distinto)."))
        os.replace(part, final)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except Exception as e:  # noqa: BLE001  red caída a mitad, disco lleno...
        part.unlink(missing_ok=True)
        raise UpdateError(str(e) or e.__class__.__name__) from e
    log.info("Actualización descargada de GitHub: %s (%s bytes)", final, got)
    return final

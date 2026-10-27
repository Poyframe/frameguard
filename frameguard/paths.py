"""Rutas de datos de Frameguard. Los datos viven fuera de la carpeta de instalación para que
actualizar el programa nunca borre la cola, los ajustes ni los logs.

FRAMEGUARD_HOME permite usar otra carpeta (pruebas)."""
import os
import sys
from pathlib import Path

from . import APP_NAME


def data_dir() -> Path:
    env = os.environ.get("FRAMEGUARD_HOME")
    base = Path(env) if env else Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def state_file() -> Path:
    return data_dir() / "queue.json"


def logs_dir() -> Path:
    return sub("logs")


def reports_dir() -> Path:
    return sub("informes")


def runtime_dir() -> Path:
    return sub("runtime")


def resource_dir() -> Path:
    """Carpeta del paquete (funciona también empaquetado con PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frameguard"
    return Path(__file__).resolve().parent


def blender_script(name: str) -> Path:
    return resource_dir() / "blender_scripts" / name

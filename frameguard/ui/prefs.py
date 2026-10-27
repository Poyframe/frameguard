"""Preferencias de la ventana (tema, animaciones, últimas carpetas, versión vista...).

Normalmente van al registro de Windows del usuario. Con FRAMEGUARD_HOME (pruebas) van a un .ini dentro de
esa carpeta, para que una prueba nunca cambie las preferencias reales (p. ej. marcar unas Novedades como vistas)."""
import os

from PySide6.QtCore import QSettings


def prefs() -> QSettings:
    home = os.environ.get("FRAMEGUARD_HOME")
    if home:
        return QSettings(os.path.join(home, "ventana.ini"), QSettings.IniFormat)
    return QSettings("Frameguard", "Frameguard")

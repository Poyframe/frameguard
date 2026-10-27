"""Edición de Frameguard.

- Pública (la de GitHub): avisa de versiones nuevas publicadas en GitHub y, si se configura, también de una
  carpeta de actualizaciones en la red.
- Interna (build.ps1 -SinGitHub): para los PC de un estudio. Se compila SIN el módulo github_updates, así que
  ese Frameguard no tiene ningún código que se conecte a GitHub: solo se actualiza desde su carpeta de la red.

El resto del programa pregunta aquí (HAS_GITHUB / github) en vez de importar github_updates directamente.
"""
import os

try:
    from . import github_updates as github
except ImportError:  # edición interna: el módulo no está en el .exe
    github = None
if os.environ.get("FRAMEGUARD_SIN_GITHUB"):  # pruebas: simular la edición interna sin compilarla
    github = None

HAS_GITHUB = github is not None

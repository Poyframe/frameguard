"""Los avisos se van solos, pero solo cuentan tiempo mientras el usuario usa el PC.

Simula: 1) usuario ausente (sin ratón ni teclado): los avisos se quedan; 2) usuario presente: se van solos;
3) ratón encima: no se van. Usa duraciones cortas para no esperar.

    python tools/pruebas/avisos.py
"""
import os
import sys
import time

import comun  # noqa: F401  (añade el proyecto al path)

os.environ.setdefault("FRAMEGUARD_HOME", str(comun.WORK / "avisos"))
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from frameguard.ui import toast  # noqa: E402
from frameguard.ui.theme import Theme  # noqa: E402

theme = Theme()
theme.mode = "dark"
theme.apply()
toast.DURATION_MS.update({"shot_done": 1500, "queue_done": 2000, "job_failed": 2000})
idle = {"ms": 10 * 60 * 1000}  # 10 min sin tocar nada: el usuario no está
toast.idle_ms = lambda: idle["ms"]
mgr = toast.ToastManager(theme, lambda: None)


def run(seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


for kind in ("shot_done", "queue_done", "job_failed"):
    mgr.show(kind, "Prueba", kind)
run(4)
away = len([t for t in mgr.toasts if not t.closing])
print(f"{'OK ' if away == 3 else 'MAL'} usuario ausente 4 s: siguen {away} de 3 avisos")

idle["ms"] = 0  # vuelve: mueve el ratón
mgr.toasts[0].hovered = True  # y deja el ratón encima del más nuevo
run(3)
left = [t for t in mgr.toasts if not t.closing]
print(f"{'OK ' if len(left) == 1 and left[0].hovered else 'MAL'} usuario presente 3 s: quedan {len(left)} "
      "(solo el que tiene el ratón encima)")

left[0].hovered = False  # quita el ratón: lo mismo que hace Toast.leaveEvent
left[0].remaining_ms = max(left[0].remaining_ms, 3000)
run(4)
gone = not [t for t in mgr.toasts if not t.closing]
print(f"{'OK ' if gone else 'MAL'} al quitar el ratón, el último también se va")
print("PRUEBA SUPERADA" if away == 3 and len(left) == 1 and gone else "PRUEBA CON FALLOS")

"""Arrastre REAL (OLE, como desde el Explorador) de un .blend y una carpeta sobre la lista de Frameguard.
Comprueba: el .blend entra directo a la cola y la carpeta abre «Agregar desde carpetas».
Mueve el ratón unos segundos: no tocar el PC mientras corre.

    python tools/pruebas/arrastre.py [--exe dist\\Frameguard\\Frameguard.exe]
"""
import ctypes
import sys
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QMimeData, Qt, QTimer, QUrl
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QLabel

from comun import PROJ, Prueba, args, u32, windows_of

u32.SetProcessDPIAware()
exe, lang = args()
P = Prueba("arrastre", 47879, exe, lang)
previos = [P.copy_fixture(f"previo_{n}.blend") for n in "abc"]  # filas en la lista: se suelta ENCIMA de ellas
P.send("add", paths=[str(p) for p in previos])
blend = P.copy_fixture("arrastrado.blend")
folder = P.copy_fixture("carpeta/SH900/SH900_RND_V01.blend").parents[1]
ui = __import__("subprocess").Popen(P.cmd(), cwd=str(PROJ), env=P.env)
main = None
for _ in range(60):
    main = next((h for h, t in windows_of(exe) if t == "Frameguard"), None)
    if main:
        break
    time.sleep(0.25)
time.sleep(2.5)
u32.ShowWindow(main, 9)
u32.SetForegroundWindow(main)
r = wintypes.RECT()
u32.GetWindowRect(main, ctypes.byref(r))
target = ((r.left + r.right) // 2, r.top + 260)

app = QApplication(sys.argv)
src = QLabel("arrastre de prueba")
src.setGeometry(40, 40, 220, 60)
src.setWindowFlags(Qt.WindowStaysOnTopHint)
src.show()
app.processEvents()
c = src.mapToGlobal(src.rect().center())
start = (int(c.x() * src.devicePixelRatioF()), int(c.y() * src.devicePixelRatioF()))


def mover():
    time.sleep(0.6)
    for i in range(1, 41):  # el cursor viaja hasta Frameguard con el botón pulsado
        u32.SetCursorPos(start[0] + (target[0] - start[0]) * i // 40, start[1] + (target[1] - start[1]) * i // 40)
        u32.mouse_event(0x0001, 0, 0, 0, 0)
        time.sleep(0.03)
    time.sleep(0.8)
    u32.mouse_event(0x0004, 0, 0, 0, 0)  # soltar


def press():
    u32.SetForegroundWindow(int(src.winId()))
    u32.SetCursorPos(*start)
    u32.mouse_event(0x0002, 0, 0, 0, 0)  # DoDragDrop exige el botón pulsado (y ya procesado)
    QTimer.singleShot(300, drag)


def drag():
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(blend)), QUrl.fromLocalFile(str(folder))])
    d = QDrag(src)
    d.setMimeData(md)
    threading.Thread(target=mover, daemon=True).start()
    d.exec(Qt.CopyAction)
    app.quit()


QTimer.singleShot(300, press)
app.exec()
time.sleep(2.5)
names = [j["name"] for j in P.jobs()]
titles = [t for _, t in windows_of(exe)]
for h, t in windows_of(exe):  # cerrar la lista de carpetas y luego la ventana (WM_CLOSE)
    if t != "Frameguard":
        u32.PostMessageW(h, 0x0010, 0, 0)
time.sleep(0.8)
for h, t in windows_of(exe):
    u32.PostMessageW(h, 0x0010, 0, 0)
time.sleep(1.5)
ui.kill()
errs = P.errors()
P.close()
ok_file = "arrastrado" in names
ok_folder = len(titles) >= 2
print(f"{'OK ' if ok_file else 'MAL'} el .blend arrastrado entró directo a la cola: {names}")
print(f"{'OK ' if ok_folder else 'MAL'} la carpeta abrió la lista para elegir: {titles}")
print("errores en los logs:", {k: v for k, v in errs.items() if v} or "ninguno")
print("PRUEBA SUPERADA" if ok_file and ok_folder and not any(errs.values()) else "PRUEBA CON FALLOS")

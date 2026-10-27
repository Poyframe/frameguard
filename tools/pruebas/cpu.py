"""Consumo de CPU de la ventana: en reposo, renderizando a la vista y renderizando minimizada (10 s cada uno).
Referencia (0.1.8, .exe): reposo 0,3-0,8 %, a la vista 3-5 %, minimizada 0-0,2 % de un núcleo.
En modo desarrollo las cifras no valen (el proceso medido sería el intermediario de Python): usar --exe.

    python tools/pruebas/cpu.py --exe dist\\Frameguard\\Frameguard.exe
"""
import ctypes
import subprocess
import time
from ctypes import wintypes

from comun import PROJ, Prueba, args, kill_ui, u32

exe, lang = args()
if not exe:
    raise SystemExit("Usa --exe: en modo desarrollo se mediría el intermediario de Python, no la ventana.")


def cpu_seconds(pid: int) -> float:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)
    ft = [wintypes.FILETIME() for _ in range(4)]
    k32.GetProcessTimes(h, *[ctypes.byref(f) for f in ft])
    k32.CloseHandle(h)
    return sum(((f.dwHighDateTime << 32) | f.dwLowDateTime) / 1e7 for f in ft[2:])


def measure(pid, secs=10) -> float:
    c0 = cpu_seconds(pid)
    time.sleep(secs)
    return (cpu_seconds(pid) - c0) / secs * 100


P = Prueba("cpu", 47880, exe, lang)
lento = P.copy_fixture("lento.blend")
P.send("add", paths=[str(lento)], test={"output_root": str(P.home / "out"), "debug_slow_frame_seconds": 2})
P.wait_reading()
ui = subprocess.Popen(P.cmd(), cwd=str(PROJ), env=P.env)
time.sleep(6)
idle = measure(ui.pid)
P.send("start")
time.sleep(4)
e0 = cpu_seconds(P.engine.pid)
busy = measure(ui.pid)
eng = (cpu_seconds(P.engine.pid) - e0) / 10 * 100
found = []


@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def _cb(h, _):
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    buf = ctypes.create_unicode_buffer(200)
    u32.GetWindowTextW(h, buf, 200)
    if pid.value == ui.pid and u32.IsWindowVisible(h) and buf.value == "Frameguard":
        found.append(h)
    return True


u32.EnumWindows(_cb, 0)
if not found:
    kill_ui(exe)
    P.close()
    raise SystemExit("No apareció la ventana (¿había otra Frameguard de prueba abierta?)")
u32.ShowWindow(found[0], 6)  # minimizar
time.sleep(2)
mini = measure(ui.pid)
u32.ShowWindow(found[0], 9)
running = P.api("/api/state")["running_job"] is not None
ui.kill()
kill_ui(exe)
errs = P.errors()
P.close()
print(f"ventana en reposo:             {idle:.1f} % de un núcleo")
print(f"ventana renderizando visible:  {busy:.1f} % de un núcleo")
print(f"ventana renderizando minimiz.: {mini:.1f} % de un núcleo")
print(f"motor renderizando:            {eng:.1f} % de un núcleo (sin contar Blender)")
print("el render seguía:", running, "| errores:", {k: v for k, v in errs.items() if v} or "ninguno")

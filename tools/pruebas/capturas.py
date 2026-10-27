"""Prueba completa con capturas de cada pantalla (en el idioma pedido) y un render real lento.

Comprueba: migración de la espera de apagado (60 s -> 10 min), límite de CPU (afinidad y prioridad reales de
Blender, también en caliente), avisos del motor en el idioma pedido, y que la ventana arranca y conecta en cada
escenario. Las capturas quedan en %TEMP%\\frameguard_pruebas\\capturas_<idioma>\\.

    python tools/pruebas/capturas.py [--exe dist\\Frameguard\\Frameguard.exe] [--lang en|es]
"""
import ctypes
import json
import shutil
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from comun import PROJ, Prueba, args

exe, lang = args()
lang = lang or "en"
P = Prueba(f"capturas_{lang}", 47883, exe, lang)
OUT = P.dir / "capturas"
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir()

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wintypes.HANDLE
k32.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
k32.GetPriorityClass.argtypes = [wintypes.HANDLE]


def proc_info(pid):
    h = k32.OpenProcess(0x1000, False, pid)
    pm, sm = ctypes.c_size_t(), ctypes.c_size_t()
    k32.GetProcessAffinityMask(h, ctypes.byref(pm), ctypes.byref(sm))
    prio = k32.GetPriorityClass(h)
    k32.CloseHandle(h)
    return bin(pm.value).count("1"), bin(sm.value).count("1"), {0x4000: "baja", 0x20: "normal"}.get(prio, hex(prio))


def shot(name, delay=5200, **extra_env):
    target = OUT / f"{name}.png"
    env = {**P.env, "FRAMEGUARD_SCREENSHOT": str(target), "FRAMEGUARD_SCREENSHOT_DELAY": str(delay), **extra_env}
    rc = subprocess.run(P.cmd(), cwd=str(PROJ), env=env, timeout=90).returncode
    res = json.loads(Path(str(target) + ".json").read_text())
    extras = sorted(p.name for p in OUT.glob(f"{name}_*.png"))
    ok = rc == 0 and res["connected"]
    print(f"{'OK ' if ok else 'MAL'} [{name}] código={rc} conectada={res['connected']} filas={res['rows']} extra={extras}")
    return ok


# --- migración: un estado guardado por una versión anterior con 60 s de espera
P.close()
# queue.json es el estado del motor (paths.state_file). Además de los 60 s, un valor propio (7 intentos) para
# confirmar que el motor de verdad leyó este archivo y no está devolviendo sus valores por defecto.
(P.home / "queue.json").write_text(json.dumps({"schema": 1, "settings": {"countdown_seconds": 60, "max_attempts": 7},
                                               "jobs": [], "queue": {"running": False, "after": "none",
                                                                     "started_at": None}}))
P.start_engine()
s = P.api("/api/state")["settings"]
ok = s["countdown_seconds"] == 600 and s["max_attempts"] == 7
print(f"{'OK ' if ok else 'MAL'} migración de la espera de apagado: {s['countdown_seconds']} s (esperado 600), "
      f"intentos {s['max_attempts']} (esperado 7: el archivo se leyó)")
P.send("settings", values={"max_attempts": 3})

# --- carpetas para el escaneo múltiple, un shot ya en la cola y uno lento renderizando con el límite activado
scan_root = P.dir / "carpetas"
shutil.rmtree(scan_root, ignore_errors=True)
for rel in ("CAP_A/SH010/SH010_RND_V01.blend", "CAP_A/SH010/SH010_RND_V02.blend", "CAP_A/SH020/SH020_RND_V01.blend",
            "CAP_B/SH030/SH030_RND_V03.blend", "CAP_B/SH040/SH040_RND_V01.blend"):
    P.copy_fixture("carpetas/" + rel)
(scan_root / "VACIA").mkdir()
P.send("add", paths=[str(scan_root / "CAP_B/SH030/SH030_RND_V03.blend")])
lento = P.copy_fixture("lento.blend")
P.send("add", paths=[str(lento)], test={"output_root": str(P.home / "out"), "debug_slow_frame_seconds": 3})
P.wait_reading()
for j in P.jobs():
    if j["name"] != "lento":
        P.send("enable", id=j["id"], enabled=False)
print("avisos del motor:", [w["text"] for j in P.jobs() for w in j["warnings"]])
P.send("settings", values={"limit_resources": True, "limit_percent": 50})
P.send("start")
pid = None
for _ in range(80):
    st = P.api("/api/state")
    rj = next((j for j in st["jobs"] if j["id"] == st["running_job"]), None)
    if rj and rj.get("pid"):
        pid = rj["pid"]
        break
    time.sleep(0.25)
time.sleep(1.5)
a = proc_info(pid)
P.send("settings", values={"limit_percent": 25})
time.sleep(0.5)
b = proc_info(pid)
P.send("settings", values={"limit_resources": False})
time.sleep(0.5)
c = proc_info(pid)
P.send("settings", values={"limit_resources": True, "limit_percent": 50})
time.sleep(0.5)
ok = a[2] == "baja" and b[0] == max(1, round(a[1] * 0.25)) and c == (a[1], a[1], "normal")
print(f"{'OK ' if ok else 'MAL'} límite de CPU: al lanzar {a}, al 25 % {b}, sin límite {c}")

# --- capturas con el render en marcha
results = [
    shot("render", delay=6500),
    shot("ajustes", FRAMEGUARD_SCREENSHOT_SETTINGS="1"),
    shot("arrastre", FRAMEGUARD_SCREENSHOT_DROP="|".join([str(scan_root / "CAP_A"), str(scan_root / "CAP_B"), str(lento)])),
    shot("arrastre_malo", FRAMEGUARD_SCREENSHOT_DROP=str(Path(__file__))),
    shot("alterminar", FRAMEGUARD_SCREENSHOT_AFTER="shutdown"),
]
P.send("set_after", action="none")  # que la cuenta atrás real no tape las siguientes capturas
P.send("cancel_countdown")
results += [
    shot("cuenta", FRAMEGUARD_SCREENSHOT_COUNTDOWN="shutdown"),
    shot("carpetas", FRAMEGUARD_SCREENSHOT_SCAN="|".join([str(scan_root / "CAP_A"), str(scan_root / "CAP_B"),
                                                           str(scan_root / "VACIA")])),
    shot("menu", FRAMEGUARD_SCREENSHOT_DRAWER="1"),
    shot("panel", FRAMEGUARD_SCREENSHOT_POPUP="1", FRAMEGUARD_SCREENSHOT_POPUP_INDEX="1"),
]
(P.home / "ventana.ini").write_text("[General]\nlast_seen_version=0.1.8\n", encoding="utf-8")  # novedades de la 0.1.9
results.append(shot("novedades", FRAMEGUARD_SCREENSHOT_WHATSNEW="1"))
results.append((OUT / "novedades_novedades.png").exists())
errs = P.errors()
P.close()
print("errores en los logs:", {k: v for k, v in errs.items() if v} or "ninguno")
print("capturas en:", OUT)
print("PRUEBA SUPERADA" if all(results) and not any(errs.values()) else "PRUEBA CON FALLOS")

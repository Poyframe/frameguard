"""Reabrir la ventana (lo que hace Frameguard al cambiar de idioma): la ventana vieja se cierra, aparece una
nueva conectada al mismo motor y el render no se interrumpe.

    python tools/pruebas/reinicio.py --exe dist\\Frameguard\\Frameguard.exe
"""
import subprocess
import time

from comun import PROJ, Prueba, args, kill_ui, u32, windows_of

exe, lang = args()
if not exe:
    raise SystemExit("Usa --exe: en modo desarrollo el proceso lanzado es un intermediario de Python.")
P = Prueba("reinicio", 47884, exe, lang)
lento = P.copy_fixture("lento.blend")
P.send("add", paths=[str(lento)], test={"output_root": str(P.home / "out"), "debug_slow_frame_seconds": 2})
P.wait_reading()
P.send("start")
time.sleep(2)
pid_blender = P.api("/api/state")["jobs"][0].get("pid")
ui = subprocess.Popen(P.cmd(), cwd=str(PROJ), env={**P.env, "FRAMEGUARD_TEST_RESTART": "1"})
time.sleep(10)
old_closed = ui.poll() is not None
wins = [t for _, t in windows_of(exe) if t == "Frameguard"]
st = P.api("/api/state")
same_render = st["running_job"] is not None and st["jobs"][0].get("pid") == pid_blender
log = (P.home / "ui.log").read_text(encoding="utf-8")
restarted = log.count("Se reinicia la ventana") == 1 and log.count("Ventana ") >= 2
kill_ui(exe)  # con el render en marcha, cerrar la ventana solo la esconde en la bandeja
errs = P.errors()
P.close()
print(f"{'OK ' if old_closed else 'MAL'} la ventana vieja se cerró")
print(f"{'OK ' if len(wins) == 1 else 'MAL'} hay una ventana nueva (ventanas: {len(wins)})")
print(f"{'OK ' if restarted else 'MAL'} se reinició una sola vez (no en bucle)")
print(f"{'OK ' if same_render else 'MAL'} el render siguió con el mismo Blender (pid {pid_blender})")
print("errores en los logs:", {k: v for k, v in errs.items() if v} or "ninguno")
ok = old_closed and len(wins) == 1 and restarted and same_render and not any(errs.values())
print("PRUEBA SUPERADA" if ok else "PRUEBA CON FALLOS")

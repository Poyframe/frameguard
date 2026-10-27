"""Avisos de versiones nuevas desde GitHub, contra un servidor local que imita la API (nunca el GitHub real).

1. updater.py: lectura de la release, prioridad de la carpeta de red frente a GitHub, errores silenciosos (sin
   red, 404, límite de peticiones, JSON roto, lentitud) y descarga con progreso, tamaño y SHA-256.
2. La ventana (mejor con --exe): aviso desde GitHub, «Actualizar ahora» descarga a %TEMP% con progreso y lanza el
   instalador (en modo prueba no se ejecuta); la carpeta manda si tiene la misma versión; con la casilla de GitHub
   apagada no se consulta; con un render en marcha no se descarga nada.

    python tools/pruebas/actualizaciones.py [--exe dist\\Frameguard\\Frameguard.exe] [--lang en|es]
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import comun
from comun import PROJ, Prueba, args, kill_ui

sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows no imprime «», → ni acentos
exe, lang = args()
WORK = comun.WORK / "actualizaciones"
shutil.rmtree(WORK, ignore_errors=True)
TEMP = WORK / "temp"  # %TEMP% propio: la descarga nunca cae en el %TEMP%\Frameguard-update real
TEMP.mkdir(parents=True)

NEW = "9.0.0"
SETUP = f"Frameguard-Setup-{NEW}.exe"
BLOB = b"MZ" + os.urandom(3 * 1024 * 1024)  # «instalador» de 3 MB (solo se descarga, nunca se ejecuta)
BODY = ("## Download\r\n\r\nDownload **Frameguard-Setup-9.0.0.exe** below.\r\n\r\n## What's new in 9.0.0\r\n\r\n"
        "- **Faster queue:** everything is [faster](https://example.com).\r\n- **Fix:** `SH040_RND_V01` renders.\r\n\r\n"
        "---\r\n\r\n### Novedades de la 9.0.0 (español)\r\n\r\n- **Cola más rápida:** todo va más rápido.\r\n"
        "- **Corrección:** `SH040_RND_V01` renderiza.\r\n")
# Comportamiento del servidor falso; cada caso lo cambia.
S = {"api": "ok", "version": NEW, "blob": BLOB, "size": len(BLOB), "digest": "sha256:" + hashlib.sha256(BLOB).hexdigest(),
     "download": "ok", "slow": 0.0, "api_hits": 0, "dl_hits": 0}


class FakeGitHub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json", length=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body) if length is None else length))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        host = f"http://127.0.0.1:{self.server.server_port}"
        if self.path.endswith("/releases/latest"):
            S["api_hits"] += 1
            mode = S["api"]
            if mode == "lenta":
                time.sleep(3)
            if mode in ("404", "403", "500"):
                return self._send(int(mode), b'{"message": "Not Found"}')
            if mode == "basura":
                return self._send(200, b"<html>no es json</html>", "text/html")
            v = S["version"]
            assets = [{"name": "notas.txt", "size": 3, "browser_download_url": f"{host}/x/notas.txt"}]
            if mode != "sin_exe":
                assets.append({"name": f"Frameguard-Setup-{v}.exe", "size": S["size"], "digest": S["digest"],
                               "browser_download_url": f"{host}/Poyframe/frameguard/releases/download/v{v}/"
                                                       f"Frameguard-Setup-{v}.exe"})
            return self._send(200, json.dumps({"tag_name": f"v{v}", "draft": False, "prerelease": False,
                                               "html_url": f"{host}/releases/tag/v{v}", "body": BODY,
                                               "assets": assets}).encode())
        if "/releases/download/" in self.path:  # GitHub redirige el enlace de descarga a otro servidor
            self.send_response(302)
            self.send_header("Location", f"{host}/blob/{self.path.rsplit('/', 1)[-1]}")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if self.path.startswith("/blob/"):
            S["dl_hits"] += 1
            blob, mode = S["blob"], S["download"]
            if mode == "cortada":  # promete el archivo entero y corta a la mitad
                self.send_response(200)
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob[:len(blob) // 2])
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            for i in range(0, len(blob), 64 * 1024):
                self.wfile.write(blob[i:i + 64 * 1024])
                if S["slow"]:
                    time.sleep(S["slow"])
            return
        self._send(404, b"{}")


srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
srv.handle_error = lambda *a: None  # el cliente que corta (timeout, cancelar) no es un error de la prueba
threading.Thread(target=srv.serve_forever, daemon=True).start()
API = f"http://127.0.0.1:{srv.server_port}/repos/Poyframe/frameguard/releases/latest"

# --- 1. updater.py en este mismo proceso
os.environ["FRAMEGUARD_GITHUB_API"] = API  # antes de importar: updater lo lee al cargarse
os.environ["FRAMEGUARD_DRY_UPDATE"] = "1"
os.environ["TEMP"] = os.environ["TMP"] = os.environ["TMPDIR"] = str(TEMP)
tempfile.tempdir = None
from frameguard import __version__, github_updates, i18n, updater  # noqa: E402

results = []


def check(ok, text):
    results.append(bool(ok))
    print(f"{'OK ' if ok else 'MAL'} {text}")


def reset(**kw):
    S.update({"api": "ok", "version": NEW, "blob": BLOB, "size": len(BLOB),
              "digest": "sha256:" + hashlib.sha256(BLOB).hexdigest(), "download": "ok", "slow": 0.0}, **kw)


def folder_with(*versions) -> str:
    d = WORK / ("carpeta_" + "_".join(versions))
    d.mkdir(exist_ok=True)
    for v in versions:
        (d / f"Frameguard-Setup-{v}.exe").write_bytes(b"MZ local")
    return str(d)


check(updater.update_dir() == TEMP / "Frameguard-update", f"la descarga va a %TEMP% ({updater.update_dir()})")
i18n.set_lang("es")
it = github_updates.latest()
check(it and it["version"] == (9, 0, 0) and it["newer"] and it["source"] == "github" and it["size"] == len(BLOB),
      f"lee la release de GitHub: {it and it['label']}, {it and it['size']} bytes")
check(it and it["notes"].splitlines() == ["• Cola más rápida: todo va más rápido.", "• Corrección: SH040_RND_V01 renderiza."],
      f"notas en español sin Markdown: {it and it['notes']!r}")
i18n.set_lang("en")
it = github_updates.latest()
check(it and it["notes"].splitlines() == ["• Faster queue: everything is faster.", "• Fix: SH040_RND_V01 renders."],
      f"notas en inglés: {it and it['notes']!r}")
i18n.set_lang(lang or "es")

# prioridad: la carpeta manda si tiene la misma versión o una más nueva
cases = [("sin carpeta -> GitHub", "", True, ("github", "9.0.0")),
         ("carpeta con la misma versión -> carpeta", folder_with("9.0.0"), True, ("folder", "9.0.0")),
         ("carpeta más nueva -> carpeta", folder_with("9.1.0"), True, ("folder", "9.1.0")),
         ("carpeta más vieja -> GitHub", folder_with("8.0.0"), True, ("github", "9.0.0")),
         ("carpeta inaccesible -> GitHub", str(WORK / "no_existe"), True, ("github", "9.0.0")),
         ("GitHub desactivado -> solo carpeta", folder_with("8.0.0"), False, ("folder", "8.0.0"))]
for name, folder, use_gh, want in cases:
    hits = S["api_hits"]
    r = updater.find_update(folder, use_gh)
    got = (r["source"], r["label"]) if r else None
    asked = S["api_hits"] > hits
    check(got == want and asked == use_gh, f"{name}: {got} (consultó GitHub: {asked})")
reset(version=__version__)
check(updater.find_update("", True) is None, f"GitHub con la versión instalada ({__version__}) -> sin aviso")
reset(version="0.0.1")
check(updater.find_update(folder_with("8.0.0"), True)["label"] == "8.0.0", "GitHub más viejo que la carpeta -> carpeta")

# errores: siempre None, sin excepción y sin colgarse
for mode, extra in (("404", {}), ("403", {}), ("500", {}), ("basura", {}), ("sin_exe", {}), ("lenta", {"timeout": 1})):
    reset(api=mode)
    t0 = time.time()
    try:
        r, err = github_updates.latest(**extra), None
    except Exception as e:  # noqa: BLE001
        r, err = "excepción", e
    check(r is None, f"GitHub responde «{mode}»: se ignora en silencio ({time.time() - t0:.1f} s){' ' + str(err) if err else ''}")
saved = github_updates.GITHUB_API
github_updates.GITHUB_API = comun.NO_GITHUB
t0 = time.time()
check(github_updates.latest() is None and updater.find_update("", True) is None,
      f"sin red (nadie escucha): sin aviso ({time.time() - t0:.1f} s)")
github_updates.GITHUB_API = saved

# descarga: progreso, tamaño y SHA-256
reset()
item = github_updates.latest()
seen = []
path = github_updates.download(item, lambda d, t: seen.append((d, t)))
check(path == TEMP / "Frameguard-update" / SETUP and path.read_bytes() == BLOB,
      f"descarga completa en {path} ({path.stat().st_size} bytes, siguiendo la redirección)")
check(seen and seen[-1] == (len(BLOB), len(BLOB)) and all(a[0] < b[0] for a, b in zip(seen, seen[1:])),
      f"progreso creciente hasta el 100 % ({len(seen)} avisos)")
path.unlink()


def fails(text, it, cancel=None, **kw):
    reset(**kw)
    try:
        github_updates.download(it, cancel=cancel)
        check(False, f"{text}: no falló")
    except github_updates.UpdateError as e:
        left = list((TEMP / "Frameguard-update").glob("*"))
        check(not left, f"{text}: «{e}» (sin restos: {[p.name for p in left]})")


fails("se corta a mitad", item, download="cortada")
fails("tamaño distinto del que dice GitHub", {**item, "size": item["size"] + 10})
fails("SHA-256 distinto", {**item, "sha256": "0" * 64})
cancel = threading.Event()
cancel.set()
fails("cancelada", item, cancel=cancel)

# lanzar: el de GitHub ya está en %TEMP% (no se copia sobre sí mismo); el de la carpeta se copia antes
reset()
p = github_updates.download(item)
try:
    updater.launch_installer({**item, "path": str(p)})
    updater.launch_installer(updater.list_versions(folder_with("8.0.0"))[0])
    ok = (TEMP / "Frameguard-update" / "Frameguard-Setup-8.0.0.exe").exists()
except OSError as e:
    ok = False
    print("   ", e)
check(ok, "lanzar el instalador (modo prueba): desde GitHub y desde la carpeta")
shutil.rmtree(TEMP / "Frameguard-update")

# --- 2. la ventana (el .exe compilado con --exe)
P = Prueba("actualizaciones_ui", 47886, exe, lang)
P.env.update({"FRAMEGUARD_GITHUB_API": API, "FRAMEGUARD_DRY_UPDATE": "1", "TEMP": str(TEMP), "TMP": str(TEMP),
              "TMPDIR": str(TEMP)})
P.close()
P.start_engine()  # con el entorno de la prueba
OUT = WORK / "capturas"
OUT.mkdir()


def window(name, delay=6000, **extra_env):
    target = OUT / f"{name}.png"
    env = {**P.env, "FRAMEGUARD_SCREENSHOT": str(target), "FRAMEGUARD_SCREENSHOT_DELAY": str(delay), **extra_env}
    rc = subprocess.run(P.cmd(), cwd=str(PROJ), env=env, timeout=120).returncode
    j = Path(str(target) + ".json")
    return rc, (json.loads(j.read_text(encoding="utf-8")) if j.exists() else None)


# a) GitHub desactivado y sin carpeta: ni se consulta
reset()
P.send("settings", values={"update_github": False, "update_folder": ""})
hits = S["api_hits"]
rc, res = window("sin_github")
check(rc == 0 and res and not res["banner"] and S["api_hits"] == hits,
      f"casilla de GitHub apagada: sin aviso y sin consultar (consultas: {S['api_hits'] - hits})")

# b) la carpeta tiene la misma versión que GitHub: el aviso es el de la carpeta
P.send("settings", values={"update_github": True, "update_folder": folder_with("9.0.0")})
hits = S["api_hits"]
rc, res = window("carpeta_manda")
check(rc == 0 and res and NEW in res["banner"] and res["update_source"] == "folder" and S["api_hits"] > hits,
      f"carpeta con la misma versión: aviso de la carpeta ({res and res['update_source']}: {res and res['banner'][:70]!r})")

# c) solo GitHub: aviso, «Actualizar ahora», descarga con progreso y lanza el instalador
P.send("settings", values={"update_folder": ""})
reset(slow=0.05)  # unos 2,5 s de descarga para ver la barra
dl = S["dl_hits"]
rc, res = window("github", delay=15000, FRAMEGUARD_SCREENSHOT_UPDATE="1")
log = (P.home / "ui.log").read_text(encoding="utf-8")
got = TEMP / "Frameguard-update" / SETUP
check(rc == 0 and res is None, f"la ventana se cerró sola para instalar (código {rc})")
check(S["dl_hits"] == dl + 1 and got.exists() and got.read_bytes() == BLOB,
      f"descargó el instalador entero a {got} ({got.stat().st_size if got.exists() else 0} bytes)")
check((OUT / "github_descarga.png").exists(), "se vio la barra de progreso (captura github_descarga.png)")
check("Actualización descargada de GitHub" in log and f"FRAMEGUARD_DRY_UPDATE: no se ejecuta {got} /SILENT" in log,
      "ui.log: descargado y lanzado el instalador (modo prueba)")
time.sleep(2)
check(P.engine.poll() is not None, "el motor se cerró para dejar instalar")

# d) la cola arranca mientras se descarga: el instalador queda descargado, pero no se ejecuta
P.start_engine()
lento = P.copy_fixture("lento.blend")
P.send("add", paths=[str(lento)], test={"output_root": str(P.home / "out"), "debug_slow_frame_seconds": 2})
P.wait_reading()
got.unlink(missing_ok=True)
reset(slow=0.15)  # unos 7 s de descarga
dl = S["dl_hits"]
target = OUT / "arranca.png"
ui = subprocess.Popen(P.cmd(), cwd=str(PROJ), env={**P.env, "FRAMEGUARD_SCREENSHOT": str(target),
                                                    "FRAMEGUARD_SCREENSHOT_DELAY": "20000",
                                                    "FRAMEGUARD_SCREENSHOT_UPDATE": "1"})
for _ in range(300):
    if S["dl_hits"] > dl:
        break
    time.sleep(0.1)
P.send("start")
rc = ui.wait(timeout=120)
log = (P.home / "ui.log").read_text(encoding="utf-8")
res = json.loads(Path(str(target) + ".json").read_text(encoding="utf-8")) if Path(str(target) + ".json").exists() else None
check(rc == 0 and res and got.exists() and log.count("Actualización aplazada: la cola está renderizando") == 1
      and log.count("FRAMEGUARD_DRY_UPDATE") == 1 and P.engine.poll() is None and P.api("/api/state")["running_job"],
      f"la cola arrancó durante la descarga: descargado, pero no se instala y el render sigue "
      f"(mensaje capturado: {(OUT / 'arranca_dialogo.png').exists()})")

# e) con un render en marcha: el botón está apagado y, por otro camino (Versiones…), tampoco se descarga nada
got.unlink(missing_ok=True)
reset()
dl = S["dl_hits"]
rc, res = window("renderizando", delay=8000, FRAMEGUARD_SCREENSHOT_UPDATE="1")
refused = (P.home / "ui.log").read_text(encoding="utf-8").count("Actualización aplazada: la cola está renderizando")
check(rc == 0 and res and res["banner"] and not res["update_enabled"] and not res["downloading"]
      and S["dl_hits"] == dl and not got.exists() and refused == 2,
      f"render en marcha: «Actualizar ahora» apagado, no descarga ni instala (descargas: {S['dl_hits'] - dl}, "
      f"mensaje capturado: {(OUT / 'renderizando_dialogo.png').exists()})")
kill_ui(exe)
errs = P.errors()
P.close()
srv.shutdown()
print("errores en los logs:", {k: v for k, v in errs.items() if v} or "ninguno")
print("capturas en:", OUT)
print("PRUEBA SUPERADA" if all(results) and not any(errs.values()) else "PRUEBA CON FALLOS")

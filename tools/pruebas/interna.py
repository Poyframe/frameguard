"""Edición interna (build.ps1 -SinGitHub): nunca consulta GitHub y se actualiza solo desde la carpeta de la red.

Un servidor local hace de «GitHub» y cuenta cada petición que recibe. Con una versión nueva en la carpeta y la
casilla de GitHub activada en los ajustes guardados, la edición interna debe:
- avisar de la versión de la carpeta,
- no hacer NINGUNA petición a «GitHub»,
- no mostrar la casilla de GitHub en Ajustes y mostrar sus propias Novedades.

    python tools/pruebas/interna.py --exe dist\\Frameguard\\Frameguard.exe   (compilado con build.ps1 -SinGitHub)
    python tools/pruebas/interna.py                                          (desarrollo: simula la edición)
"""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from comun import PROJ, Prueba, args

sys.stdout.reconfigure(encoding="utf-8")
exe, lang = args()
hits = []


class FakeGitHub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        hits.append(self.path)
        body = json.dumps({"tag_name": "v9.9.9", "assets": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
threading.Thread(target=srv.serve_forever, daemon=True).start()

control = "--control" in sys.argv  # edición PÚBLICA: el falso GitHub SÍ debe recibir peticiones (valida la prueba)
P = Prueba("interna", 47885, exe, lang, seen_version="0.1.9")  # 0.1.9 vista: salen las Novedades de esta versión
P.env["FRAMEGUARD_GITHUB_API"] = f"http://127.0.0.1:{srv.server_port}/repos/x/frameguard/releases/latest"
if not exe and not control:
    P.env["FRAMEGUARD_SIN_GITHUB"] = "1"
folder = P.dir / "carpeta_red"
folder.mkdir(exist_ok=True)
(folder / "Frameguard-Setup-9.0.0.exe").write_bytes(b"instalador de prueba")
P.send("settings", values={"update_folder": str(folder), "update_github": True})

out = P.dir / "capturas"
out.mkdir(exist_ok=True)
target = out / "interna.png"
env = {**P.env, "FRAMEGUARD_SCREENSHOT": str(target), "FRAMEGUARD_SCREENSHOT_DELAY": "7000",
       "FRAMEGUARD_SCREENSHOT_SETTINGS": "1", "FRAMEGUARD_SCREENSHOT_WHATSNEW": "1"}
rc = subprocess.run(P.cmd(), cwd=str(PROJ), env=env, timeout=90).returncode
res = json.loads(Path(str(target) + ".json").read_text(encoding="utf-8"))
aj = json.loads(Path(str(target) + ".ajustes.json").read_text(encoding="utf-8"))
errs = P.errors()
P.close()
srv.shutdown()

if control:
    ok = bool(hits) and aj["github_checkbox"]
    print(("OK  " if ok else "MAL ") + f"control (edición pública): peticiones a «GitHub» {hits}, casilla "
          f"{'visible' if aj['github_checkbox'] else 'ausente'}")
    print("CONTROL SUPERADO" if ok else "CONTROL CON FALLOS")
    sys.exit(0)
checks = [
    (rc == 0 and res["connected"], f"la ventana arrancó y conectó (código {rc})"),
    ("9.0.0" in res.get("banner", "") and res.get("update_source") == "folder",
     f"avisa de la versión de la carpeta: {res.get('banner')!r} (origen {res.get('update_source')})"),
    (not hits, f"ninguna petición a «GitHub» (recibidas: {hits})"),
    (not aj["github_checkbox"], "Ajustes no muestra la casilla de GitHub"),
    ((out / "interna_novedades.png").exists(), "Novedades de esta versión (ver interna_novedades.png)"),
    (not any(errs.values()), f"sin errores en los logs {({k: v for k, v in errs.items() if v}) or ''}"),
]
for ok, text in checks:
    print(("OK  " if ok else "MAL ") + text)
print("capturas en:", out)
print("PRUEBA SUPERADA" if all(ok for ok, _ in checks) else "PRUEBA CON FALLOS")

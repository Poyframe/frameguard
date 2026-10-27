"""Utilidades compartidas por las pruebas de Frameguard (tools/pruebas/*.py).

Cada prueba trabaja en %TEMP%\\frameguard_pruebas\\<nombre>: su propio motor (puerto propio), su propia carpeta
de datos (FRAMEGUARD_HOME) y sus propias preferencias de ventana. Nunca toca la cola, los ajustes ni el registro
del usuario. El .blend de prueba se genera con tools/make_fixture.py si no existe.

Uso típico:  python tools/pruebas/capturas.py [--exe dist\\Frameguard\\Frameguard.exe] [--lang en]
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("TEMP", PROJ)) / "frameguard_pruebas"
PY = PROJ / ".venv" / "Scripts" / "python.exe"
BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
NO_GITHUB = "http://127.0.0.1:9/sin-red"  # las pruebas nunca consultan el GitHub real (en el puerto 9 nadie escucha)
sys.path.insert(0, str(PROJ))


def fixture() -> Path:
    """El .blend de prueba (Workbench 160x90, frames 1-12, File Output BEAUTY y CRYPTO)."""
    f = WORK / "fixture" / "fg_test.blend"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(BLENDER), "-b", "--factory-startup", "--python", str(PROJ / "tools" / "make_fixture.py"),
                        "--", str(f)], check=True, capture_output=True, timeout=300)
    return f


class Prueba:
    """Motor de prueba + carpeta de datos propia. exe=None usa el código fuente (modo desarrollo)."""

    def __init__(self, name: str, port: int, exe: str | None = None, lang: str | None = None,
                 seen_version: str | None = "9.9.9"):
        self.exe, self.port = exe, port
        self.dir = WORK / name
        self.home = self.dir / "home"
        if self.home.exists():
            shutil.rmtree(self.home)
        self.home.mkdir(parents=True)
        if seen_version:  # Novedades ya vistas: si no, su ventana modal tapa la principal
            (self.home / "ventana.ini").write_text(f"[General]\nlast_seen_version={seen_version}\n", encoding="utf-8")
        self.env = {**os.environ, "FRAMEGUARD_HOME": str(self.home), "FRAMEGUARD_DRY_POWER": "1",
                    "FRAMEGUARD_THEME": "dark", "FRAMEGUARD_GITHUB_API": NO_GITHUB}
        if lang:
            self.env["FRAMEGUARD_LANG"] = lang
        self.start_engine()

    def start_engine(self):
        self.engine = subprocess.Popen(self.cmd("--engine"), cwd=str(PROJ), env=self.env)
        for _ in range(80):
            try:
                self.api("/api/ping")
                return
            except OSError:
                time.sleep(0.25)

    def cmd(self, *extra) -> list[str]:
        base = [self.exe] if self.exe else [str(PY), "-m", "frameguard"]
        return [*base, *extra, "--port", str(self.port)]

    def api(self, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def send(self, cmd: str, **values) -> dict:
        return self.api("/api/cmd", {"cmd": cmd, **values})

    def jobs(self) -> list[dict]:
        return self.api("/api/state")["jobs"]

    def wait_reading(self):
        while any(j["status"] == "reading" for j in self.jobs()):
            time.sleep(0.3)

    def copy_fixture(self, rel: str) -> Path:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fixture(), p)
        return p

    def errors(self) -> dict:
        out = {}
        for log in ("ui.log", "engine.log"):
            f = self.home / log
            if f.exists():
                out[log] = [l for l in f.read_text(encoding="utf-8").splitlines() if " ERROR " in l or "Traceback" in l]
        return out

    def close(self):
        try:
            self.send("pause")
            time.sleep(0.5)
            self.send("quit")
            self.engine.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            self.engine.kill()


# ---------------------------------------------------------------- ventanas de Windows
u32 = ctypes.windll.user32


def image_of(pid: int) -> str:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)
    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(1024)
    k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    k32.CloseHandle(h)
    return buf.value.lower()


def windows_of(exe: str | None) -> list[tuple[int, str]]:
    """Ventanas visibles de la Frameguard de la prueba. En modo desarrollo el proceso lanzado es un intermediario
    de Python, así que se busca por ejecutable (python del venv o el .exe probado), nunca la Frameguard instalada."""
    want = os.path.normcase(exe).lower() if exe else "python"
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        buf = ctypes.create_unicode_buffer(200)
        u32.GetWindowTextW(h, buf, 200)
        if u32.IsWindowVisible(h) and buf.value and pid.value != os.getpid():
            img = image_of(pid.value)
            if (img == want) if exe else (want in img):
                out.append((h, buf.value))
        return True
    u32.EnumWindows(cb, 0)
    return out


def kill_ui(exe: str | None):
    """Cierra las ventanas de Frameguard del .exe probado que sigan vivas (p. ej. escondidas en la bandeja
    porque había un render en marcha). Solo las de ese .exe: nunca la Frameguard instalada ni el motor."""
    if not exe:
        return
    ps = (f"Get-CimInstance Win32_Process -Filter \"Name='{Path(exe).name}'\" | Where-Object {{ "
          f"$_.ExecutablePath -eq '{exe}' -and $_.CommandLine -notlike '*--engine*' }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60)


def args() -> tuple[str | None, str | None]:
    """--exe <ruta> y --lang <es|en> de la línea de comandos."""
    a = sys.argv[1:]
    exe = a[a.index("--exe") + 1] if "--exe" in a else None
    lang = a[a.index("--lang") + 1] if "--lang" in a else None
    return (str(Path(exe).resolve()) if exe else None), lang

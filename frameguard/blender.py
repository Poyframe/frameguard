"""Todo lo que habla con blender.exe: detectar instalaciones, leer un .blend y armar el comando de render."""
import json
import os
import re
import subprocess
from pathlib import Path

from . import paths, util
from .i18n import tr

CREATE_NO_WINDOW = 0x08000000
SAFETY_EXIT_CODE = 87  # Blender sale con este código si el script de arranque falla


def detect_blenders() -> list[dict]:
    """Instalaciones en 'Program Files\\Blender Foundation', de la más nueva a la más vieja."""
    roots = {Path(os.environ.get(v, "")) / "Blender Foundation"
             for v in ("ProgramFiles", "ProgramW6432") if os.environ.get(v)}
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for d in root.iterdir():
            exe = d / "blender.exe"
            if exe.is_file():
                m = re.search(r"(\d+)\.(\d+)", d.name)
                ver = [int(m.group(1)), int(m.group(2))] if m else [0, 0]
                found.append({"path": str(exe), "label": d.name, "version": ver})
    found.sort(key=lambda b: b["version"], reverse=True)
    return found


def _last_lines(text: str, n: int = 12) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip() and "GPUShader" not in ln and "gpu.init" not in ln]
    return "\n".join(lines[-n:])


def inspect_blend(blender: str, blend_path: str, scene: str | None = None, timeout: int = 900) -> dict:
    """Lee los datos del .blend con Blender en segundo plano (sin add-ons, sin guardar nada)."""
    cmd = [blender, "-b", "--factory-startup", blend_path]
    if scene:
        cmd += ["-S", scene]
    cmd += ["--python-exit-code", str(SAFETY_EXIT_CODE), "--python", str(paths.blender_script("fg_inspect.py"))]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
                          stdin=subprocess.DEVNULL)
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    for line in out.splitlines():
        if line.startswith("@@FG|INFO|"):
            return json.loads(line[len("@@FG|INFO|"):])
    for line in out.splitlines():
        if line.startswith("@@FG|ERROR|"):
            msg = json.loads(line[len("@@FG|ERROR|"):]).get("msg", "")
            raise RuntimeError(msg.strip().splitlines()[-1] if msg.strip() else tr("Error leyendo el archivo"))
    raise RuntimeError(_last_lines(out) or tr("Blender terminó con código {rc} sin leer el archivo", rc=proc.returncode))


def render_command(blender: str, blend_path: str, scene: str | None, frames: list[int], step: int,
                   cfg_path: Path) -> tuple[list[str], int]:
    """Comando de render por tramos contiguos (-s/-e/-a), que respeta Persistent Data de Cycles.
    Devuelve (comando, número de tramos)."""
    cmd = [blender, "-b", blend_path]
    if scene:
        cmd += ["-S", scene]
    cmd += ["--python-exit-code", str(SAFETY_EXIT_CODE),
            "--python", str(paths.blender_script("fg_render_bootstrap.py"))]
    ranges = util.to_ranges(frames, step)
    for a, b in ranges:
        cmd += ["-s", str(a), "-e", str(b), "-j", str(step), "-a"]
    cmd += ["--", "--fg-config", str(cfg_path)]
    return cmd, len(ranges)


def blender_version_label(path: str) -> str:
    m = re.search(r"Blender\s*(\d+\.\d+)", path, re.I)
    return f"Blender {m.group(1)}" if m else "Blender"

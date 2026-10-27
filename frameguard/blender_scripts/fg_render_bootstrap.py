"""Frameguard: se ejecuta DENTRO de Blender antes de renderizar.

Nunca guarda el .blend: todos los cambios viven solo en la memoria de esta sesión de render.

Uso (lo arma el motor de Frameguard; --python-exit-code hace que Blender se cierre sin renderizar
si este script falla):
    blender -b archivo.blend -S Escena --python-exit-code 87 --python fg_render_bootstrap.py
            -s 101 -e 200 -a  [-s 210 -e 250 -a ...]  -- --fg-config cfg.json

Config JSON (todas las claves son opcionales):
    disable_save_output  bool   apaga render.save_output (Save Output) si hay File Outputs
    resolution_pct       int    sobrescribe render.resolution_percentage (renders de prueba)
    samples              int    sobrescribe las samples del engine (renders de prueba)
    output_root          str    redirige TODAS las salidas a esta carpeta (renders de prueba)
    segments             int    cuántos tramos -s/-e/-a se renderizan (para saber cuándo terminó todo)
    attempt              int    número de intento
    debug_hang_at_end    bool   PRUEBAS: se cuelga al terminar el último tramo (el fallo de BRC)
    debug_crash_frame    int    PRUEBAS: se cae tras ese frame, solo en el intento 1
    debug_stall_frame    int    PRUEBAS: se congela sin imprimir nada en ese frame, solo en el intento 1

Marcadores en stdout (una línea cada uno, con flush):
    @@FG|BOOT|{json}         escena, salidas resueltas y ajustes aplicados (el motor no deja
                             renderizar nada antes de recibirlo)
    @@FG|FRAME_START|{json}  empieza un frame
    @@FG|FRAME_DONE|{json}   terminó un frame (render_post llega DESPUÉS de escribir los archivos)
    @@FG|COMPLETE|{json}     terminó un tramo -s/-e/-a
    @@FG|CANCEL              render cancelado
    @@FG|ERROR|{json}        error dentro de este script
"""
import json
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from fg_common import describe_outputs, file_output_nodes  # noqa: E402


def emit(kind, payload=None):
    line = "@@FG|" + kind
    if payload is not None:
        line += "|" + json.dumps(payload, ensure_ascii=False, default=str)
    print(line, flush=True)


def read_config():
    """Lee la config. Si se pidió y no se puede leer, lanza excepción para que Blender se cierre
    (gracias a --python-exit-code) ANTES de renderizar nada."""
    argv = sys.argv
    if "--" not in argv:
        return {}
    rest = argv[argv.index("--") + 1:]
    if "--fg-config" not in rest:
        return {}
    with open(rest[rest.index("--fg-config") + 1], encoding="utf-8-sig") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("fg-config debe ser un objeto JSON")
    return cfg


def apply_overrides(scene, cfg):
    r = scene.render
    applied = {}
    if cfg.get("disable_save_output") and getattr(r, "save_output", False) and file_output_nodes(scene):
        applied["save_output"] = [True, False]
        r.save_output = False
    if cfg.get("resolution_pct"):
        applied["resolution_pct"] = [r.resolution_percentage, int(cfg["resolution_pct"])]
        r.resolution_percentage = int(cfg["resolution_pct"])
    if cfg.get("samples"):
        s = int(cfg["samples"])
        if r.engine == "CYCLES":
            applied["samples"] = [scene.cycles.samples, s]
            scene.cycles.samples = s
        elif hasattr(scene, "eevee"):
            applied["samples"] = [scene.eevee.taa_render_samples, s]
            scene.eevee.taa_render_samples = s
    root = cfg.get("output_root")
    if root:
        for n in file_output_nodes(scene):
            new_dir = os.path.join(root, n.name) + os.sep
            os.makedirs(new_dir, exist_ok=True)
            if hasattr(n, "directory"):
                n.directory = new_dir
            else:
                n.base_path = new_dir
        if getattr(r, "save_output", False):
            os.makedirs(os.path.join(root, "SaveOutput"), exist_ok=True)
            r.filepath = os.path.join(root, "SaveOutput", "frame_")
        applied["output_root"] = root
    return applied


def pattern_path(pattern, frame):
    """Igual que util.pattern_path del motor: la última serie de '#' del nombre es el frame."""
    head, tail = os.path.split(pattern)
    runs = list(re.finditer(r"#+", tail))
    if not runs:
        return pattern
    m = runs[-1]
    num = ("-" if frame < 0 else "") + str(abs(frame)).zfill(m.end() - m.start())
    return os.path.join(head, tail[:m.start()] + num + tail[m.end():])


def mtime_or_none(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def main():
    cfg = read_config()
    scene = bpy.context.scene
    applied = apply_overrides(scene, cfg)
    attempt = int(cfg.get("attempt", 1))
    state = {"completes": 0, "before": {}}
    outputs = describe_outputs(scene)
    patterns = [p for o in outputs for p in o["patterns"]]

    def on_pre(sc, *_):
        frame = sc.frame_current
        # Foto de los archivos ANTES de renderizar, tomada aquí (sincrónica con Blender) para que el
        # motor pueda exigir archivos recién escritos sin carreras de tiempos.
        before = {pattern_path(p, frame): mtime_or_none(pattern_path(p, frame)) for p in patterns}
        state["before"][frame] = before
        emit("FRAME_START", {"frame": frame, "t": time.time(), "before": before})
        if cfg.get("debug_slow_frame_seconds"):
            time.sleep(float(cfg["debug_slow_frame_seconds"]))  # PRUEBAS: frames lentos
        if cfg.get("debug_stall_frame") == frame and attempt == 1:
            while True:  # PRUEBAS: congelado sin imprimir nada
                time.sleep(60)

    def on_post(sc, *_):
        frame = sc.frame_current
        files = []
        for path, old in state["before"].pop(frame, {}).items():
            new = mtime_or_none(path)
            size = os.path.getsize(path) if new is not None else 0
            files.append({"path": path, "size": size, "fresh": new is not None and new != old})
        emit("FRAME_DONE", {"frame": frame, "t": time.time(), "files": files})
        if cfg.get("debug_crash_frame") == frame and attempt == 1:
            emit("ERROR", {"msg": "debug_crash_frame: simulando caída de Blender"})
            os._exit(3)

    def on_complete(sc, *_):
        state["completes"] += 1
        emit("COMPLETE", {"segment": state["completes"]})
        if cfg.get("debug_hang_at_end") and state["completes"] >= int(cfg.get("segments", 1)):
            print("debug_hang_at_end: Blender se queda colgado a propósito", flush=True)
            while True:
                time.sleep(60)

    def on_cancel(sc, *_):
        emit("CANCEL")

    h = bpy.app.handlers
    h.render_pre.append(on_pre)
    h.render_post.append(on_post)
    h.render_complete.append(on_complete)
    h.render_cancel.append(on_cancel)

    r = scene.render
    emit("BOOT", {
        "blender": bpy.app.version_string,
        "file": bpy.data.filepath,
        "scene": scene.name,
        "engine": r.engine,
        "resolution": [r.resolution_x, r.resolution_y, r.resolution_percentage],
        "camera": scene.camera.name if scene.camera else None,
        "save_output": getattr(r, "save_output", None),
        "outputs": outputs,
        "applied": applied,
        "attempt": attempt,
        "pid": os.getpid(),
    })


try:
    main()
except Exception:
    emit("ERROR", {"msg": traceback.format_exc()})
    raise

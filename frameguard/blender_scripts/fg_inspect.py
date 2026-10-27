"""Frameguard: lee los datos de un .blend SIN modificarlo (se lanza con --factory-startup).

    blender -b --factory-startup archivo.blend --python-exit-code 87 --python fg_inspect.py

Imprime una sola línea:  @@FG|INFO|{json}
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from fg_common import describe_outputs  # noqa: E402


def _exists(path):
    try:
        return os.path.exists(path)
    except (OSError, ValueError):
        return False


def missing_images():
    out = []
    for img in bpy.data.images:
        if img.users == 0 or img.packed_file or img.source not in {"FILE", "SEQUENCE", "MOVIE", "TILED"}:
            continue
        if not img.filepath:
            continue
        path = bpy.path.abspath(img.filepath, library=img.library)
        if img.source == "TILED":
            # UDIM: basta con que exista alguno de sus tiles
            nums = [t.number for t in img.tiles] or [1001]
            cands = []
            for n in nums:
                u, v = (n - 1001) % 10 + 1, (n - 1001) // 10 + 1
                cands.append(path.replace("<UDIM>", str(n)).replace("<UVTILE>", f"u{u}_v{v}"))
            if not any(_exists(c) for c in cands):
                out.append({"name": img.name, "path": cands[0]})
            continue
        if not _exists(path):
            out.append({"name": img.name, "path": path})
    return out


def missing_libraries():
    return [{"name": lib.name, "path": bpy.path.abspath(lib.filepath)}
            for lib in bpy.data.libraries if not _exists(bpy.path.abspath(lib.filepath))]


def missing_caches():
    out = []
    for cf in getattr(bpy.data, "cache_files", []):
        path = bpy.path.abspath(cf.filepath, library=cf.library)
        if cf.filepath and not _exists(path):
            out.append({"name": cf.name, "path": path})
    return out


def main():
    sc = bpy.context.scene
    r = sc.render
    samples = None
    if r.engine == "CYCLES":
        samples = sc.cycles.samples
    elif hasattr(sc, "eevee"):
        samples = sc.eevee.taa_render_samples
    info = {
        "blender": bpy.app.version_string,
        "blender_version": list(bpy.app.version),
        "file_version": list(bpy.data.version),
        "file": bpy.data.filepath,
        "scenes": [s.name for s in bpy.data.scenes],
        "scene": sc.name,
        "engine": r.engine,
        "frame_start": sc.frame_start,
        "frame_end": sc.frame_end,
        "frame_step": sc.frame_step,
        "fps": round(r.fps / r.fps_base, 3),
        "resolution": [r.resolution_x, r.resolution_y, r.resolution_percentage],
        "camera": sc.camera.name if sc.camera else None,
        "samples": samples,
        "save_output": getattr(r, "save_output", None),
        "use_compositing": getattr(r, "use_compositing", None),
        "view_layers": [vl.name for vl in sc.view_layers if vl.use],
        "outputs": describe_outputs(sc),
        "missing_images": missing_images(),
        "missing_libraries": missing_libraries(),
        "missing_caches": missing_caches(),
    }
    print("@@FG|INFO|" + json.dumps(info, ensure_ascii=False, default=str), flush=True)


try:
    main()
except Exception:
    print("@@FG|ERROR|" + json.dumps({"msg": traceback.format_exc()}, ensure_ascii=False), flush=True)
    raise

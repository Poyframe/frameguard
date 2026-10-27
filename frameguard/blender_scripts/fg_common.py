"""Funciones compartidas por los scripts de Frameguard que corren DENTRO de Blender.

Patrones de salida: rutas absolutas donde la ÚLTIMA serie de '#' del nombre de archivo representa
el número de frame (con su relleno de ceros). Reglas verificadas en Blender 5.2:
  - File Output multilayer:  directorio + file_name + ext            ("SH_BEAUTY_" -> "SH_BEAUTY_0101.exr")
  - File Output imagen:      directorio + file_name + item + ext     ("plain_"     -> "plain_Image0007.exr")
  - Si el nombre no tiene '#', Blender añade 4 dígitos al final; si los tiene, los reemplaza.
  - Video: no se puede verificar por frame (sin patrones).
"""
import os

import bpy

EXT_BY_FORMAT = {
    "OPEN_EXR": ".exr", "OPEN_EXR_MULTILAYER": ".exr", "PNG": ".png", "JPEG": ".jpg",
    "JPEG2000": ".jp2", "TIFF": ".tif", "TARGA": ".tga", "TARGA_RAW": ".tga", "BMP": ".bmp",
    "HDR": ".hdr", "DPX": ".dpx", "CINEON": ".cin", "WEBP": ".webp", "IRIS": ".rgb",
}


def compositor_tree(scene):
    return getattr(scene, "compositing_node_group", None) or getattr(scene, "node_tree", None)


def iter_nodes(tree, seen=None):
    """Recorre los nodos entrando en grupos (el compositor de 5.x usa node groups)."""
    seen = seen if seen is not None else set()
    if tree is None or tree.as_pointer() in seen:
        return
    seen.add(tree.as_pointer())
    for node in tree.nodes:
        yield node
        sub = getattr(node, "node_tree", None)
        if sub is not None:
            yield from iter_nodes(sub, seen)


def file_output_nodes(scene):
    if not getattr(scene.render, "use_compositing", True):
        return []
    return [n for n in iter_nodes(compositor_tree(scene))
            if n.bl_idname == "CompositorNodeOutputFile" and not n.mute]


def node_items(node):
    items = getattr(node, "file_output_items", None)
    if items is None:
        items = getattr(node, "file_slots", None) or []
    return [getattr(it, "name", None) or getattr(it, "path", "") for it in items]


def _with_frame_marker(base):
    return base if "#" in base else base + "####"


def describe_outputs(scene):
    """Lista las salidas que escribirá el render, con sus patrones de archivo por frame."""
    outs = []
    for n in file_output_nodes(scene):
        fmt = n.format
        ff = fmt.file_format
        media = getattr(fmt, "media_type", "")
        directory = bpy.path.abspath(getattr(n, "directory", "") or getattr(n, "base_path", ""))
        directory = os.path.normpath(directory) if directory else ""
        ext = EXT_BY_FORMAT.get(ff, "")
        file_name = getattr(n, "file_name", "")
        items = node_items(n)
        multilayer = ff == "OPEN_EXR_MULTILAYER"
        if media == "VIDEO":
            patterns = []
        elif multilayer:
            patterns = [os.path.join(directory, _with_frame_marker(file_name) + ext)]
        else:
            patterns = [os.path.join(directory, _with_frame_marker(file_name + it) + ext) for it in items]
        outs.append({
            "kind": "file_output", "node": n.name, "directory": directory, "file_name": file_name,
            "format": ff, "media_type": media, "multilayer": multilayer, "items": items,
            "patterns": patterns,
        })

    r = scene.render
    if getattr(r, "save_output", True):
        img = r.image_settings
        tpl = r.frame_path(frame=1234567)
        p7 = r.frame_path(frame=7)
        pad = max(1, len(p7) - len(tpl) + 7)
        video = getattr(img, "media_type", "") == "VIDEO"
        patterns = [] if video or "1234567" not in tpl else [tpl.replace("1234567", "#" * pad)]
        outs.append({
            "kind": "main", "node": "Save Output", "directory": os.path.dirname(tpl),
            "file_name": os.path.basename(r.filepath), "format": img.file_format,
            "media_type": getattr(img, "media_type", ""), "multilayer": img.file_format == "OPEN_EXR_MULTILAYER",
            "items": [], "patterns": patterns,
        })
    return outs

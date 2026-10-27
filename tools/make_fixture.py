"""Crea el .blend de prueba de Frameguard (se ejecuta DENTRO de Blender 5.2):

    blender -b --factory-startup --python tools/make_fixture.py -- <salida.blend>

Escena mínima y rápida de renderizar: Workbench, 160x90, frames 1-12, Save Output apagado y la salida por
dos nodos File Output del compositor (BEAUTY en EXR multicapa y CRYPTO en PNG), como en producción.
Las pruebas redirigen esas salidas a una carpeta temporal (override «output_root» del arranque)."""
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1]
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x, scene.render.resolution_y = 160, 90
scene.render.resolution_percentage = 100
scene.frame_start, scene.frame_end = 1, 12
scene.render.filepath = "//render/main_"
scene.render.use_file_extension = True
if hasattr(scene.render, "save_output"):
    scene.render.save_output = False
cube = bpy.data.objects.get("Cube")
if cube is not None:  # algo que se mueva, para que cada frame sea distinto
    cube.rotation_euler = (0, 0, 0)
    cube.keyframe_insert("rotation_euler", frame=1)
    cube.rotation_euler = (0, 0, 3.14)
    cube.keyframe_insert("rotation_euler", frame=12)

tree = bpy.data.node_groups.new("FG_Compositor", "CompositorNodeTree")
scene.compositing_node_group = tree
rl = tree.nodes.new("CompositorNodeRLayers")
for name, media, fmt, x in (("BEAUTY", "MULTI_LAYER_IMAGE", "OPEN_EXR_MULTILAYER", 300),
                            ("CRYPTO", "IMAGE", "PNG", 300)):
    node = tree.nodes.new("CompositorNodeOutputFile")
    node.name = node.label = name
    node.location = (x, 0 if name == "BEAUTY" else -250)
    node.directory = f"//render/{name}/"
    node.file_name = f"fg_test_{name}_"
    node.format.media_type = media  # primero el tipo de medio; si no, el formato no se puede cambiar
    node.format.file_format = fmt
    item = node.file_output_items.new("RGBA", "Image")
    tree.links.new(rl.outputs["Image"], node.inputs[item.name])
bpy.ops.wm.save_as_mainfile(filepath=out, check_existing=False)
print("FIXTURE_OK", out)

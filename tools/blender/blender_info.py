"""Prints the Blender/Python versions and checks that the glTF exporter + numpy are available (npm run assets:info)."""
import sys

import bpy

print("[AF] Blender", bpy.app.version_string, "| Python", sys.version.split()[0])
try:
    import numpy

    print("[AF] numpy", numpy.__version__)
except Exception as exc:  # pragma: no cover
    print("[AF] numpy MISSING:", exc)
print("[AF] glTF exporter operator:", hasattr(bpy.ops.export_scene, "gltf"))

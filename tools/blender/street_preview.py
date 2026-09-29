"""Preview helpers for the street kit: a sunset lighting rig closer to the game's look (low warm sun, cool fill, AgX view).

`use_sunset()` monkey-patches common.setup_preview_scene so that common.render_views() renders with it.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import common
from common import make_material


def sunset_scene(sun_elevation=7.0, sun_azimuth=215.0, ground=True, bg_strength=1.0, **_):
    scene = bpy.context.scene
    world = bpy.data.worlds.new("SunsetWorld")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 0.55
    try:
        sky = nt.nodes.new("ShaderNodeTexSky")
        sky.sky_type = "MULTIPLE_SCATTERING"
        sky.sun_elevation = math.radians(sun_elevation)
        sky.sun_rotation = math.radians(sun_azimuth)
        sky.sun_size = math.radians(1.2)
        sky.sun_intensity = 0.35
        sky.air_density = 1.4
        sky.dust_density = 2.2
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    except Exception:
        bg.inputs["Color"].default_value = (0.35, 0.22, 0.25, 1.0)
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    sun = bpy.data.lights.new("PV_Sun", "SUN")
    sun.energy = 4.2
    sun.color = (1.0, 0.58, 0.32)
    sun.angle = math.radians(2.0)
    so = bpy.data.objects.new("PV_Sun", sun)
    scene.collection.objects.link(so)
    so.rotation_euler = (math.radians(90 - sun_elevation), 0, math.radians(sun_azimuth + 180))
    fill = bpy.data.lights.new("PV_Fill", "SUN")
    fill.energy = 0.55
    fill.color = (0.45, 0.55, 0.95)
    fo = bpy.data.objects.new("PV_Fill", fill)
    scene.collection.objects.link(fo)
    fo.rotation_euler = (math.radians(55), 0, math.radians(sun_azimuth))
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.exposure = 0.0
    except Exception:
        pass
    extra = []
    if ground:
        bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 0, 0))
        gp = bpy.context.active_object
        gp.name = "PV_Ground"
        gp.data.materials.append(make_material("PV_GroundMat", "#2E2E33", 0.0, 0.92))
        extra.append(gp)
    return extra


def use_sunset():
    common.setup_preview_scene = sunset_scene

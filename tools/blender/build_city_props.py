"""Armored Flight - street / rooftop props  ->  public/assets/city_props.glb

Top-level roots (Empties at the ground centre of each prop, facing +Y Blender = -Z glTF, children = meshes / wheels):
  contract : Prop_StreetLamp, Prop_Car_A (sedan), Prop_Car_B (SUV), Prop_Car_C (pickup), Prop_Barrier_Jersey, Prop_Barrier_Striped,
             Prop_Antenna, Prop_AC_Unit_A, Prop_AC_Unit_B, Prop_Vent_Stack, Prop_Roof_Access, Prop_Cooling_Tower, Prop_Solar_Array
  extras   : Prop_Hydrant, Prop_Bench, Prop_BusShelter, Prop_TrafficLight, Prop_Planter, Prop_Dumpster, Prop_Tree,
             Prop_TrafficCone, Prop_TrashBin

The geometry lives in the helper modules props_street / props_cars / props_rooftop / props_rooftop2 / props_extras
(shared plumbing + materials: props_common, geometry helpers: street_geo, procedural textures: ground_texlib).

Run:   node tools/run-blender.mjs tools/blender/build_city_props.py [-- --preview --sunset --lineup --street --qa --verbose]
                                                                       [--only Prop_Car_A,Prop_StreetLamp]
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from props_common import *          # noqa: F401,F403
import props_street
import props_cars
import props_rooftop
import props_rooftop2
import props_extras

FILE = "city_props.glb"


def builders():
    """(root name, builder) in export order: the contract props first, then the optional extras."""
    return [
        ("Prop_StreetLamp", props_street.build_lamp),
        ("Prop_Car_A", props_cars.build_car_a),
        ("Prop_Car_B", props_cars.build_car_b),
        ("Prop_Car_C", props_cars.build_car_c),
        ("Prop_Barrier_Jersey", props_street.build_jersey),
        ("Prop_Barrier_Striped", props_street.build_striped),
        ("Prop_Antenna", props_rooftop2.build_antenna),
        ("Prop_AC_Unit_A", props_rooftop.build_ac_a),
        ("Prop_AC_Unit_B", props_rooftop.build_ac_b),
        ("Prop_Vent_Stack", props_rooftop2.build_vent),
        ("Prop_Roof_Access", props_rooftop2.build_roof_access),
        ("Prop_Cooling_Tower", props_rooftop2.build_cooling_tower),
        ("Prop_Solar_Array", props_rooftop2.build_solar),
    ] + list(props_extras.BUILDERS)


def build_all(only=None):
    M = make_mats()
    roots = []
    for name, fn in builders():
        if only and name not in only:
            continue
        roots.append(fn(M))
    return roots


# ----------------------------------------------------------------------------------------------------
# previews
# ----------------------------------------------------------------------------------------------------
def focus_box(center, size, name="PV_Focus"):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    o.hide_render = True
    return o


# per prop preview setup: distance multiplier for the standard views + detail views {name: (center, size, (az, el, dist))}
PREVIEW = {
    "Prop_StreetLamp": dict(dist=1.55, details={"head": ((0, 2.3, 9.0), (2.2, 2.2, 1.6), (205, 14, 1.0)),
                                                "base": ((0, 0, 0.7), (1.4, 1.4, 1.6), (215, 22, 1.0))}),
    "Prop_Antenna": dict(dist=1.5, details={"dish": ((0, 0.6, 12.0), (3.0, 3.0, 2.6), (200, 12, 1.0)), "top": ((0, 0, 15.2), (2.2, 2.2, 2.6), (150, 20, 1.0)),
                                            "foot": ((0.3, 0, 1.2), (3.0, 3.0, 2.4), (215, 25, 1.0))}),
    "Prop_AC_Unit_A": dict(dist=0.9), "Prop_AC_Unit_B": dict(dist=0.9),
    "Prop_TrafficLight": dict(dist=1.4), "Prop_BusShelter": dict(dist=1.0),
    "Prop_Car_B": dict(dist=1.05, details={"rear": ((0, -2.2, 0.9), (2.4, 1.4, 1.6), (25, 16, 1.0)),
                                           "rear34": ((0, 0, 0.9), (2.4, 5.0, 1.8), (330, 22, 1.0))}),
    "Prop_Car_C": dict(dist=1.1, details={"bed": ((0, -1.4, 1.0), (2.4, 2.8, 1.0), (200, 45, 1.0)),
                                           "rear34": ((0, 0, 0.9), (2.4, 5.4, 1.8), (330, 22, 1.0))}),
    "Prop_Car_A": dict(dist=1.0, details={"front": ((0, 2.0, 0.7), (2.2, 1.2, 1.2), (160, 14, 1.0)),
                                          "rear": ((0, -2.0, 0.7), (2.2, 1.2, 1.2), (20, 14, 1.0)),
                                          "wheel": ((0.85, 1.42, 0.4), (1.0, 1.4, 0.9), (85, 8, 1.0))}),
}


def preview(roots):
    for r in roots:
        cfg = PREVIEW.get(r.name, {})
        for o in bpy.data.objects:
            if o.type in ("MESH", "EMPTY") and not o.name.startswith("PV_"):
                o.hide_render = True
        for o in [r] + descendants(r):
            o.hide_render = False
        tag = "props_" + r.name[5:].lower()
        render_views(tag, [r], views=("three_quarter", "front", "left", "top"), size=(900, 700), samples=24, ground=True,
                     distance_scale=cfg.get("dist", 1.0), custom_views={"top": (180, 84, 1.0)})
        for dname, (c, sz, cv) in cfg.get("details", {}).items():
            fb = focus_box(c, sz, "PV_Focus_" + dname)
            render_views(f"{tag}_{dname}", [fb], views=("v",), size=(900, 700), samples=24, ground=True, custom_views={"v": cv}, lens=50)
    for o in bpy.data.objects:
        if o.type in ("MESH", "EMPTY") and not o.name.startswith("PV_"):
            o.hide_render = False


LINEUP_GROUPS = (
    ("street", ("Prop_Car_A", "Prop_Car_B", "Prop_Car_C", "Prop_Barrier_Jersey", "Prop_Barrier_Striped", "Prop_TrafficCone", "Prop_Hydrant",
                "Prop_Bench", "Prop_TrashBin", "Prop_Planter", "Prop_Dumpster", "Prop_BusShelter")),
    ("tall", ("Prop_StreetLamp", "Prop_TrafficLight", "Prop_Tree", "Prop_Antenna")),
    ("roof", ("Prop_AC_Unit_A", "Prop_AC_Unit_B", "Prop_Vent_Stack", "Prop_Roof_Access", "Prop_Cooling_Tower", "Prop_Solar_Array")),
)


def lineup_preview(roots):
    """Groups of props side by side (after export) in real size."""
    by_name = {r.name: r for r in roots}
    for gname, names in LINEUP_GROUPS:
        group = [by_name[n] for n in names if n in by_name]
        if not group:
            continue
        for o in bpy.data.objects:
            if o.type in ("MESH", "EMPTY") and not o.name.startswith("PV_"):
                o.hide_render = True
        x = 0.0
        for r in group:
            mn, mx = world_bbox(descendants(r))
            w = max(mx.x - mn.x, 1.0)
            r.location.x = x - mn.x
            x += w + 1.6
            for o in [r] + descendants(r):
                o.hide_render = False
        bpy.context.view_layer.update()
        render_views(f"props_lineup_{gname}", group, views=("front", "three_quarter"), size=(1600, 640), samples=24, ground=True,
                     distance_scale=0.62, custom_views={"front": (180, 5, 1.0), "three_quarter": (200, 24, 1.0)}, lens=50)


def build():
    reset_scene()
    args = script_args()
    only = None
    if "--only" in args:
        only = set(args[args.index("--only") + 1].split(","))
    roots = build_all(only)
    # partial (--only) builds go to the cache folder so public/assets only ever contains the full asset
    path = export_glb(FILE if not only else os.path.join(CACHE_DIR, "city_props_partial.glb"), roots, animations=False)
    info = report(path)
    total = 0
    for r in roots:
        mn, mx = world_bbox(descendants(r))
        t = tri_count(descendants(r))
        total += t
        log(f"  {r.name}: x={mx.x - mn.x:.2f} y(glTF)={mx.z - mn.z:.2f} z(glTF)={mx.y - mn.y:.2f}  tris={t}  nodes={len(descendants(r))}")
        if "--verbose" in args:
            for c in descendants(r):
                if c.type == "MESH":
                    log(f"      {c.name}: {tri_count([c])} tris, {len(c.data.materials)} mats")
        if "--qa" in args:
            for c in descendants(r):
                if c.type == "MESH":
                    isl, cl, neg, deg = qa_islands(c)
                    log(f"      QA {c.name}: islands={isl} closed={cl} inverted={neg} degenerate_faces={deg}")
    log(f"  total tris (evaluated) = {total}")
    if "--sunset" in args:
        import street_preview
        street_preview.use_sunset()
    if "--preview" in args:
        preview(roots)
    if "--lineup" in args:
        lineup_preview(roots)
    if "--street" in args:
        import street_scene_preview as ssp
        made = ssp.compose({r.name: r for r in roots})
        focus = [o for o in made if o.name.startswith("pv_car") or o.name.startswith("pv_lamp") or o.name.startswith("pv_road")]
        ssp.street_views(focus, "props_street")
        roof = [o for o in made if o.name.startswith("pv_Prop_") or o.name == "pv_building"]
        render_views("props_roof", roof, views=("a", "b", "c"), size=(1400, 800), samples=32, ground=False,
                     custom_views={"a": (200, 30, 0.55), "b": (140, 24, 0.5), "c": (250, 60, 0.7)}, lens=35)


build()

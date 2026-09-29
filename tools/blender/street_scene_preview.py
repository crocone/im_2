"""Compose the exported ground kit + props into a small street scene for visual scale / placement checks (preview only)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from mathutils import Matrix, Vector
from common import ASSET_DIR, descendants, make_material, render_views, log


def import_glb(name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(ASSET_DIR, name))
    return [o for o in bpy.data.objects if o not in before]


def clone(obj, name, loc=(0, 0, 0), rot_deg=0.0, parent=None):
    """Linked-data clone of an object hierarchy."""
    new = bpy.data.objects.new(name, obj.data if obj.type == "MESH" else None)
    bpy.context.scene.collection.objects.link(new)
    new.rotation_mode = "XYZ"
    if parent is None:
        new.location = loc
        new.rotation_euler = (0.0, 0.0, math.radians(rot_deg))
    else:
        new.parent = parent
        new.location = obj.location
        new.rotation_euler = obj.rotation_euler
        new.scale = obj.scale
    for c in obj.children:
        clone(c, name + "_" + c.name, parent=new)
    if new.type == "EMPTY":
        new.empty_display_type = "PLAIN_AXES"
    return new


def compose(props):
    """props: dict name -> root Empty (built in the current scene).  Returns (all new objects, focus points)."""
    ground = {o.name.split(".")[0]: o for o in import_glb("city_ground.glb") if o.type == "MESH"}
    for o in ground.values():
        o.hide_render = True
    made = []

    def put(src, name, x, y, rot=0.0, z=0.0):
        o = clone(src, name, (x, y, z), rot)
        made.append(o)
        return o

    rs, ri, ss, sc, lot = (ground[k] for k in ("Road_Straight", "Road_Intersection", "Sidewalk_Straight", "Sidewalk_Corner", "Lot_Ground"))
    # a 100 m street along +Y: intersection - road - intersection, sidewalks + corners + lots on both sides
    for k, y in enumerate((-50.0, 50.0)):
        made.append(clone(ri, f"pv_int{k}", (0, y, 0)))
    made.append(clone(rs, "pv_road", (0, 0, 0)))
    for k, (sx, sgn) in enumerate(((-12.0, 1), (12.0, -1))):
        # west sidewalk (x<0): its road side is +X -> rotate 180 deg;  east sidewalk keeps the native -X kerb
        made.append(clone(ss, f"pv_sw{k}", (sx, 0, 0), 180.0 if sx < 0 else 0.0))
        for j, y in enumerate((-38.0, 38.0)):
            # corner tile: native outer corner is (-X,+Y).  West side: outer corner faces +X.
            if sx > 0:
                rot = 0.0 if y > 0 else 90.0
            else:
                rot = -90.0 if y > 0 else 180.0
            made.append(clone(sc, f"pv_c{k}{j}", (sx, y, 0), rot))
        made.append(clone(lot, f"pv_lot{k}", (50.0 if sx > 0 else -50.0, 0, 0)))
    P = props
    for r in P.values():
        for o in [r] + descendants(r):
            o.hide_render = True
    bpy.ops.mesh.primitive_plane_add(size=800, location=(0, 0, -0.3))
    fl = bpy.context.active_object
    fl.name = "PV_StreetFloor"
    fl.data.materials.append(make_material("PV_StreetFloorMat", "#34343A", 0.0, 0.95))
    put(P["Prop_Car_A"], "pv_carA", 8.75, -18.0, 0.0)
    put(P["Prop_Car_B"], "pv_carB", 8.75, -3.0, 0.0)
    put(P["Prop_Car_C"], "pv_carC", 8.75, 12.0, 0.0)
    put(P["Prop_Car_A"], "pv_carA2", -8.75, 6.0, 180.0)
    put(P["Prop_Car_C"], "pv_carC2", -8.75, -14.0, 180.0)
    put(P["Prop_Car_B"], "pv_carB2", -1.9, -25.0, 0.0)
    put(P["Prop_Car_A"], "pv_carA3", 5.6, 25.0, 180.0)
    for k, y in enumerate((-30.0, -5.0, 20.0)):
        put(P["Prop_StreetLamp"], f"pv_lampE{k}", 10.9, y, 90.0)
        put(P["Prop_StreetLamp"], f"pv_lampW{k}", -10.9, y + 12.0, -90.0)
    put(P["Prop_Barrier_Jersey"], "pv_jersey1", -1.9, 36.0, 90.0)
    put(P["Prop_Barrier_Jersey"], "pv_jersey2", -1.9, 39.2, 90.0)
    put(P["Prop_Barrier_Striped"], "pv_striped", 3.3, 33.0, 0.0)
    if "Prop_TrafficCone" in P:
        for k, (cx, cy) in enumerate(((0.6, 30.0), (1.6, 28.0), (2.6, 26.0), (5.4, 31.0), (6.0, 29.0))):
            put(P["Prop_TrafficCone"], f"pv_cone{k}", cx, cy, 0.0)
    if "Prop_TrashBin" in P:
        put(P["Prop_TrashBin"], "pv_bin", 12.9, -8.0, 0.0, z=0.15)
        put(P["Prop_TrashBin"], "pv_bin2", 12.9, 12.5, 0.0, z=0.15)
    put(P["Prop_Hydrant"], "pv_hydrant", 11.6, -10.0, 0.0)
    put(P["Prop_Bench"], "pv_bench", 12.7, -22.0, 90.0)
    put(P["Prop_BusShelter"], "pv_shelter", 12.2, 8.0, 90.0)
    put(P["Prop_TrafficLight"], "pv_tl", 10.6, 42.0, 90.0)
    put(P["Prop_Planter"], "pv_planter", -12.0, -5.0, 0.0)
    if "Prop_Tree" in P:
        for k, y in enumerate((-32.0, -14.0, 4.0, 22.0, 34.0)):
            put(P["Prop_Tree"], f"pv_treeE{k}", 12.6, y, 0.0, z=0.15)
            put(P["Prop_Tree"], f"pv_treeW{k}", -12.6, y + 6.0, 0.0, z=0.15)
    put(P["Prop_Dumpster"], "pv_dumpster", -13.0, 20.0, 90.0)
    # a plain building on the east lot carrying the rooftop props
    bx, by, bh = 46.0, -6.0, 14.0
    mat = make_material("pv_building", "#6B7280", 0.0, 0.8)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(bx, by, bh / 2))
    b = bpy.context.active_object
    b.name = "pv_building"
    b.scale = (30, 30, bh)
    b.data.materials.append(mat)
    made.append(b)
    roof = [("Prop_Antenna", -9, 8, 0), ("Prop_Cooling_Tower", 6, 9, 0), ("Prop_Solar_Array", 5, -8, 0), ("Prop_Roof_Access", -9, -9, 0),
            ("Prop_AC_Unit_A", 10, 0, 0), ("Prop_AC_Unit_B", -3, 0, 90), ("Prop_Vent_Stack", -3, -9, 0)]
    for name, dx, dy, rot in roof:
        if name in P:
            put(P[name], "pv_" + name, bx + dx, by + dy, rot, z=bh)
    return made


def street_views(made, tag="props_street"):
    render_views(tag, [o for o in made if o.type == "MESH" or o.type == "EMPTY"], views=("a", "b", "c", "d"), size=(1400, 800), samples=32,
                 ground=False, custom_views={"a": (180, 24, 0.30), "b": (35, 20, 0.28), "c": (250, 34, 0.42), "d": (140, 55, 0.6)}, lens=35)

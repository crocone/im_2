"""Armored Flight - shared Blender helpers (Blender 4.4 / bpy).

CONVENTIONS  (see ASSET_SPEC.md - they are part of the contract with the game)
  * 1 Blender unit = 1 metre.  Blender axes: +X right, +Y FORWARD, +Z up.
  * The glTF exporter converts to Y-up:  Blender +Y (forward) -> glTF -Z (three.js "forward"),
    Blender +Z (up) -> glTF +Y, +X stays +X.  Everything that "faces forward" is modelled facing +Y.
  * Muzzle / nozzle / launcher Empties: their local +Y axis is the emission direction
    (this becomes local -Z in three.js).
  * Every rigged asset is authored in its REST POSE with identity rotations, so the local
    location of a part is simply  pivot_world - parent_pivot_world  (see `add_part`).

Everything here is deterministic: no time based seeds, stable iteration order.
"""
import bmesh
import bpy
import json
import math
import os
import random
import struct
import sys

import numpy as np
from mathutils import Euler, Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ASSET_DIR = os.path.join(REPO, "public", "assets")
CACHE_DIR = os.path.join(REPO, "tools", ".cache")
PREVIEW_DIR = os.path.join(CACHE_DIR, "previews")
TEXTURE_DIR = os.path.join(CACHE_DIR, "textures")


def log(*args):
    print("[AF]", *args, flush=True)


def script_args():
    """Arguments after `--` on the blender command line."""
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


# --------------------------------------------------------------------------------------
# Scene management
# --------------------------------------------------------------------------------------
def reset_scene():
    """Remove every datablock so a script always starts from a clean, empty file."""
    try:
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.actions,
                 bpy.data.curves, bpy.data.cameras, bpy.data.lights, bpy.data.node_groups, bpy.data.worlds):
        for item in list(coll):
            coll.remove(item)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.fps = 30
    scene.frame_start = 1
    scene.frame_end = 60
    scene.frame_set(1)
    return scene


# --------------------------------------------------------------------------------------
# Colour + material helpers
# --------------------------------------------------------------------------------------
def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hexc(h, alpha=1.0):
    """'#rrggbb' (sRGB, as a designer would write it) -> linear RGBA tuple for Blender."""
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), alpha)


def _rgba(color):
    if isinstance(color, str):
        return hexc(color)
    if len(color) == 3:
        return (color[0], color[1], color[2], 1.0)
    return tuple(color)


def make_material(name, color="#808080", metallic=0.0, roughness=0.5, emission=None, emission_strength=0.0,
                  alpha=1.0, ior=1.45, coat=0.0, coat_roughness=0.15, double_sided=False):
    """Create (or fetch) a Principled BSDF material.  `color`/`emission` are '#rrggbb' or linear tuples."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = _rgba(color)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["IOR"].default_value = ior
    if coat > 0.0:
        bsdf.inputs["Coat Weight"].default_value = coat
        bsdf.inputs["Coat Roughness"].default_value = coat_roughness
    if emission is not None and emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = _rgba(emission)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        try:
            mat.surface_render_method = "BLENDED"
        except Exception:
            pass
        try:
            mat.blend_method = "BLEND"
        except Exception:
            pass
    mat.use_backface_culling = not double_sided
    return mat


# Shared PBR palette used across the whole game.  Player = light armour with navy + amber trim and
# cyan reactors; enemies = charcoal steel with red sensors; boss = black steel, brass trim, red-orange core.
PALETTE = {
    # player
    "armor_primary": dict(color="#B7C2CE", metallic=0.80, roughness=0.28),      # pearl titanium
    "armor_secondary": dict(color="#1C2B47", metallic=0.85, roughness=0.34),    # deep navy plate
    "armor_accent": dict(color="#F08A1C", metallic=0.55, roughness=0.38),       # amber trim
    "armor_dark": dict(color="#22262D", metallic=0.90, roughness=0.55),         # joints / mechanical
    "armor_glass": dict(color="#0A1418", metallic=0.20, roughness=0.10, emission="#66E8FF", emission_strength=1.5),
    "glow_cyan": dict(color="#0A2228", metallic=0.0, roughness=0.3, emission="#3FE6FF", emission_strength=7.0),
    "glow_white": dict(color="#DDF8FF", metallic=0.0, roughness=0.3, emission="#E8FBFF", emission_strength=9.0),
    # enemies
    "enemy_hull": dict(color="#2B3038", metallic=0.78, roughness=0.48),
    "enemy_plate": dict(color="#4A5462", metallic=0.80, roughness=0.40),
    "enemy_dark": dict(color="#15181D", metallic=0.85, roughness=0.60),
    "enemy_warning": dict(color="#C7301F", metallic=0.45, roughness=0.45),
    "enemy_hazard": dict(color="#E2A11B", metallic=0.45, roughness=0.45),
    "glow_red": dict(color="#2A0805", metallic=0.0, roughness=0.3, emission="#FF2A18", emission_strength=8.0),
    "glow_orange": dict(color="#2A1205", metallic=0.0, roughness=0.3, emission="#FF7A1A", emission_strength=7.0),
    # boss
    "boss_plate": dict(color="#343B47", metallic=0.85, roughness=0.36),
    "boss_dark": dict(color="#101319", metallic=0.90, roughness=0.55),
    "boss_brass": dict(color="#A2722F", metallic=0.85, roughness=0.32),
    "glow_core": dict(color="#300A05", metallic=0.0, roughness=0.3, emission="#FF4A1F", emission_strength=10.0),
    # projectiles
    "missile_body": dict(color="#C9CED4", metallic=0.55, roughness=0.35),
    "missile_band": dict(color="#D6291B", metallic=0.4, roughness=0.45),
    "mini_body": dict(color="#E8D9B0", metallic=0.35, roughness=0.42),
    "mini_band": dict(color="#F0A020", metallic=0.4, roughness=0.42),
    "exhaust": dict(color="#301005", metallic=0.0, roughness=0.5, emission="#FFB25A", emission_strength=9.0),
    # generic
    "concrete": dict(color="#8A8D92", metallic=0.0, roughness=0.9),
    "concrete_dark": dict(color="#55585E", metallic=0.0, roughness=0.92),
    "asphalt": dict(color="#2C2E33", metallic=0.0, roughness=0.95),
    "steel": dict(color="#79808A", metallic=0.85, roughness=0.45),
    "steel_dark": dict(color="#30343B", metallic=0.85, roughness=0.55),
    "rubber": dict(color="#141518", metallic=0.0, roughness=0.85),
    "glass_dark": dict(color="#0F1C2A", metallic=0.6, roughness=0.12),
    "wood": dict(color="#6B4A2E", metallic=0.0, roughness=0.8),
    "paint_white": dict(color="#E6E3D8", metallic=0.0, roughness=0.6),
    "paint_yellow": dict(color="#E0B52F", metallic=0.0, roughness=0.6),
    "paint_red": dict(color="#B3261E", metallic=0.0, roughness=0.55),
    "lamp_glow": dict(color="#332005", metallic=0.0, roughness=0.4, emission="#FFC777", emission_strength=6.0),
    "beacon_red": dict(color="#300505", metallic=0.0, roughness=0.4, emission="#FF2222", emission_strength=6.0),
}


def pal(key, name=None, **override):
    """Material from the shared palette: pal('armor_primary') -> material named 'armor_primary'."""
    spec = dict(PALETTE[key])
    spec.update(override)
    return make_material(name or key, **spec)


# --------------------------------------------------------------------------------------
# Mesh builder (accumulate primitives into one bmesh, then turn it into an object)
# --------------------------------------------------------------------------------------
def _vec(v):
    return Vector(v) if not isinstance(v, Vector) else v.copy()


def rot_matrix(rot):
    """rot: None | (rx,ry,rz) degrees XYZ euler | Matrix | Quaternion  ->  4x4 Matrix."""
    if rot is None:
        return Matrix.Identity(4)
    if isinstance(rot, Matrix):
        return rot.to_4x4()
    if isinstance(rot, Quaternion):
        return rot.to_matrix().to_4x4()
    return Euler(tuple(math.radians(a) for a in rot), "XYZ").to_matrix().to_4x4()


class MB:
    """MeshBuilder.  Build armour plates / hulls out of primitives in ONE bmesh, then `to_object()`.

    Material handling: pass a bpy material (or None) per primitive; slots are created in first-use order.
    All coordinates are in the object's local space (metres, +Y forward, +Z up).
    """

    def __init__(self):
        self.bm = bmesh.new()
        self.mats = []

    # -- materials -----------------------------------------------------------------
    def slot(self, mat):
        if mat is None:
            return 0
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def _finish_faces(self, faces, mat):
        idx = self.slot(mat)
        for f in faces:
            f.material_index = idx
        return faces

    # -- raw ---------------------------------------------------------------------------
    def face(self, pts, mat=None):
        """One polygon from a list of points (counter-clockwise seen from the outside)."""
        vs = [self.bm.verts.new(Vector(p)) for p in pts]
        try:
            f = self.bm.faces.new(vs)
        except ValueError:
            return None
        self._finish_faces([f], mat)
        return f

    def hexa(self, p, mat=None):
        """Hexahedron from 8 corners: p[0..3] = bottom quad CCW seen from below-outside... (see below),
        p[4..7] = top quad above p[0..3].  Bottom ring order: p0 (-x,-y) p1 (+x,-y) p2 (+x,+y) p3 (-x,+y)."""
        vs = [self.bm.verts.new(Vector(q)) for q in p]
        quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        faces = []
        for q in quads:
            try:
                faces.append(self.bm.faces.new([vs[i] for i in q]))
            except ValueError:
                pass
        return self._finish_faces(faces, mat)

    # -- primitives --------------------------------------------------------------------
    def box(self, center=(0, 0, 0), size=(1, 1, 1), mat=None, rot=None, taper=(1.0, 1.0), top_shift=(0.0, 0.0),
            bottom_scale=(1.0, 1.0)):
        """Axis aligned box (then rotated by `rot` about `center`).
        taper       = (sx, sy)  scale of the TOP face relative to the middle section
        bottom_scale= (sx, sy)  scale of the BOTTOM face
        top_shift   = (dx, dy)  offset of the top face (sheared plates / wedges)"""
        sx, sy, sz = size[0] / 2, size[1] / 2, size[2] / 2
        bs, ts = bottom_scale, taper
        pts = [
            (-sx * bs[0], -sy * bs[1], -sz), (sx * bs[0], -sy * bs[1], -sz),
            (sx * bs[0], sy * bs[1], -sz), (-sx * bs[0], sy * bs[1], -sz),
            (-sx * ts[0] + top_shift[0], -sy * ts[1] + top_shift[1], sz),
            (sx * ts[0] + top_shift[0], -sy * ts[1] + top_shift[1], sz),
            (sx * ts[0] + top_shift[0], sy * ts[1] + top_shift[1], sz),
            (-sx * ts[0] + top_shift[0], sy * ts[1] + top_shift[1], sz),
        ]
        m = rot_matrix(rot)
        c = _vec(center)
        return self.hexa([m @ Vector(q) + c for q in pts], mat)

    def cyl(self, center=(0, 0, 0), r=0.5, h=1.0, seg=16, axis="Z", mat=None, r_top=None, caps=True, rot=None,
            scale=(1, 1)):
        """Cylinder / frustum along `axis` ('X'|'Y'|'Z'); r = bottom radius, r_top = top radius.
        scale=(a,b) stretches the two cross-section directions (elliptical / octagonal plates)."""
        r_top = r if r_top is None else r_top
        rings = []
        for k, (rad, z) in enumerate(((r, -h / 2), (r_top, h / 2))):
            ring = []
            for i in range(seg):
                a = 2 * math.pi * i / seg
                ring.append(Vector((math.cos(a) * rad * scale[0], math.sin(a) * rad * scale[1], z)))
            rings.append(ring)
        return self._lathe_rings(rings, center, axis, mat, caps, rot)

    def _axis_matrix(self, axis):
        if axis == "Z":
            return Matrix.Identity(4)
        if axis == "X":   # local Z -> world X
            return Euler((0, math.radians(90), 0), "XYZ").to_matrix().to_4x4()
        if axis == "Y":   # local Z -> world Y
            return Euler((math.radians(-90), 0, 0), "XYZ").to_matrix().to_4x4()
        raise ValueError(axis)

    def _lathe_rings(self, rings, center, axis, mat, caps, rot):
        m = rot_matrix(rot) @ self._axis_matrix(axis)
        c = _vec(center)
        vr = [[self.bm.verts.new(m @ p + c) for p in ring] for ring in rings]
        faces = []
        n = len(vr[0])
        for a, b in zip(vr[:-1], vr[1:]):
            for i in range(n):
                j = (i + 1) % n
                try:
                    faces.append(self.bm.faces.new((a[i], a[j], b[j], b[i])))
                except ValueError:
                    pass
        if caps:
            try:
                faces.append(self.bm.faces.new(list(reversed(vr[0]))))
            except ValueError:
                pass
            try:
                faces.append(self.bm.faces.new(vr[-1]))
            except ValueError:
                pass
        return self._finish_faces(faces, mat)

    def revolve(self, profile, center=(0, 0, 0), seg=24, axis="Z", mat=None, caps=True, rot=None, scale=(1, 1)):
        """Surface of revolution.  profile = [(radius, height), ...] from bottom to top (radius 0 allowed)."""
        rings = []
        for rad, z in profile:
            ring = [Vector((math.cos(2 * math.pi * i / seg) * rad * scale[0],
                            math.sin(2 * math.pi * i / seg) * rad * scale[1], z)) for i in range(seg)]
            rings.append(ring)
        return self._lathe_rings(rings, center, axis, mat, caps, rot)

    def sphere(self, center=(0, 0, 0), r=0.5, seg=16, rings=10, mat=None, scale=(1, 1, 1), rot=None):
        """UV sphere with a fully deterministic vertex order (bmesh.ops.create_uvsphere is not stable between
        Blender processes).  rings = number of latitude bands; seg = segments around the Z axis."""
        m = rot_matrix(rot)
        c = _vec(center)

        def P(x, y, z):
            return m @ Vector((x * scale[0] * r, y * scale[1] * r, z * scale[2] * r)) + c

        bm = self.bm
        top = bm.verts.new(P(0, 0, 1))
        bottom = bm.verts.new(P(0, 0, -1))
        ring_verts = []
        for j in range(1, rings):
            phi = math.pi * j / rings
            sz, rr = math.cos(phi), math.sin(phi)
            ring_verts.append([bm.verts.new(P(rr * math.cos(2 * math.pi * i / seg), rr * math.sin(2 * math.pi * i / seg), sz))
                               for i in range(seg)])
        faces = []
        for i in range(seg):
            j = (i + 1) % seg
            try:
                faces.append(bm.faces.new((top, ring_verts[0][i], ring_verts[0][j])))
            except ValueError:
                pass
        for a_, b_ in zip(ring_verts[:-1], ring_verts[1:]):
            for i in range(seg):
                j = (i + 1) % seg
                try:
                    faces.append(bm.faces.new((a_[i], b_[i], b_[j], a_[j])))
                except ValueError:
                    pass
        for i in range(seg):
            j = (i + 1) % seg
            try:
                faces.append(bm.faces.new((bottom, ring_verts[-1][j], ring_verts[-1][i])))
            except ValueError:
                pass
        return self._finish_faces(faces, mat)

    def prism(self, outline, z0, z1, mat=None, plane="XY", rot=None, center=(0, 0, 0)):
        """Extrude a 2D outline (list of (u,v), CCW) between z0 and z1 along the plane normal.
        plane 'XY' extrudes along Z, 'XZ' along Y (u=x,v=z), 'YZ' along X (u=y,v=z)."""
        m = rot_matrix(rot)
        c = _vec(center)

        def to3(u, v, w):
            if plane == "XY":
                return Vector((u, v, w))
            if plane == "XZ":
                return Vector((u, w, v))
            return Vector((w, u, v))

        lo = [self.bm.verts.new(m @ to3(u, v, z0) + c) for u, v in outline]
        hi = [self.bm.verts.new(m @ to3(u, v, z1) + c) for u, v in outline]
        n = len(outline)
        faces = []
        for i in range(n):
            j = (i + 1) % n
            try:
                faces.append(self.bm.faces.new((lo[i], lo[j], hi[j], hi[i])))
            except ValueError:
                pass
        for ring, rev in ((lo, True), (hi, False)):
            try:
                faces.append(self.bm.faces.new(list(reversed(ring)) if rev else ring))
            except ValueError:
                pass
        # outward orientation is fixed globally in finish()
        return self._finish_faces(faces, mat)

    def loft(self, sections, mat=None, caps=True, rot=None, center=(0, 0, 0)):
        """Loft through cross-sections; each section is a list of Vector/tuples with the SAME vertex count,
        ordered CCW when seen along +sweep direction.  Used for hulls, fuselages, armour shells."""
        m = rot_matrix(rot)
        c = _vec(center)
        vr = [[self.bm.verts.new(m @ Vector(p) + c) for p in sec] for sec in sections]
        n = len(vr[0])
        faces = []
        for a, b in zip(vr[:-1], vr[1:]):
            for i in range(n):
                j = (i + 1) % n
                try:
                    faces.append(self.bm.faces.new((a[i], a[j], b[j], b[i])))
                except ValueError:
                    pass
        if caps:
            for ring, rev in ((vr[0], True), (vr[-1], False)):
                try:
                    faces.append(self.bm.faces.new(list(reversed(ring)) if rev else ring))
                except ValueError:
                    pass
        return self._finish_faces(faces, mat)

    # -- whole-mesh operations -----------------------------------------------------------
    def transform(self, matrix):
        bmesh.ops.transform(self.bm, matrix=matrix, verts=list(self.bm.verts))
        return self

    def merge_into(self, other, matrix=None, mat_map=None):
        """Copy `other` MB into this one (optionally transformed)."""
        matrix = matrix or Matrix.Identity(4)
        vmap = {}
        for v in other.bm.verts:
            vmap[v] = self.bm.verts.new(matrix @ v.co)
        for f in other.bm.faces:
            try:
                nf = self.bm.faces.new([vmap[v] for v in f.verts])
            except ValueError:
                continue
            m = other.mats[f.material_index] if other.mats and f.material_index < len(other.mats) else None
            nf.material_index = self.slot(m)
        return self

    def mirrored_x(self):
        """Return a NEW MB that is this one mirrored across the X=0 plane (winding flipped)."""
        out = MB()
        out.mats = list(self.mats)
        vmap = {v: out.bm.verts.new(Vector((-v.co.x, v.co.y, v.co.z))) for v in self.bm.verts}
        for f in self.bm.faces:
            try:
                nf = out.bm.faces.new(list(reversed([vmap[v] for v in f.verts])))
                nf.material_index = f.material_index
            except ValueError:
                pass
        return out

    def finish(self):
        """Weld duplicate verts, recalc outward normals."""
        bm = self.bm
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
        try:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        except Exception:
            pass
        return self

    def to_object(self, name, parent=None, location=(0, 0, 0), collection=None, bevel=None, smooth=True,
                  sharp_angle=35.0, weighted=True, uv=None):
        """Create the Blender object.  `bevel` = (width, segments) adds Bevel + WeightedNormal modifiers
        (applied by the exporter).  `uv` = metres-per-UV-unit for box projection UVs."""
        self.finish()
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        for m in self.mats:
            mesh.materials.append(m)
        obj = bpy.data.objects.new(name, mesh)
        (collection or bpy.context.scene.collection).objects.link(obj)
        obj.location = location
        if parent is not None:
            obj.parent = parent
        if smooth:
            shade_smooth_by_angle(obj, sharp_angle)
        if uv:
            box_project_uv(obj, uv)
        if bevel:
            add_bevel(obj, bevel[0], bevel[1] if len(bevel) > 1 else 2, sharp_angle, weighted)
        self.bm.free()
        return obj


def shade_smooth_by_angle(obj, angle_deg=35.0):
    """Mark edges sharper than angle as sharp, everything else smooth (replaces 'auto smooth', Blender 4.1+)."""
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    lim = math.radians(angle_deg)
    for e in bm.edges:
        if len(e.link_faces) == 2:
            e.smooth = e.calc_face_angle(0.0) <= lim
        else:
            e.smooth = True
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def add_bevel(obj, width=0.01, segments=2, angle_deg=35.0, weighted=True, name_suffix=""):
    """Bevel sharp edges + weighted normals (crisp panel edges, smooth flats).  Applied at export."""
    mod = obj.modifiers.new("Bevel" + name_suffix, "BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(angle_deg)
    mod.harden_normals = True
    try:
        mod.miter_outer = "MITER_ARC"
    except Exception:
        pass
    if weighted:
        wn = obj.modifiers.new("WeightedNormal" + name_suffix, "WEIGHTED_NORMAL")
        wn.keep_sharp = True
        wn.weight = 50
        wn.mode = "FACE_AREA"
    return obj


def apply_modifiers(obj):
    """Bake all modifiers into the mesh (use when a script needs the final mesh, e.g. for fracture)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    new_mesh = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    old = obj.data
    obj.modifiers.clear()
    obj.data = new_mesh
    new_mesh.name = old.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return obj


# --------------------------------------------------------------------------------------
# Objects, pivots, hierarchy
# --------------------------------------------------------------------------------------
def add_empty(name, location=(0, 0, 0), parent=None, rot=None, display="ARROWS", size=0.15, collection=None):
    """Empty.  For muzzles / nozzles / launchers `rot` must make the LOCAL +Y axis point along emission."""
    o = bpy.data.objects.new(name, None)
    o.empty_display_type = display
    o.empty_display_size = size
    (collection or bpy.context.scene.collection).objects.link(o)
    o.location = location
    if rot is not None:
        o.rotation_mode = "XYZ"
        o.rotation_euler = Euler(tuple(math.radians(a) for a in rot), "XYZ")
    if parent is not None:
        o.parent = parent
    return o


def aim_rot_for_direction(direction, up=(0, 0, 1)):
    """Euler XYZ degrees such that the LOCAL +Y axis of an empty points along `direction`."""
    d = Vector(direction).normalized()
    q = d.to_track_quat("Y", "Z") if abs(d.z) < 0.999 else d.to_track_quat("Y", "X")
    e = q.to_euler("XYZ")
    return tuple(math.degrees(a) for a in e)


def set_origin_world(obj, world_point):
    """Move the object's origin to `world_point` WITHOUT moving the geometry (identity-rotation objects only)."""
    p = Vector(world_point)
    delta = p - obj.location
    obj.data.transform(Matrix.Translation(-delta))
    obj.location = p
    obj.data.update()


_PIVOTS = {}   # object name -> world pivot Vector (kept out of custom properties so nothing leaks into glTF extras)


def pivot_of(obj):
    return _PIVOTS.get(obj.name, Vector((0, 0, 0)))


def add_part(name, mb_or_obj, pivot_world, parent=None, parent_pivot_world=None, collection=None, **to_object_kwargs):
    """Create a rig part.  `mb_or_obj` is an MB (geometry in WORLD/rest-pose coordinates) or an existing object.
    The object's origin becomes `pivot_world`; it is parented to `parent` with local location
    pivot_world - parent_pivot_world (all rest rotations are identity, so this is exact)."""
    if isinstance(mb_or_obj, MB):
        obj = mb_or_obj.to_object(name, collection=collection, **to_object_kwargs)
    else:
        obj = mb_or_obj
        obj.name = name
    set_origin_world(obj, pivot_world)
    if parent is not None:
        obj.parent = parent
        pp = Vector(parent_pivot_world) if parent_pivot_world is not None else pivot_of(parent)
        obj.location = Vector(pivot_world) - Vector(pp)
    _PIVOTS[obj.name] = Vector(pivot_world)
    return obj


def descendants(obj):
    out = []
    for c in obj.children:
        out.append(c)
        out.extend(descendants(c))
    return out


def link_recursive(obj, collection):
    """Make sure obj and all descendants live in `collection`."""
    for o in [obj] + descendants(obj):
        for c in list(o.users_collection):
            c.objects.unlink(o)
        collection.objects.link(o)


def world_bbox(objs):
    """World-space (Blender axes) AABB of mesh objects -> (min Vector, max Vector)."""
    dg = bpy.context.evaluated_depsgraph_get()
    mn = Vector((1e9, 1e9, 1e9))
    mx = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        if o.type != "MESH":
            continue
        ev = o.evaluated_get(dg)
        for corner in ev.bound_box:
            w = o.matrix_world @ Vector(corner)
            mn = Vector((min(mn.x, w.x), min(mn.y, w.y), min(mn.z, w.z)))
            mx = Vector((max(mx.x, w.x), max(mx.y, w.y), max(mx.z, w.z)))
    return mn, mx


def tri_count(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    total = 0
    for o in objs:
        if o.type != "MESH":
            continue
        me = o.evaluated_get(dg).to_mesh()
        me.calc_loop_triangles()
        total += len(me.loop_triangles)
        o.evaluated_get(dg).to_mesh_clear()
    return total


# --------------------------------------------------------------------------------------
# UVs
# --------------------------------------------------------------------------------------
def box_project_uv(obj, meters_per_uv=(4.0, 4.0), uv_name="UVMap", world_space=False, offset=(0.0, 0.0)):
    """Per-face box projection: every face is projected along its dominant normal axis so textures keep a
    constant metric density (U = horizontal metres / meters_per_uv[0], V = vertical metres / meters_per_uv[1]).
    Vertical faces use V = height (Z); horizontal faces use (X, Y).  Good for facades and roofs."""
    mesh = obj.data
    if uv_name not in mesh.uv_layers:
        mesh.uv_layers.new(name=uv_name)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_layer = bm.loops.layers.uv.get(uv_name) or bm.loops.layers.uv.new(uv_name)
    mw = obj.matrix_world if world_space else Matrix.Identity(4)
    su, sv = meters_per_uv
    for f in bm.faces:
        n = f.normal
        ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
        for loop in f.loops:
            p = mw @ loop.vert.co
            if az >= ax and az >= ay:
                u, v = p.x / su, p.y / sv
            elif ax >= ay:
                u, v = p.y / su, p.z / sv
            else:
                u, v = p.x / su, p.z / sv
            loop[uv_layer].uv = (u + offset[0], v + offset[1])
    bm.to_mesh(mesh)
    bm.free()


def uv_unit_planar(obj, axis="Z", uv_name="UVMap"):
    """Simple 0..1 planar unwrap of the object's bounding box along an axis (for decals / panels)."""
    mesh = obj.data
    if uv_name not in mesh.uv_layers:
        mesh.uv_layers.new(name=uv_name)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_layer = bm.loops.layers.uv.get(uv_name)
    xs = [v.co for v in bm.verts]
    mn = Vector((min(p.x for p in xs), min(p.y for p in xs), min(p.z for p in xs)))
    mx = Vector((max(p.x for p in xs), max(p.y for p in xs), max(p.z for p in xs)))
    size = mx - mn
    for f in bm.faces:
        for loop in f.loops:
            p = loop.vert.co - mn
            if axis == "Z":
                loop[uv_layer].uv = (p.x / max(size.x, 1e-6), p.y / max(size.y, 1e-6))
            elif axis == "Y":
                loop[uv_layer].uv = (p.x / max(size.x, 1e-6), p.z / max(size.z, 1e-6))
            else:
                loop[uv_layer].uv = (p.y / max(size.y, 1e-6), p.z / max(size.z, 1e-6))
    bm.to_mesh(mesh)
    bm.free()


# --------------------------------------------------------------------------------------
# Procedural textures (numpy -> packed PNG images -> Principled material)
# --------------------------------------------------------------------------------------
def image_from_array(name, arr, srgb=True):
    """arr: float array (H, W, 3|4), values 0..1, row 0 = TOP of the picture.  Returns a PACKED image so the
    glTF exporter embeds it.  srgb=False for data maps (roughness/metal/normal)."""
    arr = np.asarray(arr, dtype=np.float32)
    if arr.shape[2] == 3:
        arr = np.concatenate([arr, np.ones(arr.shape[:2] + (1,), np.float32)], axis=2)
    h, w = arr.shape[:2]
    ensure_dir(TEXTURE_DIR)
    path = os.path.join(TEXTURE_DIR, name + ".png")
    img = bpy.data.images.new(name + "_gen", w, h, alpha=True, float_buffer=False, is_data=not srgb)
    img.pixels.foreach_set(np.clip(arr[::-1], 0.0, 1.0).ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    img = bpy.data.images.load(path)
    img.name = name
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    img.pack()
    return img


def make_textured_material(name, albedo=None, orm=None, emissive=None, emissive_strength=1.0, normal=None,
                           base_color=(1, 1, 1, 1), metallic=0.0, roughness=0.8, alpha=1.0, double_sided=False,
                           normal_strength=1.0):
    """Principled material driven by packed images.
    orm = glTF-style packed map: G = roughness, B = metallic (R free / AO).  emissive = colour image (sRGB)."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = base_color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    x = -600

    def tex(img, y):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        n.location = (x, y)
        n.interpolation = "Linear"
        n.extension = "REPEAT"
        return n

    if albedo is not None:
        t = tex(albedo, 300)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        if alpha < 1.0 or (albedo.channels == 4 and False):
            pass
    if orm is not None:
        t = tex(orm, 0)
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        sep.location = (x + 300, 0)
        nt.links.new(t.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    if emissive is not None:
        t = tex(emissive, -300)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = emissive_strength
    if normal is not None:
        t = tex(normal, -600)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (x + 300, -600)
        nm.inputs["Strength"].default_value = normal_strength
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        try:
            mat.surface_render_method = "BLENDED"
        except Exception:
            pass
        try:
            mat.blend_method = "BLEND"
        except Exception:
            pass
    mat.use_backface_culling = not double_sided
    return mat


# --------------------------------------------------------------------------------------
# Animation: pose clips exported as glTF animations (one NLA track per pose)
# --------------------------------------------------------------------------------------
def build_pose_clips(objects, poses, idle=None, frames=60, fps=30):
    """Create looping pose clips.

    objects : dict name -> bpy object (every node that may be animated)
    poses   : dict clip_name -> dict node_name -> dict(loc=(x,y,z) local metres [optional],
                                                       rot=(rx,ry,rz) local euler DEGREES, XYZ order [optional])
              Nodes missing from a pose keep their REST transform (location = rest location, rotation 0).
    idle    : optional callable(clip_name, node_name, phase 0..2pi) -> (drx, dry, drz) degrees added to rot.
              Called at 5 phases (0, 90, 180, 270, 360 deg) so every pose gets a subtle looping idle animation.
    Each clip becomes one glTF animation (`export_animation_mode='NLA_TRACKS'`), 1 sec = `fps` frames.
    """
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.frame_start = 1
    scene.frame_end = frames + 1
    rest = {n: (o.location.copy(), o.rotation_mode) for n, o in objects.items()}
    for o in objects.values():
        o.rotation_mode = "QUATERNION"
    keys = [1 + int(round(frames * k / 4)) for k in range(5)]
    # The LAST created NLA track wins at export time (its pose becomes the node base transform = glTF rest pose),
    # so create tracks in reverse order: the FIRST pose of the dict (Pose_Standing) ends up on top / as rest pose.
    for clip, pose in reversed(list(poses.items())):
        for name, obj in objects.items():
            spec = pose.get(name, {})
            ad = obj.animation_data or obj.animation_data_create()
            act = bpy.data.actions.new(f"{clip}__{name}")
            ad.action = act
            for k, fr in enumerate(keys):
                phase = 2 * math.pi * k / 4
                rot = list(spec.get("rot", (0, 0, 0)))
                if idle is not None:
                    d = idle(clip, name, phase)
                    if d:
                        rot = [rot[i] + d[i] for i in range(3)]
                q = Euler(tuple(math.radians(a) for a in rot), "XYZ").to_quaternion()
                obj.rotation_quaternion = q
                obj.location = spec.get("loc", rest[name][0])
                obj.keyframe_insert("rotation_quaternion", frame=fr)
                obj.keyframe_insert("location", frame=fr)
            track = ad.nla_tracks.new()
            track.name = clip
            strip = track.strips.new(f"{clip}", 1, act)
            strip.name = clip
            ad.action = None
    # restore rest transform
    for name, obj in objects.items():
        obj.location = rest[name][0]
        obj.rotation_quaternion = (1, 0, 0, 0)
    return list(poses.keys())


def apply_pose_static(objects, pose, rest_locations=None):
    """Set a pose on the live scene (for preview renders): rotation only / optional loc override."""
    for name, obj in objects.items():
        spec = pose.get(name, {})
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = Euler(tuple(math.radians(a) for a in spec.get("rot", (0, 0, 0))), "XYZ")
        if "loc" in spec:
            obj.location = spec["loc"]
        elif rest_locations is not None:
            obj.location = rest_locations[name]
    bpy.context.view_layer.update()


# --------------------------------------------------------------------------------------
# Export + inspection
# --------------------------------------------------------------------------------------
def export_glb(filename, roots, animations=False, apply_mods=True, extras=True):
    """Export `roots` (objects) and all their descendants to public/assets/<filename> as .glb."""
    ensure_dir(ASSET_DIR)
    path = filename if os.path.isabs(filename) else os.path.join(ASSET_DIR, filename)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    everything = []
    for r in roots:
        everything.append(r)
        everything.extend(descendants(r))
    for o in everything:
        o.hide_set(False)
        o.hide_viewport = False
        o.select_set(True)
    bpy.context.view_layer.objects.active = roots[0]
    kwargs = dict(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_apply=apply_mods,
        export_yup=True,
        export_extras=extras,
        export_cameras=False,
        export_lights=False,
        export_image_format="AUTO",
        export_texcoords=True,
        export_normals=True,
        export_tangents=False,
        export_materials="EXPORT",
        export_animations=animations,
        export_draco_mesh_compression_enable=False,
    )
    if animations:
        kwargs.update(export_animation_mode="NLA_TRACKS", export_force_sampling=True,
                      export_optimize_animation_size=False, export_frame_range=False)
    bpy.ops.export_scene.gltf(**kwargs)
    size_kb = os.path.getsize(path) / 1024.0
    log(f"exported {os.path.relpath(path, REPO)}  ({size_kb:.0f} KB)")
    return path


def glb_info(path):
    """Parse a .glb without Blender/three: returns dict(nodes, meshes, tris, animations, materials, images)."""
    with open(path, "rb") as f:
        data = f.read()
    magic, ver, total = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF", "not a glb"
    clen, ctype = struct.unpack_from("<II", data, 12)
    js = json.loads(data[20:20 + clen].decode("utf-8"))
    tris = 0
    for m in js.get("meshes", []):
        for p in m["primitives"]:
            if "indices" in p:
                tris += js["accessors"][p["indices"]]["count"] // 3
            else:
                tris += js["accessors"][p["attributes"]["POSITION"]]["count"] // 3
    return dict(
        nodes=[n.get("name", "") for n in js.get("nodes", [])],
        node_count=len(js.get("nodes", [])),
        mesh_count=len(js.get("meshes", [])),
        tris=tris,
        animations=[(a.get("name"), len(a.get("channels", []))) for a in js.get("animations", [])],
        materials=[m.get("name") for m in js.get("materials", [])],
        images=len(js.get("images", [])),
        json=js,
    )


def report(path):
    info = glb_info(path)
    log(f"  {os.path.basename(path)}: nodes={info['node_count']} meshes={info['mesh_count']} tris={info['tris']} "
        f"materials={len(info['materials'])} images={info['images']} anims={info['animations']}")
    return info


# --------------------------------------------------------------------------------------
# Preview rendering (headless, for visually checking assets)
# --------------------------------------------------------------------------------------
def _look_at(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def setup_preview_scene(sun_elevation=14.0, sun_azimuth=215.0, ground=True, bg_strength=1.0):
    """Sunset-ish lighting close to the game's look: warm low sun, cool sky fill, dark ground."""
    scene = bpy.context.scene
    world = bpy.data.worlds.new("PreviewWorld")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = bg_strength
    sky = None
    try:
        sky = nt.nodes.new("ShaderNodeTexSky")
        try:
            sky.sky_type = "MULTIPLE_SCATTERING"
        except Exception:
            pass
        sky.sun_elevation = math.radians(sun_elevation)
        sky.sun_rotation = math.radians(sun_azimuth)
        sky.sun_size = math.radians(1.5)
        sky.sun_intensity = 0.6
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    except Exception:
        bg.inputs["Color"].default_value = (0.35, 0.28, 0.35, 1.0)
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    # key light (warm sun) + cool fill so shadows stay readable
    sun = bpy.data.lights.new("PV_Sun", "SUN")
    sun.energy = 3.5
    sun.color = (1.0, 0.72, 0.5)
    so = bpy.data.objects.new("PV_Sun", sun)
    scene.collection.objects.link(so)
    so.rotation_euler = (math.radians(90 - sun_elevation - 8), 0, math.radians(sun_azimuth + 180))
    fill = bpy.data.lights.new("PV_Fill", "SUN")
    fill.energy = 1.2
    fill.color = (0.55, 0.7, 1.0)
    fo = bpy.data.objects.new("PV_Fill", fill)
    scene.collection.objects.link(fo)
    fo.rotation_euler = (math.radians(60), 0, math.radians(sun_azimuth))
    extra = []
    if ground:
        bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 0, 0))
        gp = bpy.context.active_object
        gp.name = "PV_Ground"
        gp.data.materials.append(make_material("PV_GroundMat", "#2A2A2E", 0.0, 0.9))
        extra.append(gp)
    return extra


def render_views(tag, focus_objs, views=("front", "back", "left", "three_quarter"), size=(960, 720),
                 samples=32, engine="EEVEE", ground=False, distance_scale=1.0, sun_elevation=14.0,
                 custom_views=None, lens=50):
    """Render PNGs of `focus_objs` to tools/.cache/previews/<tag>_<view>.png and return the paths.
    Views are named directions around the bbox centre (Blender axes: front = looking from -Y at +Y face...
    NOTE the model FACES +Y, so 'front' looks from +Y toward -Y).  custom_views: dict name -> (azim, elev, dist_mult)."""
    ensure_dir(PREVIEW_DIR)
    scene = bpy.context.scene
    extra = setup_preview_scene(sun_elevation=sun_elevation, ground=ground)
    mn, mx = world_bbox([o for o in focus_objs if o.type == "MESH"] + [c for o in focus_objs for c in descendants(o) if c.type == "MESH"])
    center = (mn + mx) / 2
    radius = max((mx - mn).length / 2, 0.5)
    cam_data = bpy.data.cameras.new("PV_Cam")
    cam_data.lens = lens
    cam = bpy.data.objects.new("PV_Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    r = scene.render
    r.resolution_x, r.resolution_y = size
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    r.film_transparent = False
    try:
        if engine == "CYCLES":
            r.engine = "CYCLES"
            scene.cycles.samples = samples
            scene.cycles.device = "CPU"
            try:
                scene.cycles.use_denoising = True
            except Exception:
                pass
        elif engine == "WORKBENCH":
            r.engine = "BLENDER_WORKBENCH"
        else:
            r.engine = "BLENDER_EEVEE_NEXT"
            try:
                scene.eevee.taa_render_samples = samples
            except Exception:
                pass
    except Exception as e:
        log("render engine fallback:", e)
    az_table = {"front": (180, 8), "back": (0, 8), "left": (270, 8), "right": (90, 8),
                "three_quarter": (215, 18), "three_quarter_back": (325, 18), "top": (180, 80), "low": (200, -10)}
    if custom_views:
        az_table.update({k: v[:2] for k, v in custom_views.items()})
    paths = []
    fov = 2 * math.atan((cam_data.sensor_width / 2) / cam_data.lens)
    dist = radius / math.sin(fov / 2) * 1.05 * distance_scale
    for v in views:
        az, el = az_table[v]
        d = dist * (custom_views[v][2] if custom_views and v in custom_views and len(custom_views[v]) > 2 else 1.0)
        # azimuth 0 = camera on -Y looking toward +Y (sees the BACK of a +Y facing model); 180 = camera on +Y (front)
        a, e = math.radians(az), math.radians(el)
        cam.location = center + Vector((math.sin(a) * math.cos(e) * -d * -1, -math.cos(a) * math.cos(e) * d, math.sin(e) * d))
        _look_at(cam, center)
        path = os.path.join(PREVIEW_DIR, f"{tag}_{v}.png")
        r.filepath = path
        bpy.ops.render.render(write_still=True)
        paths.append(path)
    log("previews:", ", ".join(os.path.relpath(p, REPO) for p in paths))
    # remove preview-only objects so the scene can still be exported afterwards
    for o in [cam] + extra + [bpy.data.objects.get("PV_Sun"), bpy.data.objects.get("PV_Fill")]:
        if o is not None:
            bpy.data.objects.remove(o)
    return paths


# --------------------------------------------------------------------------------------
# Armour / hard-surface helpers (used by build_player.py; reusable by other scripts)
# --------------------------------------------------------------------------------------
def ring(z, wx, wy, x0=0.0, y0=0.0, n=8, sq=0.6, rot=22.5):
    """Faceted superellipse cross-section at height z (half-widths wx/wy, centre x0/y0) as a list of Vectors."""
    pts = []
    for i in range(n):
        a = math.radians(rot) + 2 * math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        x = math.copysign(abs(c) ** sq, c) * wx
        y = math.copysign(abs(s) ** sq, s) * wy
        pts.append(Vector((x0 + x, y0 + y, z)))
    return pts


def shell(mb, specs, mat, n=8, sq=0.6, caps=True, x0=0.0, rot=22.5, xform_rot=None, center=(0, 0, 0)):
    """Loft a faceted shell through cross-sections. specs: [(z, half_width_x, half_width_y, y_offset), ...] bottom->top.
    xform_rot/center rotate the finished shell (degrees XYZ) about the world point `center`."""
    rings = [ring(z, wx, wy, x0=x0, y0=y0, n=n, sq=sq, rot=rot) for (z, wx, wy, y0) in specs]
    if xform_rot is None:
        return mb.loft(rings, mat=mat, caps=caps)
    c = Vector(center)
    moved = [[p - c for p in r] for r in rings]
    return mb.loft(moved, mat=mat, caps=caps, rot=xform_rot, center=c)


def bar(mb, a, b, w, t, mat, roll=0.0):
    """Thin strip from point a to point b (long axis), width w, thickness t (emissive seams, stripes, cables)."""
    a, b = Vector(a), Vector(b)
    d = b - a
    q = Vector((0, 0, 1)).rotation_difference(d.normalized())
    if roll:
        q = q @ Quaternion((0, 0, 1), math.radians(roll))
    mb.box((a + b) / 2, (w, t, d.length), mat=mat, rot=q)


def plate(mb, p0, p1, p2, p3, thick, mat, out=None):
    """Quad plate from 4 corner points with thickness pushed toward `out` (default +normal of the corner order)."""
    p0, p1, p2, p3 = (Vector(p) for p in (p0, p1, p2, p3))
    n = (p1 - p0).cross(p3 - p0).normalized()
    if out is not None and n.dot(Vector(out)) < 0:
        n = -n
    n = n * abs(thick)
    mb.hexa([p0, p1, p2, p3, p0 + n, p1 + n, p2 + n, p3 + n], mat)


def vent_slats(mb, center, w, h, n, mat, depth=0.012, axis="Y", gap=0.55):
    """n horizontal slats stacked along Z on a face whose normal is `axis` ('Y' front/back, 'X' side)."""
    pitch = h / n
    for i in range(n):
        z = center[2] - h / 2 + pitch * (i + 0.5)
        if axis == "Y":
            mb.box((center[0], center[1], z), (w, depth, pitch * gap), mat=mat)
        else:
            mb.box((center[0], center[1], z), (depth, w, pitch * gap), mat=mat)


# --------------------------------------------------------------------------------------
# Deterministic UV sphere.  NOTE: MB.sphere() (bmesh.ops.create_uvsphere) returns a different face / vertex ORDER in every Blender
# process (4.4), so any GLB that uses it is not byte-reproducible.  sphere_det() builds the same shape by revolving a semicircle.
# --------------------------------------------------------------------------------------
def sphere_det(mb, center=(0, 0, 0), r=0.5, seg=16, rings=10, mat=None, scale=(1, 1, 1), rot=None):
    """Drop-in for MB.sphere with a deterministic vertex / face order (poles are welded by mb.finish() / to_object())."""
    prof = [(math.sin(math.pi * i / rings) * r, -math.cos(math.pi * i / rings) * r * scale[2]) for i in range(rings + 1)]
    return mb.revolve(prof, center=center, seg=seg, axis="Z", mat=mat, caps=False, rot=rot, scale=(scale[0], scale[1]))

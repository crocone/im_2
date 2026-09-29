"""Armored Flight - destructible props (spec 4.5):  intact + fractured GLBs for four objects.

    node tools/run-blender.mjs tools/blender/build_destructibles.py                      # build + verify all
    node tools/run-blender.mjs tools/blender/build_destructibles.py -- --preview          # + preview renders
    node tools/run-blender.mjs tools/blender/build_destructibles.py -- --only column,watertower --preview

Outputs  public/assets/destructible_{column,citysign,watertower,smallbuilding}_{intact,fractured}.glb

Intact GLB     <Name>_Intact (Empty, origin = base centre on the ground)
               |- <Name>_Body   one merged visual mesh (bevelled parts, WeightedNormal shading, several materials)
               |- COL_1..n      collider Empties (display CUBE, location = box centre, scale = half extents)
Fractured GLB  <Name>_Fractured (Empty, same origin) with ONLY chunk_001..NNN children: real Voronoi fragments of the
               authored geometry (fracture.py), outer faces keep their materials, cut faces use `debris_interior`,
               every chunk is closed, origin = its volume centroid.

The authored geometry of every object is built as a list of convex-ish PARTS (objects).  The intact body is the merge
of all parts; the fractured state fractures every part separately (bigger parts -> more chunks, thin parts 1-3) and
numbers all chunks in one contiguous sequence.  All randomness is seeded -> byte-identical output on every run.
"""
import os
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa: E402,F401
import fracture as FR  # noqa: E402
import destr_textures as TX  # noqa: E402

ARGS = script_args()
PREVIEW = "--preview" in ARGS
ONLY = None
if "--only" in ARGS and ARGS.index("--only") + 1 < len(ARGS):
    ONLY = set(ARGS[ARGS.index("--only") + 1].split(","))

CHUNK_LIMITS = {"column": (10, 48), "citysign": (10, 48), "watertower": (10, 48), "smallbuilding": (12, 64)}


def seed_of(name):
    return zlib.crc32(name.encode("utf-8")) & 0xFFFFFFFF


# ======================================================================================================================
# Materials (created per object after reset_scene; names are shared across the game where they come from PALETTE)
# ======================================================================================================================
_TEX_CACHE = {}


def tex(name, fn):
    img = bpy.data.images.get(name)
    if img is None:
        if name not in _TEX_CACHE:
            _TEX_CACHE[name] = fn()
        img = TX.jpeg_image(name, _TEX_CACHE[name])
    return img


def mat_debris(kind="stone"):
    """The rough cut-face material.  Always named `debris_interior`; stone/concrete props get exposed aggregate
    concrete, metal props (sign, water tower) raw torn steel (each GLB carries its own variant)."""
    if kind == "metal":
        img = tex("destr_debris_metal", lambda: TX.debris_metal_albedo(512, 212))
        return make_textured_material("debris_interior", albedo=img, roughness=0.8, metallic=0.4)
    img = tex("destr_debris", lambda: TX.debris_albedo(512, 202))
    return make_textured_material("debris_interior", albedo=img, roughness=0.96, metallic=0.0)


COLUMN_H = 12.0


def mat_stone():
    img = tex("destr_column_stone", lambda: TX.column_stone_albedo(512, 2048, 111, height=COLUMN_H))
    return make_textured_material("column_stone", albedo=img, roughness=0.8, metallic=0.0)


def height_uv(obj, height=COLUMN_H, tiles=2.0, cyl=True, u_scale=2.5):
    """UVs for the full-height column texture: v = z / height (unique weathering over the height), u = `tiles` around
    (cylindrical parts) or x|y / u_scale (box parts); horizontal faces sample the texture at their own height."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    lay = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        n = f.normal
        if abs(n.z) > 0.75:
            for l in f.loops:
                p = l.vert.co
                l[lay].uv = (p.x / u_scale, p.z / height + p.y / (u_scale * 12.0))
        elif cyl:
            us = [math.atan2(l.vert.co.y, l.vert.co.x) / (2 * math.pi) * tiles for l in f.loops]
            for k in range(len(us)):
                while us[k] - us[0] > tiles * 0.5:
                    us[k] -= tiles
                while us[k] - us[0] < -tiles * 0.5:
                    us[k] += tiles
            for l, u in zip(f.loops, us):
                l[lay].uv = (u, l.vert.co.z / height)
        else:
            for l in f.loops:
                p = l.vert.co
                l[lay].uv = ((p.y if abs(n.x) >= abs(n.y) else p.x) / u_scale, p.z / height)
    bm.to_mesh(me)
    bm.free()
    me.update()


SHOP_H = 6.0


def mat_stucco():
    img = tex("destr_stucco", lambda: TX.stucco_facade_albedo(512, 1024, 313, height=SHOP_H, base="#D3A07A"))
    return make_textured_material("shop_stucco", albedo=img, roughness=0.86, metallic=0.0)


def mat_concrete(dark=False):
    if dark:
        img = tex("destr_concrete_dark", lambda: TX.concrete_albedo(512, 506, base="#6F6E6A"))
        return make_textured_material("concrete_cast_dark", albedo=img, roughness=0.9, metallic=0.0)
    img = tex("destr_concrete", lambda: TX.concrete_albedo(512, 505, base="#AAA59A"))
    return make_textured_material("concrete_cast", albedo=img, roughness=0.88, metallic=0.0)


def facade_uv(obj, mat_name="shop_stucco", height=SHOP_H, u_scale=3.0):
    """Height-mapped UVs (v = z / height, u = 3 m tiles along the wall) on the faces using `mat_name`, so the stucco
    texture's base splash and run-off streaks sit at the right heights."""
    me = obj.data
    idx = [i for i, s in enumerate(me.materials) if s is not None and s.name == mat_name]
    if not idx:
        return
    bm = bmesh.new()
    bm.from_mesh(me)
    lay = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        if f.material_index not in idx:
            continue
        n = f.normal
        for l in f.loops:
            p = l.vert.co
            if abs(n.z) > 0.75:
                l[lay].uv = (p.x / u_scale, p.z / height + p.y / (u_scale * 10.0))
            else:
                l[lay].uv = ((p.y if abs(n.x) >= abs(n.y) else p.x) / u_scale, p.z / height)
    bm.to_mesh(me)
    bm.free()
    me.update()


def mat_tank():
    img = tex("destr_tankpaint", lambda: TX.painted_steel_albedo(512, 404, base="#4C7C75", rust="#86461F"))
    return make_textured_material("tank_paint", albedo=img, roughness=0.55, metallic=0.35)


def neon(color_key):
    spec = {"cyan": ("#08242A", "#2EE6FF"), "magenta": ("#2A0824", "#FF2FD2"), "amber": ("#2A1A05", "#FFB020")}[color_key]
    return make_material(f"neon_{color_key}", spec[0], 0.0, 0.3, emission=spec[1], emission_strength=7.5)


def m(name):
    """Named non-textured materials."""
    table = {
        "sign_steel": dict(color="#343A43", metallic=0.55, roughness=0.45),
        "sign_panel": dict(color="#0C1016", metallic=0.35, roughness=0.28),
        "sign_trim": dict(color="#9AA3AD", metallic=0.85, roughness=0.30),
        "tank_inner": dict(color="#3A3431", metallic=0.6, roughness=0.7),
        "shop_plaster": dict(color="#C8C2B6", metallic=0.0, roughness=0.9),
        "shop_roofing": dict(color="#3A3C41", metallic=0.0, roughness=0.95),
        "shop_glass": dict(color="#101B26", metallic=0.65, roughness=0.06),
        "shop_door": dict(color="#2C5F66", metallic=0.35, roughness=0.5),
        "awning_red": dict(color="#B3302A", metallic=0.0, roughness=0.75),
        "awning_cream": dict(color="#E6D9BD", metallic=0.0, roughness=0.75),
        "ac_body": dict(color="#B7BCC2", metallic=0.55, roughness=0.42),
    }
    if name in table:
        return make_material(name, **table[name])
    return pal(name)


# ======================================================================================================================
# Geometry helpers (all coordinates in the object root space: metres, +Y front, +Z up, origin = base centre on ground)
# ======================================================================================================================
def zdir(d):
    return Vector((0, 0, 1)).rotation_difference(Vector(d).normalized()).to_matrix().to_4x4()


def tube(mb, p0, p1, r, seg=12, mat=None, r1=None):
    p0, p1 = Vector(p0), Vector(p1)
    return mb.cyl(center=(p0 + p1) * 0.5, r=r, h=(p1 - p0).length, seg=seg, axis="Z", mat=mat, r_top=r1,
                  rot=zdir(p1 - p0))


def bar(mb, p0, p1, w, h, mat=None, up=(0, 0, 1)):
    """Rectangular bar from p0 to p1, cross-section w (sideways) x h ('up')."""
    p0, p1 = Vector(p0), Vector(p1)
    d = (p1 - p0)
    L = d.length
    d.normalize()
    side = d.cross(Vector(up))
    if side.length < 1e-6:
        side = d.cross(Vector((1, 0, 0)))
    side.normalize()
    up2 = side.cross(d).normalized()
    M = Matrix((side, d, up2)).transposed().to_4x4()
    return mb.box(center=(p0 + p1) * 0.5, size=(w, L, h), mat=mat, rot=M)


def boxc(mb, lo, hi, mat=None, **kw):
    """Axis aligned box from min/max corners."""
    lo, hi = Vector(lo), Vector(hi)
    return mb.box(center=(lo + hi) * 0.5, size=tuple(hi - lo), mat=mat, **kw)


def ring_solid(mb, outer, inner, w0, w1, to3, mat):
    """Closed solid between an outer and an inner closed 2D outline (same vertex count), extruded from w0 to w1.
    to3(u, v, w) -> Vector.  Used for neon outline glyphs (rings, diamonds, frames)."""
    bm = mb.bm
    n = len(outer)
    oa = [bm.verts.new(to3(u, v, w0)) for u, v in outer]
    ob = [bm.verts.new(to3(u, v, w1)) for u, v in outer]
    ia = [bm.verts.new(to3(u, v, w0)) for u, v in inner]
    ib = [bm.verts.new(to3(u, v, w1)) for u, v in inner]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        for quad in ((ob[i], ob[j], ib[j], ib[i]), (oa[j], oa[i], ia[i], ia[j]),
                     (oa[i], oa[j], ob[j], ob[i]), (ia[j], ia[i], ib[i], ib[j])):
            try:
                faces.append(bm.faces.new(quad))
            except ValueError:
                pass
    return mb._finish_faces(faces, mat)


def circle2(cx, cy, r, seg, start=0.0):
    return [(cx + r * math.cos(start + 2 * math.pi * i / seg), cy + r * math.sin(start + 2 * math.pi * i / seg))
            for i in range(seg)]


def slab_with_openings(mb, origin, U, N, width, height, thick, openings, mat_out, mat_in, mat_edge):
    """Watertight wall slab with real rectangular openings (grid construction, no T-junctions).
    Local 2D: u along U in [0, width], v up (+Z) in [0, height]; w along N (outward) in [-thick/2, +thick/2].
    openings: list of (u0, u1, v0, v1)."""
    O, U, N = Vector(origin), Vector(U).normalized(), Vector(N).normalized()
    Z = Vector((0, 0, 1))
    us = sorted({0.0, width} | {o[0] for o in openings} | {o[1] for o in openings})
    vs = sorted({0.0, height} | {o[2] for o in openings} | {o[3] for o in openings})

    def p(u, v, w):
        return O + U * u + Z * v + N * w

    def solid(i, j):
        if i < 0 or j < 0 or i >= len(us) - 1 or j >= len(vs) - 1:
            return False
        cu = (us[i] + us[i + 1]) * 0.5
        cv = (vs[j] + vs[j + 1]) * 0.5
        for (u0, u1, v0, v1) in openings:
            if u0 < cu < u1 and v0 < cv < v1:
                return False
        return True

    t2 = thick * 0.5
    for i in range(len(us) - 1):
        for j in range(len(vs) - 1):
            if not solid(i, j):
                continue
            u0, u1, v0, v1 = us[i], us[i + 1], vs[j], vs[j + 1]
            mb.face([p(u0, v0, t2), p(u1, v0, t2), p(u1, v1, t2), p(u0, v1, t2)], mat_out)
            mb.face([p(u0, v0, -t2), p(u0, v1, -t2), p(u1, v1, -t2), p(u1, v0, -t2)], mat_in)
            if not solid(i - 1, j):
                mb.face([p(u0, v0, -t2), p(u0, v0, t2), p(u0, v1, t2), p(u0, v1, -t2)], mat_edge)
            if not solid(i + 1, j):
                mb.face([p(u1, v0, t2), p(u1, v0, -t2), p(u1, v1, -t2), p(u1, v1, t2)], mat_edge)
            if not solid(i, j - 1):
                mb.face([p(u0, v0, t2), p(u0, v0, -t2), p(u1, v0, -t2), p(u1, v0, t2)], mat_edge)
            if not solid(i, j + 1):
                mb.face([p(u0, v1, -t2), p(u0, v1, t2), p(u1, v1, t2), p(u1, v1, -t2)], mat_edge)


def striped_slab(mb, bl, br, fl, fr, thick, stripes, mats, down=(0, 0, -1)):
    """Closed thin slab over the quad bl-br-fl-fr (back-left, back-right, front-left, front-right), extruded by `thick`
    along `down`; the top/bottom/front/back faces are split into `stripes` strips (u from left to right) whose
    materials alternate through `mats` (awning canvas)."""
    bm = mb.bm
    bl, br, fl, fr = Vector(bl), Vector(br), Vector(fl), Vector(fr)
    dn = Vector(down).normalized() * thick
    tb, tf, bb, bf = [], [], [], []
    for k in range(stripes + 1):
        t = k / stripes
        b = bl.lerp(br, t)
        f = fl.lerp(fr, t)
        tb.append(bm.verts.new(b))
        tf.append(bm.verts.new(f))
        bb.append(bm.verts.new(b + dn))
        bf.append(bm.verts.new(f + dn))
    for k in range(stripes):
        mt = mats[k % len(mats)]
        idx = mb.slot(mt)
        for q in ((tb[k], tb[k + 1], tf[k + 1], tf[k]), (bb[k], bf[k], bf[k + 1], bb[k + 1]),
                  (tf[k], tf[k + 1], bf[k + 1], bf[k]), (tb[k + 1], tb[k], bb[k], bb[k + 1])):
            f = bm.faces.new(q)
            f.material_index = idx
    e0 = bm.faces.new((tb[0], tf[0], bf[0], bb[0]))
    e1 = bm.faces.new((tb[-1], bb[-1], bf[-1], tf[-1]))
    e0.material_index = e1.material_index = mb.slot(mats[0])


def inset_faces(mb, faces, thickness, depth, rim_mat=None, face_mat=None):
    ret = bmesh.ops.inset_individual(mb.bm, faces=faces, thickness=thickness, depth=depth, use_even_offset=True)
    if rim_mat is not None:
        idx = mb.slot(rim_mat)
        for f in ret["faces"]:
            f.material_index = idx
    if face_mat is not None:
        idx = mb.slot(face_mat)
        for f in faces:
            f.material_index = idx
    return ret["faces"]


def faces_facing(faces, direction, tol=0.9):
    d = Vector(direction)
    out = []
    for f in faces:
        f.normal_update()
        if f.normal.dot(d) > tol:
            out.append(f)
    return out


def cyl_uv(obj, center=(0.0, 0.0), tiles=2.0, v_scale=2.5, cap_scale=None, v_off=0.0):
    """Cylindrical UVs (u = tiles around, v = z / v_scale) with per-face seam unwrapping; faces facing up/down get a
    planar projection (cap_scale metres per UV unit)."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    lay = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
    cx, cy = center
    cap_scale = cap_scale or v_scale
    for f in bm.faces:
        if abs(f.normal.z) > 0.8:
            for l in f.loops:
                l[lay].uv = ((l.vert.co.x - cx) / cap_scale, (l.vert.co.y - cy) / cap_scale)
            continue
        us = [math.atan2(l.vert.co.y - cy, l.vert.co.x - cx) / (2 * math.pi) * tiles for l in f.loops]
        ref = us[0]
        for k in range(len(us)):
            while us[k] - ref > tiles * 0.5:
                us[k] -= tiles
            while us[k] - ref < -tiles * 0.5:
                us[k] += tiles
        for l, u in zip(f.loops, us):
            l[lay].uv = (u, l.vert.co.z / v_scale + v_off)
    bm.to_mesh(me)
    bm.free()
    me.update()


def clip_chip(mb, point, normal, depth, mat):
    """Wear chip on a convex corner/edge: cut the part of the mesh beyond a plane `depth` below `point`."""
    n = Vector(normal).normalized()
    FR.clip_halfspace(mb.bm, Vector(point) - n * depth, n, mb.slot(mat), cap_smooth=False)


def _hash01(p, salt=0):
    """Deterministic pseudo-random 0..1 from a position (coincident verts get the same value)."""
    x = math.sin(round(p[0], 5) * 127.1 + round(p[1], 5) * 311.7 + round(p[2], 5) * 74.7 + salt * 19.19) * 43758.5453
    return x - math.floor(x)


def ellipsoid(mb, center, radii, seg=8, rings=5, mat=None, rot=None, jitter=0.0, salt=0):
    """Deterministic UV ellipsoid (revolved half circle).  NOTE: bmesh.ops.create_uvsphere (and therefore
    common.MB.sphere) returns a different element order in every Blender process, which breaks byte-identical
    exports - never use it in this script.  The pole rings are collapsed by MB.finish()."""
    sub = MB()
    prof = [(math.sin(math.pi * k / rings), -math.cos(math.pi * k / rings)) for k in range(rings + 1)]
    sub.revolve(prof, seg=seg, mat=mat, caps=False)
    for v in sub.bm.verts:
        j = [1.0 + (_hash01(v.co, salt + a) - 0.5) * 2.0 * jitter for a in range(3)]
        v.co = Vector((v.co.x * radii[0] * j[0], v.co.y * radii[1] * j[1], v.co.z * radii[2] * j[2]))
    mb.merge_into(sub, Matrix.Translation(Vector(center)) @ rot_matrix(rot))
    sub.bm.free()


def boolean_chips(obj, cutters, mat):
    """Boolean wear chips (irregular spalls) cut out of `obj`; cutters = list of (center, scale xyz, rot deg, seed)
    -> jittered ellipsoids.  The cut faces keep `mat`."""
    cm = MB()
    for (c, s, rot, sd) in cutters:
        ellipsoid(cm, c, s, seg=7, rings=5, mat=mat, rot=rot, jitter=0.22, salt=sd)
    cutter = cm.to_object("_chip_cutter", smooth=False)
    mod = obj.modifiers.new("Chips", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    # FAST (BMesh intersect) is reproducible and leaves a clean 2-manifold here; the EXACT solver left a
    # non-manifold edge on the fluted shaft (which the fracture cannot cap)
    mod.solver = "FAST"
    mod.object = cutter
    try:
        mod.material_mode = "TRANSFER"
    except Exception:
        pass
    apply_modifiers(obj)
    bpy.data.objects.remove(cutter)
    canonicalize_mesh(obj)
    shade_smooth_by_angle(obj, 35.0)


def canonicalize_mesh(obj, q=1e-5):
    """Rebuild the mesh with vertices sorted by (quantised) position and faces sorted by their vertex indices (each
    loop rotated to start at its smallest index, winding kept).  Boolean solvers (EXACT is multithreaded) do not
    guarantee a stable element order between runs; this makes the result - and the exported GLB - byte-reproducible."""
    me = obj.data
    src = bmesh.new()
    src.from_mesh(me)
    verts = list(src.verts)
    keys = [(round(v.co.x / q), round(v.co.y / q), round(v.co.z / q)) for v in verts]
    order = sorted(range(len(verts)), key=lambda i: keys[i])
    rank = {verts[i]: r for r, i in enumerate(order)}
    faces = []
    for f in src.faces:
        ids = [rank[v] for v in f.verts]
        k = ids.index(min(ids))
        faces.append((ids[k:] + ids[:k], f.material_index))
    faces.sort()
    dst = bmesh.new()
    nv = [dst.verts.new(verts[i].co) for i in order]
    for ids, mi in faces:
        try:
            nf = dst.faces.new([nv[i] for i in ids])
            nf.material_index = mi
        except ValueError:
            pass
    dst.to_mesh(me)
    dst.free()
    src.free()
    me.update()


# ======================================================================================================================
# Part description
# ======================================================================================================================
class Part:
    """A convex-ish sub-part of an object: authored objects + how to seed its fracture."""

    def __init__(self, name, objs, mode="volume", n=6, min_volume=0.01, min_thickness=0.03, **kw):
        self.name = name
        self.objs = objs if isinstance(objs, (list, tuple)) else [objs]
        self.mode = mode          # 'volume' | 'surface' | 'axis' | 'single'
        self.n = n
        self.min_volume = min_volume
        self.min_thickness = min_thickness
        self.kw = kw

    def seeds(self, bm, mtable):
        rng = np.random.default_rng(seed_of(self.name))
        kw = self.kw
        if self.mode == "single" or self.n <= 1:
            return [], []
        if self.mode == "axis":
            s = FR.seeds_along(kw["p0"], kw["p1"], self.n, rng, lateral=kw.get("lateral", 0.45),
                               jitter=kw.get("jitter", 0.2))
            return s, [0.0] * len(s)
        if self.mode == "volume":
            src = bm
            cands = FR.sample_volume(src, kw.get("cands", 2500), rng)
            vol = FR.mesh_stats(src)["volume"]
            spacing = (vol / self.n) ** (1.0 / 3.0)
        else:  # surface
            flt = kw["face_filter"]
            cands, area = FR.sample_surface(bm, kw.get("cands", 2500), rng,
                                            face_filter=lambda f: flt(f, mtable), inset=kw.get("inset", 0.0))
            spacing = math.sqrt(area / self.n)
            if "project" in kw:
                cands = np.array([kw["project"](Vector(c))[:] for c in cands])
        seeds, weights = FR.pick_seeds(cands, self.n, rng, spacing, density=kw.get("density"),
                                       big_frac=kw.get("big_frac", 0.25), big_weight=kw.get("big_weight", 0.45),
                                       min_frac=kw.get("min_frac", 0.55))
        if kw.get("relax", 0):
            movable = [w == 0.0 for w in weights]
            seeds = FR.lloyd_relax(seeds, weights, cands, iters=kw["relax"], alpha=kw.get("relax_alpha", 0.5),
                                   movable=movable)
        if kw.get("depth_jitter"):
            nrm = Vector(kw["depth_axis"])
            seeds = [s + nrm * ((rng.random() - 0.5) * 2.0 * kw["depth_jitter"]) for s in seeds]
        return seeds, weights


# ======================================================================================================================
# 1) COLUMN  (~12 m fluted stone column: plinth, Attic base, fluted shaft with entasis, Doric-ish capital, wear)
# ======================================================================================================================
def build_column():
    stone = mat_stone()
    rng = np.random.default_rng(1201)
    Z_PL, Z_SH0, Z_SH1, Z_CAP, Z_TOP = 0.56, 1.10, 10.60, 11.40, 11.92
    parts = []

    # --- plinth + Attic base (one part: the moulding is embedded 1.5 cm into the plinth)
    mb = MB()
    mb.box((0, 0, Z_PL / 2), (2.3, 2.3, Z_PL), mat=stone)
    for (px, py, pz, nx, ny, nz, d) in ((1.15, 1.15, Z_PL, 1, 1, 0.8, 0.07), (-1.15, 1.15, Z_PL, -1, 1.2, 0.6, 0.05),
                                       (1.15, -1.15, 0.0, 1, -0.8, -0.4, 0.06), (-1.15, -1.15, Z_PL, -0.7, -1, 1.1, 0.09),
                                       (1.15, 0.2, Z_PL, 1.0, 0.1, 1.3, 0.035)):
        clip_chip(mb, (px, py, pz), (nx, ny, nz), d, stone)
    plinth = mb.to_object("Col_Plinth", bevel=(0.022, 2))
    height_uv(plinth, cyl=False)
    prof = [(0.99, Z_PL - 0.015), (1.02, 0.585), (1.045, 0.63), (1.042, 0.675), (1.012, 0.708), (0.975, 0.728),
            (0.952, 0.736), (0.93, 0.762), (0.915, 0.80), (0.922, 0.838), (0.946, 0.856), (0.962, 0.872),
            (0.972, 0.905), (0.962, 0.938), (0.94, 0.962), (0.905, 0.974), (0.868, 0.984), (0.845, 1.03),
            (0.83, Z_SH0)]
    mb = MB()
    mb.revolve(prof, seg=48, mat=stone, caps=True)
    clip_chip(mb, (0.74, 0.74, 0.64), (1, 1, -0.25), 0.05, stone)
    clip_chip(mb, (-0.88, -0.45, 0.905), (-1, -0.5, 0.35), 0.035, stone)
    base = mb.to_object("Col_Base")
    height_uv(base)
    parts.append(Part("column_base", [plinth, base], "volume", n=6, min_volume=0.05, min_thickness=0.1,
                      big_frac=0.3, relax=1))

    # --- fluted shaft with entasis and rounded flute terminations
    NFL, PER = 20, 4
    r0, r1 = 0.80, 0.67
    zs = [Z_SH0, Z_SH0 + 0.05, Z_SH0 + 0.13, Z_SH0 + 0.23, Z_SH0 + 0.36]
    mids = 10
    for k in range(1, mids):
        zs.append(Z_SH0 + 0.36 + (Z_SH1 - Z_SH0 - 0.72) * k / mids)
    zs += [Z_SH1 - 0.36, Z_SH1 - 0.23, Z_SH1 - 0.13, Z_SH1 - 0.05, Z_SH1]
    sections = []
    for z in zs:
        t = (z - Z_SH0) / (Z_SH1 - Z_SH0)
        r = r0 - (r0 - r1) * (t ** 1.5) + 0.01 * math.sin(math.pi * t)
        term = math.sin(0.5 * math.pi * min(1.0, (z - Z_SH0) / 0.36)) * math.sin(0.5 * math.pi * min(1.0, (Z_SH1 - z) / 0.36))
        depth = 0.052 * (r / r0) * term
        ring = []
        for f in range(NFL):
            for s in range(PER):
                u = s / PER
                a = 2 * math.pi * (f + u) / NFL + math.pi / NFL
                rr = r - depth * math.sin(math.pi * u)
                ring.append(Vector((rr * math.cos(a), rr * math.sin(a), z)))
        sections.append(ring)
    mb = MB()
    mb.loft(sections, mat=stone, caps=True)
    shaft = mb.to_object("Col_Shaft", sharp_angle=40.0)
    chips = []
    for (a_deg, z, s, sd) in ((28, 2.3, (0.2, 0.16, 0.24), 11), (145, 5.6, (0.16, 0.13, 0.3), 12),
                              (260, 3.1, (0.26, 0.2, 0.18), 13), (80, 8.4, (0.18, 0.14, 0.22), 14),
                              (205, 9.7, (0.14, 0.12, 0.2), 15), (330, 6.9, (0.12, 0.1, 0.28), 16)):
        a = math.radians(a_deg)
        t = (z - Z_SH0) / (Z_SH1 - Z_SH0)
        r = r0 - (r0 - r1) * (t ** 1.5)
        c = (math.cos(a) * (r + 0.06), math.sin(a) * (r + 0.06), z)
        chips.append((c, s, (rng.uniform(-30, 30), rng.uniform(-30, 30), a_deg), sd))
    boolean_chips(shaft, chips, stone)
    height_uv(shaft)
    parts.append(Part("column_shaft", [shaft], "volume", n=26, min_volume=0.06, min_thickness=0.12, big_frac=0.3,
                      big_weight=0.5, relax=1, relax_alpha=0.35,
                      density=[FR.density_impact((0.35, 0.75, 3.6), 1.4, 3.5), FR.density_base(Z_SH0, 6.0, 1.2)]))

    # --- capital: astragal + neck + annulets + echinus (revolve, embedded 1.5 cm into the abacus) + abacus
    cprof = [(0.672, Z_SH1), (0.70, 10.615), (0.715, 10.65), (0.70, 10.685), (0.675, 10.70), (0.665, 10.71),
             (0.665, 10.90), (0.682, 10.915), (0.69, 10.935), (0.682, 10.95), (0.698, 10.965), (0.705, 10.985),
             (0.742, 11.03), (0.80, 11.10), (0.878, 11.18), (0.958, 11.26), (1.025, 11.33), (1.058, 11.38),
             (1.06, Z_CAP + 0.015)]
    mb = MB()
    mb.revolve(cprof, seg=48, mat=stone, caps=True)
    clip_chip(mb, (0.0, -1.0, 11.3), (0.15, -1, 0.3), 0.05, stone)
    echinus = mb.to_object("Col_Echinus")
    height_uv(echinus)
    mb = MB()
    mb.box((0, 0, (Z_CAP + Z_TOP) / 2), (2.24, 2.24, Z_TOP - Z_CAP), mat=stone)
    for (px, py, pz, nx, ny, nz, d) in ((1.12, 1.12, Z_TOP, 1, 1, 1.0, 0.16), (-1.12, 1.12, Z_CAP, -1, 1, -0.7, 0.06),
                                       (1.12, -1.12, Z_TOP, 1, -1.2, 0.5, 0.07), (-1.12, -1.12, Z_TOP, -1, -0.9, 0.9, 0.05),
                                       (-0.3, 1.12, Z_TOP, 0.2, 1.0, 1.1, 0.04)):
        clip_chip(mb, (px, py, pz), (nx, ny, nz), d, stone)
    abacus = mb.to_object("Col_Abacus", bevel=(0.02, 2))
    height_uv(abacus, cyl=False)
    parts.append(Part("column_capital", [echinus, abacus], "volume", n=5, min_volume=0.05, min_thickness=0.1,
                      big_frac=0.2, relax=1))

    # round shaft = two crossed boxes (plus-shaped footprint hugs the circle much better than one square)
    cols = [((0, 0, Z_SH0 / 2), (1.15, 1.15, Z_SH0 / 2)),
            ((0, 0, (Z_SH0 + Z_CAP) / 2), (0.84, 0.61, (Z_CAP - Z_SH0) / 2)),
            ((0, 0, (Z_SH0 + Z_CAP) / 2), (0.61, 0.84, (Z_CAP - Z_SH0) / 2)),
            ((0, 0, (Z_CAP + Z_TOP) / 2), (1.12, 1.12, (Z_TOP - Z_CAP) / 2))]
    return dict(name="Column", parts=parts, cols=cols, impact=(0.35, 0.75, 3.6),
                closeups=[((0, 0, 0.9), 1.3, ("cq", "cb")), ((0, 0, 11.1), 1.3, ("cl",))])


# ======================================================================================================================
# 2) CITY SIGN  (~10.4 m steel mast with a projecting blade sign, neon glyphs on both faces)
# ======================================================================================================================
def glyph_face(mb, side, colors, cx=1.40):
    """Abstract neon glyph composition (no letters / brands) on one blade face.  side = +1 (front, +Y) / -1 (back).
    Every glyph is symmetric about the panel's vertical centre line, so both faces read the same.  The glyphs are
    embedded 1 cm into the recessed panel (so the fracture keeps them with their panel piece)."""
    w0, w1 = sorted((0.17 * side, 0.214 * side))

    def to3(u, v, w):
        return Vector((cx + u, w, v))
    c_ring, c_chev, c_diam, c_bar = colors
    # big ring + inner disc
    ring_solid(mb, circle2(0, 8.78, 0.62, 36), circle2(0, 8.78, 0.50, 36), w0, w1, to3, c_ring)
    mb.prism(circle2(cx, 8.78, 0.22, 20), w0, w1, mat=c_diam, plane="XZ")
    # three chevrons
    for zc in (7.62, 7.20, 6.78):
        pts = [(-0.60, zc + 0.19), (0.0, zc - 0.19), (0.60, zc + 0.19), (0.43, zc + 0.19), (0.0, zc - 0.01),
               (-0.43, zc + 0.19)]
        mb.prism([(cx + u, v) for (u, v) in pts], w0, w1, mat=c_chev, plane="XZ")
    # diamond outline + small filled diamond
    zc = 5.92
    outer = [(0.0, zc - 0.62), (0.56, zc), (0.0, zc + 0.62), (-0.56, zc)]
    inner = [(0.0, zc - 0.47), (0.42, zc), (0.0, zc + 0.47), (-0.42, zc)]
    ring_solid(mb, outer, inner, w0, w1, to3, c_diam)
    mb.prism([(cx + u, v) for (u, v) in ((0.0, zc - 0.2), (0.17, zc), (0.0, zc + 0.2), (-0.17, zc))], w0, w1,
             mat=c_ring, plane="XZ")
    # stacked bars
    for k, (zc, w) in enumerate(((5.02, 1.30), (4.76, 0.98), (4.50, 0.66))):
        boxc(mb, (cx - w / 2, w0, zc - 0.055), (cx + w / 2, w1, zc + 0.055), c_bar if k != 1 else c_ring)
    # neon border frame
    outer = [(-0.80, 4.10), (0.80, 4.10), (0.80, 9.52), (-0.80, 9.52)]
    inner = [(-0.75, 4.15), (0.75, 4.15), (0.75, 9.47), (-0.75, 9.47)]
    ring_solid(mb, outer, inner, w0, w1, to3, c_chev)


def build_citysign():
    steel = m("sign_steel")
    panel = m("sign_panel")
    trim = m("sign_trim")
    conc = mat_concrete()
    cyan, mag, amb = neon("cyan"), neon("magenta"), neon("amber")
    beacon = m("beacon_red")
    parts = []
    Z0 = 0.35                     # top of base plate
    MAST_TOP = 10.2
    H = 0.17                      # mast half width
    BX0, BX1, BZ0, BZ1, BT = 0.45, 2.35, 3.9, 9.7, 0.21

    # --- concrete footing
    mb = MB()
    mb.box((0, 0, 0.16), (1.2, 1.2, 0.32), mat=conc, taper=(0.93, 0.93))
    clip_chip(mb, (0.6, 0.6, 0.32), (1, 1, 0.9), 0.04, conc)
    footing = mb.to_object("Sign_Footing", bevel=(0.02, 2), uv=(2.0, 2.0))
    parts.append(Part("sign_footing", footing, "volume", n=3, min_volume=0.02, min_thickness=0.06, big_frac=0.0))

    # --- base plate, gussets, anchor nuts
    mb = MB()
    boxc(mb, (-0.4, -0.4, 0.32), (0.4, 0.4, Z0), steel)
    for (sx, sy) in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        mb.cyl((sx * 0.31, sy * 0.31, Z0 + 0.02), 0.036, 0.05, seg=6, mat=trim)
        mb.cyl((sx * 0.31, sy * 0.31, Z0 + 0.06), 0.016, 0.07, seg=8, mat=trim)
    for ang in (0, 90, 180, 270):
        g = MB()
        g.prism([(H + 0.002, Z0 - 0.005), (0.39, Z0 - 0.005), (0.39, Z0 + 0.06), (H + 0.002, Z0 + 0.42)], -0.012, 0.012,
                mat=steel, plane="XZ")
        mb.merge_into(g, Matrix.Rotation(math.radians(ang), 4, "Z"))
        g.bm.free()
    baseplate = mb.to_object("Sign_BasePlate", bevel=(0.006, 1), uv=(1.0, 1.0))
    parts.append(Part("sign_baseplate", baseplate, "single", n=1))

    # --- mast with collars, cable conduit, crown cap and beacon
    mb = MB()
    boxc(mb, (-H, -H, Z0), (H, H, MAST_TOP), steel)
    for zc in (4.35, 6.85, 9.35):
        boxc(mb, (-H - 0.03, -H - 0.03, zc - 0.1), (H + 0.03, H + 0.03, zc + 0.1), trim)
    boxc(mb, (-H - 0.045, -0.05, 0.6), (-H + 0.01, 0.05, 9.9), steel)
    boxc(mb, (-H - 0.04, -H - 0.04, MAST_TOP - 0.01), (H + 0.04, H + 0.04, MAST_TOP + 0.06), trim)
    mb.box((0, 0, MAST_TOP + 0.125), (0.38, 0.38, 0.14), mat=steel, taper=(0.35, 0.35))
    mb.cyl((0, 0, MAST_TOP + 0.25), 0.06, 0.14, seg=12, mat=beacon)
    mb.cyl((0, 0, MAST_TOP + 0.33), 0.075, 0.03, seg=12, mat=trim)
    mast = mb.to_object("Sign_Mast", bevel=(0.012, 2), uv=(2.0, 2.0))
    parts.append(Part("sign_mast", mast, "axis", n=4, min_volume=0.004, min_thickness=0.02,
                      p0=(0, 0, Z0), p1=(0, 0, MAST_TOP + 0.35), lateral=0.5))

    # --- blade: frame box with inset panels, crown, bottom cap, amber edge neon, brackets, glyphs on both faces
    mb = MB()
    fs = boxc(mb, (BX0, -BT, BZ0), (BX1, BT, BZ1), steel)
    inset_faces(mb, faces_facing(fs, (0, 1, 0)) + faces_facing(fs, (0, -1, 0)), 0.07, -0.03, rim_mat=steel,
                face_mat=panel)
    boxc(mb, (BX0 - 0.06, -BT - 0.04, BZ1 - 0.01), (BX1 + 0.06, BT + 0.04, BZ1 + 0.14), trim)
    mb.box(((BX0 + BX1) / 2, 0, BZ1 + 0.19), (BX1 - BX0 + 0.12, 2 * BT + 0.08, 0.12), mat=steel, taper=(0.9, 0.55))
    boxc(mb, (BX0 - 0.05, -BT - 0.035, BZ0 - 0.14), (BX1 + 0.05, BT + 0.035, BZ0 + 0.01), trim)
    boxc(mb, (BX1 - 0.015, -0.055, BZ0 + 0.2), (BX1 + 0.03, 0.055, BZ1 - 0.2), amb)
    for zc in (4.35, 6.85, 9.35):
        boxc(mb, (H + 0.032, -0.06, zc - 0.08), (BX0 + 0.015, 0.06, zc + 0.08), steel)
        boxc(mb, (H + 0.032, -0.15, zc - 0.17), (H + 0.055, 0.15, zc + 0.17), trim)
        dz = 0.46 if zc < 5 else -0.46
        bar(mb, (H + 0.05, 0.0, zc + math.copysign(0.14, dz)), (BX0 + 0.012, 0.0, zc + dz), 0.05, 0.05, steel,
            up=(0, 1, 0))
    blade = mb.to_object("Sign_Blade", bevel=(0.01, 2), uv=(2.0, 2.0))
    gm = MB()                                  # neon glyphs: separate object, no bevel (same fracture part)
    glyph_face(gm, +1, (mag, cyan, amb, cyan))
    glyph_face(gm, -1, (cyan, mag, amb, mag))
    glyphs = gm.to_object("Sign_Glyphs", uv=(2.0, 2.0))
    parts.append(Part("sign_blade", [blade, glyphs], "surface", n=19, min_volume=0.02, min_thickness=0.07, big_frac=0.3,
                      big_weight=0.5, relax=1, relax_alpha=0.4,
                      face_filter=lambda f, mt: f.normal.y > 0.95 and mt.mats[f.material_index].name == "sign_panel",
                      inset=0.18, depth_jitter=0.03, depth_axis=(0, 1, 0),
                      density=[FR.density_impact((1.6, 0.0, 6.9), 1.2, 3.0)]))

    cols = [((0, 0, 0.16), (0.6, 0.6, 0.16)),
            ((0, 0, (Z0 + MAST_TOP) / 2 + 0.1), (0.2, 0.2, (MAST_TOP - Z0) / 2 + 0.2)),
            (((BX0 + BX1) / 2 - 0.1, 0, (BZ0 + BZ1) / 2 + 0.04), ((BX1 - BX0) / 2 + 0.12, BT + 0.04, (BZ1 - BZ0) / 2 + 0.2))]
    return dict(name="CitySign", parts=parts, cols=cols, impact=(1.6, 0.0, 6.9), debris="metal",
                closeups=[((1.3, 0, 8.7), 1.3, ("cq",)), ((0, 0, 0.45), 0.8, ("cq",))])


# ======================================================================================================================
# 3) WATER TOWER  (~8.8 m: steel legs + X bracing + girders, riveted tank with hoops, conical roof, ladder, pipe)
# ======================================================================================================================
def build_watertower():
    paint = mat_tank()
    inner = m("tank_inner")
    dark = m("steel_dark")
    steel = m("steel")
    conc = mat_concrete()
    parts = []
    R, T, ZB, ZT, TF = 2.10, 0.08, 3.95, 7.35, 0.12
    GZ0 = ZB - 0.26
    LB, LT, LR = 1.62, 1.36, 0.15

    # --- tank: cup (wall + floor, closed), hoops, vertical seams, rivets
    mb = MB()
    SEG = 40
    mb.revolve([(0.0, ZB), (R, ZB), (R, ZT), (R - T, ZT)], seg=SEG, mat=paint, caps=False)
    mb.revolve([(R - T, ZT), (R - T, ZB + TF), (0.0, ZB + TF)], seg=SEG, mat=inner, caps=False)
    hoops = (ZB + 0.30, ZB + 1.10, ZB + 1.90, ZB + 2.70)
    for zc in hoops:
        prof = [(R - 0.006, zc - 0.055), (R + 0.038, zc - 0.055), (R + 0.038, zc + 0.055), (R - 0.006, zc + 0.055)]
        mb.revolve(prof + [prof[0]], seg=SEG, mat=dark, caps=False)
    prof = [(R - 0.006, ZT - 0.10), (R + 0.05, ZT - 0.10), (R + 0.05, ZT - 0.01), (R - 0.006, ZT - 0.01)]
    mb.revolve(prof + [prof[0]], seg=SEG, mat=dark, caps=False)
    NSEAM = 10
    for k in range(NSEAM):
        a = 2 * math.pi * (k + 0.5) / NSEAM
        ca, sa = math.cos(a), math.sin(a)
        mb.box((ca * (R + 0.002), sa * (R + 0.002), (ZB + ZT) / 2 - 0.05), (0.024, 0.075, ZT - ZB - 0.16), mat=paint,
               rot=(0, 0, math.degrees(a)))
        for zr in np.arange(ZB + 0.55, ZT - 0.2, 0.4):
            if min(abs(zr - h) for h in hoops) < 0.12:
                continue
            mb.cyl((ca * (R + 0.02), sa * (R + 0.02), zr), 0.017, 0.03, seg=4, axis="X", r_top=0.004,
                   rot=(0, 0, math.degrees(a)), mat=dark)
    for zc in hoops:
        for k in range(0, SEG, 2):
            a = 2 * math.pi * (k + 0.5) / SEG
            # centre R+0.040: the base sits 5 mm inside the faceted (40-gon) band even at mid-facet
            mb.cyl((math.cos(a) * (R + 0.040), math.sin(a) * (R + 0.040), zc), 0.016, 0.028, seg=4, axis="X",
                   r_top=0.004, rot=(0, 0, math.degrees(a)), mat=dark)
    tank = mb.to_object("WT_Tank", sharp_angle=40.0)
    cyl_uv(tank, tiles=3.0, v_scale=2.2, cap_scale=2.2)

    def tank_filter(f, mt):
        """Inner skin of the cup (inner wall + inner floor); inset T/2 against the normal = shell mid-surface."""
        if mt.mats[f.material_index].name == "tank_inner":
            c = f.calc_center_median()
            return f.normal.z > 0.9 or (Vector((c.x, c.y)).length < R - 0.02 and abs(f.normal.z) < 0.2)
        return False
    parts.append(Part("tank", tank, "surface", n=13, min_volume=0.03, min_thickness=0.075, big_frac=0.3,
                      big_weight=0.5, relax=1, relax_alpha=0.4, face_filter=tank_filter, inset=T / 2,
                      density=[FR.density_impact((0.4, R, 5.9), 1.6, 3.0)]))

    # --- conical roof shell + finial
    mb = MB()
    # (no two consecutive radius-0 profile points: collapsing degenerate quads in remove_doubles is order-unstable)
    rprof = [(R - T, ZT), (R + 0.16, ZT), (R + 0.16, ZT + 0.07), (0.06, ZT + 1.14), (0.06, ZT + 1.06), (R - T, ZT)]
    mb.revolve(rprof, seg=SEG, mat=paint, caps=False)
    mb.cyl((0, 0, ZT + 1.22), 0.14, 0.2, seg=12, mat=dark)
    mb.cyl((0, 0, ZT + 1.39), 0.2, 0.14, seg=12, mat=dark, r_top=0.03)
    ellipsoid(mb, (0, 0, ZT + 1.49), (0.05, 0.05, 0.05), seg=8, rings=5, mat=dark)
    def z_roof(r):
        return ZT + 0.07 + (R + 0.16 - r) * (1.10 / (R + 0.16))
    for k in range(8):
        a = 2 * math.pi * (k + 0.25) / 8
        p0 = Vector((math.cos(a) * (R + 0.1), math.sin(a) * (R + 0.1), z_roof(R + 0.1) + 0.012))
        p1 = Vector((math.cos(a) * 0.3, math.sin(a) * 0.3, z_roof(0.3) + 0.012))
        bar(mb, p0, p1, 0.05, 0.05, dark, up=(0, 0, 1))
    roof = mb.to_object("WT_Roof", sharp_angle=40.0)
    cyl_uv(roof, tiles=3.0, v_scale=2.2)
    parts.append(Part("roof", roof, "surface", n=5, min_volume=0.01, min_thickness=0.04, big_frac=0.2,
                      face_filter=lambda f, mt: f.normal.z > 0.3 and mt.mats[f.material_index].name == "tank_paint",
                      inset=0.045))

    # --- legs (tube + base plate + footing + cap), each fractured into 2 along its axis
    legs = []
    for (sx, sy) in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
        mb = MB()
        pb = Vector((sx * LB, sy * LB, 0.27))
        pt = Vector((sx * LT, sy * LT, GZ0))
        tube(mb, pb, pb.lerp(pt, 1.0 - 0.022 / (pt.z - pb.z)), LR, seg=14, mat=dark)
        boxc(mb, (pb.x - 0.26, pb.y - 0.26, 0.265), (pb.x + 0.26, pb.y + 0.26, 0.30), dark)
        for (ox, oy) in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            mb.cyl((pb.x + ox * 0.195, pb.y + oy * 0.195, 0.315), 0.026, 0.04, seg=6, mat=steel)
        mb.box((pb.x, pb.y, 0.135), (0.86, 0.86, 0.27), mat=conc, taper=(0.9, 0.9))
        boxc(mb, (pt.x - 0.19, pt.y - 0.19, GZ0 - 0.045), (pt.x + 0.19, pt.y + 0.19, GZ0 - 0.0015), dark)
        for k in range(4):                      # gusset fins at the foot
            a = math.radians(45 + 90 * k)
            d = Vector((math.cos(a), math.sin(a), 0))
            g0 = pb + d * (LR - 0.02) + Vector((0, 0, 0.03))
            bar(mb, g0 + Vector((0, 0, 0.0)), g0 + d * 0.1 + Vector((0, 0, 0.0)), 0.018, 0.2, dark,
                up=(0, 0, 1))
        leg = mb.to_object(f"WT_Leg_{len(legs) + 1}", bevel=(0.008, 1), uv=(1.5, 1.5))
        legs.append((leg, pb, pt))
        parts.append(Part(f"leg_{len(legs)}", leg, "axis", n=2, min_volume=0.005, min_thickness=0.03,
                          p0=pb + Vector((0, 0, 0.3)), p1=pt, lateral=0.55))

    # --- girders under the tank (X girders full length, Y girders between them, 2 cross beams)
    girders = [((-LT - 0.08, LT - 0.08, GZ0), (LT + 0.08, LT + 0.08, ZB)),
               ((-LT - 0.08, -LT - 0.08, GZ0), (LT + 0.08, -LT + 0.08, ZB)),
               ((LT - 0.08, -LT + 0.08, GZ0), (LT + 0.08, LT - 0.08, ZB)),
               ((-LT - 0.08, -LT + 0.08, GZ0), (-LT + 0.08, LT - 0.08, ZB)),
               ((-LT + 0.08, 0.55, GZ0 + 0.02), (LT - 0.08, 0.69, ZB)),
               ((-LT + 0.08, -0.69, GZ0 + 0.02), (LT - 0.08, -0.55, ZB))]
    for k, (lo, hi) in enumerate(girders):
        mb = MB()
        boxc(mb, lo, hi, dark)
        g = mb.to_object(f"WT_Girder_{k + 1}", bevel=(0.01, 1), uv=(1.5, 1.5))
        parts.append(Part(f"girder_{k + 1}", g, "single", n=1))

    # --- X bracing: 8 rods (each its own part), the two diagonals of a side offset in depth so they never touch
    sides = [(0, 1), (1, 2), (2, 3), (3, 0)]
    for si, (a, b) in enumerate(sides):
        _, pa0, pa1 = legs[a]
        _, pb0, pb1 = legs[b]

        def at(p0, p1, z):
            t = (z - p0.z) / (p1.z - p0.z)
            return p0.lerp(p1, t)
        mid = (pa0 + pb0) * 0.5
        outward = Vector((mid.x, mid.y, 0)).normalized()
        for di, (za, zb, off) in enumerate(((0.62, 3.35, 0.024), (3.35, 0.62, -0.024))):
            A = at(pa0, pa1, za)
            B = at(pb0, pb1, zb)
            d = (B - A).normalized()
            A2 = A + d * (LR + 0.004) + outward * off
            B2 = B - d * (LR + 0.004) + outward * off
            mb = MB()
            tube(mb, A2, B2, 0.024, seg=8, mat=steel)
            tb = A2.lerp(B2, 0.36)
            tube(mb, tb - d * 0.11, tb + d * 0.11, 0.036, seg=8, mat=dark)
            rod = mb.to_object(f"WT_Brace_{si * 2 + di + 1}")
            parts.append(Part(f"brace_{si * 2 + di + 1}", rod, "single", n=1))

    # --- ladder (rails + rungs + stand-offs to tank and girder) and the riser pipe
    mb = MB()
    LY, LX = 2.30, 0.22
    for sx in (-1, 1):
        boxc(mb, (sx * LX - 0.025, LY - 0.035, 0.0), (sx * LX + 0.025, LY + 0.035, ZT + 0.55), steel)
        for zc in (ZB + 0.8, ZB + 2.5):
            ywall = math.sqrt(R * R - LX * LX)
            boxc(mb, (sx * LX - 0.02, ywall + 0.012, zc - 0.03), (sx * LX + 0.02, LY - 0.02, zc + 0.03), steel)
        boxc(mb, (sx * LX - 0.02, LT + 0.082, GZ0 + 0.08), (sx * LX + 0.02, LY - 0.02, GZ0 + 0.16), steel)
    for zr in np.arange(0.35, ZT + 0.45, 0.3):
        mb.cyl((0, LY, float(zr)), 0.016, 2 * LX + 0.03, seg=6, axis="X", mat=steel)
    ladder = mb.to_object("WT_Ladder", uv=(1.0, 1.0))
    parts.append(Part("ladder", ladder, "axis", n=3, min_volume=0.001, min_thickness=0.01,
                      p0=(0, LY, 0.2), p1=(0, LY, ZT + 0.5), lateral=0.3))
    mb = MB()
    mb.cyl((0, 0, (ZB - 0.002) / 2), 0.13, ZB - 0.002, seg=16, mat=dark)
    for zc in (0.45, 2.2, ZB - 0.12):
        mb.cyl((0, 0, zc), 0.19, 0.06, seg=16, mat=steel)
    pipe = mb.to_object("WT_Pipe", bevel=(0.006, 1), uv=(1.0, 1.0))
    parts.append(Part("pipe", pipe, "axis", n=2, min_volume=0.002, min_thickness=0.02,
                      p0=(0, 0, 0.1), p1=(0, 0, ZB - 0.1), lateral=0.6))

    cols = [((0, 0, (ZB + ZT) / 2), (R + 0.05, 0.73 * (R + 0.05), (ZT - ZB) / 2)),
            ((0, 0, (ZB + ZT) / 2), (0.73 * (R + 0.05), R + 0.05, (ZT - ZB) / 2)),
            ((0, 0, ZT + 0.6), (R * 0.62, R * 0.62, 0.6)),
            ((0, 0, (GZ0 + ZB) / 2), (LT + 0.08, LT + 0.08, (ZB - GZ0) / 2))]
    for (sx, sy) in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
        cols.append(((sx * (LB + LT) / 2, sy * (LB + LT) / 2, GZ0 / 2), (0.26, 0.26, GZ0 / 2)))
    return dict(name="WaterTower", parts=parts, cols=cols, impact=(0.4, R, 5.9), debris="metal",
                closeups=[((0.9, 1.9, 6.4), 1.4, ("cq",)), ((1.5, 1.6, 0.6), 0.9, ("cq",))])


# ======================================================================================================================
# 4) SMALL BUILDING  (11 x 9 m corner shop: stucco walls with real openings, shopfront, neon fascia, awning, parapet,
#    roof with hatch, AC unit, vent, downpipe)
# ======================================================================================================================
def build_smallbuilding():
    stucco = mat_stucco()
    plaster = m("shop_plaster")
    roofing = m("shop_roofing")
    conc = mat_concrete()
    concd = mat_concrete(dark=True)
    frame = m("steel_dark")
    glass = m("shop_glass")
    doorm = m("shop_door")
    panel = m("sign_panel")
    red, cream = m("awning_red"), m("awning_cream")
    acm = m("ac_body")
    cyan, mag, amb = neon("cyan"), neon("magenta"), neon("amber")
    parts = []
    W2, D2, T, HW = 5.5, 4.5, 0.3, 5.5
    RZ0, RZ1 = 4.25, 4.60
    UVS = (3.0, 3.0)

    def window_unit(mb, a, b, z0, z1, N, depth_c, mullions=(), transom=None, fw=0.07, sill=True):
        """Frame + glass inside an opening from corner a to b (on the wall centre line, along the wall), z0..z1."""
        a, b, N = Vector(a), Vector(b), Vector(N)
        U = (b - a).normalized()
        L = (b - a).length

        def P(u, z, w):
            return a + U * u + N * w + Vector((0, 0, z))
        w0, w1 = depth_c - 0.06, depth_c + 0.06
        # pieces overlap by 5 mm instead of touching: coincident corners would be welded into non-manifold edges
        pieces = [(-0.01, L + 0.01, z0 - 0.01, z0 + fw), (-0.01, L + 0.01, z1 - fw, z1 + 0.01),
                  (-0.01, fw, z0 + fw - 0.005, z1 - fw + 0.005), (L - fw, L + 0.01, z0 + fw - 0.005, z1 - fw + 0.005)]
        for mu in mullions:
            pieces.append((mu - fw / 2, mu + fw / 2, z0 + fw - 0.005, z1 - fw + 0.005))
        if transom is not None:
            pieces.append((fw - 0.005, L - fw + 0.005, transom - fw / 2, transom + fw / 2))
        for (u0, u1, zz0, zz1) in pieces:
            c0, c1 = P(u0, zz0, w0), P(u1, zz1, w1)
            boxc(mb, (min(c0.x, c1.x), min(c0.y, c1.y), zz0), (max(c0.x, c1.x), max(c0.y, c1.y), zz1), frame)
        g0, g1 = P(fw - 0.01, z0 + fw - 0.01, depth_c - 0.012), P(L - fw + 0.01, z1 - fw + 0.01, depth_c + 0.012)
        boxc(mb, (min(g0.x, g1.x), min(g0.y, g1.y), z0 + fw - 0.01), (max(g0.x, g1.x), max(g0.y, g1.y), z1 - fw + 0.01),
             glass)
        if sill:
            s0, s1 = P(-0.1, z0 - 0.1, T / 2 - 0.03), P(L + 0.1, z0 + 0.0, T / 2 + 0.07)
            boxc(mb, (min(s0.x, s1.x), min(s0.y, s1.y), z0 - 0.1), (max(s0.x, s1.x), max(s0.y, s1.y), z0 + 0.0), conc)

    def bands(mb, a, b, N, gaps=(), corners=False):
        """Plinth band (dark concrete, 4 cm proud) + string course (6 cm proud) + coping along one wall, all embedded
        2 cm into the wall.  corners=True (front/back walls, which run over the full width): the bands wrap around the
        building corners (return pieces on the wall end faces) and the coping covers the corner; side walls get a
        coping that stops at the front/back coping (no overlaps between parts)."""
        a, b, N = Vector(a), Vector(b), Vector(N)
        U = (b - a).normalized()
        L = (b - a).length

        def box_uw(u0, u1, w0, w1, z0, z1, mat):
            q0 = a + U * u0 + N * w0
            q1 = a + U * u1 + N * w1
            boxc(mb, (min(q0.x, q1.x), min(q0.y, q1.y), z0), (max(q0.x, q1.x), max(q0.y, q1.y), z1), mat)
        segs = [(0.0, L)]
        for (g0, g1) in gaps:
            nsegs = []
            for (s0, s1) in segs:
                if g1 <= s0 or g0 >= s1:
                    nsegs.append((s0, s1))
                    continue
                if g0 > s0:
                    nsegs.append((s0, g0))
                if g1 < s1:
                    nsegs.append((g1, s1))
            segs = nsegs
        e = 0.04 if corners else 0.0
        for (s0, s1) in segs:
            box_uw(s0 - (e if s0 == 0.0 else 0.0), s1 + (e if s1 == L else 0.0), T / 2 - 0.02, T / 2 + 0.04, 0.0, 0.5,
                   concd)
        box_uw(-e * 1.5, L + e * 1.5, T / 2 - 0.02, T / 2 + 0.06, 4.28, 4.42, conc)
        if corners:
            for (u0, u1, pz0, pz1, ee, mt) in ((-0.04, 0.02, 0.0, 0.5, 0.04, concd), (L - 0.02, L + 0.04, 0.0, 0.5, 0.04, concd),
                                               (-0.06, 0.02, 4.28, 4.42, 0.06, conc), (L - 0.02, L + 0.06, 4.28, 4.42, 0.06, conc)):
                box_uw(u0, u1, -T / 2, T / 2 + ee - 0.001, pz0, pz1, mt)
            box_uw(-0.04, L + 0.04, -T / 2 - 0.04, T / 2 + 0.04, HW - 0.02, HW + 0.1, conc)
        else:
            box_uw(0.04, L - 0.04, -T / 2 - 0.04, T / 2 + 0.04, HW - 0.02, HW + 0.1, conc)

    # ---------------- front wall (+Y): shop window, door, small window, fascia sign with neon glyphs
    FY = D2 - T / 2
    mb = MB()
    shop = (0.9, 6.1, 0.75, 3.3)
    door = (7.0, 8.6, 0.0, 2.85)
    win = (9.3, 10.4, 1.3, 2.6)
    slab_with_openings(mb, (-W2, FY, 0), (1, 0, 0), (0, 1, 0), 2 * W2, HW, T, [shop, door, win], stucco, plaster, stucco)
    window_unit(mb, (-W2 + shop[0], FY, 0), (-W2 + shop[1], FY, 0), shop[2], shop[3], (0, 1, 0), 0.02,
                mullions=(1.75, 3.45))
    window_unit(mb, (-W2 + win[0], FY, 0), (-W2 + win[1], FY, 0), win[2], win[3], (0, 1, 0), 0.02)
    # door frame (the leaf is a separate part)
    for (u0, u1, z0, z1) in ((door[0] - 0.01, door[0] + 0.08, 0.0, door[3]), (door[1] - 0.08, door[1] + 0.01, 0.0, door[3]),
                             (door[0] - 0.01, door[1] + 0.01, door[3] - 0.1, door[3] + 0.01)):
        boxc(mb, (-W2 + u0, FY - 0.08, z0), (-W2 + u1, FY + 0.06, z1), frame)
    bands(mb, (-W2, FY, 0), (W2, FY, 0), (0, 1, 0), gaps=((door[0], door[1]),), corners=True)
    # fascia sign board + neon glyph strip
    fx0, fx1, fz0, fz1 = -W2 + 0.55, 1.05, 3.46, 4.16
    boxc(mb, (fx0, D2 - 0.02, fz0), (fx1, D2 + 0.14, fz1), panel)
    boxc(mb, (fx0 - 0.03, D2 - 0.02, fz0 - 0.04), (fx1 + 0.03, D2 + 0.17, fz0 + 0.01), frame)
    boxc(mb, (fx0 - 0.03, D2 - 0.02, fz1 - 0.01), (fx1 + 0.03, D2 + 0.17, fz1 + 0.04), frame)
    yb, yf = D2 + 0.13, D2 + 0.165

    def to3f(u, v, w):
        return Vector((u, w, v))
    zc = (fz0 + fz1) / 2
    gm = MB()                                   # abstract neon glyph strip (no letters), separate unbevelled object
    ring_solid(gm, circle2(-4.25, zc, 0.26, 24), circle2(-4.25, zc, 0.19, 24), yb, yf, to3f, mag)
    gm.prism(circle2(-4.25, zc, 0.08, 12), yb, yf, mat=amb, plane="XZ")
    gm.prism([(-3.72, zc - 0.22), (-3.22, zc - 0.22), (-3.47, zc + 0.22)], yb, yf, mat=cyan, plane="XZ")
    for k in range(5):
        x0 = -2.95 + k * 0.42
        hgt = (0.36, 0.2, 0.44, 0.28, 0.16)[k]
        boxc(gm, (x0, yb, zc - hgt / 2), (x0 + 0.1, yf, zc + hgt / 2), amb if k % 2 else cyan)
    ring_solid(gm, [(-0.8, zc - 0.24), (0.6, zc - 0.24), (0.6, zc + 0.24), (-0.8, zc + 0.24)],
               [(-0.75, zc - 0.19), (0.55, zc - 0.19), (0.55, zc + 0.19), (-0.75, zc + 0.19)], yb, yf, to3f, mag)
    for k in range(3):
        gm.prism(circle2(-0.52 + k * 0.42, zc, 0.07, 10), yb, yf, mat=cyan if k != 1 else amb, plane="XZ")
    # small neon ring + bar on the side window glass (sits on the glass, embedded 5 mm)
    gy0, gy1 = FY + 0.027, FY + 0.045
    wx = -W2 + (win[0] + win[1]) / 2
    ring_solid(gm, circle2(wx, 2.12, 0.2, 20), circle2(wx, 2.12, 0.16, 20), gy0, gy1, to3f, mag)
    boxc(gm, (wx - 0.16, gy0, 1.78), (wx + 0.16, gy1, 1.83), cyan)
    front_glyphs = gm.to_object("Shop_FrontGlyphs", uv=(1.0, 1.0))
    # gooseneck lamps over the fascia (wall plate embedded in the wall -> they stay with their wall chunk)
    for lxp in (-4.1, -1.95, 0.2):
        boxc(mb, (lxp - 0.07, D2 - 0.02, 4.53), (lxp + 0.07, D2 + 0.025, 4.71), frame)
        bar(mb, (lxp, D2 + 0.01, 4.62), (lxp, D2 + 0.42, 4.62), 0.035, 0.035, frame)
        bar(mb, (lxp, D2 + 0.40, 4.635), (lxp, D2 + 0.52, 4.45), 0.035, 0.035, frame, up=(0, 1, 0))
        # shade axis a = (0, sin32, cos32): narrow end up/out, wide mouth down towards the fascia
        mb.cyl((lxp, D2 + 0.52, 4.43), 0.07, 0.11, seg=12, mat=m("sign_trim"), r_top=0.035,
               rot=(-32, 0, 0))
        mb.cyl((lxp, D2 + 0.52 - 0.0249, 4.43 - 0.0399), 0.062, 0.02, seg=12, mat=m("lamp_glow"), rot=(-32, 0, 0))
    front = mb.to_object("Shop_Front", bevel=(0.012, 1), uv=UVS)
    facade_uv(front)

    # ---------------- back wall (-Y): back door + window + downpipe brackets
    BY = -D2 + T / 2
    mb = MB()
    bdoor = (8.4, 9.4, 0.0, 2.3)
    bwin = (2.7, 4.3, 1.5, 2.6)
    slab_with_openings(mb, (W2, BY, 0), (-1, 0, 0), (0, -1, 0), 2 * W2, HW, T, [bdoor, bwin], stucco, plaster, stucco)
    window_unit(mb, (W2 - bwin[0], BY, 0), (W2 - bwin[1], BY, 0), bwin[2], bwin[3], (0, -1, 0), -0.02,
                mullions=(0.8,))
    for (u0, u1, z0, z1) in ((bdoor[0] - 0.01, bdoor[0] + 0.07, 0.0, bdoor[3]), (bdoor[1] - 0.07, bdoor[1] + 0.01, 0.0, bdoor[3]),
                             (bdoor[0] - 0.01, bdoor[1] + 0.01, bdoor[3] - 0.08, bdoor[3] + 0.01)):
        boxc(mb, (W2 - u1, BY - 0.07, z0), (W2 - u0, BY + 0.07, z1), frame)
    bands(mb, (W2, BY, 0), (-W2, BY, 0), (0, -1, 0), gaps=((bdoor[0], bdoor[1]),), corners=True)
    # back wall details: lamp over the back door, meter cabinet, exhaust grille, roof scupper above the downpipe
    lx = W2 - (bdoor[0] + bdoor[1]) / 2
    boxc(mb, (lx - 0.16, -D2 - 0.12, 2.52), (lx + 0.16, -D2 + 0.02, 2.62), frame)
    mb.box((lx, -D2 - 0.085, 2.48), (0.26, 0.11, 0.1), mat=m("lamp_glow"), taper=(1.1, 1.2))
    fs = boxc(mb, (-1.2, -D2 - 0.2, 0.9), (-0.55, -D2 + 0.02, 1.85), m("steel"))
    inset_faces(mb, faces_facing(fs, (0, -1, 0)), 0.04, -0.01, rim_mat=m("steel"))
    tube(mb, (-0.875, -D2 - 0.1, 0.95), (-0.875, -D2 - 0.1, 0.52), 0.03, seg=8, mat=frame)
    boxc(mb, (1.9, -D2 - 0.06, 3.4), (2.9, -D2 + 0.02, 3.95), frame)
    for k in range(5):
        bar(mb, (1.95, -D2 - 0.055, 3.47 + k * 0.1), (2.85, -D2 - 0.055, 3.47 + k * 0.1), 0.06, 0.012, m("steel"),
            up=(0, -1, 1))
    boxc(mb, (4.55, -D2 - 0.26, 4.95), (4.85, -D2 + 0.05, 5.08), m("steel"))
    back = mb.to_object("Shop_Back", bevel=(0.012, 1), uv=UVS)
    facade_uv(back)

    # ---------------- side walls (between front and back walls)
    SX = W2 - T / 2
    DI = D2 - T
    mb = MB()
    lw = [(1.6, 3.2, 1.1, 2.7), (5.2, 6.8, 1.1, 2.7)]
    slab_with_openings(mb, (-SX, DI, 0), (0, -1, 0), (-1, 0, 0), 2 * DI, HW, T, lw, stucco, plaster, stucco)
    for (u0, u1, z0, z1) in lw:
        window_unit(mb, (-SX, DI - u0, 0), (-SX, DI - u1, 0), z0, z1, (-1, 0, 0), -0.02, mullions=((u1 - u0) / 2,))
    bands(mb, (-SX, DI, 0), (-SX, -DI, 0), (-1, 0, 0))
    left = mb.to_object("Shop_Left", bevel=(0.012, 1), uv=UVS)
    facade_uv(left)
    mb = MB()
    rw = [(3.3, 5.1, 1.1, 2.7)]
    slab_with_openings(mb, (SX, -DI, 0), (0, 1, 0), (1, 0, 0), 2 * DI, HW, T, rw, stucco, plaster, stucco)
    for (u0, u1, z0, z1) in rw:
        window_unit(mb, (SX, -DI + u0, 0), (SX, -DI + u1, 0), z0, z1, (1, 0, 0), 0.02, mullions=((u1 - u0) / 2,))
    boxc(mb, (W2 - 0.02, -2.9, 3.3), (W2 + 0.05, -2.1, 3.8), frame)       # louvre vent
    for k in range(4):
        bar(mb, (W2 + 0.04, -2.88, 3.36 + k * 0.12), (W2 + 0.04, -2.12, 3.36 + k * 0.12), 0.05, 0.03, conc,
            up=(1, 0, 1))
    bands(mb, (SX, -DI, 0), (SX, DI, 0), (1, 0, 0))
    right = mb.to_object("Shop_Right", bevel=(0.012, 1), uv=UVS)
    facade_uv(right)

    # ---------------- roof slab + hatch + scupper
    mb = MB()
    fs = boxc(mb, (-SX + T / 2, -DI, RZ0), (SX - T / 2, DI, RZ1), plaster)
    for f in faces_facing(fs, (0, 0, 1)):
        f.material_index = mb.slot(roofing)
    boxc(mb, (-2.7, 1.3, RZ1 - 0.02), (-1.7, 2.3, RZ1 + 0.28), conc)
    boxc(mb, (-2.76, 1.24, RZ1 + 0.27), (-1.64, 2.36, RZ1 + 0.35), frame)
    roof = mb.to_object("Shop_Roof", bevel=(0.01, 1), uv=UVS)

    # ---------------- awning (striped canvas + valance + arms), separate part
    mb = MB()
    ax0, ax1 = -W2 + 0.55, 3.45
    yb0, zb0, yf0, zf0 = D2 + 0.004, 3.36, D2 + 1.45, 2.78
    striped_slab(mb, (ax0, yb0, zb0), (ax1, yb0, zb0), (ax0, yf0, zf0), (ax1, yf0, zf0), 0.045, 16, (red, cream))
    striped_slab(mb, (ax0, yf0 - 0.01, zf0 + 0.02), (ax1, yf0 - 0.01, zf0 + 0.02), (ax0, yf0 + 0.03, zf0 + 0.02),
                 (ax1, yf0 + 0.03, zf0 + 0.02), 0.3, 16, (red, cream))
    for xa in (ax0 + 0.25, (ax0 + ax1) / 2, ax1 - 0.25):
        tube(mb, (xa, D2 + 0.02, 2.55), (xa, yf0 - 0.1, zf0 - 0.012), 0.022, seg=8, mat=frame)
        boxc(mb, (xa - 0.06, D2 + 0.002, 2.47), (xa + 0.06, D2 + 0.03, 2.63), frame)
    tube(mb, (ax0 + 0.05, yf0 - 0.1, zf0 - 0.012), (ax1 - 0.05, yf0 - 0.1, zf0 - 0.012), 0.025, seg=8, mat=frame)
    awning = mb.to_object("Shop_Awning", uv=(1.0, 1.0))

    # ---------------- AC unit, vent stack, downpipe, door leaves
    mb = MB()
    acx, acy = 2.4, -1.6
    boxc(mb, (acx - 0.78, acy - 0.5, RZ1 + 0.002), (acx - 0.66, acy + 0.5, RZ1 + 0.1), frame)
    boxc(mb, (acx + 0.66, acy - 0.5, RZ1 + 0.002), (acx + 0.78, acy + 0.5, RZ1 + 0.1), frame)
    fs = boxc(mb, (acx - 0.8, acy - 0.48, RZ1 + 0.09), (acx + 0.8, acy + 0.48, RZ1 + 1.0), acm)
    inset_faces(mb, faces_facing(fs, (0, 0, 1)), 0.1, -0.03, rim_mat=acm)
    mb.cyl((acx - 0.35, acy, RZ1 + 0.972), 0.3, 0.02, seg=20, mat=frame)
    mb.cyl((acx + 0.35, acy, RZ1 + 0.972), 0.3, 0.02, seg=20, mat=frame)
    for k in range(5):
        bar(mb, (acx - 0.72, acy - 0.26 + k * 0.13, RZ1 + 0.99), (acx + 0.72, acy - 0.26 + k * 0.13, RZ1 + 0.99),
            0.02, 0.02, acm)
    for k in range(6):
        bar(mb, (acx - 0.7, acy + 0.485, RZ1 + 0.25 + k * 0.11), (acx + 0.7, acy + 0.485, RZ1 + 0.25 + k * 0.11),
            0.07, 0.015, frame, up=(0, 1, 1))
    tube(mb, (acx + 0.8 - 0.01, acy - 0.3, RZ1 + 0.3), (acx + 1.09, acy - 0.3, RZ1 + 0.3), 0.03, seg=8, mat=m("steel"))
    tube(mb, (acx + 1.05, acy - 0.3, RZ1 + 0.31), (acx + 1.05, acy - 0.3, RZ1 + 0.004), 0.03, seg=8, mat=m("steel"))
    ac = mb.to_object("Shop_AC", bevel=(0.008, 1), uv=(1.5, 1.5))
    mb = MB()
    mb.cyl((-3.2, -2.4, RZ1 + 0.4), 0.11, 0.8 - 0.004, seg=12, mat=m("steel"))
    mb.cyl((-3.2, -2.4, RZ1 + 0.86), 0.2, 0.14, seg=12, mat=frame, r_top=0.06)
    vent = mb.to_object("Shop_Vent", uv=(1.0, 1.0))
    mb = MB()
    dpx, dpy = 4.7, -D2 - 0.14
    mb.cyl((dpx, dpy, 2.4), 0.065, 4.6, seg=10, mat=m("steel"))
    mb.cyl((dpx, dpy - 0.08, 0.2), 0.065, 0.3, seg=10, mat=m("steel"), axis="Y")
    mb.box((dpx, dpy, 4.8), (0.28, 0.22, 0.26), mat=m("steel"), bottom_scale=(0.55, 0.6))
    for zc in (1.2, 2.5, 3.8):
        boxc(mb, (dpx - 0.03, -D2 - 0.002, zc - 0.03), (dpx + 0.03, dpy, zc + 0.03), frame)
    downpipe = mb.to_object("Shop_Downpipe", uv=(1.0, 1.0))
    mb = MB()
    dx0, dx1 = -W2 + door[0] + 0.085, -W2 + door[1] - 0.085
    for (lo, hi) in (((dx0, FY - 0.03, 0.02), (dx0 + 0.1, FY + 0.03, 2.745)), ((dx1 - 0.1, FY - 0.03, 0.02), (dx1, FY + 0.03, 2.745)),
                     ((dx0 + 0.09, FY - 0.03, 0.02), (dx1 - 0.09, FY + 0.03, 0.3)),
                     ((dx0 + 0.09, FY - 0.03, 2.62), (dx1 - 0.09, FY + 0.03, 2.745))):
        boxc(mb, lo, hi, frame)
    boxc(mb, (dx0 + 0.09, FY - 0.01, 0.29), (dx1 - 0.09, FY + 0.01, 2.63), glass)
    bar(mb, (dx0 + 0.15, FY + 0.07, 1.05), (dx1 - 0.15, FY + 0.07, 1.05), 0.035, 0.035, m("sign_trim"))
    for xx in (dx0 + 0.18, dx1 - 0.18):
        boxc(mb, (xx - 0.02, FY + 0.004, 1.03), (xx + 0.02, FY + 0.08, 1.07), m("sign_trim"))
    door_f = mb.to_object("Shop_DoorFront", bevel=(0.005, 1), uv=(1.0, 1.0))
    mb = MB()
    bx0, bx1 = W2 - bdoor[1] + 0.075, W2 - bdoor[0] - 0.075
    fs = boxc(mb, (bx0, BY - 0.025, 0.02), (bx1, BY + 0.025, 2.215), doorm)
    inset_faces(mb, faces_facing(fs, (0, -1, 0)), 0.1, -0.012, rim_mat=doorm)
    boxc(mb, (bx1 - 0.16, BY - 0.07, 1.0), (bx1 - 0.1, BY - 0.006, 1.1), m("sign_trim"))
    door_b = mb.to_object("Shop_DoorBack", bevel=(0.004, 1), uv=(1.0, 1.0))

    def wall_part(name, obj, n, N, off, dens=None):
        Nv = Vector(N)
        return Part(name, obj, "surface", n=n, min_volume=0.05, min_thickness=0.12, big_frac=0.3, big_weight=0.5,
                    relax=1, relax_alpha=0.4,
                    face_filter=lambda f, mt: f.normal.dot(Nv) > 0.95 and mt.mats[f.material_index].name == "shop_stucco"
                    and abs((f.calc_center_median() - Nv * off).dot(Nv)) < 0.02,
                    inset=T / 2, depth_jitter=0.03, depth_axis=N, density=dens)
    parts += [wall_part("wall_front", [front, front_glyphs], 10, (0, 1, 0), D2,
                        [FR.density_impact((-1.8, D2, 2.2), 1.8, 3.0)]),
              wall_part("wall_back", back, 7, (0, -1, 0), D2),
              wall_part("wall_left", left, 6, (-1, 0, 0), W2),
              wall_part("wall_right", right, 6, (1, 0, 0), W2),
              Part("roof", roof, "surface", n=8, min_volume=0.05, min_thickness=0.12, big_frac=0.3, big_weight=0.5,
                   relax=1, face_filter=lambda f, mt: f.normal.z > 0.95 and mt.mats[f.material_index].name == "shop_roofing",
                   inset=(RZ1 - RZ0) / 2, depth_jitter=0.02, depth_axis=(0, 0, 1)),
              Part("awning", awning, "axis", n=3, min_volume=0.003, min_thickness=0.01,
                   p0=(ax0, D2 + 0.7, 3.0), p1=(ax1, D2 + 0.7, 3.0), lateral=0.35),
              Part("ac_unit", ac, "axis", n=2, min_volume=0.01, min_thickness=0.03,
                   p0=(acx - 0.8, acy, RZ1 + 0.5), p1=(acx + 0.8, acy, RZ1 + 0.5), lateral=0.5),
              Part("vent", vent, "single"),
              Part("downpipe", downpipe, "axis", n=2, min_volume=0.001, min_thickness=0.01,
                   p0=(dpx, dpy, 0.0), p1=(dpx, dpy, 5.4), lateral=0.5),
              Part("door_front", door_f, "single"),
              Part("door_back", door_b, "single")]
    cols = [((0, 0, (HW + 0.1) / 2), (W2 + 0.04, D2 + 0.04, (HW + 0.1) / 2)),
            (((ax0 + ax1) / 2, D2 + 0.75, 2.95), ((ax1 - ax0) / 2, 0.75, 0.42)),
            ((acx, acy, RZ1 + 0.5), (0.8, 0.5, 0.5))]
    return dict(name="SmallBuilding", parts=parts, cols=cols, impact=(-1.8, D2, 2.2),
                closeups=[((-1.0, 4.6, 2.4), 2.6, ("cq",)), ((-2.0, -4.6, 2.2), 2.4, ("cb",))])


BUILDERS = {"column": build_column, "citysign": build_citysign, "watertower": build_watertower,
            "smallbuilding": build_smallbuilding}


# ======================================================================================================================
# GLB-level verification (reads the exported file: every chunk closed + positive volume, bbox match)
# ======================================================================================================================
def _read_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    jlen = struct.unpack_from("<I", data, 12)[0]
    js = json.loads(data[20:20 + jlen].decode("utf-8"))
    off = 20 + jlen
    blen = struct.unpack_from("<I", data, off)[0]
    return js, data[off + 8: off + 8 + blen]


def _accessor(js, binary, idx):
    acc = js["accessors"][idx]
    bv = js["bufferViews"][acc["bufferView"]]
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    dt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}[acc["componentType"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride", 0)
    itemsize = np.dtype(dt).itemsize * ncomp
    if stride and stride != itemsize:
        raw = np.frombuffer(binary, dtype=np.uint8, count=stride * acc["count"], offset=start)
        arr = np.stack([np.frombuffer(raw[i * stride: i * stride + itemsize].tobytes(), dtype=dt)
                        for i in range(acc["count"])])
    else:
        arr = np.frombuffer(binary, dtype=dt, count=acc["count"] * ncomp, offset=start).reshape(acc["count"], ncomp)
    return arr


def verify_glb(path_intact, path_frac, root_int, root_frac):
    js, binary = _read_glb(path_frac)
    nodes = js["nodes"]
    ri = [i for i, n in enumerate(nodes) if n.get("name") == root_frac][0]
    kids = nodes[ri].get("children", [])
    rows = []
    lo_all = np.full(3, 1e9)
    hi_all = np.full(3, -1e9)
    rt = np.array(nodes[ri].get("translation", [0, 0, 0]))
    for c in kids:
        nd = nodes[c]
        t = np.array(nd.get("translation", [0, 0, 0])) + rt
        tris_all, pos_all = [], []
        base = 0
        for prim in js["meshes"][nd["mesh"]]["primitives"]:
            pos = _accessor(js, binary, prim["attributes"]["POSITION"]).astype(np.float64)
            ind = _accessor(js, binary, prim["indices"]).astype(np.int64).reshape(-1, 3)
            pos_all.append(pos)
            tris_all.append(ind + base)
            base += len(pos)
        P = np.concatenate(pos_all)
        Tr = np.concatenate(tris_all)
        key = np.round(P / 2e-5).astype(np.int64)
        _, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        Ti = inv[Tr]
        e = np.concatenate([Ti[:, [0, 1]], Ti[:, [1, 2]], Ti[:, [2, 0]]])
        e.sort(axis=1)
        _, cnt = np.unique(e, axis=0, return_counts=True)
        boundary = int((cnt == 1).sum())
        odd = int((cnt % 2 == 1).sum())
        a, b, cc = P[Tr[:, 0]], P[Tr[:, 1]], P[Tr[:, 2]]
        vol = float(np.einsum("ij,ij->i", a, np.cross(b, cc)).sum() / 6.0)
        lo_all = np.minimum(lo_all, P.min(axis=0) + t)
        hi_all = np.maximum(hi_all, P.max(axis=0) + t)
        rows.append((nd["name"], len(Tr), vol, boundary, odd))
    ji, bi = _read_glb(path_intact)
    ni = ji["nodes"]
    lo_i = np.full(3, 1e9)
    hi_i = np.full(3, -1e9)
    rii = [i for i, n in enumerate(ni) if n.get("name") == root_int][0]
    for c in ni[rii].get("children", []):
        nd = ni[c]
        if "mesh" not in nd:
            continue
        t = np.array(nd.get("translation", [0, 0, 0])) + np.array(ni[rii].get("translation", [0, 0, 0]))
        for prim in ji["meshes"][nd["mesh"]]["primitives"]:
            acc = ji["accessors"][prim["attributes"]["POSITION"]]
            lo_i = np.minimum(lo_i, np.array(acc["min"]) + t)
            hi_i = np.maximum(hi_i, np.array(acc["max"]) + t)
    return rows, (lo_all, hi_all), (lo_i, hi_i)


# ======================================================================================================================
# Pipeline
# ======================================================================================================================
def bm_to_object(bm, name, mats, parent=None, weighted=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    for mt in mats:
        me.materials.append(mt)
    me.update()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    if weighted:
        wn = obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.keep_sharp = True
        wn.weight = 50
        wn.mode = "FACE_AREA"
    return obj


def set_hidden(root, hidden):
    for o in [root] + descendants(root):
        o.hide_render = hidden
        o.hide_viewport = False


def process(key):
    t0 = time.time()
    reset_scene()
    spec = BUILDERS[key]()
    name = spec["name"]
    parts = spec["parts"]
    all_objs = [o for p in parts for o in p.objs]
    log(f"{name} part triangles: " + ", ".join(f"{p.name}={tri_count(p.objs)}" for p in parts))

    # ---------------- intact: one merged visual mesh + collider empties
    root_i = add_empty(f"{name}_Intact", (0, 0, 0), display="PLAIN_AXES", size=0.5)
    mt_i = FR.MaterialTable()
    body_bm = FR.part_from_objects(all_objs, mt_i, triangulate_ngons=False)
    body = bm_to_object(body_bm, f"{name}_Body", mt_i.mats, parent=root_i)
    body_bm.free()
    for k, (c, h) in enumerate(spec["cols"], 1):
        e = add_empty(f"COL_{k}", c, parent=root_i, display="CUBE", size=1.0)
        e.scale = h

    # ---------------- fracture sources (convex-ish parts) + seeds
    mt = FR.MaterialTable()
    for mat in mt_i.mats:
        mt.index(mat)
    cap = mt.index(mat_debris(spec.get("debris", "stone")))
    fparts = []
    for p in parts:
        bm = FR.part_from_objects(p.objs, mt)
        b, n = FR.topology_errors(bm)
        assert not (b or n), f"part {p.name} is not closed (boundary={b}, nonmanifold={n})"
        seeds, weights = p.seeds(bm, mt)
        fparts.append(dict(name=p.name, bm=bm, seeds=seeds, weights=weights, min_volume=p.min_volume,
                           min_thickness=p.min_thickness))
    for o in all_objs:
        bpy.data.objects.remove(o)

    path_i = export_glb(f"destructible_{key}_intact.glb", [root_i])
    info_i = report(path_i)

    # ---------------- fracture
    chunks = FR.fracture_parts(fparts, cap)
    for fp in fparts:
        fp["bm"].free()
    root_f = add_empty(f"{name}_Fractured", (0, 0, 0), display="PLAIN_AXES", size=0.5)
    chunk_objs = FR.make_chunk_objects(chunks, root_f, mt, cap, cap_uv_scale=1.6, edge_bevel=spec.get("edge_bevel"))
    rows, ok = FR.verify_chunk_objects(chunk_objs)
    path_f = export_glb(f"destructible_{key}_fractured.glb", [root_f])
    info_f = report(path_f)

    # ---------------- verification (Blender meshes + the exported GLB)
    lim = CHUNK_LIMITS[key]
    by_part = {}
    for ch in chunks:
        by_part[ch.part] = by_part.get(ch.part, 0) + 1
    log(f"{name}: {len(chunk_objs)} chunks (contract {lim[0]}-{lim[1]}): " +
        ", ".join(f"{k}={v}" for k, v in by_part.items()))
    conv = [r["convexity"] for r in rows]
    log(f"  chunk tris min/max {min(r['tris'] for r in rows)}/{max(r['tris'] for r in rows)}, "
        f"volume min/max {min(r['volume'] for r in rows):.4f}/{max(r['volume'] for r in rows):.3f} m^3, "
        f"convexity min/mean {min(conv):.2f}/{sum(conv) / len(conv):.2f}, "
        f"size ratio max/min {max(r['size'] for r in rows) / max(1e-6, min(r['size'] for r in rows)):.1f}")
    worst = sorted(zip(rows, chunks), key=lambda rc: rc[0]["convexity"])[:3]
    log("  least convex: " + ", ".join(f"{r['name']}({c.part})={r['convexity']:.2f}" for r, c in worst))
    bad = [r for r in rows if not r["ok"]]
    for r in bad:
        log(f"  !! {r['name']}: boundary={r['boundary']} nonmanifold={r['nonmanifold']} vol={r['volume']:.5f} "
            f"tris={r['tris']} centroid_err={r['centroid_err']:.4f}")
    grows, (flo, fhi), (ilo, ihi) = verify_glb(path_i, path_f, f"{name}_Intact", f"{name}_Fractured")
    open_g = [r for r in grows if r[3] or r[4] or r[2] <= 0]
    fsize, isize = fhi - flo, ihi - ilo
    ratio = fsize / np.maximum(isize, 1e-6)
    log(f"  GLB check: {len(grows)} chunks, closed {len(grows) - len(open_g)}/{len(grows)}, "
        f"volume>0 {sum(1 for r in grows if r[2] > 0)}/{len(grows)}, tris {sum(r[1] for r in grows)}")
    log(f"  bbox intact  (glTF xyz) size {np.round(isize, 3).tolist()}  min {np.round(ilo, 3).tolist()}")
    log(f"  bbox chunks  (glTF xyz) size {np.round(fsize, 3).tolist()}  min {np.round(flo, 3).tolist()}  "
        f"ratio {np.round(ratio, 4).tolist()}")
    for r in open_g:
        log(f"  !! GLB {r[0]}: boundary edges {r[3]}, odd edges {r[4]}, volume {r[2]:.5f}")
    assert lim[0] <= len(chunk_objs) <= lim[1], f"chunk count {len(chunk_objs)} outside {lim}"
    assert not open_g, "open / inverted chunks in GLB"
    assert np.all(np.abs(ratio - 1.0) < 0.02), "fractured bbox does not match the intact bbox"
    log(f"  {name}: intact tris {info_i['tris']}, fractured tris {info_f['tris']}, built in {time.time() - t0:.1f}s")

    if PREVIEW:
        render_previews(key, name, root_i, root_f, chunk_objs, spec)
    return dict(name=name, chunks=len(chunk_objs), intact_tris=info_i["tris"], frac_tris=info_f["tris"],
                by_part=by_part, convexity=(min(conv), sum(conv) / len(conv)))


def focus_proxy(center, half):
    """Invisible mesh used only to aim/frame render_views at a detail region."""
    mb = MB()
    mb.box(center, (2 * half, 2 * half, 2 * half))
    o = mb.to_object("_focus_proxy", smooth=False)
    o.hide_render = True
    return o


def render_previews(key, name, root_i, root_f, chunk_objs, spec):
    views_i = ("front", "three_quarter", "back", "left", "top")
    set_hidden(root_f, True)
    set_hidden(root_i, False)
    render_views(f"destr_{key}_intact", [root_i], views=views_i, size=(900, 900), samples=24, ground=True)
    for k, (c, half, views) in enumerate(spec.get("closeups", [])):
        px = focus_proxy(c, half)
        render_views(f"destr_{key}_intact_close{k + 1}", [px], views=views, size=(900, 900), samples=24, ground=True,
                     custom_views={"cq": (215, 18, 1.0), "cl": (200, -5, 1.0), "cb": (330, 20, 1.0)})
        bpy.data.objects.remove(px)
    # collider overlay: translucent boxes for every COL_n empty over the intact mesh
    cmat = make_material("_col_preview", "#FF3B30", 0.0, 0.5, alpha=0.35, double_sided=True)
    tmp = []
    for e in [o for o in descendants(root_i) if o.name.startswith("COL_")]:
        mb = MB()
        mb.box(e.matrix_world.translation, tuple(2.0 * s for s in e.scale), mat=cmat)
        tmp.append(mb.to_object("_col_box_" + e.name, smooth=False))
    render_views(f"destr_{key}_colliders", [root_i], views=("three_quarter",), size=(700, 700), samples=16, ground=True)
    for o in tmp:
        bpy.data.objects.remove(o)
    set_hidden(root_i, True)
    set_hidden(root_f, False)
    render_views(f"destr_{key}_fractured", [root_f], views=("three_quarter", "back"), size=(900, 900), samples=24,
                 ground=True)
    mn, mx = world_bbox(chunk_objs)
    cen = (mn + mx) * 0.5
    saved = [o.location.copy() for o in chunk_objs]
    for o in chunk_objs:
        d = o.location - cen
        o.location = Vector((o.location.x + d.x * 0.6, o.location.y + d.y * 0.6, o.location.z * 1.18 + 0.15))
    render_views(f"destr_{key}_exploded", [root_f], views=("three_quarter", "front"), size=(900, 900), samples=24,
                 ground=True)
    for k, (c, half, views) in enumerate(spec.get("closeups", [])[:1]):
        px = focus_proxy(Vector(c) + Vector((0, 0, 0.2)), half * 1.25)
        render_views(f"destr_{key}_exploded_close", [px], views=("cq",), size=(900, 900), samples=24, ground=True,
                     custom_views={"cq": (215, 18, 1.0)})
        bpy.data.objects.remove(px)
    for o, loc in zip(chunk_objs, saved):
        o.location = loc


def main():
    t0 = time.time()
    summary = []
    for key in ("column", "citysign", "watertower", "smallbuilding"):
        if ONLY and key not in ONLY:
            continue
        summary.append(process(key))
    log("=" * 100)
    for s in summary:
        log(f"{s['name']:14s} chunks={s['chunks']:3d}  intact_tris={s['intact_tris']:6d}  fractured_tris={s['frac_tris']:6d}"
            f"  convexity min/mean={s['convexity'][0]:.2f}/{s['convexity'][1]:.2f}  parts: " +
            ", ".join(f"{k}={v}" for k, v in s["by_part"].items()))
    log(f"build_destructibles finished in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

"""Armored Flight - building kit for build_city_buildings.py (bpy).

* KB            : mesh builder (common.MB subclass) with explicitly wound, optionally open primitives (box with skipped
                  faces, prisms from CCW outlines, mitred ring walls / slabs, annuli, cylinders).
* MatLib        : the 8 shared materials of city_buildings.glb (5 textured facades, textured concrete, the trim palette
                  atlas, beacon_red) + placeholder materials that tell the UV pass how to map a face:
                    facade  -> metric box projection along the face tangent (24 m x 28.8 m per tile, whole-bay/floor
                               offsets per facing direction), cylindrical projection for round towers
                    concrete-> metric box projection, 16 m tile
                    trim    -> constant UV at the centre of a palette swatch (metals, paints, lights ...)
* Bld           : one building module (mass mesh is bevelled, detail mesh is not; both are joined into one mesh),
                  COL_* collider Empties, Roof_Slot_* Empties and the <name>_LOD1 sibling.
* rooftop props : AC units, cooling towers, penthouses, water tanks, masts with beacons, helipads, solar arrays ...
"""
import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Vector

import city_facades as cf
from common import MB, TEXTURE_DIR, add_empty, apply_modifiers, ensure_dir, log, make_material, make_textured_material, pal

FACADE_TILE = (cf.TILE_W, cf.TILE_H)
CONC_TILE = (cf.CONCRETE_TILE, cf.CONCRETE_TILE)
FL = cf.FLOOR      # 3.6 m floor-to-floor
BAY = cf.BAY       # 3.0 m bay


# ----------------------------------------------------------------------------------------------------
# images + materials
# ----------------------------------------------------------------------------------------------------
def bld_image(name, arr_vup, srgb=True, fmt="PNG", quality=90):
    """v-up float array (H,W,3) -> image file in tools/.cache/textures -> packed bpy image (exported as-is)."""
    arr = np.clip(np.asarray(arr_vup, np.float32), 0.0, 1.0)
    h, w = arr.shape[:2]
    rgba = np.concatenate([arr, np.ones((h, w, 1), np.float32)], axis=2)
    ensure_dir(TEXTURE_DIR)
    ext = ".jpg" if fmt == "JPEG" else ".png"
    path = os.path.join(TEXTURE_DIR, name + ext)
    img = bpy.data.images.new(name + "_gen", w, h, alpha=False, float_buffer=False, is_data=not srgb)
    img.pixels.foreach_set(rgba.ravel())          # Blender pixel rows start at the bottom = v-up
    img.filepath_raw = path
    img.file_format = fmt
    if fmt == "JPEG":
        img.save(quality=quality)
    else:
        img.save()
    bpy.data.images.remove(img)
    img = bpy.data.images.load(path)
    img.name = name
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    img.pack()
    return img


FACADES = {
    # name: (generator, emissive strength)
    "bld_glass_blue": (lambda s: cf.facade_glass(s, "blue"), 2.2),
    "bld_glass_gold": (lambda s: cf.facade_glass(s, "gold"), 2.2),
    "bld_office": (lambda s: cf.facade_office(s), 2.0),
    "bld_brick": (lambda s: cf.facade_brick(s), 2.0),
    "bld_panel": (lambda s: cf.facade_panel(s), 2.0),
}


class MatLib:
    """Real materials + UV-mode placeholders.  info[material name] = (kind, real material, param)."""

    def __init__(self, seed=7100):
        self.seed = seed
        self.real = {}
        self.info = {}
        self._ph = {}

    def build(self):
        for i, (name, (gen, es)) in enumerate(sorted(FACADES.items())):
            d = gen(self.seed + 17 * (i + 1))
            log(f"texture {name}: lit windows {d['lit_fraction'] * 100:.0f}%")
            alb = bld_image(name + "_albedo", d["albedo"], True, "JPEG", 90)
            orm = bld_image(name + "_orm", d["orm"], False, "PNG")
            emi = bld_image(name + "_emissive", d["emissive"], True, "PNG")
            nrm = bld_image(name + "_normal", d["normal"], False, "PNG")
            self.real[name] = make_textured_material(name, albedo=alb, orm=orm, emissive=emi, emissive_strength=es,
                                                     normal=nrm, normal_strength=1.0)
            self.info[name] = ("facade", name, None)
        d = cf.concrete(self.seed + 999)
        alb = bld_image("bld_concrete_albedo", d["albedo"], True, "JPEG", 88)
        self.real["bld_concrete"] = make_textured_material("bld_concrete", albedo=alb, roughness=0.9, metallic=0.0)
        self.info["bld_concrete"] = ("concrete", "bld_concrete", None)
        d = cf.trim_palette()
        alb = bld_image("bld_trim_albedo", d["albedo"], True, "PNG")
        orm = bld_image("bld_trim_orm", d["orm"], False, "PNG")
        emi = bld_image("bld_trim_emissive", d["emissive"], True, "PNG")
        self.real["bld_trim"] = make_textured_material("bld_trim", albedo=alb, orm=orm, emissive=emi, emissive_strength=5.0)
        self.info["bld_trim"] = ("swatch", "bld_trim", "concrete")
        self.real["beacon_red"] = pal("beacon_red")
        self.info["beacon_red"] = ("plain", "beacon_red", None)
        return self

    def m(self, name):
        return self.real[name]

    def _placeholder(self, key, kind, real, param, color):
        if key in self._ph:
            return self._ph[key]
        mat = make_material("PH__" + key, color=color)
        self._ph[key] = mat
        self.info[mat.name] = (kind, real, param)
        return mat

    def sw(self, swatch):
        """Trim palette swatch placeholder (constant UV)."""
        assert swatch in cf.TRIM_INDEX, swatch
        c = cf.TRIM_SWATCHES[cf.TRIM_INDEX[swatch]][1]
        return self._placeholder("trim_" + swatch, "swatch", "bld_trim", swatch, (c[0], c[1], c[2], 1.0))

    def cyl(self, facade):
        """Facade with cylindrical UVs (36 facets per turn = one 3 m bay per facet)."""
        return self._placeholder("cyl_" + facade, "cyl", facade, 36, (0.6, 0.5, 0.3, 1.0))

    def cleanup(self):
        for me in list(bpy.data.meshes):
            if me.users == 0:
                bpy.data.meshes.remove(me)
        for key, mat in list(self._ph.items()):
            if mat.users == 0:
                bpy.data.materials.remove(mat)
        left = [m.name for m in bpy.data.materials if m.name.startswith("PH__") and m.users]
        assert not left, f"placeholder materials still in use: {left}"


# ----------------------------------------------------------------------------------------------------
# UV + material pass
# ----------------------------------------------------------------------------------------------------
def assign_uvs(obj, lib, shift=(0.0, 0.0), offsets=None, cyl_center=(0.0, 0.0), cyl_facets=36, band_offsets=None):
    """Per-face UVs from the (placeholder) material of each face, then replace placeholders by real materials.
    offsets: (4, 2) array of (du, dv) tile offsets per facing direction (+X, +Y, -X, -Y) for facade materials.
    band_offsets: (nbands, 4) extra U offsets per 28.8 m height band (whole bays) so the lit-window pattern of the
    8-floor tile does not visibly repeat up tall towers (walls are split at the band heights, see split_bands)."""
    me = obj.data
    npoly = len(me.polygons)
    if npoly == 0:
        return
    mi = np.zeros(npoly, np.int32)
    me.polygons.foreach_get("material_index", mi)
    nrm = np.zeros(npoly * 3, np.float32)
    me.polygons.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3).astype(np.float64)
    pc = np.zeros(npoly * 3, np.float32)
    me.polygons.foreach_get("center", pc)
    pc = pc.reshape(-1, 3).astype(np.float64)
    lt = np.zeros(npoly, np.int32)
    ls = np.zeros(npoly, np.int32)
    me.polygons.foreach_get("loop_total", lt)
    me.polygons.foreach_get("loop_start", ls)
    nl = len(me.loops)
    lv = np.zeros(nl, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    co = np.zeros(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    order = np.argsort(ls, kind="stable")
    pol = np.repeat(order, lt[order])                # loop -> polygon
    P = co[lv]
    N = nrm[pol]

    slots = [s.material for s in obj.material_slots]
    kinds, reals, params = [], [], []
    for m in slots:
        k, r, p = lib.info[m.name]
        kinds.append(k)
        reals.append(r)
        params.append(p)
    kind_l = np.array([kinds[i] for i in mi], dtype=object)[pol]

    uv = np.zeros((nl, 2), np.float64)
    ax, ay, az = np.abs(N[:, 0]), np.abs(N[:, 1]), np.abs(N[:, 2])
    horiz = (az >= ax) & (az >= ay)
    nxy = np.sqrt(N[:, 0] ** 2 + N[:, 1] ** 2) + 1e-12
    tx, ty = -N[:, 1] / nxy, N[:, 0] / nxy
    # snap near-axis tangents exactly
    snap = np.abs(tx) > 0.9995
    tx = np.where(snap, np.sign(tx), tx)
    ty = np.where(snap, 0.0, ty)
    snap = np.abs(ty) > 0.9995
    ty = np.where(snap, np.sign(ty), ty)
    tx = np.where(snap, 0.0, tx)
    ang = np.arctan2(N[:, 1], N[:, 0])
    dirn = np.mod(np.round(ang / (math.pi / 2)).astype(np.int64), 4)
    offs = np.zeros((4, 2)) if offsets is None else np.asarray(offsets, np.float64)
    band = np.clip(np.floor(pc[pol, 2] / FACADE_TILE[1] + 1e-4).astype(np.int64), 0, None)
    if band_offsets is not None:
        bo = np.asarray(band_offsets, np.float64)
        boff = bo[np.minimum(band, len(bo) - 1), dirn]
    else:
        boff = np.zeros(nl)
    X, Y, Z = P[:, 0] - shift[0], P[:, 1] - shift[1], P[:, 2]

    def box(su, sv, with_offsets):
        u = np.where(horiz, X / su, (X * tx + Y * ty) / su)
        v = np.where(horiz, Y / sv, Z / sv)
        if with_offsets:
            u = u + np.where(horiz, 0.0, offs[dirn, 0] + boff)
            v = v + np.where(horiz, 0.0, offs[dirn, 1])
        return u, v

    fu, fv = box(FACADE_TILE[0], FACADE_TILE[1], True)
    cu, cv = box(CONC_TILE[0], CONC_TILE[1], False)
    # cylindrical
    cx, cy = cyl_center
    th_c = np.arctan2(pc[pol, 1] - cy, pc[pol, 0] - cx)
    th = np.arctan2(P[:, 1] - cy, P[:, 0] - cx)
    th = th_c + np.mod(th - th_c + math.pi, 2 * math.pi) - math.pi
    yu = th / (2 * math.pi) * cyl_facets * BAY / FACADE_TILE[0] + boff
    yv = P[:, 2] / FACADE_TILE[1]
    yu = np.where(horiz, P[:, 0] / FACADE_TILE[0], yu)
    yv = np.where(horiz, P[:, 1] / FACADE_TILE[1], yv)

    for k, (u, v) in (("facade", (fu, fv)), ("concrete", (cu, cv)), ("cyl", (yu, yv))):
        sel = kind_l == k
        uv[sel, 0] = u[sel]
        uv[sel, 1] = v[sel]
    # swatches
    for si, m in enumerate(slots):
        if kinds[si] in ("swatch", "plain"):
            sel = mi[pol] == si
            if kinds[si] == "swatch":
                su, sv = cf.trim_uv(params[si])
            else:
                su, sv = 0.5, 0.5
            uv[sel, 0] = su
            uv[sel, 1] = sv
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    me.uv_layers[0].data.foreach_set("uv", uv.astype(np.float32).ravel())

    # replace placeholders by real materials (stable order of first slot use)
    new_names = []
    for r in reals:
        if r not in new_names:
            new_names.append(r)
    remap = np.array([new_names.index(r) for r in reals], np.int32)
    me.materials.clear()
    for n in new_names:
        me.materials.append(lib.real[n])
    me.polygons.foreach_set("material_index", remap[mi])
    me.update()


# ----------------------------------------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------------------------------------
def split_bands(obj, step=FACADE_TILE[1], zmax=180.0):
    """Bisect every face crossing z = k * step (texture tile height) so each wall piece lies in one height band."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    k = 1
    while k * step < zmax:
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0.0, 0.0, k * step), plane_no=(0.0, 0.0, 1.0), dist=1e-4)
        k += 1
    bm.to_mesh(me)
    bm.free()
    me.update()


def offset_outline(pts, d):
    """Offset a CCW polygon (list of (x, y)): d > 0 moves every edge INWARD by d (mitred corners)."""
    n = len(pts)
    out = []
    for i in range(n):
        p0, p1, p2 = Vector(pts[i - 1]), Vector(pts[i]), Vector(pts[(i + 1) % n])
        e1 = (p1 - p0).normalized()
        e2 = (p2 - p1).normalized()
        n1 = Vector((-e1.y, e1.x))
        n2 = Vector((-e2.y, e2.x))
        k = 1.0 + n1.dot(n2)
        q = p1 + (n1 + n2) * (d / k)
        out.append((q.x, q.y))
    return out


def rect(x0, x1, y0, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def octagon(hx, hy, c):
    """CCW octagon from a hx x hy half-extent rectangle with corner chamfer c."""
    return [(-hx + c, -hy), (hx - c, -hy), (hx, -hy + c), (hx, hy - c), (hx - c, hy), (-hx + c, hy), (-hx, hy - c), (-hx, -hy + c)]


class KB(MB):
    """MB with 'trusted' explicitly wound faces (open shells allowed).  Only untrusted faces (from MB primitives)
    get their normals recalculated; nothing is welded."""

    def __init__(self):
        super().__init__()
        self._tr = self.bm.faces.layers.int.new("trusted")

    def _f(self, verts, mat):
        try:
            f = self.bm.faces.new(verts)
        except ValueError:
            return None
        f.material_index = self.slot(mat)
        f[self._tr] = 1
        return f

    def finish(self):
        bm = self.bm
        faces = [f for f in bm.faces if f[self._tr] == 0]
        if faces:
            bmesh.ops.recalc_face_normals(bm, faces=faces)
        bm.faces.layers.int.remove(self._tr)
        self._tr = None
        return self

    # -- primitives ------------------------------------------------------------------------------
    def quad(self, pts, mat):
        return self._f([self.bm.verts.new(Vector(p)) for p in pts], mat)

    def box(self, x0, x1, y0, y1, z0, z1, mat, skip=(), mats=None):
        """Axis aligned box from bounds.  skip: faces to omit ('-x','+x','-y','+y','-z','+z'); mats: per-face override."""
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        v = [self.bm.verts.new(p) for p in ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                                             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
        quads = (("-z", (0, 3, 2, 1)), ("+z", (4, 5, 6, 7)), ("-y", (0, 1, 5, 4)), ("+x", (1, 2, 6, 5)),
                 ("+y", (2, 3, 7, 6)), ("-x", (3, 0, 4, 7)))
        for k, q in quads:
            if k in skip:
                continue
            m = mats.get(k, mat) if mats else mat
            self._f([v[i] for i in q], m)
        return self

    def boxc(self, cx, cy, cz, sx, sy, sz, mat, skip=(), mats=None):
        return self.box(cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, cz - sz / 2, cz + sz / 2, mat, skip, mats)

    def prism(self, outline, z0, z1, mat, top=None, bottom=None, edge_mats=None):
        """Extrude a CCW outline from z0 to z1.  top/bottom = cap material (None = no cap)."""
        n = len(outline)
        lo = [self.bm.verts.new((x, y, z0)) for x, y in outline]
        hi = [self.bm.verts.new((x, y, z1)) for x, y in outline]
        for i in range(n):
            j = (i + 1) % n
            m = edge_mats[i] if edge_mats else mat
            if m is not None:
                self._f([lo[i], lo[j], hi[j], hi[i]], m)
        if top is not None:
            self._f(list(hi), top)
        if bottom is not None:
            self._f(list(reversed(lo)), bottom)
        return self

    def frustum(self, outline, z0, z1, inset, mat, top=None, bottom=None):
        """Prism whose top outline is inset by `inset` (mansards, crowns, setback caps)."""
        up = offset_outline(outline, inset)
        n = len(outline)
        lo = [self.bm.verts.new((x, y, z0)) for x, y in outline]
        hi = [self.bm.verts.new((x, y, z1)) for x, y in up]
        for i in range(n):
            j = (i + 1) % n
            self._f([lo[i], lo[j], hi[j], hi[i]], mat)
        if top is not None:
            self._f(list(hi), top)
        if bottom is not None:
            self._f(list(reversed(lo)), bottom)
        return up

    def ring_wall(self, outline, z0, z1, t, mat, top_mat=None, inner_mat=None, outer=True):
        """Mitred wall of thickness t INSIDE the CCW outline (parapets, balustrades).  No overlaps at corners."""
        inner = offset_outline(outline, t)
        n = len(outline)
        ol = [self.bm.verts.new((x, y, z0)) for x, y in outline]
        oh = [self.bm.verts.new((x, y, z1)) for x, y in outline]
        il = [self.bm.verts.new((x, y, z0)) for x, y in inner]
        ih = [self.bm.verts.new((x, y, z1)) for x, y in inner]
        tm = top_mat or mat
        im = inner_mat or mat
        for i in range(n):
            j = (i + 1) % n
            if outer:
                self._f([ol[i], ol[j], oh[j], oh[i]], mat)
            self._f([il[j], il[i], ih[i], ih[j]], im)
            self._f([oh[i], oh[j], ih[j], ih[i]], tm)
        return inner

    def ring_slab(self, outline, z0, z1, out, mat, top_mat=None, bottom=True):
        """Ledge / cornice / balcony band projecting `out` metres OUTSIDE the CCW outline (mitred, no overlaps)."""
        outer = offset_outline(outline, -out)
        n = len(outline)
        il = [self.bm.verts.new((x, y, z0)) for x, y in outline]
        ih = [self.bm.verts.new((x, y, z1)) for x, y in outline]
        ol = [self.bm.verts.new((x, y, z0)) for x, y in outer]
        oh = [self.bm.verts.new((x, y, z1)) for x, y in outer]
        tm = top_mat or mat
        for i in range(n):
            j = (i + 1) % n
            self._f([ol[i], ol[j], oh[j], oh[i]], mat)
            self._f([oh[i], oh[j], ih[j], ih[i]], tm)
            if bottom:
                self._f([il[i], il[j], ol[j], ol[i]], mat)
        return outer

    def cylinder(self, cx, cy, r0, r1, z0, z1, seg, mat, top=None, bottom=None, phase=0.0, side=True):
        """Faceted cylinder / frustum along Z (vertex k at angle phase + 2 pi k / seg)."""
        lo, hi = [], []
        for k in range(seg):
            a = phase + 2 * math.pi * k / seg
            c, s = math.cos(a), math.sin(a)
            lo.append(self.bm.verts.new((cx + r0 * c, cy + r0 * s, z0)))
            hi.append(self.bm.verts.new((cx + r1 * c, cy + r1 * s, z1)))
        if side:
            for k in range(seg):
                j = (k + 1) % seg
                self._f([lo[k], lo[j], hi[j], hi[k]], mat)
        if top is not None:
            if r1 > 1e-6:
                self._f(list(hi), top)
        if bottom is not None and r0 > 1e-6:
            self._f(list(reversed(lo)), bottom)
        return self

    def annulus(self, cx, cy, ri, ro, z0, z1, seg, mat, faces=("top", "outer", "bottom", "inner"), phase=0.0,
                top_mat=None):
        ang = [phase + 2 * math.pi * k / seg for k in range(seg)]
        il = [self.bm.verts.new((cx + ri * math.cos(a), cy + ri * math.sin(a), z0)) for a in ang]
        ih = [self.bm.verts.new((cx + ri * math.cos(a), cy + ri * math.sin(a), z1)) for a in ang]
        ol = [self.bm.verts.new((cx + ro * math.cos(a), cy + ro * math.sin(a), z0)) for a in ang]
        oh = [self.bm.verts.new((cx + ro * math.cos(a), cy + ro * math.sin(a), z1)) for a in ang]
        for k in range(seg):
            j = (k + 1) % seg
            if "outer" in faces:
                self._f([ol[k], ol[j], oh[j], oh[k]], mat)
            if "inner" in faces:
                self._f([il[j], il[k], ih[k], ih[j]], mat)
            if "top" in faces:
                self._f([oh[k], oh[j], ih[j], ih[k]], top_mat or mat)
            if "bottom" in faces:
                self._f([il[k], il[j], ol[j], ol[k]], mat)
        return self

    def xz_prism(self, pts, y0, y1, mats, cap_mat):
        """Extrude an outline given in the XZ plane (list of (x, z), CCW seen from -Y) from y0 to y1.
        mats[i] = material of the side face on edge i (None = skip); cap_mat = both end caps (None = skip)."""
        n = len(pts)
        a = [self.bm.verts.new((x, y0, z)) for x, z in pts]
        b = [self.bm.verts.new((x, y1, z)) for x, z in pts]
        for i in range(n):
            j = (i + 1) % n
            if mats[i] is not None:
                self._f([a[i], b[i], b[j], a[j]], mats[i])
        if cap_mat is not None:
            self._f(list(a), cap_mat)            # CCW seen from -Y -> normal -Y
            self._f(list(reversed(b)), cap_mat)
        return self

    def beam(self, a, b, w, t, mat):
        """Oriented box from point a to point b (width w, thickness t) - closed, normals recalculated."""
        a, b = Vector(a), Vector(b)
        d = b - a
        q = Vector((0, 0, 1)).rotation_difference(d.normalized())
        MB.box(self, (a + b) / 2, (w, t, d.length), mat=mat, rot=q)
        return self


# ----------------------------------------------------------------------------------------------------
# module container
# ----------------------------------------------------------------------------------------------------
class Bld:
    def __init__(self, lib, idx, name, seed, shift=(0.0, 0.0), bevel=0.15):
        self.lib = lib
        self.idx = idx
        self.name = f"Bld_{idx:02d}_{name}"
        self.mass, self.det, self.lod = KB(), KB(), KB()
        self.cols, self.slots = [], []
        self.shift = shift
        self.bevel = bevel
        self.cyl_center = (0.0, 0.0)
        rng = np.random.default_rng(seed)
        self.offsets = rng.integers(0, 8, size=(4, 2)).astype(np.float64) / 8.0
        self.band_offsets = rng.integers(0, 8, size=(8, 4)).astype(np.float64) / 8.0

    # shorthands
    def m(self, name):
        return self.lib.m(name)

    def sw(self, name):
        return self.lib.sw(name)

    def col(self, x0, x1, y0, y1, z0, z1):
        self.cols.append((((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), ((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2)))

    def slot(self, x, y, z):
        self.slots.append((x, y, z))

    def finish(self):
        name = self.name
        root = add_empty(name, (0, 0, 0), display="PLAIN_AXES", size=4.0)
        mass = self.mass.to_object(name + "_Mass", smooth=False)
        split_bands(mass)
        if self.bevel:
            mod = mass.modifiers.new("Bevel", "BEVEL")
            mod.width = self.bevel
            mod.segments = 1
            mod.limit_method = "ANGLE"
            mod.angle_limit = math.radians(30)
            mod.harden_normals = False
            apply_modifiers(mass)
        n = len(mass.data.polygons)
        mass.data.polygons.foreach_set("use_smooth", np.zeros(n, bool))
        det = self.det.to_object(name + "_Detail", smooth=True, sharp_angle=40.0)
        geo = join_objects([mass, det], name + "_Geo")
        assign_uvs(geo, self.lib, self.shift, self.offsets, self.cyl_center, band_offsets=self.band_offsets)
        geo.parent = root
        tag = f"B{self.idx:02d}"
        for i, (c, h) in enumerate(self.cols, 1):
            e = add_empty(f"COL_{i}_{tag}", c, parent=root, display="CUBE", size=1.0)
            e.scale = h
        for i, p in enumerate(self.slots, 1):
            add_empty(f"Roof_Slot_{i}_{tag}", p, parent=root, display="PLAIN_AXES", size=2.0)
        lod = self.lod.to_object(name + "_LOD1", smooth=False)
        split_bands(lod)
        assign_uvs(lod, self.lib, self.shift, self.offsets, self.cyl_center, band_offsets=self.band_offsets)
        return root, lod


def join_objects(objs, name):
    target = objs[0]
    others = [o.data for o in objs[1:]]
    with bpy.context.temp_override(active_object=target, object=target, selected_objects=objs,
                                   selected_editable_objects=objs):
        bpy.ops.object.join()
    for me in others:
        if me.users == 0:
            bpy.data.meshes.remove(me)
    target.name = name
    target.data.name = name
    return target


# ----------------------------------------------------------------------------------------------------
# rooftop / detail props (all into a KB, materials from the Bld's library)
# ----------------------------------------------------------------------------------------------------
def beacon(b, kb, x, y, z, r=0.28):
    B = b.m("beacon_red")
    kb.cylinder(x, y, r * 0.8, r, z, z + r * 0.9, 8, B, top=B, bottom=None)
    kb.cylinder(x, y, r, r * 0.35, z + r * 0.9, z + r * 1.6, 8, B, top=B)


def mast(b, kb, x, y, z0, h, r0=0.35, arms=2, beacons=(1.0, 0.55)):
    """Tapered antenna mast with cross arms and red beacons at the given height fractions."""
    G, S = b.sw("graphite"), b.sw("silver")
    kb.cylinder(x, y, r0 * 1.6, r0 * 1.4, z0, z0 + 0.6, 8, G, top=G)
    kb.cylinder(x, y, r0, r0 * 0.25, z0 + 0.6, z0 + h, 6, S, top=S)
    for k in range(arms):
        zz = z0 + h * (0.35 + 0.22 * k)
        ln = 2.4 - 0.6 * k
        kb.box(x - ln / 2, x + ln / 2, y - 0.06, y + 0.06, zz - 0.06, zz + 0.06, G)
        kb.box(x - 0.06, x + 0.06, y - ln / 2, y + ln / 2, zz + 0.3 - 0.06, zz + 0.3 + 0.06, G)
        kb.box(x + ln / 2 - 0.12, x + ln / 2, y - 0.25, y + 0.25, zz - 0.9, zz + 0.1, S)
    for f in beacons:
        zz = z0 + h * f
        if f >= 0.99:
            beacon(b, kb, x, y, z0 + h, 0.3)
        else:
            beacon(b, kb, x + r0 * 0.9, y, zz, 0.2)
            beacon(b, kb, x - r0 * 0.9, y, zz, 0.2)


def ac_unit(b, kb, x, y, z, w=2.6, d=1.7, h=1.3, rot90=False):
    S, G, R = b.sw("silver"), b.sw("graphite"), b.sw("rubber")
    if rot90:
        w, d = d, w
    kb.box(x - w / 2, x + w / 2, y - d / 2, y + d / 2, z, z + h, S, skip=("-z",))
    kb.box(x - w / 2 - 0.05, x + w / 2 + 0.05, y - d / 2 - 0.05, y + d / 2 + 0.05, z, z + 0.15, G, skip=("-z",))
    nf = 2 if max(w, d) > 2.0 else 1
    for k in range(nf):
        t = (k + 0.5) / nf
        fx = x - w / 2 + w * t if w >= d else x
        fy = y if w >= d else y - d / 2 + d * t
        rr = min(w, d) * 0.34
        kb.cylinder(fx, fy, rr, rr, z + h, z + h + 0.12, 10, G, top=R)
    # grille strip
    if w >= d:
        kb.box(x - w / 2 + 0.2, x + w / 2 - 0.2, y - d / 2 - 0.03, y - d / 2, z + 0.3, z + h - 0.25, G, skip=("+y", "-z", "+z"))
    else:
        kb.box(x - w / 2 - 0.03, x - w / 2, y - d / 2 + 0.2, y + d / 2 - 0.2, z + 0.3, z + h - 0.25, G, skip=("+x", "-z", "+z"))


def cooling_tower(b, kb, x, y, z, s=4.2, h=3.4):
    S, G, R = b.sw("silver"), b.sw("graphite"), b.sw("rubber")
    kb.box(x - s / 2, x + s / 2, y - s / 2, y + s / 2, z, z + 0.6, G, skip=("-z",))
    kb.box(x - s / 2 + 0.1, x + s / 2 - 0.1, y - s / 2 + 0.1, y + s / 2 - 0.1, z + 0.6, z + h, S, skip=("-z",))
    # louvre bands
    for k in range(3):
        zz = z + 0.9 + k * 0.6
        kb.ring_slab(rect(x - s / 2 + 0.1, x + s / 2 - 0.1, y - s / 2 + 0.1, y + s / 2 - 0.1), zz, zz + 0.12, 0.06, G, bottom=True)
    r = s * 0.4
    kb.cylinder(x, y, r, r * 1.05, z + h, z + h + 0.9, 16, G, top=None)
    kb.annulus(x, y, r * 0.95, r * 1.05, z + h + 0.9, z + h + 0.95, 16, G, faces=("top",))
    kb.cylinder(x, y, r * 0.95, r * 0.95, z + h + 0.45, z + h + 0.5, 16, R, top=R, side=False)
    kb.cylinder(x, y, 0.35, 0.3, z + h + 0.5, z + h + 0.75, 8, S, top=S)


def penthouse(b, kb, x0, x1, y0, y1, z0, z1, mat=None, louvres=("-y", "+y"), door="+x"):
    """Mechanical penthouse: box + louvre bands + door + roof edge trim."""
    C = mat or b.m("bld_concrete")
    G, S = b.sw("graphite"), b.sw("silver")
    kb.box(x0, x1, y0, y1, z0, z1, C, skip=("-z",))
    kb.ring_slab(rect(x0, x1, y0, y1), z1 - 0.25, z1, 0.15, S)
    h = z1 - z0
    for side in louvres:
        for k in range(5):
            zz = z0 + h * 0.3 + k * h * 0.11
            if side in ("-y", "+y"):
                yy = y0 if side == "-y" else y1
                s = -1 if side == "-y" else 1
                kb.box(x0 + 1.0, x1 - 1.0, yy, yy + s * 0.12, zz, zz + h * 0.05, G, skip=("+y" if s < 0 else "-y",))
            else:
                xx = x0 if side == "-x" else x1
                s = -1 if side == "-x" else 1
                kb.box(xx, xx + s * 0.12, y0 + 1.0, y1 - 1.0, zz, zz + h * 0.05, G, skip=("+x" if s < 0 else "-x",))
    if door:
        if door in ("+x", "-x"):
            xx = x1 if door == "+x" else x0
            s = 1 if door == "+x" else -1
            yc = (y0 + y1) / 2
            kb.box(xx, xx + s * 0.08, yc - 0.6, yc + 0.6, z0, z0 + 2.3, G, skip=("-x" if s > 0 else "+x", "-z"))
        else:
            yy = y1 if door == "+y" else y0
            s = 1 if door == "+y" else -1
            xc = (x0 + x1) / 2
            kb.box(xc - 0.6, xc + 0.6, yy, yy + s * 0.08, z0, z0 + 2.3, G, skip=("-y" if s > 0 else "+y", "-z"))


def stair_bulkhead(b, kb, x, y, z, rot90=False):
    C = b.m("bld_concrete")
    G = b.sw("graphite")
    w, d = (3.0, 3.4) if not rot90 else (3.4, 3.0)
    kb.box(x - w / 2, x + w / 2, y - d / 2, y + d / 2, z, z + 2.7, C, skip=("-z",))
    kb.box(x - w / 2 - 0.12, x + w / 2 + 0.12, y - d / 2 - 0.12, y + d / 2 + 0.12, z + 2.7, z + 2.9, G, skip=())
    if not rot90:
        kb.box(x - 0.55, x + 0.55, y - d / 2 - 0.06, y - d / 2, z, z + 2.2, G, skip=("+y", "-z"))
    else:
        kb.box(x - w / 2 - 0.06, x - w / 2, y - 0.55, y + 0.55, z, z + 2.2, G, skip=("+x", "-z"))


def vent_stack(b, kb, x, y, z, h=2.2, r=0.3):
    S, G = b.sw("silver"), b.sw("graphite")
    kb.cylinder(x, y, r, r, z, z + h, 8, S, top=None)
    kb.cylinder(x, y, r * 1.6, r * 0.2, z + h + 0.15, z + h + 0.55, 8, G, bottom=G, top=None)


def water_tank(b, kb, x, y, z, r=2.3, h=3.6, legs=2.8):
    """Timber water tank on a steel stand with a conical roof (NYC style)."""
    W, D, Z, G = b.sw("wood"), b.sw("steel_dark"), b.sw("zinc"), b.sw("graphite")
    s = r * 0.72
    for sx in (-1, 1):
        for sy in (-1, 1):
            kb.box(x + sx * s - 0.15, x + sx * s + 0.15, y + sy * s - 0.15, y + sy * s + 0.15, z, z + legs, D, skip=("-z",))
    kb.beam((x - s, y - s, z + 0.4), (x + s, y + s, z + legs - 0.3), 0.08, 0.08, D)
    kb.beam((x + s, y - s, z + 0.4), (x - s, y + s, z + legs - 0.3), 0.08, 0.08, D)
    kb.box(x - r - 0.2, x + r + 0.2, y - r - 0.2, y + r + 0.2, z + legs, z + legs + 0.25, D)
    kb.cylinder(x, y, r, r * 0.97, z + legs + 0.25, z + legs + 0.25 + h, 14, W, top=None, bottom=None)
    for f in (0.2, 0.55, 0.88):
        zz = z + legs + 0.25 + h * f
        kb.annulus(x, y, r * 0.99, r * 1.04, zz, zz + 0.12, 14, D, faces=("top", "outer", "bottom"))
    zt = z + legs + 0.25 + h
    kb.cylinder(x, y, r * 1.06, 0.0, zt, zt + r * 0.62, 14, Z, bottom=Z)
    kb.cylinder(x, y, 0.12, 0.06, zt + r * 0.6, zt + r * 0.62 + 0.6, 6, G, top=G)
    return zt + r * 0.62 + 0.6


def solar_array(b, kb, x0, x1, y0, y1, z, rows=3, tilt=0.8):
    P, G = b.sw("solar"), b.sw("graphite")
    dy = (y1 - y0) / rows
    for k in range(rows):
        ya = y0 + k * dy + 0.3
        yb = y0 + (k + 1) * dy - 0.3
        kb.quad([(x0, ya, z + 0.3), (x1, ya, z + 0.3), (x1, yb, z + 0.3 + tilt), (x0, yb, z + 0.3 + tilt)], P)
        kb.quad([(x0, yb, z + 0.3 + tilt), (x1, yb, z + 0.3 + tilt), (x1, ya, z + 0.3), (x0, ya, z + 0.3)], G)
        for xx in (x0 + 0.3, (x0 + x1) / 2, x1 - 0.3):
            kb.box(xx - 0.05, xx + 0.05, yb - 0.1, yb, z, z + 0.3 + tilt, G, skip=("-z",))


def helipad(b, kb, cx, cy, z, size, light_r=None, round_=False):
    """Deck markings (raised 0.08 m: yellow circle, white H + edge line) + green perimeter lights.  The deck
    surface itself must exist at z."""
    Y, W, L = b.sw("yellow"), b.sw("white"), b.sw("light_green")
    h = 0.08
    r = size * 0.36
    kb.annulus(cx, cy, r - 0.45, r, z, z + h, 32, Y, faces=("top", "outer", "inner"))
    hs = size * 0.16
    kb.box(cx - hs, cx - hs + 0.9, cy - hs * 1.25, cy + hs * 1.25, z, z + h, W, skip=("-z",))
    kb.box(cx + hs - 0.9, cx + hs, cy - hs * 1.25, cy + hs * 1.25, z, z + h, W, skip=("-z",))
    kb.box(cx - hs + 0.9, cx + hs - 0.9, cy - 0.45, cy + 0.45, z, z + h, W, skip=("-z",))
    n = 20 if round_ else 12
    lr = light_r if light_r is not None else size * 0.47
    for k in range(n):
        if round_:
            a = 2 * math.pi * k / n
            px, py = cx + math.cos(a) * lr, cy + math.sin(a) * lr
        else:
            t = k / n * 4
            side, f = int(t), t - int(t)
            e = lr
            pts = [(-e, -e), (e, -e), (e, e), (-e, e)]
            p0, p1 = pts[side], pts[(side + 1) % 4]
            px, py = cx + p0[0] + (p1[0] - p0[0]) * f, cy + p0[1] + (p1[1] - p0[1]) * f
        kb.box(px - 0.18, px + 0.18, py - 0.18, py + 0.18, z, z + 0.22, L, skip=("-z",))


def light_strip_ring(b, kb, outline, z, h=0.25, out=0.06, swatch="light_warm"):
    kb.ring_slab(outline, z, z + h, out, b.sw(swatch))


def lod_prism(b, outline, z0, z1, wall, roof, bottom=None):
    b.lod.prism(outline, z0, z1, wall, top=roof, bottom=bottom)


# ----------------------------------------------------------------------------------------------------
# small rooftop clutter + deterministic scatter
# ----------------------------------------------------------------------------------------------------
def prop_hatch(b, kb, x, y, z, rot90=False):
    G, S = b.sw("graphite"), b.sw("silver")
    kb.box(x - 0.7, x + 0.7, y - 0.7, y + 0.7, z, z + 0.55, S, skip=("-z",))
    kb.box(x - 0.8, x + 0.8, y - 0.8, y + 0.8, z + 0.55, z + 0.65, G)


def prop_skylight(b, kb, x, y, z, rot90=False):
    GD, S = b.sw("glass_dark"), b.sw("silver")
    w, d = (3.2, 2.2) if not rot90 else (2.2, 3.2)
    kb.box(x - w / 2, x + w / 2, y - d / 2, y + d / 2, z, z + 0.4, S, skip=("-z",))
    if not rot90:
        kb.xz_prism([(x - w / 2, z + 0.4), (x + w / 2, z + 0.4), (x, z + 1.25)], y - d / 2, y + d / 2, [None, GD, GD], S)
    else:
        kb.xz_prism([(x - w / 2, z + 0.4), (x + w / 2, z + 0.4), (x + w / 2, z + 1.0), (x - w / 2, z + 1.0)],
                    y - d / 2, y + d / 2, [None, S, GD, S], S)


def prop_dish(b, kb, x, y, z, rot90=False, r=0.85):
    G, W = b.sw("graphite"), b.sw("white")
    kb.box(x - 0.09, x + 0.09, y - 0.09, y + 0.09, z, z + 1.35, G, skip=("-z",))
    yaw = 200.0 if not rot90 else 250.0
    MB.cyl(kb, center=(x, y, z + 1.55), r=r, h=0.18, seg=12, axis="Z", mat=W, r_top=r * 0.55, rot=(-50, 0, yaw - 90))
    MB.cyl(kb, center=(x, y, z + 1.55), r=0.05, h=1.3, seg=4, axis="Z", mat=G, rot=(-50, 0, yaw - 90))


def prop_pipe(b, kb, x, y, z, rot90=False, ln=7.0, r=0.18):
    S, G = b.sw("silver"), b.sw("graphite")
    axis = "X" if not rot90 else "Y"
    for k in range(2):
        off = (k - 0.5) * 0.5
        cx, cy = (x, y + off) if not rot90 else (x + off, y)
        MB.cyl(kb, center=(cx, cy, z + 0.55), r=r, h=ln, seg=8, axis=axis, mat=S if k == 0 else G)
    n = int(ln // 2.5) + 1
    for i in range(n):
        t = -ln / 2 + 0.3 + i * (ln - 0.6) / max(1, n - 1)
        if not rot90:
            kb.box(x + t - 0.08, x + t + 0.08, y - 0.45, y + 0.45, z, z + 0.4, G, skip=("-z",))
        else:
            kb.box(x - 0.45, x + 0.45, y + t - 0.08, y + t + 0.08, z, z + 0.4, G, skip=("-z",))


def prop_cabinet(b, kb, x, y, z, rot90=False):
    D, G = b.sw("steel_dark"), b.sw("graphite")
    w, d = (1.5, 0.6) if not rot90 else (0.6, 1.5)
    kb.box(x - w / 2, x + w / 2, y - d / 2, y + d / 2, z, z + 1.8, D, skip=("-z",))
    kb.box(x - w / 2 - 0.08, x + w / 2 + 0.08, y - d / 2 - 0.08, y + d / 2 + 0.08, z + 1.8, z + 1.9, G)


def prop_small_acs(b, kb, x, y, z, rot90=False, n=3):
    W, G = b.sw("white"), b.sw("graphite")
    for i in range(n):
        t = (i - (n - 1) / 2) * 1.1
        px, py = (x + t, y) if not rot90 else (x, y + t)
        kb.box(px - 0.45, px + 0.45, py - 0.3, py + 0.3, z, z + 0.75, W, skip=("-z",))
        kb.cylinder(px, py, 0.26, 0.26, z + 0.75, z + 0.8, 8, G, top=G, side=False)
    if not rot90:
        kb.box(x - n * 0.55, x + n * 0.55, y - 0.35, y + 0.35, z, z + 0.1, G, skip=("-z",))
    else:
        kb.box(x - 0.35, x + 0.35, y - n * 0.55, y + n * 0.55, z, z + 0.1, G, skip=("-z",))


def prop_htank(b, kb, x, y, z, rot90=False, ln=4.2, r=0.8):
    W, G = b.sw("silver"), b.sw("graphite")
    MB.cyl(kb, center=(x, y, z + r + 0.3), r=r, h=ln, seg=12, axis="X" if not rot90 else "Y", mat=W)
    for s in (-1, 1):
        px, py = (x + s * ln * 0.3, y) if not rot90 else (x, y + s * ln * 0.3)
        if not rot90:
            kb.box(px - 0.15, px + 0.15, py - r * 0.8, py + r * 0.8, z, z + r * 0.7, G, skip=("-z",))
        else:
            kb.box(px - r * 0.8, px + r * 0.8, py - 0.15, py + 0.15, z, z + r * 0.7, G, skip=("-z",))


def prop_mushroom(b, kb, x, y, z, rot90=False):
    S, G = b.sw("silver"), b.sw("graphite")
    kb.cylinder(x, y, 0.32, 0.32, z, z + 0.8, 8, S)
    kb.cylinder(x, y, 0.55, 0.12, z + 0.8, z + 1.1, 8, G, bottom=G)


def prop_ac(b, kb, x, y, z, rot90=False):
    ac_unit(b, kb, x, y, z, rot90=rot90)


def prop_vent(b, kb, x, y, z, rot90=False):
    vent_stack(b, kb, x, y, z, h=1.8, r=0.28)


PROPS = {
    # name: (builder, footprint w, d)
    "ac": (prop_ac, 3.0, 2.0), "acs": (prop_small_acs, 3.6, 0.9), "vent": (prop_vent, 0.8, 0.8),
    "hatch": (prop_hatch, 1.8, 1.8), "skylight": (prop_skylight, 3.3, 2.3), "dish": (prop_dish, 2.0, 2.0),
    "pipe": (prop_pipe, 7.2, 1.0), "cabinet": (prop_cabinet, 1.7, 0.8), "htank": (prop_htank, 4.4, 1.8),
    "mush": (prop_mushroom, 1.2, 1.2),
}


def overlaps(r, a):
    return not (r[1] <= a[0] or r[0] >= a[1] or r[3] <= a[2] or r[2] >= a[3])


def roof_clutter(b, kb, area, z, seed, n=8, avoid=(), kinds=None, margin=0.6):
    """Scatter n rooftop props inside area=(x0,x1,y0,y1) at height z, avoiding `avoid` rectangles and every roof slot
    at this height (4x4 m + margin kept clear).  Deterministic (numpy Generator with a fixed seed)."""
    rng = np.random.default_rng(seed)
    x0, x1, y0, y1 = area
    placed = [tuple(a) for a in avoid]
    for (sx, sy, sz) in b.slots:
        if abs(sz - z) < 0.6:
            placed.append((sx - 2.3, sx + 2.3, sy - 2.3, sy + 2.3))
    names = kinds or ["ac", "acs", "vent", "hatch", "skylight", "dish", "pipe", "cabinet", "htank", "mush"]
    count = 0
    for _ in range(n * 25):
        if count >= n:
            break
        k = names[int(rng.integers(len(names)))]
        fn, w, d = PROPS[k]
        rot = bool(rng.random() < 0.5)
        if rot:
            w, d = d, w
        if x1 - x0 < w + 2 * margin or y1 - y0 < d + 2 * margin:
            continue
        x = float(rng.uniform(x0 + w / 2 + margin, x1 - w / 2 - margin))
        y = float(rng.uniform(y0 + d / 2 + margin, y1 - d / 2 - margin))
        x, y = round(x * 4) / 4, round(y * 4) / 4
        r = (x - w / 2 - 0.35, x + w / 2 + 0.35, y - d / 2 - 0.35, y + d / 2 + 0.35)
        if any(overlaps(r, a) for a in placed):
            continue
        placed.append(r)
        fn(b, kb, x, y, z, rot90=rot)
        count += 1
    return placed

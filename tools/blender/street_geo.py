"""Street-kit geometry helpers shared by build_city_ground.py and build_city_props.py (Blender / bmesh).

Everything is deterministic and works on top of common.MB.

  GMB          MeshBuilder subclass: hand-oriented faces with optional per-vertex UVs; `finish()` only welds
               (it never re-orients faces, so open surfaces such as tile tops keep their winding).
  closed()     build a CLOSED primitive in its own MB (weld + outward normals) and merge it into a GMB.
  rbox()       box with bevelled (rounded) edges - real "designed" hard-surface parts without modifiers.
  sweep()      extrude a closed 2D profile along a 3D polyline (curbs, pipes, rails).
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MB, rot_matrix  # noqa: E402


class GMB(MB):
    """MB whose faces are oriented by the caller (see `poly`), with UV support.  `weld=False` keeps every merged part
    topologically separate (no vertex sharing between parts) - what hard-surface props want."""

    def __init__(self, weld=True):
        super().__init__()
        self.weld = weld

    def uv_layer(self):
        return self.bm.loops.layers.uv.verify()

    def finish(self):
        if self.weld:
            bmesh.ops.remove_doubles(self.bm, verts=list(self.bm.verts), dist=1e-5)
        return self

    def poly_out(self, pts, centroid, mat=None, uv=None):
        """Polygon oriented so that its normal points away from `centroid` (for convex shells built by hand)."""
        v = [Vector(p) for p in pts]
        n = (v[1] - v[0]).cross(v[2] - v[0])
        c = sum(v, Vector((0, 0, 0))) / len(v)
        if n.dot(c - Vector(centroid)) < 0:
            v = v[::-1]
            if uv is not None and not callable(uv):
                uv = uv[::-1]
        return self.poly([tuple(p) for p in v], mat, uv)

    def poly(self, pts, mat=None, uv=None):
        """Polygon whose vertex order is CCW seen from the outside.  uv: callable (x, y, z) -> (u, v)
        or a list of (u, v) tuples (one per vertex)."""
        f = self.face(pts, mat)
        if f is None or uv is None:
            return f
        layer = self.uv_layer()
        for i, loop in enumerate(f.loops):
            p = loop.vert.co
            loop[layer].uv = uv(p.x, p.y, p.z) if callable(uv) else uv[i]
        return f


def add_closed(main, sub, matrix=None, drop_bottom_z=None):
    """Weld + orient a closed sub-mesh, then copy it into `main`.  `drop_bottom_z`: delete the down-facing faces whose centre
    lies at or below this height (hidden undersides of parts that sit on a surface)."""
    sub.finish()
    if drop_bottom_z is not None:
        drop_bottom_faces(sub, drop_bottom_z)
    main.merge_into(sub, matrix)
    sub.bm.free()


def drop_bottom_faces(sub, z_max):
    sub.bm.normal_update()
    faces = [f for f in sub.bm.faces if f.normal.z < -0.9 and f.calc_center_median().z <= z_max + 1e-6]
    if faces:
        bmesh.ops.delete(sub.bm, geom=faces, context="FACES")


# ----------------------------------------------------------------------------------------------------
# axis-aligned box faces with hand-oriented winding (normal outward)
# ----------------------------------------------------------------------------------------------------
def box_face(mb, which, x0, x1, y0, y1, z0, z1, mat=None, uv=None):
    """One face of the axis aligned box [x0,x1]x[y0,y1]x[z0,z1] with the outward normal given by `which`
    ('+x','-x','+y','-y','+z','-z')."""
    if which == "+x":
        pts = [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]
    elif which == "-x":
        pts = [(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)]
    elif which == "+y":
        pts = [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)]
    elif which == "-y":
        pts = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]
    elif which == "+z":
        pts = [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    elif which == "-z":
        pts = [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)]
    else:
        raise ValueError(which)
    return mb.poly(pts, mat, uv)


# ----------------------------------------------------------------------------------------------------
# bevelled box
# ----------------------------------------------------------------------------------------------------
def rbox_mb(size, r=0.02, seg=1, mat=None, center=(0, 0, 0), rot=None, taper=(1.0, 1.0), top_shift=(0.0, 0.0),
            bottom_scale=(1.0, 1.0)):
    """Closed box MB (welded, outward normals) with all edges bevelled by `r`."""
    sub = MB()
    sub.box(center, size, mat=mat, rot=rot, taper=taper, top_shift=top_shift, bottom_scale=bottom_scale)
    sub.finish()
    if r > 0:
        bmesh.ops.bevel(sub.bm, geom=list(sub.bm.edges), offset=r, segments=seg, affect="EDGES", clamp_overlap=True)
    return sub


def add_rbox(main, center, size, mat, r=0.02, seg=1, rot=None, taper=(1.0, 1.0), top_shift=(0.0, 0.0), bottom_scale=(1.0, 1.0),
             bottom=True):
    sub = rbox_mb(size, r, seg, mat, center, rot, taper, top_shift, bottom_scale)
    if not bottom:
        drop_bottom_faces(sub, center[2] - size[2] / 2.0 + 1e-4)
    main.merge_into(sub)
    sub.bm.free()


def add_box(main, center, size, mat, rot=None, taper=(1.0, 1.0), top_shift=(0.0, 0.0), bottom_scale=(1.0, 1.0), bottom=True):
    sub = MB()
    sub.box(center, size, mat=mat, rot=rot, taper=taper, top_shift=top_shift, bottom_scale=bottom_scale)
    add_closed(main, sub, drop_bottom_z=None if bottom else center[2] - size[2] / 2.0 + 1e-4)


def add_cyl(main, center, r, h, mat, seg=12, axis="Z", r_top=None, rot=None, caps=True, scale=(1, 1)):
    sub = MB()
    sub.cyl(center, r=r, h=h, seg=seg, axis=axis, mat=mat, r_top=r_top, caps=caps, rot=rot, scale=scale)
    add_closed(main, sub)


def add_revolve(main, profile, center, mat, seg=16, axis="Z", rot=None, caps=False, scale=(1, 1), close_loop=False):
    """Surface of revolution; `close_loop` repeats the first profile point so the surface is a closed torus-like shell."""
    prof = list(profile)
    if close_loop:
        prof.append(prof[0])
    sub = MB()
    sub.revolve(prof, center=center, seg=seg, axis=axis, mat=mat, caps=caps, rot=rot, scale=scale)
    add_closed(main, sub)


# ----------------------------------------------------------------------------------------------------
# sweep a closed profile along a 3D polyline
# ----------------------------------------------------------------------------------------------------
def sweep_mb(path, profile, mat=None, frames=None, caps=True):
    """path: list of (x, y, z) points.  profile: list of (a, b) 2D points (closed polygon, CCW seen along the sweep).
    `frames`: list of (right, up) unit vectors per path point (defaults to parallel transport with world Z up).
    Section point = p + right*a + up*b."""
    pts = [Vector(p) for p in path]
    sections = []
    for k, p in enumerate(pts):
        if frames is not None:
            right, up = frames[k]
        else:
            if k == 0:
                t = pts[1] - pts[0]
            elif k == len(pts) - 1:
                t = pts[-1] - pts[-2]
            else:
                t = pts[k + 1] - pts[k - 1]
            t = t.normalized()
            up = Vector((0, 0, 1))
            if abs(t.dot(up)) > 0.98:
                up = Vector((0, 1, 0))
            right = t.cross(up).normalized()
            up = right.cross(t).normalized()
        sections.append([p + Vector(right) * a + Vector(up) * b for (a, b) in profile])
    sub = MB()
    sub.loft(sections, mat=mat, caps=caps)
    sub.finish()
    return sub


def tube_mb(path, r, seg=8, mat=None, r_end=None, caps=True):
    """Round tube along a polyline (parallel-transport frames), optional taper from r to r_end."""
    pts = [Vector(p) for p in path]
    n = len(pts)
    sections = []
    prev_up = None
    for k, p in enumerate(pts):
        if k == 0:
            t = pts[1] - pts[0]
        elif k == n - 1:
            t = pts[-1] - pts[-2]
        else:
            t = (pts[k + 1] - pts[k]).normalized() + (pts[k] - pts[k - 1]).normalized()
        t = t.normalized()
        if prev_up is None:
            up = Vector((0, 0, 1))
            if abs(t.dot(up)) > 0.98:
                up = Vector((1, 0, 0))
        else:
            up = prev_up
        right = t.cross(up).normalized()
        up = right.cross(t).normalized()
        prev_up = up
        rr = r if r_end is None else r + (r_end - r) * k / max(1, n - 1)
        sec = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            sec.append(p + right * (math.cos(a) * rr) + up * (math.sin(a) * rr))
        sections.append(sec)
    sub = MB()
    sub.loft(sections, mat=mat, caps=caps)
    sub.finish()
    return sub


def add_tube(main, path, r, mat, seg=8, r_end=None, caps=True):
    sub = tube_mb(path, r, seg, mat, r_end, caps)
    main.merge_into(sub)
    sub.bm.free()


def add_strut(main, p0, p1, r, mat, seg=6):
    """Straight round member between two points."""
    add_tube(main, [p0, p1], r, mat, seg)


def add_beam(main, p0, p1, w, h, mat, up=(0, 0, 1)):
    """Straight rectangular member between p0 and p1 (cross-section w x h; h along `up` projected)."""
    a, b = Vector(p0), Vector(p1)
    d = b - a
    L = d.length
    t = d.normalized()
    u = Vector(up)
    if abs(t.dot(u)) > 0.98:
        u = Vector((1, 0, 0))
    r = t.cross(u).normalized()
    u = r.cross(t).normalized()
    hw, hh = w / 2.0, h / 2.0
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    sections = [[a + r * x + u * y for (x, y) in corners], [b + r * x + u * y for (x, y) in corners]]
    sub = MB()
    sub.loft(sections, mat=mat, caps=True)
    sub.finish()
    main.merge_into(sub)
    sub.bm.free()


# ----------------------------------------------------------------------------------------------------
# misc
# ----------------------------------------------------------------------------------------------------
def circle_pts(cx, cy, r, n, a0=0.0):
    return [(cx + r * math.cos(a0 + 2 * math.pi * i / n), cy + r * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)]


def arc_pts(cx, cy, r, a0, a1, n):
    """n+1 points on an arc from angle a0 to a1 (radians)."""
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def signed_volume(mb):
    """Sum of signed tetra volumes (positive when closed pieces have outward normals)."""
    return mb.bm.calc_volume(signed=True)


def assign_faces(mb, fn):
    """fn(face) -> material or None: re-assigns material slots of faces."""
    for f in mb.bm.faces:
        m = fn(f)
        if m is not None:
            f.material_index = mb.slot(m)


def uv_box_for_material(mb, mat, scale=(1.0, 1.0), offset=(0.0, 0.0)):
    """Metric box-projection UVs (metres / scale) for the faces that use `mat` - for hand placed textured parts."""
    if mat not in mb.mats:
        return
    idx = mb.mats.index(mat)
    layer = mb.uv_layer()
    mb.bm.normal_update()
    for f in mb.bm.faces:
        if f.material_index != idx:
            continue
        n = f.normal
        ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
        for lp in f.loops:
            p = lp.vert.co
            if az >= ax and az >= ay:
                u, v = p.x, p.y
            elif ax >= ay:
                u, v = p.y, p.z
            else:
                u, v = p.x, p.z
            lp[layer].uv = (u / scale[0] + offset[0], v / scale[1] + offset[1])


def rr_pts(hw, zb, zt, r):
    """Rounded rectangle (XZ plane) - 8 points, CCW seen along +Y."""
    return [(-hw + r, zb), (hw - r, zb), (hw, zb + r), (hw, zt - r), (hw - r, zt), (-hw + r, zt), (-hw, zt - r), (-hw, zb + r)]


def bezier(p0, p1, p2, p3, n):
    """n+1 points on a cubic Bezier."""
    out = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append(tuple(a * p0[k] + b * p1[k] + c * p2[k] + d * p3[k] for k in range(3)))
    return out


def qa_islands(obj):
    """Return (n_islands, n_closed, negative_volume_islands, degenerate_faces) of an evaluated mesh object (QA helper)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    seen = set()
    islands = 0
    closed = 0
    neg = 0
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        stack = [f0]
        seen.add(f0.index)
        faces = []
        while stack:
            f = stack.pop()
            faces.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        islands += 1
        is_closed = all(len(e.link_faces) == 2 for f in faces for e in f.edges)
        if is_closed:
            closed += 1
            vol = 0.0
            for f in faces:
                vs = [v.co for v in f.verts]
                for i in range(1, len(vs) - 1):
                    vol += vs[0].dot(vs[i].cross(vs[i + 1])) / 6.0
            if vol < 0:
                neg += 1
    degenerate = sum(1 for f in bm.faces if f.calc_area() < 1e-9)
    bm.free()
    ev.to_mesh_clear()
    return islands, closed, neg, degenerate


def add_sphere(main, center, r, mat, seg=12, rings=8, scale=(1.0, 1.0, 1.0), jitter=None, seed=0):
    """Deterministic UV sphere (bmesh.ops.create_uvsphere is NOT deterministic between processes in Blender 4.4, so build it by
    revolving a semicircle).  `jitter` (fraction of r) displaces the vertices radially with a seeded RNG for organic bushes."""
    import random as _random
    prof = [(math.sin(math.pi * i / rings) * r, -math.cos(math.pi * i / rings) * r * scale[2]) for i in range(rings + 1)]
    sub = MB()
    sub.revolve(prof, center=center, seg=seg, axis="Z", mat=mat, caps=False, scale=(scale[0], scale[1]))
    sub.finish()
    if jitter:
        rng = _random.Random(seed)
        c = Vector(center)
        for v in sub.bm.verts:          # bm.verts order is creation order -> deterministic
            d = v.co - c
            if d.length > 1e-6:
                v.co = c + d * (1.0 + rng.uniform(-jitter, jitter))
        bmesh.ops.recalc_face_normals(sub.bm, faces=list(sub.bm.faces))
    main.merge_into(sub)
    sub.bm.free()

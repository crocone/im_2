"""Private hard-surface helpers for build_enemies.py / build_projectiles.py (hostile machines + projectiles).

Only builds on top of common.MB - nothing here touches scene state.  All functions are deterministic.
Coordinates: Blender metres, +Y forward, +Z up, +X right.
"""
import math

from mathutils import Matrix, Quaternion, Vector

from common import MB, rot_matrix  # noqa: F401


def V(x, y, z):
    return Vector((x, y, z))


# ----------------------------------------------------------------------------------------------
# cross sections / lofts
# ----------------------------------------------------------------------------------------------
def oct_sec(y, tw, mw, bw, zt, zh, zl, zb, x0=0.0, z0=0.0):
    """8-point chamfered hull cross-section in the XZ plane at depth y (top/mid/bottom half widths,
    z of top, upper-mid, lower-mid and bottom).  Used for lofting fuselages / pods along +Y."""
    return [V(x0 + tw, y, z0 + zt), V(x0 + mw, y, z0 + zh), V(x0 + mw, y, z0 + zl), V(x0 + bw, y, z0 + zb),
            V(x0 - bw, y, z0 + zb), V(x0 - mw, y, z0 + zl), V(x0 - mw, y, z0 + zh), V(x0 - tw, y, z0 + zt)]


def oct_sec_x(x, tw, mw, bw, zt, zh, zl, zb, y0=0.0, z0=0.0):
    """Same as oct_sec but the section lies in the YZ plane at x (loft along X; 'width' = along Y)."""
    return [V(x, y0 + tw, z0 + zt), V(x, y0 + mw, z0 + zh), V(x, y0 + mw, z0 + zl), V(x, y0 + bw, z0 + zb),
            V(x, y0 - bw, z0 + zb), V(x, y0 - mw, z0 + zl), V(x, y0 - mw, z0 + zh), V(x, y0 - tw, z0 + zt)]


def lathe_closed(mb, profile, center=(0, 0, 0), seg=24, axis="Z", mat=None, rot=None, phase=0.0, scale=(1.0, 1.0)):
    """Revolve a CLOSED cross-section loop [(radius, height), ...] around `axis` -> watertight ring solid
    (ducts, collars, nozzle bells, bands).  `mat` may be a list with one material per profile edge
    (edge k joins profile[k] -> profile[k+1], the last one closes the loop)."""
    m = rot_matrix(rot) @ mb._axis_matrix(axis)
    c = Vector(center)
    rings = []
    for (r, z) in profile:
        ring = []
        for i in range(seg):
            a = phase + 2 * math.pi * i / seg
            ring.append(mb.bm.verts.new(m @ Vector((math.cos(a) * r * scale[0], math.sin(a) * r * scale[1], z)) + c))
        rings.append(ring)
    n = len(rings)
    out = []
    for k in range(n):
        a, b = rings[k], rings[(k + 1) % n]
        mk = mat[k % len(mat)] if isinstance(mat, (list, tuple)) else mat
        idx = mb.slot(mk)
        for i in range(seg):
            j = (i + 1) % seg
            try:
                f = mb.bm.faces.new((a[i], a[j], b[j], b[i]))
            except ValueError:
                continue
            f.material_index = idx
            out.append(f)
    return out


def revolve_mats(mb, profile, center=(0, 0, 0), seg=24, axis="Z", mats=None, rot=None, phase=0.0, cap_bottom=True,
                 cap_top=True, cap_mats=(None, None)):
    """Open profile [(r, h), ...] revolved (like MB.revolve) with one material per profile edge + optional caps.
    A radius of 0 makes a real pole (one vertex + triangle fan), so nothing relies on vertex welding
    (bmesh welding / create_uvsphere are not order-deterministic across Blender processes)."""
    m = rot_matrix(rot) @ mb._axis_matrix(axis)
    c = Vector(center)
    rings = []
    for (r, z) in profile:
        if abs(r) < 1e-9:
            rings.append([mb.bm.verts.new(m @ Vector((0.0, 0.0, z)) + c)] * seg)
        else:
            rings.append([mb.bm.verts.new(m @ Vector((math.cos(phase + 2 * math.pi * i / seg) * r,
                                                      math.sin(phase + 2 * math.pi * i / seg) * r, z)) + c)
                          for i in range(seg)])
    out = []
    for k in range(len(rings) - 1):
        a, b = rings[k], rings[k + 1]
        mk = mats[k % len(mats)] if isinstance(mats, (list, tuple)) else mats
        idx = mb.slot(mk)
        for i in range(seg):
            j = (i + 1) % seg
            quad = (a[i], a[j], b[j], b[i])
            vs = []
            for v in quad:
                if v not in vs:
                    vs.append(v)
            if len(vs) < 3:
                continue
            try:
                f = mb.bm.faces.new(vs)
            except ValueError:
                continue
            f.material_index = idx
            out.append(f)
    for ring, rev, use, cm in ((rings[0], True, cap_bottom, cap_mats[0]), (rings[-1], False, cap_top, cap_mats[1])):
        if not use or ring[0] is ring[-1]:
            continue
        mk = cm if cm is not None else (mats[0] if isinstance(mats, (list, tuple)) else mats)
        try:
            f = mb.bm.faces.new(list(reversed(ring)) if rev else ring)
            f.material_index = mb.slot(mk)
            out.append(f)
        except ValueError:
            pass
    return out


def ball(mb, center, r, mat, seg=16, rings=8, scale=(1.0, 1.0, 1.0)):
    """Deterministic UV sphere (poles on Z) - use instead of MB.sphere, whose bmesh.ops.create_uvsphere produces a
    different loop order in every Blender process (-> non byte-identical GLBs)."""
    prof = [(math.sin(math.pi * k / rings) * r if 0 < k < rings else 0.0, -math.cos(math.pi * k / rings) * r)
            for k in range(rings + 1)]
    faces = revolve_mats(mb, prof, center=(0, 0, 0), seg=seg, axis="Z", mats=mat, cap_bottom=False, cap_top=False)
    seen = {}
    for f in faces:
        for v in f.verts:
            if v not in seen:
                seen[v] = True
    c = Vector(center)
    for v in seen:
        v.co = Vector((v.co.x * scale[0], v.co.y * scale[1], v.co.z * scale[2])) + c
    return faces


# ----------------------------------------------------------------------------------------------
# small mechanical details
# ----------------------------------------------------------------------------------------------
def quat_z_to(direction):
    return Vector((0, 0, 1)).rotation_difference(Vector(direction).normalized())


def bolt(mb, pos, normal, mat, r=0.012, h=0.008, seg=6):
    """Hex bolt head sitting on a surface (pos on the surface, normal = outward)."""
    n = Vector(normal).normalized()
    mb.cyl(Vector(pos) + n * (h / 2 - 0.002), r, h, seg=seg, axis="Z", mat=mat, rot=quat_z_to(n))


def bolt_ring(mb, center, axis_dir, radius, count, mat, r=0.012, h=0.008, phase=0.0):
    """Ring of bolts on a face with normal `axis_dir` around `center`."""
    n = Vector(axis_dir).normalized()
    q = quat_z_to(n)
    for i in range(count):
        a = phase + 2 * math.pi * i / count
        p = Vector(center) + q @ Vector((math.cos(a) * radius, math.sin(a) * radius, 0))
        bolt(mb, p, n, mat, r=r, h=h)


def tube(mb, center, r_out, r_in, length, mat_out, mat_in=None, axis="Y", rot=None, seg=16, bore_depth=None,
         bore_mat=None, lip=None):
    """Hollow launch tube / barrel along `axis`; mouth at +length/2.  The bore is closed at `bore_depth` by a
    disc (bore_mat) so it never looks through.  lip=(r, h) adds a reinforcing ring at the mouth."""
    h2 = length / 2
    depth = min(length * 0.8 if bore_depth is None else bore_depth, length - 0.004)
    mi = mat_in or mat_out
    # solid of revolution: back disc, outer wall, mouth annulus, bore wall, bore bottom (radius 0 ends are welded)
    prof = [(0.0, -h2), (r_out, -h2), (r_out, h2), (r_in, h2), (r_in, h2 - depth), (0.0, h2 - depth)]
    revolve_mats(mb, prof, center=center, seg=seg, axis=axis, rot=rot,
                 mats=[mat_out, mat_out, mat_out, mi, bore_mat or mi], cap_bottom=False, cap_top=False)
    if lip:
        lr, lh = lip
        m = rot_matrix(rot) @ mb._axis_matrix(axis)
        c = Vector(center) + m @ Vector((0, 0, h2 - lh / 2))
        lathe_closed(mb, [(r_out * 0.98, -lh / 2), (lr, -lh / 2), (lr, lh / 2), (r_out * 0.98, lh / 2)], center=c, seg=seg,
                     axis=axis, rot=rot, mat=mat_out)


def fan_blades(mb, center, r_hub, r_tip, n, mat, chord=(0.07, 0.05), pitch=(34.0, 16.0), thick=0.008, phase=0.0,
               sweep=0.0):
    """n twisted rotor blades around the local Z axis at `center` (blade root pitch -> tip pitch, degrees).
    sweep (radians) bends the tip backward along the rotation (scimitar blades)."""
    c = Vector(center)
    up = Vector((0, 0, 1))
    for i in range(n):
        a0 = phase + 2 * math.pi * i / n
        corners = []
        for (r, ch, pd, a) in ((r_hub, chord[0], pitch[0], a0), (r_tip, chord[1], pitch[1], a0 + sweep)):
            radial = Vector((math.cos(a), math.sin(a), 0))
            tang = Vector((-math.sin(a), math.cos(a), 0))
            p = math.radians(pd)
            d = tang * math.cos(p) + up * math.sin(p)
            nrm = (-tang * math.sin(p) + up * math.cos(p)) * (thick / 2)
            base = c + radial * r
            corners.append((base + d * ch / 2, base - d * ch / 2, nrm))
        (le0, te0, n0), (le1, te1, n1) = corners
        mb.hexa([te0 - n0, le0 - n0, le1 - n1, te1 - n1, te0 + n0, le0 + n0, le1 + n1, te1 + n1], mat)


def strip(mb, a, b, w, t, mat, normal=(0, 0, 1)):
    """Flat strip (stripe, seam, rail) from a to b lying on a surface with `normal`: width w across the surface,
    thickness t along the normal, centred on the segment a-b (so half of t is embedded when a/b are on the surface)."""
    a, b = Vector(a), Vector(b)
    d = (b - a).normalized()
    n = Vector(normal).normalized()
    s = d.cross(n)
    if s.length < 1e-6:
        s = d.orthogonal()
    s.normalize()
    n = s.cross(d).normalized()
    if n.dot(Vector(normal)) < 0:
        n = -n
    hw, ht = w / 2, t / 2
    mb.hexa([a - s * hw - n * ht, a + s * hw - n * ht, b + s * hw - n * ht, b - s * hw - n * ht,
             a - s * hw + n * ht, a + s * hw + n * ht, b + s * hw + n * ht, b - s * hw + n * ht], mat)


def quad_plate(mb, p0, p1, p2, p3, thick, mat, out):
    """Solid plate from 4 corners (any winding) extruded by `thick` toward `out` (world direction)."""
    p0, p1, p2, p3 = (Vector(p) for p in (p0, p1, p2, p3))
    n = (p1 - p0).cross(p3 - p0).normalized()
    if n.dot(Vector(out)) < 0:
        n = -n
    n = n * abs(thick)
    mb.hexa([p0, p1, p2, p3, p0 + n, p1 + n, p2 + n, p3 + n], mat)


def hazard_band(mb, a, b, z0, z1, out, mat, stripe=0.09, depth=0.006, slant=1.0, gap_ratio=1.0):
    """Diagonal hazard stripes (only the coloured stripes; the surface below provides the dark gaps) on a vertical
    face whose bottom edge runs from a to b (z0..z1 heights, face normal `out`).  Stripes lean by `slant`*height."""
    a = Vector((a[0], a[1], 0.0))
    b = Vector((b[0], b[1], 0.0))
    d = b - a
    L = d.length
    u = d.normalized()
    n = Vector(out).normalized()
    h = z1 - z0
    lean = h * slant
    pitch = stripe * (1.0 + gap_ratio)
    s = 0.0
    while s + stripe + lean <= L + 1e-6:
        q0 = a + u * s
        q1 = a + u * (s + stripe)
        q2 = a + u * (s + stripe + lean)
        q3 = a + u * (s + lean)
        pts = [Vector((q0.x, q0.y, z0)), Vector((q1.x, q1.y, z0)), Vector((q2.x, q2.y, z1)), Vector((q3.x, q3.y, z1))]
        quad_plate(mb, *[p - n * 0.002 for p in pts], depth, mat, n)
        s += pitch


def stripe_on_quad(mb, p0, p1, p2, p3, t0, t1, thick, mat, out):
    """Sub-strip of a quad (p0-p1 bottom edge, p3-p2 top edge) between fractions t0..t1 along p0->p1, raised by thick."""
    p0, p1, p2, p3 = (Vector(p) for p in (p0, p1, p2, p3))
    a0, a1 = p0.lerp(p1, t0), p0.lerp(p1, t1)
    b0, b1 = p3.lerp(p2, t0), p3.lerp(p2, t1)
    quad_plate(mb, a0, a1, b1, b0, thick, mat, out)


def lerp(a, b, t):
    return a + (b - a) * t


def mat_about(point, rot_deg):
    """4x4 matrix rotating by rot_deg (XYZ degrees) about a world point."""
    p = Vector(point)
    return Matrix.Translation(p) @ rot_matrix(rot_deg) @ Matrix.Translation(-p)


def mirror_list(points):
    return [V(-p[0], p[1], p[2]) for p in points]


def quat(axis, deg):
    return Quaternion(Vector(axis), math.radians(deg))


# ----------------------------------------------------------------------------------------------
# conforming armour plates on lofted shells (common.shell specs: [(z, wx, wy, y0), ...])
# ----------------------------------------------------------------------------------------------
def ring_pts2(wx, wy, x0=0.0, y0=0.0, n=8, sq=0.6, rot=22.5):
    """2D vertices of common.ring (faceted superellipse), CCW; vertex i at angle rot + 360*i/n (0 = +X, 90 = +Y)."""
    pts = []
    for i in range(n):
        a = math.radians(rot) + 2 * math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        pts.append(Vector((x0 + math.copysign(abs(c) ** sq, c) * wx, y0 + math.copysign(abs(s) ** sq, s) * wy)))
    return pts


def interp_spec(specs, z):
    specs = sorted(specs, key=lambda s: s[0])
    if z <= specs[0][0]:
        return tuple(specs[0])
    if z >= specs[-1][0]:
        return tuple(specs[-1])
    for a, b in zip(specs[:-1], specs[1:]):
        if a[0] <= z <= b[0]:
            t = (z - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
            return tuple(a[k] + (b[k] - a[k]) * t for k in range(4))
    return tuple(specs[-1])


def _edge_n(pts, i):
    n = len(pts)
    a, b = pts[i % n], pts[(i + 1) % n]
    d = (b - a).normalized()
    return Vector((d.y, -d.x))


def _sample(pts, t, t0, t1):
    """point + outward normal at polygon parameter t (vertex i at t = i)."""
    n = len(pts)
    fl = math.floor(t + 1e-9)
    f = t - fl
    i = int(fl) % n
    p = pts[i].lerp(pts[(i + 1) % n], f)
    if f < 1e-6:  # on a vertex
        if abs(t - t0) < 1e-6:
            nrm = _edge_n(pts, i)
        elif abs(t - t1) < 1e-6:
            nrm = _edge_n(pts, i - 1)
        else:
            a, b = _edge_n(pts, i - 1), _edge_n(pts, i)
            m = (a + b).normalized()
            nrm = m / max(0.35, m.dot(b))
    else:
        nrm = _edge_n(pts, i)
    return p, nrm


def shell_patch(mb, specs, t0, t1, z0, z1, thick, mat, inset=0.012, n=8, sq=0.6, rot=22.5, x0=0.0, xform_rot=None,
                center=(0, 0, 0), grow=0.0):
    """Armour plate that CONFORMS to a common.shell loft: polygon parameter range t0..t1 (vertex i of the ring at
    t = i; with rot=22.5, n=8: [0,1] front-right facet, [1,2] front, [2,3] front-left, [3,4] left side, [5,6] back,
    [7,8] right side), height range z0..z1.  Inner face sits `inset` inside the shell, outer face `thick` above it.
    grow widens the plate outline outward by `grow` metres at the outer face (chamfered-looking edges)."""
    specs = sorted(specs, key=lambda s: s[0])
    levels = [z0] + [s[0] for s in specs if z0 + 1e-6 < s[0] < z1 - 1e-6] + [z1]
    ts = [t0] + [float(k) for k in range(int(math.floor(t0)) + 1, int(math.ceil(t1)))
                 if t0 + 1e-6 < k < t1 - 1e-6] + [t1]
    sections = []
    for z in levels:
        _, wx, wy, y0 = interp_spec(specs, z)
        pts = ring_pts2(wx, wy, x0, y0, n, sq, rot)
        inner, outer = [], []
        for t in ts:
            p, nrm = _sample(pts, t, t0, t1)
            inner.append(Vector((p.x - nrm.x * inset, p.y - nrm.y * inset, z)))
            outer.append(Vector((p.x + nrm.x * (thick - inset), p.y + nrm.y * (thick - inset), z)))
        sections.append(inner + list(reversed(outer)))
    if xform_rot is None:
        return mb.loft(sections, mat=mat)
    c = Vector(center)
    return mb.loft([[p - c for p in s] for s in sections], mat=mat, rot=xform_rot, center=c)


def shell_point(specs, t, z, n=8, sq=0.6, rot=22.5, x0=0.0, off=0.0):
    """world point on a shell surface at polygon parameter t and height z (+ `off` along the outward normal),
    returns (point, normal3)."""
    _, wx, wy, y0 = interp_spec(specs, z)
    pts = ring_pts2(wx, wy, x0, y0, n, sq, rot)
    p, nrm = _sample(pts, t, t - 1, t + 1)
    nn = Vector((nrm.x, nrm.y, 0.0)).normalized()
    return Vector((p.x, p.y, z)) + nn * off, nn


def hazard_quad(mb, q0, q1, q2, q3, mat, out, n=5, lean=0.25, fill=0.5, depth=0.01):
    """Diagonal hazard stripes inside a planar quad (q0-q1 bottom edge, q3-q2 top edge).  n stripes leaning by `lean`
    (fraction of the width) bottom->top; fill = stripe/pitch ratio.  Raised by `depth` along `out`."""
    q = [Vector(p) for p in (q0, q1, q2, q3)]
    o = Vector(out).normalized()

    def bl(u, v):
        return q[0].lerp(q[1], u).lerp(q[3].lerp(q[2], u), v)

    pitch = (1.0 - lean) / (n - 1 + fill) if n > 1 else (1.0 - lean)
    w = pitch * fill
    for i in range(n):
        a = i * pitch
        pts = [bl(a, 0.0), bl(a + w, 0.0), bl(a + w + lean, 1.0), bl(a + lean, 1.0)]
        quad_plate(mb, *[p - o * 0.003 for p in pts], depth, mat, o)


# ----------------------------------------------------------------------------------------------
# assembling a node out of a bevelled "main" mesh and unbevelled "detail" meshes
# ----------------------------------------------------------------------------------------------
def assemble(name, pieces):
    """pieces: [(MB, bevel(w, seg) | None, sharp_angle_deg), ...].  Every piece becomes a temporary object with its own
    Bevel/WeightedNormal modifiers, the modifiers are applied and the pieces are joined into ONE mesh object `name`.
    This keeps triangle budgets sane (bolts, stripes, slats, lathed rings are not bevelled) while big forms stay crisp."""
    import bpy
    from common import apply_modifiers
    objs = []
    for k, (mb, bevel, sharp) in enumerate(pieces):
        if mb is None or len(mb.bm.faces) == 0:
            if mb is not None:
                mb.bm.free()
            continue
        o = mb.to_object(f"{name}__part{k}", bevel=bevel, sharp_angle=sharp)
        if o.modifiers:
            apply_modifiers(o)
        objs.append(o)
    target = objs[0]
    if len(objs) > 1:
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        for o in objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.join()
    target.name = name
    target.data.name = name
    return target

"""Car props: sedan (A), SUV (B), pickup (C).  One parametric builder: lofted body shell with real wheel arches / wheel
wells, cabin with recessed glass panes, separate wheel nodes (tyre + alloy hub), emissive head / tail lights, plates."""
from props_common import *          # noqa: F401,F403


def wheel_gmb(M, R, w, r_rim, seg=14, out=1):
    """One wheel centred on its axle (origin), spin axis X.  out=+1: outer face towards +X, -1: towards -X."""
    g = GMB(weld=False)
    sw = R - r_rim
    prof = [(r_rim, -0.44 * w), (r_rim + 0.28 * sw, -0.50 * w), (R - 0.08 * sw, -0.44 * w), (R, -0.26 * w),
            (R, 0.26 * w), (R - 0.08 * sw, 0.44 * w), (r_rim + 0.28 * sw, 0.50 * w), (r_rim, 0.44 * w)]
    add_revolve(g, prof, (0, 0, 0), M["tyre"], seg=seg, axis="X", close_loop=True)
    d = 0.5 * w - 0.045                                  # rim face plane
    hub = [(0.0, d + 0.022), (0.05, d + 0.022), (0.068, d), (0.72 * r_rim, d - 0.022), (r_rim, d - 0.008), (r_rim, -0.42 * w),
           (0.0, -0.42 * w)]
    add_revolve(g, hub, (0, 0, 0), M["alloy"], seg=12, axis="X", caps=False)
    for k in range(5):                                    # dark windows between the spokes
        th = math.radians(72.0 * k + 36.0)
        rr = 0.60 * r_rim
        add_box(g, (d - 0.020 + 0.004, -rr * math.sin(th), rr * math.cos(th)), (0.014, 0.055, 0.075), M["under"],
                rot=(math.degrees(th), 0, 0))
    if out < 0:
        g.transform(Matrix.Rotation(math.pi, 4, "Z"))
    return g


def interp_keys(keys, y):
    """Piecewise-linear interpolation of body station rows (y, hw, zb, zt, zs)."""
    if y <= keys[0][0]:
        return keys[0][1:]
    for a, b in zip(keys[:-1], keys[1:]):
        if a[0] <= y <= b[0]:
            t = 0.0 if b[0] == a[0] else (y - a[0]) / (b[0] - a[0])
            return tuple(a[i] + (b[i] - a[i]) * t for i in range(1, 5))
    return keys[-1][1:]


def body_section(y, hw, zb, zt, zs, za, w_in, tuck=0.012):
    P = [(w_in, zb), (w_in, za), (hw - tuck, za), (hw, max(zs, za + 0.03)), (hw - 0.02, zt - 0.07), (hw - 0.16, zt)]
    pts = P + [(-x, z) for (x, z) in reversed(P)]
    return [(x, y, z) for (x, z) in pts]


def build_car_body(M, spec):
    """Lofted body shell with real wheel arches / wheel wells."""
    keys = spec["keys"]
    w_in = spec["w_in"]
    R_a = spec["wheel_R"] + spec["arch_gap"]
    zc = spec["wheel_R"]
    axles = spec["axles"]
    def arch_z(y):
        """Height of the wheel arch ceiling at y (None outside every arch)."""
        for ya in axles:
            d = y - ya
            if abs(d) < R_a - 1e-9:
                return zc + math.sqrt(R_a * R_a - d * d)
        return None

    ys = set(round(k[0], 6) for k in keys)
    for ya in axles:
        for i in range(0, 9):
            ys.add(round(ya - R_a * math.cos(math.pi * i / 8.0), 6))
    stations = []
    for y in sorted(ys):
        stations.append((y, arch_z(y)))
    # duplicate stations at the arch start / end (one section without notch, one with): the loft makes the vertical arch legs
    extra = []
    for ya in axles:
        extra.append((round(ya - R_a, 6), "start"))
        extra.append((round(ya + R_a, 6), "end"))
    out = []
    for (y, za) in stations:
        tag = None
        for (ye, kind) in extra:
            if abs(y - ye) < 1e-6:
                tag = kind
        if tag == "start":
            out.append((y, None))
            out.append((y, zc))
        elif tag == "end":
            out.append((y, zc))
            out.append((y, None))
        else:
            out.append((y, za))
    secs = []
    for (y, za) in out:
        hw, zb, zt, zs = interp_keys(keys, y)
        secs.append(body_section(y, hw, zb, zt, zs, zb if za is None else max(za, zb), w_in))
    body = MB()
    body.loft(secs, mat=M[spec["paint"]], caps=True)
    body.finish()
    # drop zero-area slivers left by the notch start / end
    body.bm.normal_update()
    bad = [f for f in body.bm.faces if f.calc_area() < 1e-7]
    if bad:
        bmesh.ops.delete(body.bm, geom=bad, context="FACES")
    body.bm.normal_update()
    for f in body.bm.faces:
        c = f.calc_center_median()
        n = f.normal
        xs = [abs(v.co.x) for v in f.verts]
        if n.z < -0.35 or all(abs(x - w_in) < 1e-4 for x in xs):
            f.material_index = body.slot(M["under"])
        elif spec.get("sill_trim") and c.z < spec["sill_trim"] and abs(n.x) > 0.8:
            f.material_index = body.slot(M["trim"])
        elif spec.get("bed_y") is not None and c.y < spec["bed_y"] and n.z > 0.9 and abs(c.x) < 0.9:
            f.material_index = body.slot(M["trim"])
    return body


def cabin_mesh(M, spec, paint):
    """Greenhouse: loft between two chamfered rectangles (belt -> roof) built from planar quads; windshield, rear window and
    side panes are inset + recessed glass, the four corner facets stay painted (thick A / C pillars)."""
    c = spec["cabin"]
    g = GMB(weld=False)
    wb, wr, zb, zr = c["wb"], c["wr"], c["zb"] - 0.01, c["zr"]
    yfb, yrb, yfr, yrr = c["yfb"], c["yrb"], c["yfr"], c["yrr"]
    cb, ct = c["cb"], c["ct"]
    cen = (0.0, (yfb + yrb) / 2.0, (zb + zr) / 2.0)

    def outline(w, yf, yr, ch, z):
        return [(w - ch, yf, z), (w, yf - ch, z), (w, yr + ch, z), (w - ch, yr, z),
                (-w + ch, yr, z), (-w, yr + ch, z), (-w, yf - ch, z), (-w + ch, yf, z)]

    B = outline(wb, yfb, yrb, cb, zb)
    Tt = outline(wr, yfr, yrr, ct, zr)

    def quad(p, mat):
        return g.poly_out(p, cen, mat)

    # roof (n-gon)
    g.poly_out(Tt, cen, paint)
    panes = []
    # windshield: edge 7 -> 0 ; rear window: edge 3 -> 4
    panes.append(quad([B[7], B[0], Tt[0], Tt[7]], paint))
    panes.append(quad([B[3], B[4], Tt[4], Tt[3]], paint))
    # corner facets (painted)
    for (i, j) in ((0, 1), (2, 3), (4, 5), (6, 7)):
        quad([B[i], B[j], Tt[j], Tt[i]], paint)
    # side panes split by the pillars (bottom and top edges share the pillar y positions)
    yb0, yb1 = yfb - cb, yrb + cb
    yt0, yt1 = yfr - ct, yrr + ct
    eb = [yb0] + list(c["pillars"]) + [yb1]
    et = [yt0] + list(c["pillars"]) + [yt1]
    for sgn in (1, -1):
        for i in range(len(eb) - 1):
            panes.append(quad([(sgn * wb, eb[i], zb), (sgn * wb, eb[i + 1], zb), (sgn * wr, et[i + 1], zr), (sgn * wr, et[i], zr)], paint))
    bm = g.bm
    bm.normal_update()
    bmesh.ops.inset_individual(bm, faces=panes, thickness=c.get("frame", 0.05), depth=-0.014, use_even_offset=True)
    for f in panes:                      # the original faces are the recessed inner panes (the ring stays painted)
        f.material_index = g.slot(M["glass"])
    return g


def plate_quad(g, M, center, facing):
    """Licence plate panel (0.52 x 0.11) facing +Y (facing=+1: front plate) or -Y (rear plate)."""
    cx, cy, cz = center
    hw_, hh = 0.26, 0.055
    if facing > 0:      # normal +Y; viewed from +Y the image right is -X
        pts = [(cx + hw_, cy, cz - hh), (cx - hw_, cy, cz - hh), (cx - hw_, cy, cz + hh), (cx + hw_, cy, cz + hh)]
        uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
        return g.poly(pts, M["plate"], uv=uv)
    pts = [(cx - hw_, cy, cz - hh), (cx + hw_, cy, cz - hh), (cx + hw_, cy, cz + hh), (cx - hw_, cy, cz + hh)]
    uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
    return g.poly(pts, M["plate"], uv=uv)


def add_car_details(g, M, spec, paint):
    keys = spec["keys"]
    yF, yR = keys[-1][0], keys[0][0]
    hwF, zbF, ztF, _ = keys[-1][1:]
    hwR, zbR, ztR, _ = keys[0][1:]
    c = spec["cabin"]
    hw = spec["hw"]
    hF = ztF - zbF
    hR = ztR - zbR
    # ---- front fascia: lower valance, plate, grille, headlights
    add_rbox(g, (0, yF + 0.005, zbF + 0.06), (hwF * 1.9, 0.05, 0.12), M["trim"], r=0.012)
    plate_quad(g, M, (0, yF + 0.010, zbF + 0.20), +1)
    zg = ztF - 0.07
    add_rbox(g, (0, yF + 0.004, zg), (spec["grille_w"], 0.03, 0.10), M["trim"], r=0.01)
    add_box(g, (0, yF + 0.02, zg), (spec["grille_w"] - 0.06, 0.010, 0.020), M["chrome"])
    for s in (-1, 1):
        xh = s * spec["head_x"]
        add_rbox(g, (xh, yF - 0.030, ztF - 0.075), (0.40, 0.09, 0.12), M["trim"], r=0.012, rot=(0, 0, -s * spec["head_rot"]))
        add_rbox(g, (xh, yF - 0.030 + 0.046, ztF - 0.075), (0.36, 0.012, 0.09), M["headlight"], r=0.005,
                 rot=(0, 0, -s * spec["head_rot"]))
    # ---- rear: lower valance, plate, tail lights, exhaust
    add_rbox(g, (0, yR - 0.005, zbR + 0.06), (hwR * 1.9, 0.05, 0.12), M["trim"], r=0.012)
    plate_quad(g, M, (0, yR - 0.010, spec["plate_rear_z"]), -1)
    for s in (-1, 1):
        xt = s * spec["tail_x"]
        add_rbox(g, (xt, yR + 0.030, ztR - 0.08), (0.40, 0.09, 0.12), M["trim"], r=0.012, rot=(0, 0, s * spec["tail_rot"]))
        add_rbox(g, (xt, yR + 0.030 - 0.046, ztR - 0.08), (0.36, 0.012, 0.09), M["taillight"], r=0.005,
                 rot=(0, 0, s * spec["tail_rot"]))
    add_cyl(g, (0.52, yR - 0.04, zbR + 0.07), 0.035, 0.12, M["chrome"], seg=8, axis="Y")
    if spec.get("spoiler"):
        ys, zs_, ws = spec["spoiler"]
        add_rbox(g, (0, ys, zs_), (ws, 0.16, 0.035), paint, r=0.01, rot=(-8.0, 0, 0))
        for s_ in (-1, 1):
            add_rbox(g, (s_ * (ws / 2 - 0.05), ys, zs_ - 0.03), (0.04, 0.10, 0.04), M["trim"], r=0.006)
    # ---- mirrors
    ym = c["yfb"] - 0.26
    for s in (-1, 1):
        add_rbox(g, (s * (c["wb"] + 0.20), ym, c["zb"] + 0.06), (0.14, 0.10, 0.11), paint, r=0.02)
        add_box(g, (s * (c["wb"] + 0.08), ym + 0.02, c["zb"] + 0.02), (0.14, 0.05, 0.03), M["trim"])
    # ---- door handles + seams
    for s in (-1, 1):
        for yh in spec["handles"]:
            add_box(g, (s * (hw + 0.005), yh, c["zb"] - 0.10), (0.016, 0.14, 0.024), M["chrome"])
        for ys in spec["seams"]:
            add_box(g, (s * (hw + 0.002), ys, (c["zb"] + spec["seam_z0"]) / 2.0), (0.006, 0.008, c["zb"] - spec["seam_z0"] - 0.02),
                    M["under"])


SEDAN = dict(
    paint="paint_a", hw=0.91, w_in=0.60, wheel_R=0.33, wheel_w=0.225, rim=0.215, arch_gap=0.075, axles=(-1.35, 1.42), track=0.78,
    keys=[(-2.33, 0.66, 0.40, 0.84, 0.66), (-2.28, 0.76, 0.32, 0.92, 0.72), (-2.15, 0.83, 0.25, 0.98, 0.77),
          (-1.95, 0.875, 0.21, 1.00, 0.80), (-1.55, 0.905, 0.20, 0.995, 0.80), (-1.0, 0.91, 0.20, 0.98, 0.80),
          (0.95, 0.91, 0.20, 0.98, 0.80), (1.30, 0.91, 0.20, 0.96, 0.80), (1.75, 0.895, 0.21, 0.92, 0.78),
          (2.05, 0.86, 0.23, 0.89, 0.75), (2.22, 0.80, 0.29, 0.86, 0.71), (2.30, 0.73, 0.35, 0.83, 0.68),
          (2.33, 0.64, 0.40, 0.80, 0.64)],
    cabin=dict(yfb=0.92, yrb=-1.28, yfr=0.04, yrr=-0.80, zb=0.98, zr=1.45, wb=0.75, wr=0.62, cb=0.22, ct=0.18, pillars=[-0.20],
               frame=0.05),
    grille_w=0.80, head_x=0.56, head_rot=14.0, tail_x=0.58, tail_rot=12.0, plate_rear_z=0.62,
    handles=(0.50, -0.55), seams=(0.92, -0.20, -0.92), seam_z0=0.34, spoiler=(-2.02, 1.035, 1.20),
)


def suv_extras(g, M, spec, paint):
    c = spec["cabin"]
    # roof rails + cross bars
    for sgn in (-1, 1):
        add_rbox(g, (sgn * 0.56, (c["yfr"] + c["yrr"]) / 2.0 + 0.05, c["zr"] + 0.035), (0.045, c["yfr"] - c["yrr"] - 0.5, 0.05), M["trim"],
                 r=0.01)
        for yy in (c["yfr"] - 0.35, (c["yfr"] + c["yrr"]) / 2.0, c["yrr"] + 0.30):
            add_rbox(g, (sgn * 0.56, yy, c["zr"] + 0.012), (0.06, 0.06, 0.03), M["trim"], r=0.008)
    for yy in (c["yfr"] - 0.45, c["yrr"] + 0.40):
        add_rbox(g, (0, yy, c["zr"] + 0.075), (1.20, 0.04, 0.03), M["alu"], r=0.008)
    # running boards
    for sgn in (-1, 1):
        add_rbox(g, (sgn * (spec["hw"] + 0.04), 0.12, 0.36), (0.16, 1.78, 0.06), M["trim"], r=0.015)
    # rear mounted spare wheel (tyre + cover disc)
    R, w = 0.36, 0.24
    yS = spec["keys"][0][0] - 0.02 - w / 2.0
    tyre = [(0.16, -0.44 * w), (0.16 + 0.07, -0.5 * w), (R - 0.03, -0.44 * w), (R, -0.26 * w), (R, 0.26 * w), (R - 0.03, 0.44 * w),
            (0.16 + 0.07, 0.5 * w), (0.16, 0.44 * w)]
    add_revolve(g, tyre, (0, yS, 0.86), M["tyre"], seg=14, axis="Y", close_loop=True)
    add_cyl(g, (0, yS - w / 2.0 - 0.006, 0.86), 0.23, 0.02, M["trim"], seg=14, axis="Y")
    add_cyl(g, (0, yS - w / 2.0 - 0.02, 0.86), 0.06, 0.02, M["alloy"], seg=10, axis="Y")
    add_box(g, (0, spec["keys"][0][0] - 0.02, 0.86), (0.10, 0.05, 0.05), M["trim"])


def pickup_extras(g, M, spec, paint):
    c = spec["cabin"]
    hw = spec["hw"]
    yb0, yb1 = 0.02, spec["keys"][0][0] + 0.02             # bed from the cab back wall to the tailgate
    floor = 0.985
    wall_h = 0.30
    L = yb0 - yb1
    yc = (yb0 + yb1) / 2.0
    for sgn in (-1, 1):
        add_rbox(g, (sgn * (hw - 0.05), yc, floor + wall_h / 2.0 - 0.03), (0.10, L, wall_h + 0.06), paint, r=0.02)
        add_rbox(g, (sgn * (hw - 0.05), yc, floor + wall_h + 0.005), (0.13, L, 0.04), M["alu"], r=0.012)     # bed rail cap
        add_rbox(g, (sgn * 0.80, spec["axles"][0], floor + 0.07), (0.20, 0.90, 0.14), M["trim"], r=0.03)      # wheel houses
    add_rbox(g, (0, yb0 - 0.045, floor + wall_h / 2.0 + 0.02), (2 * hw - 0.2, 0.09, wall_h + 0.08), paint, r=0.02)   # front wall
    add_rbox(g, (0, yb1 + 0.035, floor + wall_h / 2.0 - 0.02), (2 * hw - 0.12, 0.07, wall_h + 0.02), paint, r=0.02)   # tailgate
    add_rbox(g, (0, yb1 + 0.035 - 0.038, floor + wall_h - 0.04), (0.50, 0.02, 0.05), M["chrome"], r=0.008)          # handle
    add_rbox(g, (0, spec["keys"][0][0] - 0.02, 0.44), (1.92, 0.16, 0.13), M["chrome"], r=0.03)                      # step bumper
    # roof beacon + light bar
    add_rbox(g, (0, (c["yfr"] + c["yrr"]) / 2.0, c["zr"] + 0.03), (0.34, 0.16, 0.06), M["trim"], r=0.015)
    add_cyl(g, (0, (c["yfr"] + c["yrr"]) / 2.0, c["zr"] + 0.11), 0.07, 0.10, M["amber_lens"], seg=10, r_top=0.055)
    for sgn in (-1, 1):
        add_rbox(g, (sgn * (hw + 0.04), 0.60, 0.36), (0.16, 0.86, 0.06), M["trim"], r=0.015)                          # side steps


SUV = dict(
    paint="paint_b", hw=0.965, w_in=0.66, wheel_R=0.385, wheel_w=0.26, rim=0.25, arch_gap=0.08, axles=(-1.30, 1.55), track=0.83,
    keys=[(-2.42, 0.84, 0.44, 1.08, 0.90), (-2.36, 0.90, 0.34, 1.12, 0.92), (-2.20, 0.945, 0.29, 1.14, 0.94),
          (-1.90, 0.965, 0.27, 1.14, 0.95), (-1.0, 0.965, 0.27, 1.14, 0.95), (1.10, 0.965, 0.27, 1.14, 0.95),
          (1.45, 0.965, 0.27, 1.12, 0.95), (2.00, 0.95, 0.28, 1.05, 0.91), (2.25, 0.91, 0.32, 1.00, 0.86),
          (2.36, 0.85, 0.40, 0.96, 0.82), (2.43, 0.76, 0.48, 0.92, 0.78)],
    cabin=dict(yfb=1.10, yrb=-2.36, yfr=0.62, yrr=-2.28, zb=1.14, zr=1.84, wb=0.84, wr=0.75, cb=0.22, ct=0.18,
               pillars=[-0.35, -1.35], frame=0.055),
    grille_w=0.84, head_x=0.60, head_rot=10.0, tail_x=0.66, tail_rot=8.0, plate_rear_z=0.74,
    handles=(0.30, -0.75), seams=(1.02, -0.35, -1.35, -2.02), seam_z0=0.42, sill_trim=0.50, extras=[suv_extras],
)

PICKUP = dict(
    paint="paint_c", hw=0.965, w_in=0.66, wheel_R=0.375, wheel_w=0.265, rim=0.24, arch_gap=0.08, axles=(-1.55, 1.55), track=0.83,
    keys=[(-2.68, 0.88, 0.46, 0.94, 0.80), (-2.62, 0.93, 0.36, 0.97, 0.84), (-2.45, 0.96, 0.29, 0.99, 0.88),
          (-2.0, 0.965, 0.28, 1.00, 0.90), (-0.2, 0.965, 0.28, 1.00, 0.90), (0.10, 0.965, 0.28, 1.06, 0.90),
          (0.95, 0.965, 0.28, 1.10, 0.92), (1.55, 0.965, 0.28, 1.10, 0.92), (2.05, 0.95, 0.29, 1.02, 0.88),
          (2.35, 0.90, 0.33, 0.97, 0.84), (2.55, 0.84, 0.42, 0.93, 0.78), (2.66, 0.76, 0.50, 0.90, 0.74)],
    cabin=dict(yfb=1.50, yrb=0.06, yfr=0.98, yrr=0.30, zb=1.10, zr=1.80, wb=0.84, wr=0.76, cb=0.20, ct=0.18, pillars=[0.72],
               frame=0.055),
    grille_w=0.86, head_x=0.60, head_rot=10.0, tail_x=0.80, tail_rot=0.0, plate_rear_z=0.66,
    handles=(1.00, 0.45), seams=(1.42, 0.72, 0.10), seam_z0=0.42, sill_trim=0.50, bed_y=0.0, extras=[pickup_extras],
)


def mark_bevel_edges(g, n_shell_faces, angle_deg=35.0):
    """Give bevel weight 1.0 to the sharp edges of the first `n_shell_faces` faces (body shell + cabin) only, so that the Bevel
    modifier (limit method WEIGHT) rounds the important panel edges without multiplying the triangles of the small details."""
    bm = g.bm
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    lay = bm.edges.layers.float.get("bevel_weight_edge") or bm.edges.layers.float.new("bevel_weight_edge")
    lim = math.radians(angle_deg)
    n = 0
    for i in range(n_shell_faces):
        f = bm.faces[i]
        for e in f.edges:
            if len(e.link_faces) == 2 and e[lay] == 0.0:
                a, b = e.link_faces
                if a.index < n_shell_faces and b.index < n_shell_faces and e.calc_face_angle(0.0) > lim:
                    e[lay] = 1.0
                    n += 1
    return n


def build_car(M, spec, root_name, tag):
    r = new_root(root_name)
    paint = M[spec["paint"]]
    body = build_car_body(M, spec)
    g = GMB(weld=False)
    g.merge_into(body)
    body.bm.free()
    cab = cabin_mesh(M, spec, paint)
    g.merge_into(cab)
    cab.bm.free()
    n_shell = len(g.bm.faces)
    add_car_details(g, M, spec, paint)
    for fn in spec.get("extras", []):
        fn(g, M, spec, paint)
    bevel = spec.get("bevel")             # e.g. (0.012, 1): weight-limited bevel of the shell edges (+~500 tris per car) - off by default
    if bevel:
        g.bm.faces.index_update()
        mark_bevel_edges(g, n_shell)
    obj = finish(g, f"Car{tag}_Body", r, bevel=bevel, sharp=40.0)
    if bevel:
        obj.modifiers["Bevel"].limit_method = "WEIGHT"
    axles = spec["axles"]
    for name_y, ya in (("F", axles[1]), ("R", axles[0])):
        for side_name, side in (("L", -1), ("R", 1)):
            wg = wheel_gmb(M, spec["wheel_R"], spec["wheel_w"], spec["rim"], seg=12, out=side)
            finish(wg, f"Car{tag}_Wheel_{name_y}{side_name}", r, loc=(side * spec["track"], ya, spec["wheel_R"]))
    return r


def build_car_a(M):
    return build_car(M, SEDAN, "Prop_Car_A", "A")


def build_car_b(M):
    return build_car(M, SUV, "Prop_Car_B", "B")


def build_car_c(M):
    return build_car(M, PICKUP, "Prop_Car_C", "C")

"""Rooftop props: antenna mast, AC units A / B, vent stack, roof access bulkhead, cooling tower, solar array."""
from props_common import *          # noqa: F401,F403


def T(x, y, z):
    return Matrix.Translation((x, y, z))


def to_axis(axis):
    """Matrix taking a local +Z-up part to point along +Y (front) or stay +Z."""
    if axis == "Y":
        return Matrix.Rotation(math.radians(-90.0), 4, "X")
    if axis == "-Y":
        return Matrix.Rotation(math.radians(90.0), 4, "X")
    return Matrix.Identity(4)


def fan_gmb(M, r, blades=5, hub=0.07, shroud=True, guard=True, seg=12, dark=None, metal=None):
    """Axial fan facing local +Z: shroud ring, dark fan blades on a hub, guard spokes + ring."""
    dark = dark or M["fan_dark"]
    metal = metal or M["galv"]
    g = GMB(weld=False)
    if shroud:
        add_revolve(g, [(r + 0.012, 0.0), (r + 0.03, 0.0), (r + 0.03, 0.10), (r + 0.012, 0.10), (r - 0.005, 0.085), (r - 0.005, 0.0)],
                    (0, 0, 0), metal, seg=seg, axis="Z", close_loop=True)
    add_cyl(g, (0, 0, 0.055), hub, 0.06, dark, seg=10)
    for k in range(blades):
        th = 2 * math.pi * k / blades
        rm = (hub + r * 0.86) / 2.0
        c = (rm * math.cos(th), rm * math.sin(th), 0.055)
        add_box(g, c, (r * 0.86 - hub, 0.10, 0.012), dark, rot=(22.0, 0.0, math.degrees(th)))
    if guard:
        for k in range(6):
            th = 2 * math.pi * k / 6 + math.pi / 6
            rm = r * 0.5
            add_box(g, (rm * math.cos(th), rm * math.sin(th), 0.105), (r * 1.0, 0.016, 0.014), metal, rot=(0, 0, math.degrees(th)))
        for rr in (0.62,):
            add_revolve(g, [(r * rr - 0.008, 0.098), (r * rr + 0.008, 0.098), (r * rr + 0.008, 0.114), (r * rr - 0.008, 0.114)],
                        (0, 0, 0), metal, seg=seg, axis="Z", close_loop=True)
    return g


def louvres(g, center, size, n, mat, tilt=28.0, axis="Y", sgn=1):
    """n horizontal louvre slats filling a panel of `size` (w, h) on a face whose normal is +/-Y (axis 'Y') or +/-X ('X')."""
    cx, cy, cz = center
    w, h = size
    for i in range(n):
        z = cz - h / 2.0 + h * (i + 0.5) / n
        if axis == "Y":
            add_box(g, (cx, cy, z), (w, 0.030, 0.026), mat, rot=(sgn * tilt, 0, 0))
        else:
            add_box(g, (cx, cy, z), (0.030, w, 0.026), mat, rot=(0, -sgn * tilt, 0))


# ----------------------------------------------------------------------------------------------------
# Prop_AC_Unit_A : rooftop packaged unit (single big top fan, louvred service face, refrigerant lines)
# ----------------------------------------------------------------------------------------------------
def build_ac_a(M):
    r = new_root("Prop_AC_Unit_A")
    g = GMB(weld=False)
    paint, dark, metal = M["unit_a"], M["steel_dark"], M["galv"]
    # base rails + cross ties
    for sy in (-1, 1):
        add_rbox(g, (0, sy * 0.46, 0.07), (2.44, 0.10, 0.14), dark, r=0.012, bottom=False)
    for sx in (-1.0, 0.0, 1.0):
        add_box(g, (sx, 0, 0.05), (0.08, 1.0, 0.08), dark, bottom=False)
    # cabinet + lid
    add_rbox(g, (0, 0, 0.14 + 0.44), (2.20, 1.20, 0.88), paint, r=0.035, seg=1)
    add_rbox(g, (0, 0, 1.055), (2.26, 1.26, 0.05), paint, r=0.015)
    for sx in (-1, 1):                                     # lid edge reinforcement + lifting lugs
        add_box(g, (sx * 1.08, 0.0, 1.10), (0.06, 0.5, 0.05), dark)
    # fan (offset towards -X)
    fan = fan_gmb(M, 0.44, blades=6, hub=0.07)
    g.merge_into(fan, T(-0.45, 0.0, 1.075))
    fan.bm.free()
    # second, smaller exhaust cap on the +X side of the lid
    add_cyl(g, (0.62, 0.0, 1.12), 0.20, 0.09, metal, seg=12, r_top=0.17)
    add_cyl(g, (0.62, 0.0, 1.185), 0.24, 0.03, dark, seg=12)
    # +Y service face: recessed louvre panel + latches + data plate
    add_rbox(g, (-0.35, 0.612, 0.62), (1.10, 0.03, 0.56), dark, r=0.008)
    louvres(g, (-0.35, 0.632, 0.62), (1.02, 0.50), 11, metal)
    for sx in (-1, 1):
        add_rbox(g, (-0.35 + sx * 0.66, 0.622, 0.62), (0.05, 0.03, 0.12), M["chrome"], r=0.008)
    add_box(g, (0.62, 0.606, 0.72), (0.34, 0.012, 0.18), M["paint_white"])
    add_box(g, (0.62, 0.606, 0.42), (0.34, 0.012, 0.12), M["paint_yellow"])
    # -Y face: coil grille (fine slats)
    louvres(g, (0, -0.618, 0.60), (2.0, 0.62), 14, dark, tilt=-20.0, sgn=1)
    # +X end: compressor access with louvres + refrigerant lines dropping to the roof
    add_rbox(g, (1.112, 0.0, 0.60), (0.03, 0.90, 0.60), dark, r=0.008)
    louvres(g, (1.132, 0.0, 0.60), (0.80, 0.52), 9, metal, axis="X")
    for i, yy in enumerate((-0.12, 0.12)):
        pts = [(1.14, yy, 0.30), (1.32, yy, 0.30), (1.46, yy, 0.22), (1.52, yy, 0.08)]
        add_tube(g, pts, 0.032 if i == 0 else 0.022, M["steel_dark"] if i == 0 else M["galv"], seg=6)
    # -X end: electrical disconnect box + conduit
    add_rbox(g, (-1.185, -0.30, 0.66), (0.14, 0.26, 0.34), M["paint_yellow"], r=0.015)
    add_box(g, (-1.262, -0.30, 0.66), (0.012, 0.20, 0.28), dark)
    add_tube(g, [(-1.185, -0.30, 0.49), (-1.185, -0.30, 0.20), (-1.30, -0.30, 0.10)], 0.018, dark, seg=6)
    finish(g, "ACUnitA_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_AC_Unit_B : twin-fan condenser bank on a stand (side discharge fans face +Y)
# ----------------------------------------------------------------------------------------------------
def build_ac_b(M):
    r = new_root("Prop_AC_Unit_B")
    g = GMB(weld=False)
    paint, dark, metal = M["unit_b"], M["steel_dark"], M["galv"]
    # steel stand
    for sx in (-0.95, 0.95):
        for sy in (-0.34, 0.34):
            add_rbox(g, (sx, sy, 0.16), (0.10, 0.10, 0.32), dark, r=0.01, bottom=False)
    for sy in (-0.34, 0.34):
        add_rbox(g, (0, sy, 0.33), (2.16, 0.08, 0.06), dark, r=0.01)
    # casing with corner posts
    add_rbox(g, (0, 0, 0.36 + 0.60), (2.10, 0.86, 1.20), paint, r=0.03)
    for sx in (-1, 1):
        for sy in (-1, 1):
            add_box(g, (sx * 1.06, sy * 0.44, 0.96), (0.07, 0.07, 1.22), dark)
    add_rbox(g, (0, 0, 1.585), (2.16, 0.92, 0.05), dark, r=0.012)
    # two side-discharge fans on the +Y face
    for sx in (-0.52, 0.52):
        add_rbox(g, (sx, 0.435, 0.96), (0.98, 0.03, 0.98), dark, r=0.01)
        fan = fan_gmb(M, 0.40, blades=5, hub=0.07)
        g.merge_into(fan, T(sx, 0.45, 0.96) @ to_axis("Y"))
        fan.bm.free()
    # coil louvres on the back and both ends
    louvres(g, (0, -0.445, 0.96), (1.86, 1.02), 10, dark, tilt=-20.0, sgn=1)
    for sx in (-1, 1):
        louvres(g, (sx * 1.07, 0.0, 0.96), (0.66, 1.02), 6, dark, axis="X", sgn=sx)
    finish(g, "ACUnitB_Body", r)
    return r

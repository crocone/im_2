"""Rooftop props (part 2): antenna mast, vent stack, roof access bulkhead, cooling tower, solar array."""
from props_common import *          # noqa: F401,F403
from props_rooftop import T, to_axis, fan_gmb, louvres


# ----------------------------------------------------------------------------------------------------
# Prop_Antenna : 15 m triangular lattice mast (red / white aviation bands), sector panels, cross arm,
#                microwave dish facing +Y, whip and red beacon (+ equipment cabinet at the foot)
# ----------------------------------------------------------------------------------------------------
def build_antenna(M):
    r = new_root("Prop_Antenna")
    g = GMB(weld=False)
    steel, dark, red, white = M["galv"], M["steel_dark"], M["paint_red"], M["paint_white"]
    heights = (1.85, 1.80, 1.74, 1.68, 1.62, 1.55, 1.48, 1.40, 1.32)
    zs = [0.30]
    for h in heights:
        zs.append(zs[-1] + h)
    n = len(zs) - 1
    r_bot, r_top = 0.80, 0.30

    def rad(z):
        return r_bot + (r_top - r_bot) * (z - zs[0]) / (zs[-1] - zs[0])

    def leg(k, z):
        a = math.radians(90 + 120 * k)
        return (rad(z) * math.cos(a), rad(z) * math.sin(a), z)

    # base plate + concrete feet
    tri = [(1.02 * math.cos(math.radians(90 + 120 * k)), 1.02 * math.sin(math.radians(90 + 120 * k))) for k in range(3)]
    sub = MB()
    sub.prism(tri, 0.20, 0.28, mat=dark)
    add_closed(g, sub)
    for k in range(3):
        a = math.radians(90 + 120 * k)
        add_rbox(g, (0.80 * math.cos(a), 0.80 * math.sin(a), 0.10), (0.44, 0.44, 0.20), M["concrete_dark"], r=0.03, bottom=False)
    # lattice
    for i in range(n):
        band = red if (i >= 4 and i % 2 == 0) else (white if i >= 4 else steel)
        tl = 0.040 if i < 5 else 0.032
        for k in range(3):
            add_strut(g, leg(k, zs[i]), leg(k, zs[i + 1]), tl, band, 5)
            k2 = (k + 1) % 3
            if (i + k) % 2 == 0:
                add_strut(g, leg(k, zs[i]), leg(k2, zs[i + 1]), 0.016, steel, 4)
            else:
                add_strut(g, leg(k2, zs[i]), leg(k, zs[i + 1]), 0.016, steel, 4)
    for i in range(n + 1):
        for k in range(3):
            add_strut(g, leg(k, zs[i]), leg((k + 1) % 3, zs[i]), 0.020, steel, 4)
    # tier A (z ~ 9): three sector panel antennas between the legs
    zA = zs[5] + 0.05
    for k in range(3):
        a_deg = 90 + 120 * k + 60
        a = math.radians(a_deg)
        rr = 0.5 * rad(zA) + 0.27
        add_rbox(g, (rr * math.cos(a), rr * math.sin(a), zA), (0.24, 0.07, 1.15), white, r=0.012, rot=(0, 0, a_deg - 90))
        r0 = 0.5 * rad(zA)
        for dz in (-0.40, 0.40):
            add_strut(g, (r0 * math.cos(a), r0 * math.sin(a), zA + dz), ((rr - 0.04) * math.cos(a), (rr - 0.04) * math.sin(a), zA + dz),
                      0.016, steel, 4)
    # tier B (z ~ 12): cross arm with whip antennas + microwave dish on the front leg
    zB = zs[7]
    add_strut(g, (-1.25, 0.0, zB), (1.25, 0.0, zB), 0.035, steel, 6)
    for sx in (-1, 1):
        add_strut(g, (sx * 1.25, 0.0, zB - 0.05), (sx * 1.25, 0.0, zB + 1.35), 0.014, dark, 4)
        add_strut(g, (sx * 0.30, 0.0, zB - 0.45), (sx * 1.20, 0.0, zB - 0.02), 0.018, steel, 4)
    yD = rad(zB) + 0.72
    zD = zB + 0.05
    prof = [(0.0, 0.0), (0.09, 0.004), (0.18, 0.017), (0.27, 0.040), (0.36, 0.072), (0.45, 0.113), (0.45, 0.130), (0.36, 0.089),
            (0.27, 0.057), (0.18, 0.034), (0.09, 0.019), (0.0, 0.015)]
    add_revolve(g, prof, (0, yD, zD), white, seg=16, axis="Y")
    add_strut(g, (0, yD + 0.13, zD), (0, yD + 0.44, zD), 0.012, dark, 4)                                # feed boom
    add_cyl(g, (0, yD + 0.46, zD), 0.035, 0.07, dark, seg=8, axis="Y")
    add_strut(g, (0, yD - 0.02, zD - 0.55), (0, yD - 0.02, zD + 0.55), 0.035, steel, 6)              # mounting pipe
    for zz in (zD - 0.42, zD + 0.42):
        add_strut(g, leg(0, zB + (zz - zD)), (0, yD - 0.02, zz), 0.024, steel, 5)
    # second, smaller dish on the left side of the mast (opens towards -X)
    zE = zs[6]
    xE = -(rad(zE) + 0.62)
    prof2 = [(0.0, 0.0), (0.075, 0.003), (0.15, 0.013), (0.225, 0.030), (0.30, 0.056), (0.30, 0.070), (0.225, 0.043), (0.15, 0.024),
             (0.075, 0.014), (0.0, 0.010)]
    add_revolve(g, prof2, (xE, 0.0, zE), white, seg=14, axis="X", rot=(0, 0, 180))
    add_strut(g, (xE + 0.09, 0.0, zE), (xE + 0.36, 0.0, zE), 0.010, dark, 4)
    add_strut(g, (xE - 0.03, 0.0, zE - 0.40), (xE - 0.03, 0.0, zE + 0.40), 0.03, steel, 6)
    for zz in (zE - 0.32, zE + 0.32):
        add_strut(g, leg(2, zz), (xE - 0.03, 0.0, zz), 0.02, steel, 5)
    # tier C (z ~ 13.4): short arm with two small panels
    zC = zs[8]
    add_strut(g, (-0.85, 0.0, zC), (0.85, 0.0, zC), 0.028, steel, 5)
    for sx in (-1, 1):
        add_rbox(g, (sx * 0.85, 0.06, zC + 0.05), (0.14, 0.05, 0.60), white, r=0.01)
    # whip + beacons
    zt = zs[-1]
    add_strut(g, (0, 0, zt), (0, 0, zt + 1.55), 0.014, steel, 6)
    add_cyl(g, (0, 0, zt + 1.60), 0.075, 0.12, dark, seg=10)
    add_sphere(g, (0, 0, zt + 1.74), 0.15, M["beacon_red"], seg=10, rings=7)
    add_sphere(g, (0, rad(zs[5]) + 0.12, zs[5]), 0.10, M["beacon_red"], seg=8, rings=6)
    add_rbox(g, (0, rad(zs[5]) + 0.06, zs[5]), (0.10, 0.10, 0.06), dark, r=0.008)
    # equipment cabinet + cable run at the foot
    add_rbox(g, (1.35, -0.25, 0.55), (0.80, 0.55, 1.10), M["unit_a"], r=0.025, bottom=False)
    add_box(g, (1.35, 0.03, 0.55), (0.60, 0.012, 0.86), dark)
    add_rbox(g, (1.35, -0.25, 1.13), (0.86, 0.60, 0.05), dark, r=0.01)
    add_tube(g, [(0.95, -0.2, 0.9), (0.7, -0.15, 0.9), (0.45, 0.0, 0.7), (0.35, 0.05, 1.6)], 0.02, dark, seg=6)
    finish(g, "Antenna_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_Vent_Stack : exhaust stack with rain cap, gooseneck, turbine vent, roof curb
# ----------------------------------------------------------------------------------------------------
def build_vent(M):
    r = new_root("Prop_Vent_Stack")
    g = GMB(weld=False)
    galv, dark, conc = M["galv"], M["steel_dark"], M["concrete_dark"]
    add_rbox(g, (0, 0, 0.16), (2.10, 1.40, 0.32), conc, r=0.03, bottom=False)                  # roof curb / flashing
    add_rbox(g, (0, 0, 0.34), (1.90, 1.20, 0.05), dark, r=0.01)
    # main stack with flanges and rain cap on posts
    x0 = -0.55
    add_cyl(g, (x0, 0, 1.72), 0.27, 2.8, galv, seg=14)
    for zz, rr in ((0.45, 0.35), (1.35, 0.30), (2.35, 0.30), (3.05, 0.31)):
        add_cyl(g, (x0, 0, zz), rr, 0.06, dark, seg=14)
    for k in range(3):
        a = 2 * math.pi * k / 3 + 0.4
        add_strut(g, (x0 + 0.22 * math.cos(a), 0.22 * math.sin(a), 3.06), (x0 + 0.22 * math.cos(a), 0.22 * math.sin(a), 3.34), 0.025, dark, 5)
    add_cyl(g, (x0, 0, 3.47), 0.48, 0.26, galv, seg=14, r_top=0.05)                                 # cone cap
    add_cyl(g, (x0, 0, 3.61), 0.06, 0.05, dark, seg=8)
    for zz in (0.9, 2.0):
        add_cyl(g, (x0, 0, zz), 0.285, 0.05, dark, seg=14)
    # gooseneck vent
    path = bezier((0.45, 0.22, 0.34), (0.45, 0.22, 1.9), (0.45, 0.95, 2.05), (0.45, 0.95, 1.30), 14)
    add_tube(g, path, 0.12, galv, seg=10)
    add_cyl(g, (0.45, 0.95, 1.16), 0.20, 0.22, galv, seg=10, r_top=0.12)                             # flared mouth (downwards)
    add_cyl(g, (0.45, 0.22, 0.42), 0.19, 0.10, dark, seg=10)
    # turbine vent (whirlybird) on a short riser
    tx, ty = 0.62, -0.38
    add_cyl(g, (tx, ty, 0.75), 0.11, 0.85, galv, seg=10)
    add_cyl(g, (tx, ty, 0.42), 0.17, 0.06, dark, seg=10)
    add_revolve(g, [(0.0, 1.16), (0.13, 1.19), (0.25, 1.26), (0.30, 1.40), (0.27, 1.55), (0.14, 1.66), (0.0, 1.69)],
                (tx, ty, 0.0), galv, seg=12, axis="Z")
    for k in range(10):
        a = 2 * math.pi * k / 10
        add_box(g, (tx + 0.285 * math.cos(a), ty + 0.285 * math.sin(a), 1.42), (0.02, 0.15, 0.36), dark,
                rot=(0, 0, math.degrees(a) + 35.0))
    # small B-vent with hat
    px, py = 0.35, -0.45
    add_cyl(g, (px, py, 0.90), 0.05, 1.0, galv, seg=8)
    add_cyl(g, (px, py, 1.50), 0.13, 0.06, dark, seg=8, r_top=0.03)
    # guy / brace to the curb
    add_strut(g, (x0 + 0.24, 0.12, 2.35), (0.85, 0.55, 0.36), 0.02, dark, 5)
    add_strut(g, (x0 - 0.24, -0.12, 2.35), (-0.95, -0.55, 0.36), 0.02, dark, 5)
    finish(g, "VentStack_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_Roof_Access : stair bulkhead 3.0 x 3.0 x 2.6 m with door, canopy, louvre and roof details
# ----------------------------------------------------------------------------------------------------
def build_roof_access(M):
    r = new_root("Prop_Roof_Access")
    g = GMB(weld=False)
    plaster, conc, dark, steel = M["plaster"], M["concrete_dark"], M["steel_dark"], M["galv"]
    add_rbox(g, (0, 0, 0.09), (2.96, 2.96, 0.18), conc, r=0.02, bottom=False)                        # plinth
    add_rbox(g, (0, 0, 1.26), (2.80, 2.80, 2.16), plaster, r=0.025, seg=1)                            # walls
    add_rbox(g, (0, 0, 2.47), (3.00, 3.00, 0.26), conc, r=0.03, seg=1)                                # roof slab with overhang
    add_rbox(g, (0, 0, 2.62), (2.76, 2.76, 0.06), M["asphalt"], r=0.01)                               # roofing membrane
    # +Y face: door with frame, kick plate, handle, canopy, lamp
    add_rbox(g, (0.0, 1.415, 1.12), (1.20, 0.05, 2.14), dark, r=0.012)                                # frame
    add_rbox(g, (0.0, 1.435, 1.08), (1.00, 0.05, 2.02), M["steel"], r=0.012)                          # door leaf
    add_box(g, (0.0, 1.462, 1.55), (0.80, 0.008, 0.50), dark)                                          # door window / louvre panel
    add_rbox(g, (0.32, 1.47, 1.02), (0.05, 0.05, 0.28), M["chrome"], r=0.01)                           # handle
    add_box(g, (0.0, 1.465, 0.16), (0.90, 0.008, 0.26), dark)                                          # kick plate
    add_rbox(g, (0.0, 1.70, 2.28), (1.70, 0.62, 0.07), conc, r=0.015, rot=(-7.0, 0, 0))               # canopy
    for sx in (-1, 1):
        add_strut(g, (sx * 0.70, 1.42, 2.18), (sx * 0.70, 1.86, 2.30), 0.02, dark, 5)
    add_rbox(g, (0.85, 1.46, 2.02), (0.16, 0.10, 0.12), M["lamp_glow"], r=0.015)                       # wall lamp (emissive)
    # +X face: louvre vent
    add_rbox(g, (1.415, -0.3, 1.45), (0.05, 1.0, 0.85), dark, r=0.008)
    louvres(g, (1.44, -0.3, 1.45), (0.92, 0.78), 8, steel, axis="X")
    # -X face: pipe run + gas meter box
    add_rbox(g, (-1.43, 0.6, 0.85), (0.08, 0.60, 0.70), M["paint_yellow"], r=0.01)
    add_tube(g, [(-1.40, 0.6, 1.20), (-1.40, 0.6, 2.30), (-1.20, 0.6, 2.62)], 0.03, dark, seg=6)
    # roof: exhaust cap, antenna stub, hatch
    add_rbox(g, (-0.7, -0.6, 2.78), (0.42, 0.42, 0.28), steel, r=0.02)
    add_cyl(g, (-0.7, -0.6, 2.95), 0.26, 0.05, dark, seg=10, r_top=0.30)
    add_strut(g, (0.85, -0.85, 2.65), (0.85, -0.85, 3.05), 0.02, dark, 5)
    add_rbox(g, (0.7, 0.4, 2.78), (0.6, 0.6, 0.20), plaster, r=0.02)
    finish(g, "RoofAccess_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_Cooling_Tower : louvred counterflow tower with fan stack, pipes, ladder
# ----------------------------------------------------------------------------------------------------
def build_cooling_tower(M):
    r = new_root("Prop_Cooling_Tower")
    g = GMB(weld=False)
    body, conc, dark, steel = M["tower"], M["concrete_dark"], M["steel_dark"], M["galv"]
    add_rbox(g, (0, 0, 0.22), (3.70, 3.70, 0.44), conc, r=0.03, bottom=False)                        # basin
    add_rbox(g, (0, 0, 0.47), (3.50, 3.50, 0.10), dark, r=0.012)
    add_rbox(g, (0, 0, 1.68), (3.30, 3.30, 2.32), body, r=0.03)                                        # casing
    for sx in (-1, 1):
        for sy in (-1, 1):
            add_rbox(g, (sx * 1.62, sy * 1.62, 1.68), (0.14, 0.14, 2.34), dark, r=0.012)              # corner posts
    add_rbox(g, (0, 0, 2.92), (3.50, 3.50, 0.14), dark, r=0.02)                                        # top deck
    # louvres on all four faces (horizontal slats)
    for side in range(4):
        for i in range(9):
            z = 0.75 + i * 0.2
            if side == 0:
                add_box(g, (0, 1.685, z), (2.9, 0.06, 0.05), steel, rot=(35, 0, 0))
            elif side == 1:
                add_box(g, (0, -1.685, z), (2.9, 0.06, 0.05), steel, rot=(-35, 0, 0))
            elif side == 2:
                add_box(g, (1.685, 0, z), (0.06, 2.9, 0.05), steel, rot=(0, -35, 0))
            else:
                add_box(g, (-1.685, 0, z), (0.06, 2.9, 0.05), steel, rot=(0, 35, 0))
    # fan stack (tapered fibreglass cylinder) with fan + guard
    add_revolve(g, [(1.50, 2.99), (1.50, 3.05), (1.28, 3.25), (1.16, 3.72), (1.16, 3.80), (1.06, 3.80), (1.06, 3.70), (1.16, 3.25), (1.36, 3.05),
                    (1.40, 2.99)], (0, 0, 0), M["paint_white"], seg=20, axis="Z", close_loop=True)
    fan = fan_gmb(M, 0.98, blades=6, hub=0.16, shroud=False, seg=20)
    g.merge_into(fan, T(0, 0, 3.55))
    fan.bm.free()
    # pipes with flanges into the casing, valve + ladder
    for sx, zz in ((-0.7, 0.85), (0.7, 1.25)):
        add_tube(g, [(sx, 2.55, 0.5), (sx, 2.55, zz), (sx, 1.72, zz)], 0.13, dark, seg=10)
        add_cyl(g, (sx, 2.55, zz), 0.19, 0.05, steel, seg=10)
    add_cyl(g, (-0.7, 2.55, 0.85), 0.24, 0.12, M["paint_red"], seg=10)
    for sx in (-0.30, 0.30):
        add_strut(g, (1.72, sx + 1.0, 0.45), (1.72, sx + 1.0, 3.0), 0.025, steel, 5)
    for i in range(10):
        add_strut(g, (1.72, 0.70, 0.7 + i * 0.24), (1.72, 1.30, 0.7 + i * 0.24), 0.018, steel, 5)
    # handrail on the deck
    for sx in (-1, 1):
        add_strut(g, (sx * 1.7, -1.7, 3.05), (sx * 1.7, -1.7, 3.55), 0.02, steel, 5)
    add_strut(g, (-1.7, -1.7, 3.55), (1.7, -1.7, 3.55), 0.02, steel, 5)
    finish(g, "CoolingTower_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_Solar_Array : 2 rows x 6 panels tilted 25 deg towards +Y on steel racks with ballast
# ----------------------------------------------------------------------------------------------------
def build_solar(M):
    r = new_root("Prop_Solar_Array")
    g = GMB(weld=False)
    galv, alu, dark = M["galv"], M["alu"], M["steel_dark"]
    alpha = math.radians(25.0)
    PW, PL = 1.0, 1.65
    u = Vector((1, 0, 0))
    v = Vector((0, -math.cos(alpha), math.sin(alpha)))
    n = v.cross(u)
    cols, rows = 6, 2
    row_pitch = 2.9
    x_start = -cols * PW / 2.0
    z_low = 0.62
    for j in range(rows):
        y_front = 0.35 + (rows - 1 - j) * row_pitch - (rows - 1) * row_pitch / 2.0        # +Y row first
        for i in range(cols):
            O = Vector((x_start + i * PW + 0.005, y_front, z_low))
            W = PW - 0.01
            top = O + n * 0.046
            g.poly([tuple(top), tuple(top + v * PL), tuple(top + u * W + v * PL), tuple(top + u * W)], M["solar"],
                   uv=[(0, 0), (0, 1), (1, 1), (1, 0)])
            Ot = O + v * PL          # right-handed frame: local x = u, local y = -v (down the slope), local z = n
            basis = Matrix([[u.x, -v.x, n.x, Ot.x], [u.y, -v.y, n.y, Ot.y], [u.z, -v.z, n.z, Ot.z], [0, 0, 0, 1]])
            sub = GMB(weld=False)
            add_box(sub, (W / 2, PL / 2, 0.018), (W, PL, 0.036), dark)
            for (cx, cy, sx_, sy_) in ((W / 2, 0.0225, W, 0.045), (W / 2, PL - 0.0225, W, 0.045), (0.0225, PL / 2, 0.045, PL),
                                       (W - 0.0225, PL / 2, 0.045, PL)):
                add_box(sub, (cx, cy, 0.024), (sx_, sy_, 0.048), alu)
            sub.finish()
            g.merge_into(sub, basis)
            sub.bm.free()
        # rack: two rails along X under the panels, A-frame legs every two panels, ballast
        for t in (0.30, 1.35):
            p0 = Vector((x_start, y_front, z_low)) + v * t - n * 0.05
            p1 = p0 + u * (cols * PW)
            add_beam(g, tuple(p0), tuple(p1), 0.06, 0.06, galv)
        for xi in range(0, cols + 1, 2):
            x = x_start + xi * PW
            front = Vector((x, y_front, z_low)) + v * 0.30 - n * 0.05
            back = Vector((x, y_front, z_low)) + v * 1.35 - n * 0.05
            add_strut(g, (x, front.y, 0.10), tuple(front), 0.03, galv, 6)
            add_strut(g, (x, back.y, 0.10), tuple(back), 0.03, galv, 6)
            add_strut(g, (x, front.y, 0.20), (x, back.y, 0.10), 0.02, galv, 5)
            add_rbox(g, (x, front.y, 0.07), (0.16, 0.42, 0.14), M["concrete"], r=0.02, bottom=False)
            add_rbox(g, (x, back.y, 0.07), (0.16, 0.42, 0.14), M["concrete"], r=0.02, bottom=False)
    # combiner box + conduit
    add_rbox(g, (-3.4, 0.0, 0.35), (0.32, 0.22, 0.50), M["unit_a"], r=0.015, bottom=False)
    add_tube(g, [(-3.4, 0.0, 0.6), (-3.4, 0.0, 0.9), (-3.05, -0.4, 1.0)], 0.02, dark, seg=6)
    finish(g, "SolarArray_Body", r)
    return r

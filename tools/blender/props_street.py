"""Street furniture props: street lamp, jersey barrier, striped barrier (+ extras added further down)."""
from props_common import *          # noqa: F401,F403


# ----------------------------------------------------------------------------------------------------
# Prop_Barrier_Jersey  (3.0 m long along Y, 0.81 m high)
# ----------------------------------------------------------------------------------------------------
def build_jersey(M):
    r = new_root("Prop_Barrier_Jersey")
    mb = GMB(weld=False)
    prof = [(-0.30, 0.0), (0.30, 0.0), (0.30, 0.08), (0.205, 0.34), (0.078, 0.81), (-0.078, 0.81), (-0.205, 0.34), (-0.30, 0.08)]
    sub = MB()
    sub.prism(prof, -1.5, 1.5, mat=M["concrete"], plane="XZ")
    sub.finish()
    bmesh.ops.bevel(sub.bm, geom=list(sub.bm.edges), offset=0.014, segments=1, affect="EDGES", clamp_overlap=True)
    mb.merge_into(sub)
    sub.bm.free()
    # slope-break reveal lines (dark grooves) on both faces
    for sgn in (-1, 1):
        add_box(mb, (sgn * 0.208, 0.0, 0.34), (0.008, 2.98, 0.012), M["concrete_dark"])
    # interlocking end profile: recessed dark slot + steel lifting loops on top
    for ys in (-1.5, 1.5):
        add_box(mb, (0, ys - math.copysign(0.004, ys), 0.42), (0.12, 0.012, 0.44), M["concrete_dark"])
        for xs in (-0.045, 0.045):
            add_box(mb, (xs, ys - math.copysign(0.05, ys), 0.822), (0.02, 0.09, 0.03), M["steel_dark"])
    # amber reflectors on both slopes, white toe stripes
    for sgn in (-1, 1):
        for yy in (-1.15, 1.15):
            add_box(mb, (sgn * 0.145, yy, 0.58), (0.012, 0.32, 0.10), M["paint_yellow"], rot=(0, sgn * 15.0, 0))
        add_box(mb, (sgn * 0.301, 0.0, 0.04), (0.006, 2.94, 0.05), M["paint_white"])
    finish(mb, "Barrier_Jersey_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_Barrier_Striped  (Type-III barricade: two striped rails, two posts, feet, amber lamps)
# ----------------------------------------------------------------------------------------------------
def build_striped(M):
    r = new_root("Prop_Barrier_Striped")
    mb = GMB(weld=False)
    hx = 0.95
    for sx in (-1, 1):
        x = sx * hx
        add_rbox(mb, (x, 0.0, 0.05), (0.07, 1.10, 0.08), M["steel_dark"], r=0.012)
        add_rbox(mb, (x, 0.0, 0.62), (0.06, 0.06, 1.08), M["steel"], r=0.01)
        add_strut(mb, (x, 0.38, 0.09), (x, 0.02, 0.85), 0.018, M["steel"], 6)
        add_strut(mb, (x, -0.38, 0.09), (x, -0.02, 0.85), 0.018, M["steel"], 6)
        add_rbox(mb, (x, 0.0, 1.20), (0.14, 0.14, 0.10), M["steel_dark"], r=0.012)              # lamp housing
        add_cyl(mb, (x, 0.0, 1.30), 0.075, 0.12, M["amber_lens"], seg=12, r_top=0.062)             # amber lens
        add_cyl(mb, (x, 0.0, 1.37), 0.075, 0.03, M["steel_dark"], seg=12, r_top=0.05)              # hood
        add_rbox(mb, (x, 0.28, 0.16), (0.16, 0.30, 0.14), M["concrete_dark"], r=0.03, seg=1)        # ballast bags
        add_rbox(mb, (x, -0.28, 0.16), (0.16, 0.30, 0.14), M["concrete_dark"], r=0.03, seg=1)
    for zc in (0.72, 1.02):                                                                        # striped rails
        add_rbox(mb, (0.0, 0.0, zc), (2.10, 0.035, 0.24), M["stripes"], r=0.008)
    add_box(mb, (0.0, 0.0, 0.9), (1.90, 0.02, 0.02), M["steel_dark"])
    uv_box_for_material(mb, M["stripes"], (1.0, 1.0))
    finish(mb, "Barrier_Striped_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_StreetLamp   (9.3 m, curved arm towards +Y, glowing cobra-head luminaire)
# ----------------------------------------------------------------------------------------------------
def build_lamp(M):
    r = new_root("Prop_StreetLamp")
    mb = GMB(weld=False)
    pole, dark, glow = M["pole"], M["steel_dark"], M["lamp_glow"]
    # base plate + anchor bolts + flange
    add_rbox(mb, (0, 0, 0.02), (0.58, 0.58, 0.04), dark, r=0.008, bottom=False)
    for sx in (-1, 1):
        for sy in (-1, 1):
            add_cyl(mb, (sx * 0.21, sy * 0.21, 0.075), 0.03, 0.07, M["galv"], seg=6, caps=True)
    add_cyl(mb, (0, 0, 0.09), 0.27, 0.10, pole, seg=8, r_top=0.23, rot=(0, 0, 22.5))
    # octagonal pedestal with service door
    add_cyl(mb, (0, 0, 0.60), 0.215, 0.98, pole, seg=8, r_top=0.155, rot=(0, 0, 22.5))
    add_rbox(mb, (0, 0.157, 0.50), (0.17, 0.02, 0.40), dark, r=0.006)
    add_box(mb, (0.055, 0.170, 0.50), (0.02, 0.012, 0.09), M["galv"])
    add_cyl(mb, (0, 0, 1.12), 0.17, 0.07, pole, seg=8, r_top=0.14, rot=(0, 0, 22.5))
    # tapered pole with collars
    add_cyl(mb, (0, 0, 4.72), 0.112, 7.20, pole, seg=10, r_top=0.062)
    for (zc, rr, hh) in ((1.20, 0.135, 0.08), (3.70, 0.098, 0.05), (6.20, 0.084, 0.05), (8.05, 0.092, 0.11)):
        add_cyl(mb, (0, 0, zc), rr, hh, dark, seg=10)
    # curved arm: rises, then bends over towards +Y
    arm = []
    n = 12
    for i in range(n + 1):
        t = (math.pi / 2) * i / n
        arm.append((0.0, 2.05 * (1 - math.cos(t)), 8.05 + 1.0 * math.sin(t)))
    arm.append((0.0, 2.05 + 0.35, 9.05))
    add_tube(mb, arm, 0.056, pole, seg=8, r_end=0.043)
    # bracket: collar block + diagonal strut
    add_rbox(mb, (0, 0.10, 8.05), (0.20, 0.28, 0.26), dark, r=0.02)
    add_strut(mb, (0, 0.07, 7.45), (0, 1.32, 8.96), 0.028, pole, 6)
    add_box(mb, (0, 0.06, 7.45), (0.10, 0.10, 0.10), dark)
    # luminaire: metal housing + glowing bowl whose lip is visible from above + rim + photocell
    yc, zc = 2.78, 9.03
    housing = ((-0.56, 0.12, 0.09), (-0.40, 0.235, 0.14), (0.06, 0.275, 0.13), (0.44, 0.225, 0.095), (0.62, 0.11, 0.05))
    secs = [[(x, yc + dy, zc + z) for (x, z) in rr_pts(hw, -0.055, zt, min(0.05, hw * 0.4))] for (dy, hw, zt) in housing]
    sub = MB()
    sub.loft(secs, mat=M["galv"], caps=True)
    add_closed(mb, sub)
    bowl = []
    for (dy, hw, zt) in housing:
        ht, hb = hw + 0.018, max(0.03, hw - 0.045)
        bowl.append([(-ht, yc + dy, zc - 0.052), (ht, yc + dy, zc - 0.052), (hb, yc + dy, zc - 0.132), (-hb, yc + dy, zc - 0.132)])
    bowl = [b[::-1] for b in bowl]
    sub = MB()
    sub.loft(bowl, mat=glow, caps=True)
    add_closed(mb, sub)
    add_cyl(mb, (0, yc - 0.10, zc + 0.15), 0.05, 0.05, dark, seg=8)                                # photocell
    add_rbox(mb, (0, yc - 0.42, zc + 0.02), (0.10, 0.16, 0.10), dark, r=0.01)                           # arm clamp
    finish(mb, "StreetLamp_Body", r)
    return r

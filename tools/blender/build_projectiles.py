"""Projectiles -> public/assets/missile.glb, mini_missile.glb

Both fly nose-first along +Y (Blender) = -Z (three.js), origin at mid-length, glowing exhaust at the tail and an
`Exhaust_Point` Empty whose local +Y points BACK (exhaust direction).

  node tools/run-blender.mjs tools/blender/build_projectiles.py [-- --preview]

  Missile     : Missile_Body (ogive nose + seeker, red bands, panel lines), Missile_Fins (4 swept tail fins in X
                configuration + 4 canards in + configuration), Missile_Engine (nozzle bell), Missile_Exhaust (emissive),
                Exhaust_Point.   length 1.60 m, body diameter 0.22 m
  MiniMissile : Mini_Body (blunt nose, cream + amber bands), Mini_Fins (3 wedge fins), Mini_Engine, Mini_Exhaust,
                Exhaust_Point.   length 0.75 m, body diameter 0.09 m
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa: E402,F401,F403
import common  # noqa: E402
from enemy_kit import *  # noqa: E402,F401,F403

import math  # noqa: E402

from mathutils import Vector  # noqa: E402


def root_empty(name, size=0.3):
    r = add_empty(name, (0, 0, 0), display="PLAIN_AXES", size=size)
    common._PIVOTS[name] = Vector((0, 0, 0))
    return r


def node(name, mb, pivot, parent, sharp=35.0, bevel=None):
    obj = assemble(name, [(mb, bevel, sharp)])
    return add_part(name, obj, pivot, parent=parent, parent_pivot_world=(0, 0, 0))


def exhaust_point(parent, y):
    e = add_empty("Exhaust_Point", (0, y, 0), parent=parent, rot=aim_rot_for_direction((0, -1, 0)), display="SINGLE_ARROW",
                  size=0.15)
    return e


def fin_solid(mb, angle_deg, root_r, tip_r, root_le, root_te, tip_le, tip_te, thick_root, thick_tip, mat):
    """One tapered fin plate lying in the plane containing the +Y axis at polar angle `angle_deg` (0 = +X, 90 = +Z).
    Leading/trailing edges are given as y values at the root (radius root_r) and the tip (radius tip_r)."""
    a = math.radians(angle_deg)
    radial = Vector((math.cos(a), 0.0, math.sin(a)))
    side = Vector((-math.sin(a), 0.0, math.cos(a)))
    pts = []
    for (r, le, te, t) in ((root_r, root_le, root_te, thick_root), (tip_r, tip_le, tip_te, thick_tip)):
        base = radial * r
        pts.append((base + Vector((0, le, 0)), base + Vector((0, te, 0)), side * (t / 2)))
    (rle, rte, rs), (tle, tte, ts) = pts
    # bottom quad (one side), top quad (other side)
    mb.hexa([rte - rs, rle - rs, tle - ts, tte - ts, rte + rs, rle + rs, tle + ts, tte + ts], mat)


# ==============================================================================================
# big homing missile
# ==============================================================================================
def build_missile(preview):
    reset_scene()
    body_m = pal("missile_body")
    band = pal("missile_band")
    dark = pal("steel_dark")
    glass = pal("glass_dark")
    exh = pal("exhaust")
    seeker = make_material("missile_seeker", color="#140A0C", metallic=0.3, roughness=0.12, emission="#FF3322",
                           emission_strength=1.5)
    root = root_empty("Missile")

    # ---- body: seeker dome, ogive, seeker ring, bands and panel grooves, boat tail
    R = 0.11
    prof = [
        (0.004, 0.800), (0.020, 0.792), (0.034, 0.776),                      # seeker dome (glass)
        (0.040, 0.764), (0.056, 0.720), (0.074, 0.660), (0.090, 0.590), (0.101, 0.520), (0.108, 0.460),  # ogive
        (0.110, 0.420), (0.104, 0.414), (0.104, 0.396), (0.110, 0.390),       # seeker ring groove
        (0.110, 0.360), (0.110, 0.300),                                        # red band 1
        (0.110, 0.060), (0.107, 0.056), (0.107, 0.044), (0.110, 0.040),       # panel groove
        (0.110, -0.200), (0.107, -0.204), (0.107, -0.216), (0.110, -0.220),   # panel groove
        (0.110, -0.400), (0.110, -0.460),                                      # red band 2
        (0.110, -0.620), (0.098, -0.672), (0.080, -0.700),                     # boat tail
    ]
    mats = ([seeker] * 2 + [glass] + [body_m] * 6 + [dark] * 3 + [body_m] + [band] + [body_m] + [dark] * 3 + [body_m] + [dark] * 3
            + [body_m] + [band] + [body_m] + [dark] * 2)
    assert len(mats) == len(prof) - 1, (len(mats), len(prof))
    mb = MB()
    revolve_mats(mb, prof, seg=20, axis="Y", mats=mats, cap_bottom=True, cap_top=True)
    # dorsal conduit + a few access panels along the body
    strip(mb, (0, -0.38, R + 0.004), (0, 0.16, R + 0.004), 0.030, 0.014, dark, normal=(0, 0, 1))
    for yy in (-0.08, 0.18):
        mb.box((0.0, yy, -R + 0.002), (0.05, 0.10, 0.012), mat=dark)
    body = node("Missile_Body", mb, (0, 0, 0), root, sharp=30.0)

    # ---- fins: 4 swept tail fins in X configuration, 4 small canards in + configuration
    mb = MB()
    for k in range(4):
        fin_solid(mb, 45 + 90 * k, 0.100, 0.265, -0.395, -0.660, -0.575, -0.690, 0.016, 0.008, dark)
        fin_solid(mb, 45 + 90 * k, 0.262, 0.272, -0.572, -0.692, -0.588, -0.700, 0.010, 0.009, band)   # red tip caps
        fin_solid(mb, 90 * k, 0.100, 0.168, 0.300, 0.190, 0.262, 0.222, 0.010, 0.006, body_m)
    node("Missile_Fins", mb, (0, -0.55, 0), root, sharp=30.0)

    # ---- engine nozzle bell
    mb = MB()
    lathe_closed(mb, [(0.056, -0.660), (0.082, -0.660), (0.092, -0.790), (0.086, -0.800), (0.070, -0.745), (0.054, -0.705)],
                 seg=20, axis="Y", mat=[dark, dark, dark, dark, dark, dark])
    node("Missile_Engine", mb, (0, -0.73, 0), root, sharp=30.0)

    # ---- emissive exhaust: glowing throat disc + inner cone
    mb = MB()
    mb.cyl((0, -0.742, 0), 0.068, 0.010, seg=20, axis="Y", mat=exh)
    revolve_mats(mb, [(0.056, -0.736), (0.036, -0.722), (0.004, -0.708)], seg=16, axis="Y", mats=[exh, exh],
                 cap_bottom=False, cap_top=False)
    node("Missile_Exhaust", mb, (0, -0.74, 0), root, sharp=60.0)
    exhaust_point(root, -0.80)
    del body
    path = export_glb("missile.glb", [root])
    report(path)
    if preview:
        render_views("missile", [root], views=("three_quarter", "three_quarter_back", "left", "front"), size=(800, 600),
                     samples=24)


# ==============================================================================================
# mini missile
# ==============================================================================================
def build_mini_missile(preview):
    reset_scene()
    body_m = pal("mini_body")
    band = pal("mini_band")
    dark = pal("steel_dark")
    exh = pal("exhaust")
    root = root_empty("MiniMissile", 0.15)
    R = 0.045
    prof = [
        (0.004, 0.375), (0.018, 0.371), (0.030, 0.362), (0.039, 0.349), (0.044, 0.334), (0.045, 0.318),   # blunt nose
        (0.045, 0.300), (0.045, 0.268),                                                                    # amber band
        (0.045, 0.080), (0.043, 0.077), (0.043, 0.069), (0.045, 0.066),                                    # groove
        (0.045, -0.170), (0.045, -0.205),                                                                  # amber band
        (0.045, -0.300), (0.038, -0.325),                                                                  # tail cone
    ]
    mats = [band] * 5 + [body_m] + [band] + [body_m] + [dark] * 3 + [body_m] + [band] + [body_m] + [dark]
    assert len(mats) == len(prof) - 1, (len(mats), len(prof))
    mb = MB()
    revolve_mats(mb, prof, seg=14, axis="Y", mats=mats, cap_bottom=True, cap_top=True)
    node("Mini_Body", mb, (0, 0, 0), root, sharp=30.0)

    mb = MB()
    for k in range(3):
        # wedge fins: thick root tapering to a thin sharp tip, root chord along the tail
        fin_solid(mb, 90 + 120 * k, 0.040, 0.112, -0.150, -0.318, -0.282, -0.345, 0.014, 0.004, band)
    node("Mini_Fins", mb, (0, -0.26, 0), root, sharp=30.0)

    mb = MB()
    lathe_closed(mb, [(0.026, -0.318), (0.038, -0.318), (0.040, -0.372), (0.036, -0.376), (0.029, -0.350), (0.024, -0.335)],
                 seg=14, axis="Y", mat=dark)
    node("Mini_Engine", mb, (0, -0.35, 0), root, sharp=30.0)

    mb = MB()
    mb.cyl((0, -0.352, 0), 0.028, 0.006, seg=14, axis="Y", mat=exh)
    revolve_mats(mb, [(0.024, -0.349), (0.014, -0.341), (0.002, -0.334)], seg=12, axis="Y", mats=[exh, exh],
                 cap_bottom=False, cap_top=False)
    node("Mini_Exhaust", mb, (0, -0.35, 0), root, sharp=60.0)
    exhaust_point(root, -0.378)
    path = export_glb("mini_missile.glb", [root])
    report(path)
    if preview:
        render_views("mini", [root], views=("three_quarter", "three_quarter_back", "left", "front"), size=(800, 600),
                     samples=24)


BUILDERS = {"missile": build_missile, "mini_missile": build_mini_missile}


def main():
    args = script_args()
    preview = "--preview" in args
    only = None
    for i, a in enumerate(args):
        if a == "--only" and i + 1 < len(args):
            only = set(args[i + 1].split(","))
    for key, fn in BUILDERS.items():
        if only and key not in only:
            continue
        log(f"=== building {key}")
        fn(preview)


main()

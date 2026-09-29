"""Hostile machines -> public/assets/drone.glb, turret.glb, boss.glb, boss_shield.glb

Charcoal steel + red warning trim + hazard yellow + red glow (drone / turret); black steel + brass + red-orange core
(boss).  Everything is modelled facing +Y (Blender), Z up; rigged parts get their pivot with common.add_part.
Big forms are bevelled, small details (bolts, stripes, slats, lathed rings) are joined unbevelled into the same node
(enemy_kit.assemble) to keep triangle budgets sane.

  node tools/run-blender.mjs tools/blender/build_enemies.py                      # all four GLBs
  node tools/run-blender.mjs tools/blender/build_enemies.py -- --only drone --preview

Hierarchies (tools/asset-contract.json):
  Drone  : Drone_Body, Drone_Rotor_FL/FR/RL/RR (pivot on the rotor axis), Drone_Sensor, Drone_Engine,
           Muzzle_L/R, Nozzle_Rear
  Turret : Turret_Base, Turret_Yaw -> Turret_Pitch -> {Turret_Sensor, Muzzle_1..4}
  Boss   : Boss_Torso -> {Boss_Head, Boss_Core, Boss_Arm_L/R -> Boss_Forearm_L/R -> Hardpoint_*2/3,
           Boss_Arm_* -> Hardpoint_*1, Boss_Thruster_1..4 -> Nozzle_1..4}, Shield_Center
  BossShield (unit sphere)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa: E402,F401,F403
import common  # noqa: E402
from enemy_kit import *  # noqa: E402,F401,F403

import math  # noqa: E402

import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Quaternion, Vector  # noqa: E402


class M:
    """material table for the asset being built (filled per asset after reset_scene)"""


def enemy_materials():
    M.H = pal("enemy_hull")
    M.P = pal("enemy_plate")
    M.D = pal("enemy_dark")
    M.W = pal("enemy_warning")
    M.Y = pal("enemy_hazard")
    M.S = pal("steel")
    M.R = pal("glow_red")
    M.O = pal("glow_orange")
    M.N = pal("missile_band")


def boss_materials():
    enemy_materials()
    M.BP = pal("boss_plate")
    M.BD = pal("boss_dark")
    M.BB = pal("boss_brass")
    M.C = pal("glow_core")
    M.SD = pal("steel_dark")


def emp(name, world, direction, parent, parent_pivot, size=0.12, disp="SINGLE_ARROW"):
    e = add_empty(name, (0, 0, 0), parent=parent, rot=aim_rot_for_direction(direction), display=disp, size=size)
    e.location = Vector(world) - Vector(parent_pivot)
    return e


def root_empty(name, size=0.5):
    r = add_empty(name, (0, 0, 0), display="PLAIN_AXES", size=size)
    common._PIVOTS[name] = Vector((0, 0, 0))
    return r


def part(name, pieces, pivot, parent, parent_pivot):
    obj = assemble(name, pieces)
    return add_part(name, obj, pivot, parent=parent, parent_pivot_world=parent_pivot)


def axis_of(obj):
    return (obj.matrix_world.to_quaternion() @ Vector((0, 1, 0))).normalized()


# ==============================================================================================
# DRONE
# ==============================================================================================
DR_ROTORS = {  # name -> rotor axis position (Blender)
    "Drone_Rotor_FL": (-0.58, 0.33, 0.02),
    "Drone_Rotor_FR": (0.58, 0.33, 0.02),
    "Drone_Rotor_RL": (-0.58, -0.37, 0.02),
    "Drone_Rotor_RR": (0.58, -0.37, 0.02),
}
DR_GUN_X = 0.165
DR_GUN_Z = -0.128
DR_EYE = (0.0, 0.47, -0.004)


def drone_duct(main, det, c):
    """static duct ring + clamps + stator struts + motor pod around rotor axis c (part of the body)"""
    H, P, D, W, R, S = M.H, M.P, M.D, M.W, M.R, M.S
    prof = [(0.206, -0.048), (0.222, -0.064), (0.250, -0.064), (0.262, -0.050), (0.262, -0.010), (0.262, 0.006),
            (0.262, 0.040), (0.250, 0.058), (0.226, 0.064), (0.212, 0.058), (0.206, 0.044)]
    lathe_closed(det, prof, center=c, seg=24, axis="Z", mat=[H, H, H, H, W, H, P, P, P, R, D])
    cx, cy, cz = c
    to_hull = 0.0 if cx < 0 else math.pi
    for k in range(4):
        a = to_hull + math.pi / 4 + k * math.pi / 2
        d = Vector((math.cos(a), math.sin(a), 0))
        main.box(Vector(c) + d * 0.262, (0.045, 0.06, 0.118), mat=D, rot=(0, 0, math.degrees(a)))
    revolve_mats(det, [(0.012, -0.105), (0.034, -0.095), (0.052, -0.065), (0.054, -0.012), (0.046, -0.004)],
                 center=c, seg=12, mats=[D, D, H, H], cap_bottom=False)
    for k in range(3):
        a = to_hull + 2 * math.pi * k / 3
        d = Vector((math.cos(a), math.sin(a), 0))
        strip(det, Vector(c) + d * 0.045 + Vector((0, 0, -0.03)), Vector(c) + d * 0.212 + Vector((0, 0, -0.03)), 0.014,
              0.022, S, normal=(0, 0, 1))


def drone_rotor(c):
    """spinning part: spinner + 5 scimitar blades (pivot = c on the rotor axis)"""
    mb = MB()
    fan_blades(mb, (c[0], c[1], c[2] + 0.012), 0.036, 0.197, 5, M.S, chord=(0.078, 0.052), pitch=(34, 15), thick=0.009,
               sweep=0.28)
    revolve_mats(mb, [(0.044, -0.012), (0.046, 0.016), (0.036, 0.034), (0.018, 0.046), (0.004, 0.050)],
                 center=c, seg=16, mats=[M.D, M.W, M.W, M.W], cap_top=True)
    return mb


def drone_body():
    main, det = MB(), MB()
    H, P, D, W, Y, S, R = M.H, M.P, M.D, M.W, M.Y, M.S, M.R
    # ---- fuselage: chamfered octagonal loft, blunt head at the front, tapering tail
    secs = [
        (-0.585, 0.085, 0.115, 0.085, 0.065, 0.030, -0.035, -0.070),
        (-0.50, 0.130, 0.180, 0.120, 0.100, 0.045, -0.050, -0.095),
        (-0.34, 0.180, 0.250, 0.160, 0.150, 0.065, -0.065, -0.130),
        (0.06, 0.200, 0.280, 0.170, 0.165, 0.070, -0.070, -0.145),
        (0.28, 0.170, 0.245, 0.150, 0.150, 0.060, -0.065, -0.130),
        (0.40, 0.140, 0.200, 0.125, 0.125, 0.052, -0.058, -0.112),
        (0.46, 0.120, 0.175, 0.110, 0.105, 0.046, -0.052, -0.100),
    ]
    main.loft([oct_sec(*s) for s in secs], mat=D)
    # ---- two layered carapace plates overhanging the flanks (rear one lower, front one overlaps it)
    rear = [
        (-0.44, 0.075, 0.160, 0.130, 0.120, 0.074, 0.058, 0.048),
        (-0.33, 0.135, 0.275, 0.220, 0.182, 0.096, 0.076, 0.064),
        (-0.04, 0.150, 0.300, 0.235, 0.198, 0.102, 0.080, 0.068),
        (0.04, 0.140, 0.285, 0.225, 0.192, 0.098, 0.078, 0.066),
    ]
    main.loft([oct_sec(*s) for s in rear], mat=H)
    front = [
        (-0.09, 0.120, 0.265, 0.200, 0.226, 0.118, 0.090, 0.078),
        (-0.03, 0.160, 0.320, 0.240, 0.222, 0.114, 0.088, 0.076),
        (0.20, 0.140, 0.290, 0.220, 0.205, 0.102, 0.080, 0.068),
        (0.33, 0.085, 0.190, 0.150, 0.160, 0.084, 0.064, 0.056),
    ]
    main.loft([oct_sec(*s) for s in front], mat=H)
    # lighter armour inlays on the front carapace
    for sx in (-1, 1):
        quad_plate(main, (sx * 0.05, 0.25, 0.200), (sx * 0.135, 0.22, 0.197), (sx * 0.135, -0.02, 0.214), (sx * 0.05, -0.02, 0.216),
                   0.012, P, (0, 0, 1))
    # red chevron on the front plate, dark spine + red stripe on the rear plate, glowing seams under the shell edge
    for sx in (-1, 1):
        strip(det, (sx * 0.012, 0.19, 0.2075), (sx * 0.125, 0.03, 0.2205), 0.034, 0.010, W)
        strip(det, (sx * 0.2975, -0.25, 0.089), (sx * 0.3190, -0.01, 0.094), 0.012, 0.008, R, normal=(sx, 0, 0))
    strip(det, (0, -0.30, 0.1835), (0, -0.10, 0.1960), 0.06, 0.014, D)
    strip(det, (0, -0.29, 0.1905), (0, -0.11, 0.2025), 0.020, 0.008, W)
    # dorsal intake on the rear plate
    main.box((0, -0.21, 0.205), (0.16, 0.12, 0.05), mat=D, taper=(0.85, 0.7))
    vent_slats(det, (0, -0.148, 0.205), 0.12, 0.04, 3, H, depth=0.008, axis="Y", gap=0.5)
    # ---- head: pointed V brow (prow) over the sensor socket, cheek plates framing the face
    for sx in (-1, 1):
        quad_plate(main, (sx * 0.0, 0.30, 0.150), (sx * 0.21, 0.28, 0.118), (sx * 0.20, 0.49, 0.100), (sx * 0.0, 0.565, 0.062),
                   0.032, P, (0, 0, 1))
        strip(det, (sx * 0.015, 0.563, 0.081), (sx * 0.195, 0.492, 0.117), 0.018, 0.010, W, normal=(0, 0.4, 1))
        quad_plate(main, (sx * 0.229, 0.30, 0.050), (sx * 0.160, 0.520, 0.035), (sx * 0.160, 0.520, -0.060), (sx * 0.229, 0.30, -0.062),
                   0.03, P, (sx, 0.4, 0))
    lathe_closed(det, [(0.064, -0.035), (0.094, -0.035), (0.094, 0.018), (0.086, 0.030), (0.068, 0.030), (0.064, 0.018)],
                 center=DR_EYE, seg=20, axis="Y", mat=D)
    for sx in (-1, 1):
        det.cyl((sx * 0.122, 0.468, 0.02), 0.022, 0.03, seg=10, axis="Y", mat=D)
        det.cyl((sx * 0.122, 0.484, 0.02), 0.014, 0.006, seg=10, axis="Y", mat=R)
    # ---- chin gun pods + barrels with muzzle brakes
    for sx in (-1, 1):
        x0 = sx * DR_GUN_X
        pod = [(0.10, 0.022, 0.034, 0.024, 0.036, 0.014, -0.016, -0.030),
               (0.17, 0.034, 0.048, 0.034, 0.046, 0.020, -0.022, -0.046),
               (0.40, 0.034, 0.048, 0.034, 0.046, 0.020, -0.022, -0.046),
               (0.46, 0.026, 0.038, 0.026, 0.036, 0.016, -0.018, -0.036)]
        main.loft([oct_sec(*p, x0=x0, z0=DR_GUN_Z) for p in pod], mat=D)
        quad_plate(main, (x0 + sx * 0.040, 0.16, DR_GUN_Z + 0.03), (x0 + sx * 0.040, 0.47, DR_GUN_Z + 0.03),
                   (x0 + sx * 0.050, 0.43, DR_GUN_Z - 0.045), (x0 + sx * 0.050, 0.20, DR_GUN_Z - 0.05), 0.016, P, (sx, 0, 0))
        det.box((x0, 0.455, DR_GUN_Z + 0.038), (0.05, 0.03, 0.012), mat=Y)
        tube(det, (x0, 0.555, DR_GUN_Z), 0.021, 0.011, 0.22, S, mat_in=D, bore_depth=0.05, seg=10)
        tube(det, (x0, 0.655, DR_GUN_Z), 0.030, 0.013, 0.05, D, mat_in=D, bore_depth=0.03, seg=10)
        for k in range(3):
            det.box((x0, 0.643 + k * 0.013, DR_GUN_Z), (0.066, 0.006, 0.014), mat=D)
        # forward mandible blade over each gun
        main.prism([(0.19 * sx, 0.28), (0.25 * sx, 0.30), (0.22 * sx, 0.50), (0.15 * sx, 0.70), (0.17 * sx, 0.46)][::sx],
                   -0.088, -0.050, mat=P, plane="XY")
        det.prism([(0.176 * sx, 0.60), (0.196 * sx, 0.60), (0.152 * sx, 0.705), (0.146 * sx, 0.69)][::sx], -0.091, -0.047,
                  mat=W, plane="XY")
    # ---- pylons to the ducts + ducts
    for name, c in sorted(DR_ROTORS.items()):
        sx = 1 if c[0] > 0 else -1
        cy = c[1]
        main.box((sx * 0.265, cy, c[2] + 0.004), (0.17, 0.12, 0.08), mat=H, taper=(0.9, 0.75), bottom_scale=(0.9, 0.8))
        det.box((sx * 0.27, cy, c[2] + 0.046), (0.13, 0.05, 0.012), mat=W)
        det.cyl((sx * 0.21, cy, c[2] - 0.035), 0.022, 0.12, seg=8, axis="X", mat=S)
        drone_duct(main, det, c)
    # ---- flank intakes between the ducts
    for sx in (-1, 1):
        main.box((sx * 0.285, -0.02, -0.005), (0.04, 0.20, 0.11), mat=D)
        vent_slats(det, (sx * 0.306, -0.02, -0.005), 0.17, 0.09, 4, H, depth=0.012, axis="X", gap=0.5)
    # ---- belly: armour plate + glowing keel strip + skid rails
    quad_plate(main, (-0.13, -0.30, -0.136), (0.13, -0.30, -0.136), (0.11, 0.12, -0.134), (-0.11, 0.12, -0.134), 0.022, P, (0, 0, -1))
    strip(det, (0, -0.26, -0.160), (0, 0.08, -0.160), 0.030, 0.010, R, normal=(0, 0, -1))
    for sx in (-1, 1):
        main.box((sx * 0.105, -0.09, -0.163), (0.02, 0.30, 0.018), mat=D)
    # ---- V tail fins with red tips
    fin = [(-0.16, 0.0), (0.12, 0.0), (-0.08, 0.22), (-0.22, 0.22)]
    tip = [(-0.211, 0.165), (-0.019, 0.165), (-0.078, 0.226), (-0.226, 0.226)]
    for sx in (-1, 1):
        rot = (0, sx * 32, 0)
        cen = (sx * 0.075, -0.40, 0.062)
        main.prism(fin, -0.011, 0.011, mat=P, plane="YZ", rot=rot, center=cen)
        det.prism(tip, -0.0145, 0.0145, mat=W, plane="YZ", rot=rot, center=cen)
    # ---- small antenna with a red tip light
    det.cyl((0.09, -0.36, 0.23), 0.006, 0.16, seg=6, axis="Z", mat=S, rot=(-18, 0, 0))
    ball(det, (0.09, -0.385, 0.305), 0.013, R, seg=8, rings=6)
    # ---- engine housing (the glowing nozzle itself is Drone_Engine)
    main.cyl((0, -0.585, 0.0), 0.098, 0.05, seg=16, axis="Y", mat=D, r_top=0.09)
    return main, det


def drone_engine():
    mb = MB()
    c = (0.0, -0.62, 0.0)
    lathe_closed(mb, [(0.062, 0.035), (0.082, 0.035), (0.090, 0.0), (0.086, -0.040), (0.074, -0.046), (0.066, -0.020)],
                 center=c, seg=20, axis="Y", mat=[M.S, M.D, M.D, M.S, M.D, M.D])
    mb.cyl((0, -0.61, 0.0), 0.063, 0.02, seg=20, axis="Y", mat=M.O)
    mb.cyl((0, -0.622, 0.0), 0.032, 0.008, seg=16, axis="Y", mat=M.R)
    return mb


def drone_sensor():
    mb = MB()
    ex, ey, ez = DR_EYE
    revolve_mats(mb, [(0.062, 0.0), (0.062, 0.010), (0.051, 0.024), (0.030, 0.033), (0.004, 0.036)],
                 center=(ex, ey + 0.012, ez), seg=20, axis="Y", mats=[M.R], cap_top=True)
    mb.cyl((ex, ey + 0.049, ez), 0.020, 0.006, seg=12, axis="Y", mat=M.O)
    return mb


def build_drone(preview):
    reset_scene()
    enemy_materials()
    root = root_empty("Drone", 0.4)
    main, det = drone_body()
    part("Drone_Body", [(main, (0.006, 2), 32.0), (det, None, 40.0)], (0, 0, 0), root, (0, 0, 0))
    for name, c in sorted(DR_ROTORS.items()):
        if c[0] > 0:  # right-hand rotors spin the other way (game: +spin) -> mirrored blade pitch
            mb = drone_rotor((-c[0], c[1], c[2])).mirrored_x()
        else:
            mb = drone_rotor(c)
        part(name, [(mb, None, 40.0)], c, root, (0, 0, 0))
    part("Drone_Sensor", [(drone_sensor(), None, 40.0)], (DR_EYE[0], DR_EYE[1] + 0.02, DR_EYE[2]), root, (0, 0, 0))
    part("Drone_Engine", [(drone_engine(), None, 40.0)], (0, -0.62, 0.0), root, (0, 0, 0))
    emp("Muzzle_L", (-DR_GUN_X, 0.685, DR_GUN_Z), (0, 1, 0), root, (0, 0, 0))
    emp("Muzzle_R", (DR_GUN_X, 0.685, DR_GUN_Z), (0, 1, 0), root, (0, 0, 0))
    emp("Nozzle_Rear", (0, -0.675, 0.0), (0, -1, 0), root, (0, 0, 0))
    path = export_glb("drone.glb", [root])
    report(path)
    if preview:
        render_views("drone", [root], views=("front", "three_quarter", "three_quarter_back", "top", "low", "left"),
                     size=(800, 800), samples=24)


# ==============================================================================================
# TURRET
# ==============================================================================================
TU_YAW = (0.0, 0.0, 1.10)
TU_PITCH = (0.0, 0.08, 1.85)
TU_POD_X = 0.96
TU_TUBES = [(-0.835, 1), (0.835, 2), (-1.085, 3), (1.085, 4)]   # (x, muzzle index)
TU_POD_DY = 0.34                # pods sit forward on the trunnion (short rear overhang -> clears the deck at high pitch)
TU_MOUTH_Y = 0.885 + TU_POD_DY


def oct_face(rb, rt, zb, zt, theta_deg):
    """corners (b0, b1, t1, t0) of face `theta` of an 8-sided frustum whose faces are centred on 0/45/90.. degrees"""
    out = []
    for (r, z) in ((rb, zb), (rt, zt)):
        for da in (-22.5, 22.5):
            a = math.radians(theta_deg + da)
            out.append(V(math.cos(a) * r, math.sin(a) * r, z))
    b0, b1, t0, t1 = out
    return b0, b1, t1, t0


def bilerp(q, u, v):
    p0, p1, p2, p3 = q
    return p0.lerp(p1, u).lerp(p3.lerp(p2, u), v)


def turret_base():
    main, det = MB(), MB()
    H, P, D, W, Y, S, R = M.H, M.P, M.D, M.W, M.Y, M.S, M.R
    OCT = (0, 0, 22.5)
    main.cyl((0, 0, 0.09), 1.26, 0.18, seg=8, axis="Z", mat=D, rot=OCT)
    main.cyl((0, 0, 0.54), 1.14, 0.72, seg=8, axis="Z", mat=H, rot=OCT, r_top=0.98)
    main.cyl((0, 0, 0.955), 1.035, 0.11, seg=8, axis="Z", mat=P, rot=OCT, r_top=1.0)
    main.cyl((0, 0, 1.055), 0.95, 0.09, seg=8, axis="Z", mat=D, rot=OCT, r_top=0.93)
    for k in range(8):
        th = 45 * k
        n = V(math.cos(math.radians(th)), math.sin(math.radians(th)), 0)
        tng = V(-n.y, n.x, 0)
        ap = 1.26 * math.cos(math.radians(22.5))
        half = 1.26 * math.sin(math.radians(22.5))
        hazard_band(det, n * ap - tng * (half - 0.05), n * ap + tng * (half - 0.05), 0.035, 0.145, n, Y, stripe=0.075, slant=0.8)
        q = oct_face(1.14, 0.98, 0.18, 0.90, th)
        fn = (q[1] - q[0]).cross(q[3] - q[0]).normalized()
        if fn.dot(n) < 0:
            fn = -fn
        if k in (0, 4):       # side vents
            corners = [bilerp(q, u, v) - fn * 0.01 for (u, v) in ((0.16, 0.14), (0.84, 0.14), (0.84, 0.80), (0.16, 0.80))]
            quad_plate(main, *corners, 0.04, D, fn)
            for i in range(5):
                v0 = 0.20 + i * 0.12
                sl = [bilerp(q, u, v) + fn * 0.02 for (u, v) in ((0.22, v0), (0.78, v0), (0.78, v0 + 0.05), (0.22, v0 + 0.05))]
                quad_plate(det, *sl, 0.03, H, fn)
        elif k == 6:          # rear access hatch
            corners = [bilerp(q, u, v) - fn * 0.01 for (u, v) in ((0.22, 0.10), (0.78, 0.10), (0.78, 0.84), (0.22, 0.84))]
            quad_plate(main, *corners, 0.04, P, fn)
            inner = [bilerp(q, u, v) + fn * 0.025 for (u, v) in ((0.30, 0.18), (0.70, 0.18), (0.70, 0.76), (0.30, 0.76))]
            quad_plate(main, *inner, 0.02, D, fn)
            bar(det, bilerp(q, 0.40, 0.5) + fn * 0.06, bilerp(q, 0.60, 0.5) + fn * 0.06, 0.03, 0.03, S)
            quad_plate(det, *[bilerp(q, u, v) + fn * 0.02 for (u, v) in ((0.22, 0.86), (0.78, 0.86), (0.78, 0.93), (0.22, 0.93))],
                       0.015, W, fn)
        else:                 # bolted armour plates
            corners = [bilerp(q, u, v) - fn * 0.008 for (u, v) in ((0.10, 0.10), (0.90, 0.10), (0.90, 0.86), (0.10, 0.86))]
            quad_plate(main, *corners, 0.042, P, fn)
            for (u, v) in ((0.17, 0.18), (0.83, 0.18), (0.83, 0.78), (0.17, 0.78)):
                bolt(det, bilerp(q, u, v) + fn * 0.034, fn, S, r=0.026, h=0.02)
            if k == 2:        # front: red warning bands
                for v0 in (0.44, 0.56):
                    quad_plate(det, *[bilerp(q, u, v) + fn * 0.03 for (u, v) in ((0.26, v0), (0.74, v0), (0.74, v0 + 0.07), (0.26, v0 + 0.07))],
                               0.014, W, fn)
    for th in (45, 135, 225, 315):   # collar warning lamps (static)
        n = V(math.cos(math.radians(th)), math.sin(math.radians(th)), 0)
        p = n * 0.955 + V(0, 0, 0.955)
        q = quat_z_to(n)
        det.cyl(p, 0.05, 0.05, seg=10, axis="Z", mat=D, rot=q)
        det.cyl(p + n * 0.03, 0.036, 0.016, seg=10, axis="Z", mat=R, rot=q)
    n = V(math.cos(math.radians(315)), math.sin(math.radians(315)), 0)   # cable conduit
    t = V(-n.y, n.x, 0)
    bar(main, n * 1.083 + t * 0.30 + V(0, 0, 0.18), n * 0.935 + t * 0.26 + V(0, 0, 0.90), 0.07, 0.07, D)
    return main, det


def turret_yaw():
    main, det = MB(), MB()
    H, P, D, W, Y, S, R = M.H, M.P, M.D, M.W, M.Y, M.S, M.R
    det.cyl((0, 0, 1.14), 0.86, 0.08, seg=32, axis="Z", mat=D)
    for i in range(40):
        a = 2 * math.pi * (i + 0.5) / 40
        det.box((math.cos(a) * 0.868, math.sin(a) * 0.868, 1.14), (0.03, 0.045, 0.06), mat=S, rot=(0, 0, math.degrees(a)))
    main.cyl((0, 0, 1.24), 0.98, 0.12, seg=8, axis="Z", mat=H, rot=(0, 0, 22.5), r_top=0.93)
    rear = [(-1.00, 0.44, 0.52, 0.52, 1.95, 1.85, 1.40, 1.28),
            (-0.90, 0.50, 0.58, 0.58, 2.08, 1.98, 1.36, 1.28),
            (-0.33, 0.50, 0.58, 0.58, 2.12, 2.02, 1.36, 1.28)]
    main.loft([oct_sec(*s) for s in rear], mat=H)
    for sx in (-1, 1):
        quad_plate(main, (sx * 0.575, -0.95, 1.42), (sx * 0.575, -0.36, 1.42), (sx * 0.575, -0.36, 1.96), (sx * 0.575, -0.88, 1.92),
                   0.035, P, (sx, 0, 0))
        strip(det, (sx * 0.61, -0.86, 1.86), (sx * 0.61, -0.40, 1.88), 0.05, 0.012, W, normal=(sx, 0, 0))
    vent_slats(det, (0, -1.0, 1.62), 0.64, 0.34, 5, D, depth=0.03, axis="Y")
    hazard_band(det, (0.46, -1.0), (-0.46, -1.0), 1.33, 1.41, (0, -1, 0), Y, stripe=0.06, slant=0.9)
    cheek = [(-0.40, 1.28), (0.42, 1.28), (0.52, 1.50), (0.46, 1.98), (0.22, 2.17), (-0.40, 2.17)]
    cheek_in = [(-0.30, 1.40), (0.36, 1.40), (0.43, 1.52), (0.38, 1.94), (0.19, 2.08), (-0.30, 2.08)]
    for sx in (-1, 1):
        x0, x1 = (0.36, 0.60) if sx > 0 else (-0.60, -0.36)
        main.prism(cheek, x0, x1, mat=H, plane="YZ")
        a0, a1 = (0.595, 0.63) if sx > 0 else (-0.63, -0.595)
        main.prism(cheek_in, a0, a1, mat=P, plane="YZ")
        det.cyl((sx * 0.662, TU_PITCH[1], TU_PITCH[2]), 0.17, 0.064, seg=16, axis="X", mat=D)
        bolt_ring(det, (sx * 0.694, TU_PITCH[1], TU_PITCH[2]), (sx, 0, 0), 0.13, 8, S, r=0.016, h=0.012)
        det.box((sx * 0.64, 0.38, 1.45), (0.03, 0.12, 0.10), mat=Y, rot=(-35, 0, 0))
    # top: phased-array sensor panel on a mast, beacon mast, dome
    det.cyl((-0.30, -0.72, 2.28), 0.03, 0.36, seg=8, axis="Z", mat=S)
    main.box((-0.30, -0.70, 2.50), (0.46, 0.06, 0.26), mat=D, rot=(-20, 0, 0))
    det.box((-0.30, -0.665, 2.455), (0.40, 0.012, 0.04), mat=R, rot=(-20, 0, 0))
    det.cyl((0.30, -0.80, 2.22), 0.02, 0.22, seg=8, axis="Z", mat=S)
    ball(det, (0.30, -0.80, 2.35), 0.04, R, seg=10, rings=6)
    ball(main, (0.22, -0.55, 2.12), 0.14, D, seg=12, rings=6, scale=(1, 1, 0.6))
    return main, det


def turret_pitch():
    main, det = MB(), MB()
    H, P, D, W, Y, S, R, N = M.H, M.P, M.D, M.W, M.Y, M.S, M.R, M.N
    px, py, pz = TU_PITCH
    det.cyl((0, py, pz), 0.085, 1.44, seg=12, axis="X", mat=S)
    main.cyl((0, py, pz), 0.33, 0.64, seg=12, axis="X", mat=H)
    front = [(0.16, 0.30, 0.32, 0.30, 0.25, 0.12, -0.12, -0.22),
             (0.56, 0.27, 0.30, 0.27, 0.18, 0.08, -0.10, -0.16),
             (0.62, 0.23, 0.26, 0.23, 0.14, 0.06, -0.08, -0.13)]
    main.loft([oct_sec(*s, z0=pz) for s in front], mat=P)
    lathe_closed(det, [(0.096, -0.03), (0.14, -0.03), (0.14, 0.03), (0.128, 0.048), (0.10, 0.048), (0.096, 0.03)],
                 center=(0, 0.62, pz + 0.0), seg=20, axis="Y", mat=D)
    for sx in (-1, 1):
        det.box((sx * 0.20, 0.62, pz + 0.085), (0.07, 0.03, 0.03), mat=D)
        det.box((sx * 0.20, 0.633, pz + 0.085), (0.05, 0.01, 0.014), mat=R)
        vent_slats(det, (sx * 0.30, 0.36, pz - 0.02), 0.26, 0.16, 3, D, depth=0.014, axis="X")
    strip(det, (-0.265, 0.30, pz + 0.230), (0.265, 0.30, pz + 0.230), 0.06, 0.012, W, normal=(0, 0.17, 0.98))
    for sx in (-1, 1):
        x0 = sx * TU_POD_X
        dy = TU_POD_DY
        pod = [(-0.62 + dy, 0.21, 0.24, 0.21, 0.19, 0.15, -0.15, -0.19),
               (-0.55 + dy, 0.23, 0.26, 0.23, 0.22, 0.18, -0.18, -0.22),
               (0.72 + dy, 0.23, 0.26, 0.23, 0.22, 0.18, -0.18, -0.22),
               (0.80 + dy, 0.22, 0.25, 0.22, 0.21, 0.17, -0.17, -0.21)]
        main.loft([oct_sec(*s, x0=x0, z0=pz) for s in pod], mat=H)
        det.cyl((sx * 0.715, py, pz), 0.16, 0.05, seg=14, axis="X", mat=D)
        xo = x0 + sx * 0.255
        quad_plate(main, (xo, -0.48 + dy, pz - 0.15), (xo, 0.66 + dy, pz - 0.15), (xo, 0.66 + dy, pz + 0.15), (xo, -0.48 + dy, pz + 0.15),
                   0.035, P, (sx, 0, 0))
        strip(det, (xo + sx * 0.035, -0.40 + dy, pz + 0.07), (xo + sx * 0.035, 0.58 + dy, pz + 0.07), 0.05, 0.012, W, normal=(sx, 0, 0))
        for (yy, zz) in ((-0.42, -0.10), (0.60, -0.10), (-0.42, 0.10), (0.60, 0.10), (0.09, -0.10)):
            bolt(det, (xo + sx * 0.035, yy + dy, pz + zz), (sx, 0, 0), S, r=0.018, h=0.012)
        quad_plate(main, (x0 - 0.20, -0.50 + dy, pz + 0.215), (x0 + 0.20, -0.50 + dy, pz + 0.215), (x0 + 0.20, 0.70 + dy, pz + 0.215),
                   (x0 - 0.20, 0.70 + dy, pz + 0.215), 0.03, P, (0, 0, 1))
        hazard_band(det, (x0 - sx * 0.22, 0.80 + dy), (x0 + sx * 0.22, 0.80 + dy), pz + 0.12, pz + 0.19, (0, 1, 0), Y, stripe=0.05,
                    slant=1.0)
        vent_slats(det, (x0, -0.625 + dy, pz), 0.36, 0.26, 4, D, depth=0.02, axis="Y")
    for (tx, idx) in TU_TUBES:
        tube(det, (tx, 0.82 + TU_POD_DY, pz), 0.106, 0.086, 0.13, P, mat_in=D, bore_depth=0.06, bore_mat=D, seg=20,
             lip=(0.118, 0.025))
        revolve_mats(det, [(0.072, 0.0), (0.066, 0.018), (0.046, 0.036), (0.020, 0.048), (0.003, 0.052)],
                     center=(tx, 0.825 + TU_POD_DY, pz), seg=16, axis="Y", mats=[N], cap_top=True, cap_bottom=True)
    return main, det


def turret_sensor():
    mb = MB()
    pz = TU_PITCH[2]
    revolve_mats(mb, [(0.094, 0.0), (0.094, 0.012), (0.076, 0.030), (0.044, 0.044), (0.004, 0.049)],
                 center=(0, 0.635, pz), seg=24, axis="Y", mats=[M.R], cap_top=True)
    mb.cyl((0, 0.683, pz), 0.030, 0.006, seg=12, axis="Y", mat=M.O)
    return mb


def build_turret(preview):
    reset_scene()
    enemy_materials()
    root = root_empty("Turret", 0.6)
    m, d = turret_base()
    part("Turret_Base", [(m, (0.012, 2), 32.0), (d, None, 40.0)], (0, 0, 0), root, (0, 0, 0))
    m, d = turret_yaw()
    yaw = part("Turret_Yaw", [(m, (0.01, 2), 32.0), (d, None, 40.0)], TU_YAW, root, (0, 0, 0))
    m, d = turret_pitch()
    pitch = part("Turret_Pitch", [(m, (0.008, 2), 32.0), (d, None, 40.0)], TU_PITCH, yaw, TU_YAW)
    part("Turret_Sensor", [(turret_sensor(), None, 40.0)], (0, 0.65, TU_PITCH[2]), pitch, TU_PITCH)
    for (tx, idx) in sorted(TU_TUBES, key=lambda t: t[1]):
        emp(f"Muzzle_{idx}", (tx, TU_MOUTH_Y, TU_PITCH[2]), (0, 1, 0), pitch, TU_PITCH, size=0.2)
    # self-checks: positive X rotation of the pitch node raises the barrels; the pitching assembly clears the
    # turntable / yaw housing over the whole useful range (-25..+75 degrees)
    for deg in (-25, 0, 30, 50, 75):
        pitch.rotation_euler = (math.radians(deg), 0, 0)
        bpy.context.view_layer.update()
        d = axis_of(bpy.data.objects["Muzzle_1"])
        if deg > 0:
            assert d.z > 0.4, f"turret pitch sign wrong: {tuple(d)}"
        mw = pitch.matrix_world
        low = min((mw @ v.co).z for v in pitch.data.vertices if (mw @ v.co).xy.length < 1.0)
        log(f"  pitch {deg:+d} deg: muzzle axis z={d.z:+.2f}, lowest point over the deck z={low:.2f} (deck top 1.30)")
        assert low > 1.30, f"turret pitch assembly hits the deck at {deg} deg"
    pitch.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()
    path = export_glb("turret.glb", [root])
    report(path)
    if preview:
        render_views("turret", [root], views=("front", "three_quarter", "three_quarter_back", "left"),
                     size=(800, 800), samples=24)
        pitch.rotation_euler = (math.radians(30), 0, 0)
        yaw.rotation_euler = (0, 0, math.radians(35))
        bpy.context.view_layer.update()
        render_views("turret_aim", [root], views=("three_quarter",), size=(800, 800), samples=24)
        pitch.rotation_euler = (0, 0, 0)
        yaw.rotation_euler = (0, 0, 0)


# ==============================================================================================
# BOSS  ("Armored Behemoth", ~6.3 m tall, root at the chest centre)
# ==============================================================================================
B_SH = (2.10, 0.0, 1.08)        # right shoulder pivot (left mirrored)
B_EL = (2.36, 0.15, -0.55)      # right elbow pivot
B_NECK = (0.0, 0.66, 1.62)
B_CORE = (0.0, 1.12, 0.12)
G_X = 2.36                      # gauntlet centre line x
G_Z = -0.80                     # gauntlet centre height
G_CANNON_Z = -0.88
G_MOUTH_Y = 2.60
G_ROT_Z = -0.02                 # rotary cannon axis height
G_ROT_MOUTH_Y = 2.24
POD_ROT = (18, 0, 0)            # shoulder missile pod tilt
POD_C = (2.36, 0.10, 2.14)

T_SQ = 0.74
T_SPECS = [
    (-1.15, 0.80, 0.66, -0.06),
    (-0.70, 1.06, 0.86, 0.02),
    (-0.05, 1.42, 1.04, 0.10),
    (0.60, 1.72, 1.14, 0.12),
    (1.12, 1.80, 1.10, 0.06),
    (1.46, 1.62, 1.00, -0.04),
    (1.72, 1.12, 0.80, -0.14),
    (1.86, 0.64, 0.60, -0.20),
]
WAIST_SPECS = [(-1.85, 0.70, 0.60, -0.22), (-1.10, 0.84, 0.70, -0.10)]
PELVIS_SPECS = [(-2.25, 1.00, 0.86, -0.30), (-1.98, 1.46, 1.16, -0.26), (-1.58, 1.34, 1.04, -0.20)]
COWL_SPECS = [(1.40, 1.10, 0.88, -0.16), (2.14, 0.96, 0.70, -0.30)]
PAUL = [(1.45, 2.06), (2.90, 1.93), (3.58, 1.30), (3.48, 0.64), (2.42, 0.44), (1.52, 1.20)]

# thrusters: index -> (mount/pivot, exhaust direction, size scale)
B_THR = {
    1: ((-0.86, -0.58, -1.80), (-0.16, -0.36, -0.92), 1.0),
    2: ((0.86, -0.58, -1.80), (0.16, -0.36, -0.92), 1.0),
    3: ((-1.55, -0.75, -1.55), (-0.55, -0.30, -0.78), 0.72),
    4: ((1.55, -0.75, -1.55), (0.55, -0.30, -0.78), 0.72),
}
THR_LEN = 1.78


def facet_quad(specs, t0, t1, z0, z1, off=0.0, sq=0.6, x0=0.0):
    """4 corners of a patch on a shell (for hazard stripes / decals): bottom t0, bottom t1, top t1, top t0."""
    return [shell_point(specs, t, z, sq=sq, x0=x0, off=off)[0] for (t, z) in ((t0, z0), (t1, z0), (t1, z1), (t0, z1))]


def rivet_row(det, specs, t0, t1, z, off, count, mat, sq, r=0.035):
    for i in range(count):
        t = t0 + (t1 - t0) * (i + 0.5) / count
        p, nn = shell_point(specs, t, z, sq=sq, off=off)
        bolt(det, p, nn, mat, r=r, h=0.03)


def boss_torso():
    main, det = MB(), MB()
    BP, BD, BB, S, Y, W, O, R, SD = M.BP, M.BD, M.BB, M.S, M.Y, M.W, M.O, M.R, M.SD
    sq = T_SQ
    # ---- core body shell (black steel) + waist + pelvis skirt
    shell(main, T_SPECS, BD, n=8, sq=sq)
    shell(main, WAIST_SPECS, BD, n=8, sq=0.6)
    shell(main, PELVIS_SPECS, BP, n=8, sq=0.6)
    for z in (-1.30, -1.52):
        det.cyl((0, -0.16, z), 0.86, 0.08, seg=16, axis="Z", mat=S, scale=(1.0, 0.84))
    # ---- chest: layered conforming armour (pecs, thick upper tier with brass edge + rivets), abdomen, flanks, back
    for (t0, t1) in ((0.35, 1.44), (1.56, 2.65)):
        shell_patch(main, T_SPECS, t0, t1, 0.58, 1.40, 0.13, BP, sq=sq)
    for (t0, t1) in ((0.05, 1.10), (1.90, 2.95)):
        shell_patch(main, T_SPECS, t0, t1, 1.06, 1.66, 0.22, BP, sq=sq)
        shell_patch(det, T_SPECS, t0 + 0.02, t1 - 0.02, 1.04, 1.09, 0.245, BB, sq=sq)
        rivet_row(det, T_SPECS, t0 + 0.08, t1 - 0.08, 1.16, 0.22, 5, S, sq)
    for (z0, z1) in ((-0.44, -0.14), (-0.78, -0.50), (-1.12, -0.86)):
        shell_patch(main, T_SPECS, 0.55, 2.45, z0, z1, 0.10, BP, sq=sq)
        shell_patch(det, T_SPECS, 0.62, 2.38, z1 - 0.035, z1, 0.115, BB, sq=sq)
    for (t0, t1) in ((6.85, 8.15), (2.85, 4.15)):
        shell_patch(main, T_SPECS, t0, t1, -0.62, 0.98, 0.12, BP, sq=sq)
        shell_patch(det, T_SPECS, t0 + 0.05, t1 - 0.05, 0.98, 1.03, 0.13, BB, sq=sq)
        q = facet_quad(T_SPECS, t0 + 0.25, t1 - 0.25, -0.52, -0.30, off=0.12, sq=sq)
        nn = shell_point(T_SPECS, (t0 + t1) / 2, -0.4, sq=sq)[1]
        hazard_quad(det, *q, Y, nn, n=6, lean=0.18, fill=0.5, depth=0.012)
        # flank vents above the hazard band
        q = facet_quad(T_SPECS, t0 + 0.30, t1 - 0.30, 0.05, 0.62, off=0.10, sq=sq)
        quad_plate(main, *q, 0.05, SD, nn)
        q = facet_quad(T_SPECS, t0 + 0.33, t1 - 0.33, 0.09, 0.58, off=0.14, sq=sq)
        quad_plate(det, *q, 0.012, O, nn)
        for i in range(5):
            v0 = 0.12 + i * 0.105
            qq = facet_quad(T_SPECS, t0 + 0.34, t1 - 0.34, v0, v0 + 0.05, off=0.14, sq=sq)
            quad_plate(det, *qq, 0.03, BD, nn)
    shell_patch(main, T_SPECS, 4.35, 6.65, -0.95, 1.52, 0.10, BP, sq=sq)
    # trapezius yoke plates rising toward the pauldrons
    for sx in (-1, 1):
        quad_plate(main, (sx * 0.55, -0.55, 1.80), (sx * 1.55, -0.60, 1.72), (sx * 1.55, 0.55, 1.62), (sx * 0.55, 0.45, 1.74),
                   0.12, BP, (0, 0, 1))
        strip(det, (sx * 0.60, 0.50, 1.86), (sx * 1.52, 0.60, 1.74), 0.06, 0.04, BB, normal=(0, 0.3, 1))
    # ---- high cowl collar around the head (open at the front)
    shell_patch(main, COWL_SPECS, 2.55, 8.45, 1.40, 2.14, 0.16, BP, sq=0.6)
    shell_patch(det, COWL_SPECS, 2.58, 8.42, 2.09, 2.14, 0.18, BB, sq=0.6)
    main.cyl((0, B_NECK[1] - 0.06, 1.62), 0.34, 0.40, seg=10, axis="Z", mat=BD)
    # ---- core housing: octagonal brass frame + dark back plate + cage bars
    cx, cy, cz = B_CORE
    lathe_closed(main, [(0.46, -0.12), (0.68, -0.12), (0.68, 0.20), (0.62, 0.30), (0.48, 0.30), (0.46, 0.20)],
                 center=(cx, cy, cz), seg=8, axis="Y", mat=BB, phase=math.pi / 8)
    det.cyl((cx, cy - 0.06, cz), 0.47, 0.10, seg=16, axis="Y", mat=BD)
    for bx in (-0.22, 0.0, 0.22):
        strip(det, (cx + bx, cy + 0.30, cz - 0.50), (cx + bx, cy + 0.30, cz + 0.50), 0.06, 0.06, BD, normal=(0, 1, 0))
    strip(det, (cx - 0.50, cy + 0.345, cz), (cx + 0.50, cy + 0.345, cz), 0.06, 0.05, BD, normal=(0, 1, 0))
    for a in range(8):
        ang = math.pi / 8 + a * math.pi / 4
        bolt(det, (cx + math.cos(ang) * 0.57, cy + 0.30, cz + math.sin(ang) * 0.57), (0, 1, 0), S, r=0.035, h=0.03)
    # chevron keel plates below the core (point down toward the waist)
    for sx in (-1, 1):
        p0, n0 = shell_point(T_SPECS, 1.5, -0.46, sq=sq, off=0.10)
        quad_plate(main, (sx * 0.04, p0.y + 0.02, -0.62), (sx * 0.52, p0.y - 0.02, -0.40), (sx * 0.52, p0.y + 0.0, -0.28),
                   (sx * 0.04, p0.y + 0.04, -0.46), 0.08, BB, (0, 1, 0))
    # ---- backpack: reactor block, vents, smoke stacks, pipes to the shoulders
    main.box((0, -1.30, 0.80), (2.20, 0.80, 1.70), mat=BP, taper=(0.92, 0.85), bottom_scale=(0.86, 0.9))
    main.box((0, -1.32, 1.70), (1.90, 0.66, 0.14), mat=BD)
    main.box((0, -1.72, 0.55), (1.50, 0.12, 0.90), mat=BD)
    for sx in (-1, 1):
        quad_plate(main, (sx * 1.10, -1.62, 0.10), (sx * 1.10, -0.98, 0.10), (sx * 1.04, -0.98, 1.55), (sx * 1.04, -1.58, 1.55),
                   0.06, BD, (sx, 0, 0))
        hazard_quad(det, (sx * 1.162, -1.55, 0.18), (sx * 1.162, -1.05, 0.18), (sx * 1.162, -1.05, 0.42),
                    (sx * 1.162, -1.55, 0.42), Y, (sx, 0, 0), n=5, lean=0.2, fill=0.5, depth=0.012)
    for i in range(4):
        z = 0.22 + i * 0.22
        det.box((0, -1.785, z), (1.30, 0.03, 0.07), mat=O)
        det.box((0, -1.80, z + 0.05), (1.36, 0.05, 0.05), mat=BP, rot=(30, 0, 0))
    for sx in (-1, 1):
        base = Vector((sx * 0.62, -1.50, 1.30))
        rot = (12, 0, sx * -6)
        Rm = rot_matrix(rot)
        main.cyl(base + Rm @ Vector((0, 0, 0.62)), 0.20, 1.25, seg=12, axis="Z", mat=BD, rot=rot)
        for hh in (0.60, 1.02):
            lathe_closed(det, [(0.20, -0.04), (0.235, -0.04), (0.235, 0.04), (0.20, 0.04)], center=base + Rm @ Vector((0, 0, hh)),
                         seg=12, axis="Z", mat=BB, rot=rot)
        tube(det, base + Rm @ Vector((0, 0, 1.28)), 0.24, 0.16, 0.14, BD, axis="Z", rot=rot, seg=12, bore_depth=0.10, bore_mat=O)
        # coolant pipes from the backpack to the shoulder joints
        a = Vector((sx * 0.95, -1.05, 1.52))
        b = Vector((sx * 1.55, -0.70, 1.62))
        c = Vector((sx * 1.85, -0.35, 1.30))
        for (p, q) in ((a, b), (b, c)):
            bar(det, p, q, 0.11, 0.11, SD)
        for p in (a, b):
            ball(det, p, 0.085, BB, seg=8, rings=6)
    # ---- pelvis front plate with hazard stripes, hip struts to the side thrusters
    shell_patch(main, PELVIS_SPECS, 1.05, 1.95, -2.20, -1.62, 0.07, BD, sq=0.6)
    q = facet_quad(PELVIS_SPECS, 1.15, 1.85, -2.14, -1.70, off=0.07, sq=0.6)
    hazard_quad(det, *q, Y, (0, 1, 0.25), n=7, lean=0.14, fill=0.5, depth=0.012)
    for (t0, t1) in ((6.9, 8.1), (2.9, 4.1)):
        shell_patch(main, PELVIS_SPECS, t0, t1, -2.18, -1.64, 0.07, BD, sq=0.6)
        rivet_row(det, PELVIS_SPECS, t0 + 0.1, t1 - 0.1, -1.72, 0.07, 4, BB, 0.6, r=0.03)
    for k in (3, 4):
        mnt, d, sc = B_THR[k]
        sx = 1 if mnt[0] > 0 else -1
        bar(main, (sx * 1.12, -0.55, -1.80), Vector(mnt) + Vector((-sx * 0.06, 0.02, 0.06)), 0.34, 0.30, BD)
    # ---- thruster cage: keel spine + spike, lower brass ring, converging ribs, pod struts
    main.cyl((0, -0.30, -2.70), 0.26, 1.00, seg=8, axis="Z", mat=BD, r_top=0.36, rot=(0, 0, 22.5))
    revolve_mats(main, [(0.26, 0.0), (0.17, -0.22), (0.02, -0.48)], center=(0, -0.30, -3.20), seg=8, mats=[BP, BP],
                 cap_bottom=False, phase=math.pi / 8)
    lathe_closed(det, [(0.50, -0.05), (0.60, -0.05), (0.60, 0.05), (0.50, 0.05)], center=(0, -0.30, -2.98), seg=16, axis="Z",
                 mat=BB, scale=(1.35, 1.0))
    for sx in (-1, 1):
        bar(main, (sx * 0.60, 0.50, -2.16), (sx * 0.34, 0.20, -2.97), 0.12, 0.12, BB)
        bar(main, (sx * 0.30, -0.30, -2.30), (sx * 0.62, -0.62, -2.62), 0.14, 0.14, BD)
    bar(main, (0.0, 0.56, -2.16), (0.0, 0.26, -2.97), 0.12, 0.12, BB)
    return main, det


def boss_head():
    main, det = MB(), MB()
    BP, BD, BB, R, C = M.BP, M.BD, M.BB, M.R, M.C
    z0 = 1.86
    secs = [(0.40, 0.26, 0.36, 0.28, 0.22, 0.12, -0.12, -0.22),
            (1.02, 0.24, 0.35, 0.26, 0.18, 0.10, -0.12, -0.20),
            (1.30, 0.15, 0.24, 0.17, 0.08, 0.04, -0.10, -0.15)]
    main.loft([oct_sec(*s, z0=z0) for s in secs], mat=BD)
    # hood: top plate with a pointed brow overhanging the visor, side blinkers reaching past the face, chin guard
    for sx in (-1, 1):
        quad_plate(main, (0, 0.30, 2.14), (sx * 0.42, 0.30, 2.09), (sx * 0.38, 1.22, 2.01), (0, 1.48, 1.96), 0.07, BP, (0, 0, 1))
        quad_plate(main, (sx * 0.34, 0.48, 2.01), (sx * 0.34, 1.36, 1.95), (sx * 0.30, 1.30, 1.70), (sx * 0.34, 0.48, 1.66),
                   0.06, BP, (sx, 0, 0))
        strip(det, (sx * 0.02, 1.44, 2.04), (sx * 0.36, 1.21, 2.085), 0.035, 0.03, BB, normal=(0, 0.3, 1))
        main.prism([(0.0, 0.0), (0.46, 0.0), (-0.50, 0.20), (-0.78, 0.22)], -0.035, 0.035, mat=BD, plane="YZ",
                   rot=(0, sx * 38, 0), center=(sx * 0.34, 0.50, 2.04))
        # angry V visor slits under the brow
        strip(det, (sx * 0.205, 1.305, 1.890), (sx * 0.020, 1.305, 1.815), 0.065, 0.02, R, normal=(0, 1, 0))
        det.box((sx * 0.13, 1.31, 1.735), (0.10, 0.02, 0.02), mat=BB)
    quad_plate(main, (-0.20, 1.18, 1.66), (0.20, 1.18, 1.66), (0.14, 1.36, 1.72), (-0.14, 1.36, 1.72), 0.06, BP, (0, 0.3, -1))
    return main, det


def boss_arm_R():
    main, det = MB(), MB()
    BP, BD, BB, S, Y, W, N, SD = M.BP, M.BD, M.BB, M.S, M.Y, M.W, M.N, M.SD
    ball(main, B_SH, 0.56, BD, seg=14, rings=8)
    # ---- massive angular pauldron (lofted front->back) + lames + brass trims + hazard face + horn
    cxp = sum(p[0] for p in PAUL) / len(PAUL)
    czp = sum(p[1] for p in PAUL) / len(PAUL)

    def sec(y, s, dz=0.0):
        return [V(cxp + (x - cxp) * s, y, czp + (z - czp) * s + dz) for (x, z) in PAUL]

    secs = [sec(-1.14, 0.80), sec(-0.84, 1.0), sec(0.74, 1.0), sec(1.08, 0.80, -0.04)]
    main.loft(secs, mat=BP)
    strip(det, secs[1][1], secs[2][1], 0.12, 0.06, BB, normal=(0.35, 0, 1))
    strip(det, secs[1][2], secs[2][2], 0.10, 0.06, BB, normal=(1, 0, 0.1))
    f = secs[3]
    hz = [f[5].lerp(f[4], 0.15), f[2].lerp(f[3], 0.15), f[2].lerp(f[1], 0.2), f[5].lerp(f[0], 0.2)]
    hazard_quad(det, hz[0], hz[1], hz[2], hz[3], Y, (0, 1, 0), n=6, lean=0.18, fill=0.5, depth=0.012)
    strip(det, f[5].lerp(f[4], 0.35) + Vector((0.10, 0.004, 0.02)), f[2].lerp(f[3], 0.35) + Vector((-0.10, 0.004, 0.02)),
          0.05, 0.02, M.R, normal=(0, 1, 0))
    for p in (f[0].lerp(f[1], 0.1), f[0].lerp(f[1], 0.9), f[4].lerp(f[3], 0.1), f[4].lerp(f[3], 0.9)):
        bolt(det, p + Vector((0, 0.0, -0.06 if p.z > 1.5 else 0.06)), (0, 1, 0), S, r=0.04, h=0.03)
    # outer side: dark armour plate with rivets + red running light
    q = [secs[1][2].lerp(secs[1][3], 0.12) + Vector((0, 0.10, 0)), secs[2][2].lerp(secs[2][3], 0.12) + Vector((0, -0.10, 0)),
         secs[2][2].lerp(secs[2][3], 0.88) + Vector((0, -0.10, 0)), secs[1][2].lerp(secs[1][3], 0.88) + Vector((0, 0.10, 0))]
    sn = (secs[1][3] - secs[1][2]).cross(Vector((0, 1, 0))).normalized()
    if sn.x < 0:
        sn = -sn
    quad_plate(main, *[p - sn * 0.01 for p in q], 0.06, BD, sn)
    for p in q:
        cc = p.lerp(sum(q, Vector()) / 4, 0.12)
        bolt(det, cc + sn * 0.05, sn, BB, r=0.04, h=0.03)
    strip(det, q[0].lerp(q[3], 0.5) + sn * 0.05 + Vector((0, 0.12, 0)), q[1].lerp(q[2], 0.5) + sn * 0.05 + Vector((0, -0.12, 0)),
          0.05, 0.02, M.R, normal=sn)
    # rear exhaust grille
    b = secs[0]
    quad_plate(main, b[5].lerp(b[2], 0.2), b[5].lerp(b[2], 0.8), b[0].lerp(b[1], 0.8), b[0].lerp(b[1], 0.2), 0.04, SD, (0, -1, 0))
    # swept horn at the outer rear top
    main.prism([(-0.30, 0.0), (0.50, 0.0), (-0.45, 0.62), (-1.05, 0.80), (-0.80, 0.30)], -0.07, 0.07, mat=BP, plane="YZ",
               rot=(0, 18, 0), center=(3.05, -0.10, 1.74))
    det.prism([(-0.62, 0.52), (-0.45, 0.64), (-1.07, 0.83), (-1.02, 0.70)], -0.075, 0.075, mat=BB, plane="YZ",
              rot=(0, 18, 0), center=(3.05, -0.10, 1.74))
    # lames (overlapping skirts) under the outer edge
    for k, (zc, xc, ang, mat) in enumerate(((0.52, 3.30, 16, BD), (0.16, 3.16, 12, BP))):
        main.box((xc, -0.05, zc), (0.16, 1.70 - 0.2 * k, 0.42), mat=mat, rot=(0, ang, 0), bottom_scale=(1.0, 0.92))
    # ---- upper arm: dark sleeve, front armour plate, hydraulic pistons, elbow joint
    UA = [(-0.52, 0.40, 0.42, 0.14), (0.00, 0.47, 0.46, 0.07), (0.72, 0.46, 0.44, 0.0)]
    ux = B_EL[0] - 0.04
    shell(main, UA, BD, n=8, sq=0.6, x0=ux)
    shell_patch(main, UA, 0.55, 2.45, -0.36, 0.40, 0.09, BP, sq=0.6, x0=ux)
    shell_patch(det, UA, 0.60, 2.40, -0.40, -0.35, 0.10, BB, sq=0.6, x0=ux)
    for dx in (-0.30, 0.30):
        det.cyl((ux + dx, -0.42, 0.10), 0.07, 0.80, seg=10, axis="Z", mat=BD)
        det.cyl((ux + dx, -0.42, -0.42), 0.045, 0.40, seg=10, axis="Z", mat=S)
    ex, ey, ez = B_EL
    main.cyl(B_EL, 0.46, 0.96, seg=12, axis="X", mat=BD)
    for sx in (-1, 1):
        det.cyl((ex + sx * 0.49, ey, ez), 0.30, 0.05, seg=12, axis="X", mat=BB)
    # ---- shoulder missile pod (Hardpoint_R1) on a bracket on the pauldron
    Rm = rot_matrix(POD_ROT)
    pc = Vector(POD_C)
    main.box((pc.x, 0.0, 1.98), (0.50, 0.70, 0.22), mat=BD)
    main.box(pc, (0.86, 1.26, 0.54), mat=BP, rot=POD_ROT)
    main.box(pc + Rm @ Vector((0, -0.05, 0.30)), (0.70, 1.00, 0.08), mat=BD, rot=POD_ROT)
    det.box(pc + Rm @ Vector((0.435, 0.0, 0.0)), (0.02, 1.0, 0.10), mat=W, rot=POD_ROT)
    det.box(pc + Rm @ Vector((-0.435, 0.0, 0.0)), (0.02, 1.0, 0.10), mat=W, rot=POD_ROT)
    for ix in (-0.27, 0.0, 0.27):
        for iz in (-0.125, 0.125):
            c = pc + Rm @ Vector((ix, 0.62, iz))
            tube(det, c, 0.11, 0.086, 0.10, BD, axis="Y", rot=POD_ROT, seg=12, bore_depth=0.05, bore_mat=BD)
            revolve_mats(det, [(0.07, 0.0), (0.06, 0.02), (0.035, 0.038), (0.004, 0.046)], center=c,
                         seg=10, axis="Y", rot=POD_ROT, mats=[N], cap_bottom=True, cap_top=True)
    return main, det


def boss_forearm_R():
    main, det = MB(), MB()
    BP, BD, BB, S, Y, W, O, SD = M.BP, M.BD, M.BB, M.S, M.Y, M.W, M.O, M.SD
    x0, z0 = G_X, G_Z
    secs = [(-0.58, 0.40, 0.50, 0.40, 0.50, 0.28, -0.30, -0.44),
            (-0.32, 0.50, 0.64, 0.50, 0.62, 0.40, -0.40, -0.56),
            (1.36, 0.52, 0.66, 0.50, 0.60, 0.38, -0.42, -0.58),
            (1.78, 0.42, 0.55, 0.40, 0.48, 0.30, -0.36, -0.48)]
    main.loft([oct_sec(*s, x0=x0, z0=z0) for s in secs], mat=BD)
    # top armour plate with brass edges + rivets, outer side plate with hazard stripes, inner vents
    quad_plate(main, (x0 - 0.44, -0.24, z0 + 0.595), (x0 + 0.44, -0.24, z0 + 0.595), (x0 + 0.46, 1.32, z0 + 0.575),
               (x0 - 0.46, 1.32, z0 + 0.575), 0.08, BP, (0, 0, 1))
    for sx in (-1, 1):
        strip(det, (x0 + sx * 0.45, -0.22, z0 + 0.66), (x0 + sx * 0.47, 1.30, z0 + 0.64), 0.05, 0.05, BB)
        for yy in (-0.10, 0.25):
            bolt(det, (x0 + sx * 0.36, yy, z0 + 0.672), (0, 0, 1), S, r=0.035, h=0.03)
    xo = x0 + 0.65
    quad_plate(main, (xo, -0.22, z0 - 0.36), (xo, 1.32, z0 - 0.38), (xo, 1.32, z0 + 0.34), (xo, -0.22, z0 + 0.36), 0.07, BP, (1, 0, 0))
    hazard_quad(det, (xo + 0.07, 0.84, z0 - 0.30), (xo + 0.07, 1.28, z0 - 0.31), (xo + 0.07, 1.28, z0 + 0.28),
                (xo + 0.07, 0.84, z0 + 0.29), Y, (1, 0, 0), n=4, lean=0.3, fill=0.5, depth=0.012)
    for (yy, zz) in ((-0.12, -0.26), (-0.12, 0.26), (0.62, -0.28), (0.62, 0.28)):
        bolt(det, (xo + 0.07, yy, z0 + zz), (1, 0, 0), S, r=0.035, h=0.03)
    xi = x0 - 0.65
    main.box((xi, 0.55, z0), (0.06, 0.90, 0.56), mat=SD)
    det.box((xi - 0.032, 0.55, z0), (0.012, 0.80, 0.46), mat=O)
    vent_slats(det, (xi - 0.045, 0.55, z0), 0.84, 0.50, 5, BD, depth=0.035, axis="X", gap=0.62)
    # ---- main cannon: barrel with glowing bore, cooling rings, octagonal muzzle brake (Hardpoint_R2)
    tube(det, (x0, 2.06, G_CANNON_Z), 0.30, 0.20, 1.0, SD, mat_in=BD, bore_depth=0.55, bore_mat=O, seg=16)
    for yy in (1.90, 2.04, 2.18):
        lathe_closed(det, [(0.295, -0.03), (0.34, -0.03), (0.34, 0.03), (0.295, 0.03)], center=(x0, yy, G_CANNON_Z), seg=16,
                     axis="Y", mat=BB)
    tube(main, (x0, G_MOUTH_Y - 0.12, G_CANNON_Z), 0.41, 0.21, 0.24, BD, axis="Y", seg=8, bore_depth=0.2, bore_mat=BD)
    for sx in (-1, 1):
        det.box((x0 + sx * 0.37, G_MOUTH_Y - 0.12, G_CANNON_Z), (0.12, 0.08, 0.30), mat=SD)
    hazard_quad(det, (x0 - 0.30, 1.785, z0 + 0.30), (x0 + 0.30, 1.785, z0 + 0.30), (x0 + 0.26, 1.785, z0 + 0.44),
                (x0 - 0.26, 1.785, z0 + 0.44), Y, (0, 1, 0), n=5, lean=0.15, fill=0.5, depth=0.012)
    # ---- rotary cannon on top (Hardpoint_R3)
    rz = G_ROT_Z
    main.box((x0, 1.15, rz - 0.13), (0.24, 0.62, 0.12), mat=BD)
    main.cyl((x0, 1.12, rz), 0.19, 0.72, seg=12, axis="Y", mat=BP)
    det.cyl((x0, 1.52, rz), 0.13, 0.10, seg=12, axis="Y", mat=BD)
    for k in range(6):
        a = 2 * math.pi * k / 6
        det.cyl((x0 + math.cos(a) * 0.09, 1.88, rz + math.sin(a) * 0.09), 0.03, 0.68, seg=8, axis="Y", mat=S)
    lathe_closed(det, [(0.10, -0.04), (0.16, -0.04), (0.16, 0.04), (0.10, 0.04)], center=(x0, 2.10, rz), seg=12, axis="Y",
                 mat=BD)
    # ---- claws under the gauntlet + elbow spike behind
    for dx in (-0.32, 0.0, 0.32):
        main.prism([(0.95, 0.0), (1.75, 0.0), (2.40, -0.46), (2.02, -0.42)], -0.06, 0.06, mat=BP, plane="YZ",
                   center=(x0 + dx, 0.0, z0 - 0.50))
        det.prism([(2.12, -0.36), (2.26, -0.40), (2.40, -0.465), (2.20, -0.445)], -0.065, 0.065, mat=BB, plane="YZ",
                  center=(x0 + dx, 0.0, z0 - 0.50))
    main.prism([(0.0, 0.0), (0.0, 0.55), (-0.75, -0.10), (-0.55, -0.30)], -0.10, 0.10, mat=BP, plane="YZ",
               center=(x0, -0.40, z0 + 0.05))
    return main, det


def thruster_pod(scale):
    """local frame: mount at the origin, exhaust toward -Z.  Returns (main, det, glow) MBs."""
    main, det = MB(), MB()
    BP, BD, BB, O, C, SD = M.BP, M.BD, M.BB, M.O, M.C, M.SD
    k = scale
    main.cyl((0, 0, 0.02 * k), 0.36 * k, 0.28 * k, seg=12, axis="Z", mat=BD)
    revolve_mats(main, [(0.30 * k, 0.14 * k), (0.52 * k, 0.02 * k), (0.62 * k, -0.26 * k), (0.62 * k, -0.96 * k),
                        (0.54 * k, -1.18 * k)], seg=16, mats=[BP, BP, BP, BP], cap_bottom=True, cap_top=True)
    for zz in (-0.32, -0.90):
        lathe_closed(det, [(0.61 * k, (zz - 0.04) * k), (0.66 * k, (zz - 0.04) * k), (0.66 * k, (zz + 0.04) * k),
                           (0.61 * k, (zz + 0.04) * k)], seg=16, axis="Z", mat=BB)
    for i in range(8):
        a = 2 * math.pi * (i + 0.5) / 8
        d = Vector((math.cos(a), math.sin(a), 0))
        det.box(d * 0.66 * k + Vector((0, 0, -0.61 * k)), (0.10 * k, 0.05 * k, 0.50 * k), mat=BD, rot=(0, 0, math.degrees(a)))
    lathe_closed(main, [(0.42 * k, -1.12 * k), (0.57 * k, -1.12 * k), (0.68 * k, -1.66 * k), (0.64 * k, -1.74 * k),
                        (0.55 * k, -1.70 * k), (0.44 * k, -1.30 * k)], seg=16, axis="Z", mat=[SD, SD, BD, BD, SD, SD])
    glow = MB()
    glow.cyl((0, 0, -1.26 * k), 0.44 * k, 0.04 * k, seg=16, axis="Z", mat=O)
    revolve_mats(glow, [(0.40 * k, -1.29 * k), (0.26 * k, -1.40 * k), (0.02 * k, -1.46 * k)], seg=16, mats=[C, C],
                 cap_bottom=False, cap_top=False)
    return main, det, glow


def build_boss(preview):
    reset_scene()
    boss_materials()
    root = root_empty("Boss", 1.0)
    m, d = boss_torso()
    torso = part("Boss_Torso", [(m, (0.03, 2), 32.0), (d, None, 40.0)], (0, 0, 0), root, (0, 0, 0))
    m, d = boss_head()
    part("Boss_Head", [(m, (0.02, 2), 32.0), (d, None, 40.0)], B_NECK, torso, (0, 0, 0))
    core = MB()
    ball(core, (B_CORE[0], B_CORE[1] - 0.12, B_CORE[2]), 0.36, M.C, seg=20, rings=12)
    part("Boss_Core", [(core, None, 60.0)], B_CORE, torso, (0, 0, 0))
    # arms (built for +X, mirrored)
    m, d = boss_arm_R()
    mL, dL = m.mirrored_x(), d.mirrored_x()
    shR = Vector(B_SH)
    shL = Vector((-shR.x, shR.y, shR.z))
    arm_R = part("Boss_Arm_R", [(m, (0.03, 2), 32.0), (d, None, 40.0)], shR, torso, (0, 0, 0))
    arm_L = part("Boss_Arm_L", [(mL, (0.03, 2), 32.0), (dL, None, 40.0)], shL, torso, (0, 0, 0))
    m, d = boss_forearm_R()
    mL, dL = m.mirrored_x(), d.mirrored_x()
    elR = Vector(B_EL)
    elL = Vector((-elR.x, elR.y, elR.z))
    fo_R = part("Boss_Forearm_R", [(m, (0.03, 2), 32.0), (d, None, 40.0)], elR, arm_R, shR)
    fo_L = part("Boss_Forearm_L", [(mL, (0.03, 2), 32.0), (dL, None, 40.0)], elL, arm_L, shL)
    # thrusters
    for k in sorted(B_THR):
        mnt, dirv, sc = B_THR[k]
        dirv = Vector(dirv).normalized()
        q = Vector((0, 0, -1)).rotation_difference(dirv)
        T = Matrix.Translation(Vector(mnt)) @ q.to_matrix().to_4x4()
        m, d, g = thruster_pod(sc)
        for mb in (m, d, g):
            mb.transform(T)
        thr = part(f"Boss_Thruster_{k}", [(m, (0.02, 2), 32.0), (d, None, 40.0), (g, None, 60.0)], mnt, torso, (0, 0, 0))
        exitp = Vector(mnt) + dirv * THR_LEN * sc
        emp(f"Nozzle_{k}", exitp, dirv, thr, mnt, size=0.5)
    # hardpoints: 1 = shoulder missile pod (on the arm), 2 = gauntlet cannon, 3 = rotary cannon (on the forearm)
    Rm = rot_matrix(POD_ROT)
    pod_dir = Rm @ Vector((0, 1, 0))
    for sgn, side, arm, fo, shp, elp in ((1, "R", arm_R, fo_R, shR, elR), (-1, "L", arm_L, fo_L, shL, elL)):
        pc = Vector((sgn * POD_C[0], POD_C[1], POD_C[2])) + Rm @ Vector((0, 0.68, 0))
        emp(f"Hardpoint_{side}1", pc, pod_dir, arm, shp, size=0.4)
        emp(f"Hardpoint_{side}2", (sgn * G_X, G_MOUTH_Y + 0.02, G_CANNON_Z), (0, 1, 0), fo, elp, size=0.4)
        emp(f"Hardpoint_{side}3", (sgn * G_X, G_ROT_MOUTH_Y + 0.02, G_ROT_Z), (0, 1, 0), fo, elp, size=0.3)
    e = add_empty("Shield_Center", (0, 0, 0), parent=torso, display="SPHERE", size=0.5)
    del e
    path = export_glb("boss.glb", [root])
    report(path)
    mn, mx = world_bbox([o for o in [root] + descendants(root) if o.type == "MESH"])
    log(f"  boss bbox (Blender) min={tuple(round(v, 2) for v in mn)} max={tuple(round(v, 2) for v in mx)} "
        f"size={tuple(round(v, 2) for v in (mx - mn))}")
    if preview:
        render_views("boss", [root], views=("front", "three_quarter", "three_quarter_back", "left", "low"),
                     size=(900, 900), samples=24)
        if "--closeups" in script_args():
            render_views("boss_cu_head", [bpy.data.objects["Boss_Head"]], views=("front", "three_quarter"), size=(700, 700),
                         samples=24, distance_scale=1.6)
            render_views("boss_cu_arm", [fo_R], views=("three_quarter", "right"), size=(700, 700), samples=24)
            render_views("boss_cu_thr", [bpy.data.objects["Boss_Thruster_2"]], views=("low", "three_quarter_back"),
                         size=(700, 700), samples=24, distance_scale=1.3)
            render_views("boss_extra", [root], views=("top", "under_back"), size=(900, 900), samples=24,
                         custom_views={"under_back": (340, -35, 1.0)})


# ==============================================================================================
# BOSS SHIELD
# ==============================================================================================
def uv_sphere_mesh(name, r=1.0, seg=48, rings=24):
    """UV sphere built vertex by vertex (deterministic order, unlike bmesh.ops.create_uvsphere), poles on Z,
    outward winding, smooth, UVs: u = longitude 0..1 (seam at +X), v = latitude 0 (bottom) .. 1 (top)."""
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    top = bm.verts.new((0.0, 0.0, r))
    ringv = []
    for k in range(1, rings):
        th = math.pi * k / rings
        z, rho = r * math.cos(th), r * math.sin(th)
        ringv.append([bm.verts.new((rho * math.cos(2 * math.pi * i / seg), rho * math.sin(2 * math.pi * i / seg), z))
                      for i in range(seg)])
    bot = bm.verts.new((0.0, 0.0, -r))

    def face(vs, uvs):
        f = bm.faces.new(vs)
        f.smooth = True
        for loop, uv in zip(f.loops, uvs):
            loop[uvl].uv = uv

    for i in range(seg):
        j = (i + 1) % seg
        u0, u1, um = i / seg, (i + 1) / seg, (i + 0.5) / seg
        face([top, ringv[0][i], ringv[0][j]], [(um, 1.0), (u0, 1.0 - 1.0 / rings), (u1, 1.0 - 1.0 / rings)])
        for k in range(rings - 2):
            va, vb = 1.0 - (k + 1) / rings, 1.0 - (k + 2) / rings
            face([ringv[k][i], ringv[k + 1][i], ringv[k + 1][j], ringv[k][j]], [(u0, va), (u0, vb), (u1, vb), (u1, va)])
        face([ringv[-1][i], bot, ringv[-1][j]], [(u0, 1.0 / rings), (um, 0.0), (u1, 1.0 / rings)])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def build_boss_shield(preview):
    reset_scene()
    mat = make_material("BossShield_Mat", color="#5FE3FF", metallic=0.0, roughness=0.12, emission="#38D6FF",
                        emission_strength=1.2, alpha=0.3, double_sided=True)
    mesh = uv_sphere_mesh("BossShield", r=1.0, seg=48, rings=24)
    mesh.materials.append(mat)
    obj = bpy.data.objects.new("BossShield", mesh)
    bpy.context.scene.collection.objects.link(obj)
    uv = mesh.uv_layers[0].data
    us = [d.uv[0] for d in uv]
    vs = [d.uv[1] for d in uv]
    log(f"  shield uv range u=[{min(us):.3f},{max(us):.3f}] v=[{min(vs):.3f},{max(vs):.3f}]")
    path = export_glb("boss_shield.glb", [obj])
    report(path)
    if preview:
        render_views("shield", [obj], views=("front", "three_quarter"), size=(600, 600), samples=16)


# ==============================================================================================
BUILDERS = {
    "drone": build_drone,
    "turret": build_turret,
    "boss": build_boss,
    "boss_shield": build_boss_shield,
}


def main():
    args = script_args()
    preview = "--preview" in args
    only = None
    for i, a in enumerate(args):
        if a == "--only" and i + 1 < len(args):
            only = set(args[i + 1].split(","))
        elif a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
    for key, fn in BUILDERS.items():
        if only and key not in only:
            continue
        log(f"=== building {key}")
        fn(preview)


main()

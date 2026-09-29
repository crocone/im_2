"""Player powered armour -> public/assets/player.glb

Original angular, layered-plate flight armour (~2.0 m tall).  Rest pose = arms hanging down, identity rotations on every
joint.  Geometry is authored in rest-pose world coordinates (Blender: +Y forward, +Z up); every articulated part gets its
pivot at the joint (common.add_part).

Hierarchy (contract: tools/asset-contract.json -> player):
  PlayerRoot / Pelvis / Torso {Helmet, ChestReactor, Arm_L/R -> Forearm -> Hand -> {PalmReactor, Muzzle}, Launchers}
                       / Leg_L/R -> Shin -> Boot -> {FootThruster, Nozzle_Foot}

Poses (glTF animations Pose_Standing / Pose_Flight / Pose_Hover) are joint-rotation tables blended by the game.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa: E402,F401
import common  # noqa: E402

import math  # noqa: E402

# ----------------------------------------------------------------------------------------------
# rest-pose anchor points (metres, relative to PlayerRoot at the pelvis centre)
# ----------------------------------------------------------------------------------------------
Z_SOLE = -1.0
Z_ANKLE = -0.895
Z_KNEE = -0.50
Z_HIP = -0.05
X_HIP = 0.14
Z_WAIST = 0.08
Z_SHOULDER = 0.60
X_SHOULDER = 0.39
Z_NECK = 0.70
UPPER_ARM = 0.29
FOREARM = 0.29


def Vx(x, y, z):
    return Vector((x, y, z))


class M:
    P = S = A = D = C = W = G = O = None


def init_materials():
    M.P = pal("armor_primary")
    M.S = pal("armor_secondary")
    M.A = pal("armor_accent")
    M.D = pal("armor_dark")
    M.C = pal("glow_cyan")
    M.W = pal("glow_white")
    M.G = pal("armor_glass")
    M.O = pal("glow_orange")


# ----------------------------------------------------------------------------------------------
# builders: lofted faceted shells + plates
# ----------------------------------------------------------------------------------------------
def ring(z, wx, wy, x0=0.0, y0=0.0, n=8, sq=0.6, rot=22.5):
    """Faceted superellipse cross-section at height z (half-widths wx/wy, centre x0/y0)."""
    pts = []
    for i in range(n):
        a = math.radians(rot) + 2 * math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        x = math.copysign(abs(c) ** sq, c) * wx
        y = math.copysign(abs(s) ** sq, s) * wy
        pts.append(Vector((x0 + x, y0 + y, z)))
    return pts


def shell(mb, specs, mat, n=8, sq=0.6, caps=True, x0=0.0, rot=22.5, xform_rot=None, center=(0, 0, 0)):
    """specs: [(z, wx, wy, y0), ...] bottom->top.  xform_rot/center rotate the finished shell about `center`."""
    rings = [ring(z, wx, wy, x0=x0, y0=y0, n=n, sq=sq, rot=rot) for (z, wx, wy, y0) in specs]
    if xform_rot is None:
        return mb.loft(rings, mat=mat, caps=caps)
    c = Vector(center)
    moved = [[p - c for p in r] for r in rings]
    return mb.loft(moved, mat=mat, caps=caps, rot=xform_rot, center=c)


def bar(mb, a, b, w, t, mat, roll=0.0):
    """Thin strip from point a to b (long axis), width w, thickness t."""
    a, b = Vector(a), Vector(b)
    d = b - a
    q = Vector((0, 0, 1)).rotation_difference(d.normalized())
    if roll:
        q = q @ Quaternion((0, 0, 1), math.radians(roll))
    mb.box((a + b) / 2, (w, t, d.length), mat=mat, rot=q)


def vent_slats(mb, center, w, h, n, mat, depth=0.012, axis="Y", gap=0.55):
    pitch = h / n
    for i in range(n):
        z = center[2] - h / 2 + pitch * (i + 0.5)
        if axis == "Y":
            mb.box((center[0], center[1], z), (w, depth, pitch * gap), mat=mat)
        else:
            mb.box((center[0], center[1], z), (depth, w, pitch * gap), mat=mat)


def plate(mb, p0, p1, p2, p3, thick, mat, out=None):
    """Quad plate from 4 corner points with thickness pushed toward `out` (default: +normal of the corner order)."""
    p0, p1, p2, p3 = (Vector(p) for p in (p0, p1, p2, p3))
    n = (p1 - p0).cross(p3 - p0).normalized()
    if out is not None and n.dot(Vector(out)) < 0:
        n = -n
    n = n * abs(thick)
    mb.hexa([p0, p1, p2, p3, p0 + n, p1 + n, p2 + n, p3 + n], mat)


# ----------------------------------------------------------------------------------------------
# TORSO (waist pivot)
# ----------------------------------------------------------------------------------------------
def build_torso():
    mb = MB()
    P, S, A, D, C = M.P, M.S, M.A, M.D, M.C
    # ---- abdomen (navy) and chest (pearl) shells
    shell(mb, [(0.03, 0.150, 0.108, 0.0), (0.12, 0.152, 0.108, 0.0), (0.22, 0.170, 0.120, 0.003), (0.30, 0.200, 0.135, 0.006)], S, n=8, sq=0.55)
    shell(mb, [
        (0.285, 0.205, 0.138, 0.006),
        (0.38, 0.262, 0.156, 0.012),
        (0.50, 0.322, 0.172, 0.016),
        (0.61, 0.348, 0.154, 0.004),
        (0.665, 0.235, 0.122, -0.004),
        (0.70, 0.098, 0.088, 0.0),
    ], P, n=8, sq=0.5)
    # ---- pelvis block / belt + hip armour
    shell(mb, [(-0.14, 0.195, 0.132, 0.0), (-0.06, 0.225, 0.150, 0.0), (0.05, 0.215, 0.145, 0.0)], P, n=8, sq=0.5)
    mb.box((0, 0, 0.035), (0.40, 0.29, 0.05), mat=S)
    mb.box((0, 0.152, 0.035), (0.13, 0.02, 0.05), mat=A)                                   # buckle
    mb.box((0, 0.164, 0.035), (0.055, 0.012, 0.03), mat=D)
    for sx in (-1, 1):
        # angled fauld plates over the hip joints (front + side), layered skirt look
        plate(mb, (sx * 0.05, 0.145, -0.02), (sx * 0.20, 0.115, -0.02), (sx * 0.225, 0.12, -0.20), (sx * 0.07, 0.16, -0.21), 0.02, S, out=(0, 1, 0))
        plate(mb, (sx * 0.21, 0.11, -0.03), (sx * 0.245, -0.02, -0.03), (sx * 0.275, -0.02, -0.19), (sx * 0.24, 0.11, -0.20), 0.02, P, out=(sx, 0, 0))
        mb.box((sx * 0.29, 0.03, -0.11), (0.012, 0.08, 0.03), mat=A)
        plate(mb, (sx * 0.05, -0.145, -0.02), (sx * 0.22, -0.115, -0.02), (sx * 0.25, -0.13, -0.20), (sx * 0.07, -0.165, -0.21), 0.02, S, out=(0, -1, 0))
    # ---- chest details: navy sternum plates + amber chevron + cyan seams; ab bands
    for sx in (-1, 1):
        plate(mb, (sx * 0.02, 0.160, 0.38), (sx * 0.24, 0.150, 0.40), (sx * 0.27, 0.152, 0.60), (sx * 0.04, 0.180, 0.60), 0.032, S, out=(0, 1, 0))
        bar(mb, (sx * 0.03, 0.198, 0.395), (sx * 0.26, 0.178, 0.43), 0.016, 0.014, A)
        bar(mb, (sx * 0.30, 0.150, 0.44), (sx * 0.275, 0.190, 0.60), 0.012, 0.012, C)
    for k, (z, w) in enumerate(((0.09, 0.125), (0.16, 0.14), (0.23, 0.155))):
        mb.box((0, 0.095 + k * 0.006, z), (w * 2, 0.04, 0.05), mat=P, taper=(0.97, 1.0), bottom_scale=(0.95, 1.0))
    # reactor housing: hex frame around ChestReactor at (0, 0.205, 0.50)
    mb.cyl((0, 0.196, 0.50), 0.122, 0.045, seg=6, axis="Y", mat=D, r_top=0.11)
    mb.cyl((0, 0.212, 0.50), 0.094, 0.02, seg=6, axis="Y", mat=S)
    # back: big navy plate + spine + thruster pack
    plate(mb, (-0.25, -0.16, 0.36), (0.25, -0.16, 0.36), (0.30, -0.155, 0.63), (-0.30, -0.155, 0.63), 0.045, S, out=(0, -1, 0))
    mb.box((0, -0.19, 0.50), (0.05, 0.03, 0.30), mat=D)
    mb.box((0, -0.215, 0.45), (0.30, 0.09, 0.25), mat=D, bottom_scale=(0.86, 0.9))
    for sx in (-1, 1):
        mb.cyl((sx * 0.085, -0.28, 0.395), 0.054, 0.10, seg=12, axis="Y", mat=D, r_top=0.068)
        mb.cyl((sx * 0.085, -0.332, 0.395), 0.041, 0.02, seg=12, axis="Y", mat=C)
        bar(mb, (sx * 0.20, -0.20, 0.36), (sx * 0.235, -0.18, 0.60), 0.012, 0.012, C)
    vent_slats(mb, (0, -0.264, 0.53), 0.17, 0.10, 4, S, axis="Y")
    # ---- neck ring + trapezius yoke
    mb.cyl((0, 0, 0.695), 0.10, 0.07, seg=10, axis="Z", mat=D)
    for sx in (-1, 1):
        plate(mb, (sx * 0.07, 0.12, 0.667), (sx * 0.28, 0.10, 0.64), (sx * 0.28, -0.10, 0.64), (sx * 0.07, -0.12, 0.667), 0.03, S, out=(0, 0, 1))
        mb.box((sx * 0.17, 0.0, 0.702), (0.13, 0.20, 0.010), mat=A, rot=(0, sx * -8, 0))
    # ---- rear shoulder racks: homing-missile launchers (2 tubes) angled up/out/forward
    for sx in (-1, 1):
        rot = (30, 0, sx * -14)
        R = rot_matrix(rot)
        base = Vx(sx * 0.235, -0.15, 0.72)
        mb.box(base, (0.12, 0.30, 0.10), mat=D, rot=rot, bottom_scale=(0.94, 0.94))
        mb.box(base + R @ Vx(0, -0.01, 0.055), (0.135, 0.27, 0.022), mat=S, rot=rot)
        mb.box(base + R @ Vx(sx * 0.066, 0.0, -0.005), (0.026, 0.27, 0.10), mat=P, rot=rot)
        mb.box(base + R @ Vx(0, -0.03, 0.068), (0.04, 0.22, 0.010), mat=A, rot=rot)
        for tx in (-0.03, 0.03):
            mouth = base + R @ Vx(tx, 0.15, 0.0)
            mb.cyl(mouth, 0.033, 0.05, seg=12, axis="Y", mat=D, rot=rot)
            mb.cyl(mouth + R @ Vx(0, 0.026, 0), 0.024, 0.012, seg=12, axis="Y", mat=M.O, rot=rot)
        # mini-missile pod: 3 tubes in a triangle on the outer flank of the rack
        pod = Vx(sx * 0.335, -0.165, 0.64)
        prot = (18, 0, sx * -34)
        PR = rot_matrix(prot)
        mb.box(pod, (0.10, 0.15, 0.13), mat=S, rot=prot)
        for (ox, oz) in ((-0.026, 0.027), (0.026, 0.027), (0.0, -0.027)):
            tp = pod + PR @ Vx(ox, 0.085, oz)
            mb.cyl(tp, 0.025, 0.05, seg=10, axis="Y", mat=D, rot=prot)
            mb.cyl(tp + PR @ Vx(0, 0.026, 0), 0.017, 0.01, seg=10, axis="Y", mat=M.A, rot=prot)
    # side ribs: vents
    for sx in (-1, 1):
        vent_slats(mb, (sx * 0.176, 0.02, 0.20), 0.11, 0.10, 3, D, axis="X")
    return mb


def build_chest_reactor():
    mb = MB()
    mb.cyl((0, 0.228, 0.50), 0.072, 0.02, seg=24, axis="Y", mat=M.C)
    mb.cyl((0, 0.223, 0.50), 0.088, 0.012, seg=24, axis="Y", mat=M.W, r_top=0.083)
    return mb


# ----------------------------------------------------------------------------------------------
# HELMET (neck pivot)
# ----------------------------------------------------------------------------------------------
def build_helmet():
    mb = MB()
    P, S, A, D, W, G = M.P, M.S, M.A, M.D, M.W, M.G
    k = 1.10
    shell(mb, [
        (0.715, 0.078 * k, 0.088 * k, 0.030),
        (0.760, 0.118 * k, 0.128 * k, 0.040),
        (0.815, 0.152 * k, 0.168 * k, 0.018),
        (0.885, 0.160 * k, 0.180 * k, 0.006),
        (0.950, 0.147 * k, 0.170 * k, -0.005),
        (0.996, 0.102 * k, 0.128 * k, -0.012),
        (1.012, 0.056 * k, 0.078 * k, -0.015),
    ], P, n=8, sq=0.5)
    # face mask (navy), visor chevron, brow stripe, chin guard
    plate(mb, (-0.10, 0.14, 0.735), (0.10, 0.14, 0.735), (0.125, 0.19, 0.905), (-0.125, 0.19, 0.905), 0.03, S, out=(0, 1, 0))
    plate(mb, (-0.135, 0.185, 0.850), (0.135, 0.185, 0.850), (0.135, 0.205, 0.905), (-0.135, 0.205, 0.905), 0.018, D, out=(0, 1, 0))
    bar(mb, (-0.125, 0.222, 0.888), (-0.012, 0.228, 0.860), 0.028, 0.012, W)
    bar(mb, (0.125, 0.222, 0.888), (0.012, 0.228, 0.860), 0.028, 0.012, W)
    mb.box((0, 0.222, 0.912), (0.26, 0.02, 0.012), mat=A, rot=(-10, 0, 0))
    plate(mb, (-0.065, 0.14, 0.715), (0.065, 0.14, 0.715), (0.085, 0.19, 0.78), (-0.085, 0.19, 0.78), 0.02, D, out=(0, 1, 0))
    for sx in (-1, 1):
        plate(mb, (sx * 0.11, 0.11, 0.74), (sx * 0.165, 0.03, 0.75), (sx * 0.185, 0.05, 0.86), (sx * 0.125, 0.16, 0.87), 0.022, P, out=(sx, 0, 0))
        mb.cyl((sx * 0.19, 0.0, 0.83), 0.055, 0.035, seg=10, axis="X", mat=D)
        mb.cyl((sx * 0.208, 0.0, 0.83), 0.032, 0.01, seg=10, axis="X", mat=M.C)
        plate(mb, (sx * 0.165, -0.02, 0.91), (sx * 0.175, -0.19, 0.95), (sx * 0.165, -0.21, 0.84), (sx * 0.165, 0.0, 0.81), 0.014, S, out=(sx, 0, 0))
    mb.prism([(-0.14, 0.965), (-0.05, 1.07), (0.09, 1.035), (0.16, 0.99)], -0.013, 0.013, mat=S, plane="YZ")
    mb.box((0, -0.02, 1.045), (0.008, 0.20, 0.012), mat=A)
    vent_slats(mb, (0, -0.195, 0.86), 0.14, 0.10, 4, D, axis="Y")
    mb.cyl((0, 0, 0.712), 0.09, 0.03, seg=10, axis="Z", mat=D)
    return mb


# ----------------------------------------------------------------------------------------------
# ARM chain (built for +X, mirrored for -X)
# ----------------------------------------------------------------------------------------------
def build_arm_R():
    mb = MB()
    P, S, A, D, C = M.P, M.S, M.A, M.D, M.C
    sx, sz = X_SHOULDER, Z_SHOULDER
    mb.sphere((sx, 0, sz), 0.085, seg=14, rings=8, mat=D)
    # pauldron: faceted pearl dome tilted outward + navy skirt plates + amber trim
    rings_specs =[(-0.075, 0.150, 0.150, 0.0), (-0.01, 0.185, 0.170, 0.0), (0.06, 0.150, 0.150, 0.0), (0.105, 0.085, 0.09, 0.0), (0.122, 0.04, 0.045, 0.0)]
    rr = [ring(z, wx, wy, x0=0.0, y0=y0, n=8, sq=0.62) for (z, wx, wy, y0) in rings_specs]
    mb.loft(rr, mat=P, caps=True, rot=(0, -22, 0), center=Vx(sx + 0.035, 0, sz))
    mb.box((sx + 0.125, 0, sz - 0.05), (0.05, 0.25, 0.09), mat=S, rot=(0, -30, 0), taper=(1.0, 0.9))
    mb.box((sx + 0.16, 0, sz - 0.105), (0.045, 0.22, 0.065), mat=P, rot=(0, -40, 0), taper=(1.0, 0.9))
    bar(mb, (sx + 0.05, 0.16, sz + 0.075), (sx + 0.05, -0.16, sz + 0.075), 0.02, 0.012, A)
    bar(mb, (sx + 0.15, 0.10, sz - 0.02), (sx + 0.17, -0.10, sz - 0.05), 0.014, 0.01, C)
    # upper arm: tapered faceted sleeve (navy) with a pearl front plate
    top = sz - 0.06
    ez = sz - UPPER_ARM
    shell(mb, [(top, 0.088, 0.088, 0.0), (top - 0.08, 0.085, 0.085, 0.0), (ez + 0.05, 0.072, 0.072, 0.0), (ez + 0.005, 0.066, 0.066, 0.0)],
          S, n=8, sq=0.6, x0=sx)
    mb.box((sx, 0.05, top - 0.09), (0.10, 0.05, 0.13), mat=P, bottom_scale=(0.9, 1.0))
    mb.box((sx, -0.06, top - 0.09), (0.09, 0.03, 0.12), mat=D)
    bar(mb, (sx + 0.078, 0.0, top - 0.01), (sx + 0.068, 0.0, ez + 0.06), 0.014, 0.012, C)
    # elbow: dark joint + pointed guard
    mb.cyl((sx, 0, ez), 0.056, 0.13, seg=12, axis="X", mat=D)
    mb.box((sx, -0.055, ez + 0.02), (0.10, 0.06, 0.10), mat=P, rot=(20, 0, 0), taper=(0.85, 0.8))
    return mb


def build_forearm_R():
    mb = MB()
    P, S, A, D, C = M.P, M.S, M.A, M.D, M.C
    sx = X_SHOULDER
    ez = Z_SHOULDER - UPPER_ARM
    wz = ez - FOREARM
    shell(mb, [
        (ez - 0.01, 0.066, 0.068, 0.0), (ez - 0.07, 0.080, 0.084, 0.004), (ez - 0.17, 0.088, 0.092, 0.006), (wz + 0.035, 0.092, 0.096, 0.006),
        (wz + 0.008, 0.082, 0.084, 0.0),
    ], P, n=8, sq=0.58, x0=sx)
    mb.box((sx, 0.078, ez - 0.16), (0.10, 0.04, 0.17), mat=S, bottom_scale=(1.05, 1.0))
    mb.box((sx, -0.092, ez - 0.14), (0.11, 0.04, 0.18), mat=D)
    vent_slats(mb, (sx + 0.094, 0.0, ez - 0.17), 0.11, 0.13, 4, D, axis="X")
    mb.box((sx, 0.0, ez - 0.045), (0.165, 0.17, 0.014), mat=A)
    bar(mb, (sx - 0.092, 0.03, ez - 0.05), (sx - 0.097, 0.03, wz + 0.05), 0.014, 0.012, C)
    mb.cyl((sx, 0.0, wz + 0.005), 0.078, 0.035, seg=12, axis="Z", mat=D)
    return mb


def build_hand_R():
    """glove; pivot at the wrist. Palm faces -Y at rest."""
    mb = MB()
    P, S, A, D = M.P, M.S, M.A, M.D
    sx = X_SHOULDER
    wz = Z_SHOULDER - UPPER_ARM - FOREARM
    mb.box((sx, 0, wz - 0.052), (0.115, 0.10, 0.10), mat=S, bottom_scale=(0.94, 0.94))
    mb.box((sx, 0.032, wz - 0.058), (0.10, 0.04, 0.11), mat=P, taper=(0.95, 1.0))
    mb.cyl((sx, -0.056, wz - 0.055), 0.058, 0.032, seg=12, axis="Y", mat=D)
    for fx in (-0.038, -0.013, 0.013, 0.038):
        mb.box((sx + fx, 0.014, wz - 0.130), (0.022, 0.05, 0.05), mat=D)
        mb.box((sx + fx, 0.02, wz - 0.158), (0.02, 0.046, 0.032), mat=S, taper=(0.9, 0.9))
    mb.box((sx - 0.064, 0.0, wz - 0.06), (0.03, 0.05, 0.07), mat=P, rot=(0, 0, 20))
    return mb


def build_palm_reactor_R():
    mb = MB()
    sx = X_SHOULDER
    wz = Z_SHOULDER - UPPER_ARM - FOREARM
    mb.cyl((sx, -0.073, wz - 0.055), 0.041, 0.014, seg=20, axis="Y", mat=M.C)
    mb.cyl((sx, -0.070, wz - 0.055), 0.050, 0.008, seg=20, axis="Y", mat=M.W, r_top=0.046)
    return mb


# ----------------------------------------------------------------------------------------------
# LEG chain (+X)
# ----------------------------------------------------------------------------------------------
def build_leg_R():
    mb = MB()
    P, S, A, D, C = M.P, M.S, M.A, M.D, M.C
    hx, hz, kz = X_HIP, Z_HIP, Z_KNEE
    mb.sphere((hx, 0, hz), 0.07, seg=12, rings=8, mat=D)
    shell(mb, [
        (hz + 0.01, 0.100, 0.105, 0.0), (hz - 0.10, 0.108, 0.115, 0.006), (hz - 0.25, 0.098, 0.105, 0.008), (kz + 0.06, 0.082, 0.088, 0.004),
        (kz + 0.005, 0.072, 0.078, 0.0),
    ], P, n=8, sq=0.6, x0=hx)
    plate(mb, (hx - 0.075, 0.105, hz - 0.06), (hx + 0.075, 0.105, hz - 0.06), (hx + 0.062, 0.095, kz + 0.10), (hx - 0.062, 0.095, kz + 0.10), 0.026, S, out=(0, 1, 0))
    plate(mb, (hx + 0.104, 0.09, hz - 0.05), (hx + 0.11, -0.09, hz - 0.05), (hx + 0.085, -0.075, kz + 0.10), (hx + 0.082, 0.08, kz + 0.10), 0.022, S, out=(1, 0, 0))
    mb.box((hx + 0.136, 0.0, (hz + kz) / 2 + 0.02), (0.01, 0.06, 0.27), mat=A)
    mb.box((hx, -0.108, (hz + kz) / 2 + 0.02), (0.13, 0.04, 0.29), mat=D)
    bar(mb, (hx - 0.08, 0.136, hz - 0.08), (hx - 0.062, 0.122, kz + 0.14), 0.014, 0.012, C)
    mb.cyl((hx, 0, kz), 0.062, 0.17, seg=12, axis="X", mat=D)
    mb.box((hx, 0.09, kz + 0.015), (0.15, 0.085, 0.13), mat=P, rot=(-28, 0, 0), taper=(0.85, 0.7))
    mb.box((hx, 0.137, kz + 0.035), (0.08, 0.02, 0.035), mat=A, rot=(-28, 0, 0))
    return mb


def build_shin_R():
    mb = MB()
    P, S, A, D, C = M.P, M.S, M.A, M.D, M.C
    hx, kz, az = X_HIP, Z_KNEE, Z_ANKLE
    shell(mb, [
        (kz - 0.005, 0.070, 0.076, 0.0), (kz - 0.09, 0.080, 0.090, -0.008), (kz - 0.20, 0.076, 0.092, -0.012), (az + 0.06, 0.062, 0.076, -0.004),
        (az + 0.005, 0.058, 0.068, 0.0),
    ], S, n=8, sq=0.6, x0=hx)
    plate(mb, (hx - 0.064, 0.088, az + 0.03), (hx + 0.064, 0.088, az + 0.03), (hx + 0.078, 0.082, kz - 0.05), (hx - 0.078, 0.082, kz - 0.05), 0.03, P, out=(0, 1, 0))
    mb.box((hx, 0.132, (kz + az) / 2 + 0.02), (0.02, 0.02, 0.33), mat=A, rot=(-1.5, 0, 0))
    plate(mb, (hx + 0.078, 0.07, az + 0.05), (hx + 0.08, -0.07, az + 0.05), (hx + 0.094, -0.07, kz - 0.06), (hx + 0.092, 0.07, kz - 0.06), 0.014, P, out=(1, 0, 0))
    mb.box((hx, -0.115, kz - 0.14), (0.13, 0.09, 0.22), mat=D, bottom_scale=(0.78, 0.8))
    vent_slats(mb, (hx, -0.163, kz - 0.13), 0.09, 0.14, 4, C, depth=0.008, axis="Y", gap=0.35)
    mb.cyl((hx, 0, az + 0.015), 0.055, 0.14, seg=12, axis="X", mat=D)
    return mb


def build_boot_R():
    mb = MB()
    P, S, A, D = M.P, M.S, M.A, M.D
    hx, az, zs = X_HIP, Z_ANKLE, Z_SOLE
    shell(mb, [(az + 0.02, 0.064, 0.072, 0.0), (az - 0.02, 0.078, 0.095, -0.01), (zs + 0.03, 0.082, 0.115, -0.015)], P, n=8, sq=0.55, x0=hx)
    mb.box((hx, 0.09, zs + 0.055), (0.15, 0.20, 0.09), mat=S, taper=(0.86, 0.75), top_shift=(0, 0.02))
    mb.box((hx, 0.205, zs + 0.04), (0.14, 0.10, 0.07), mat=P, taper=(0.82, 0.6))
    mb.box((hx, 0.03, zs + 0.012), (0.17, 0.36, 0.024), mat=D, bottom_scale=(0.98, 0.98))
    mb.box((hx, 0.085, zs + 0.104), (0.12, 0.15, 0.014), mat=A, rot=(-8, 0, 0))
    mb.box((hx, -0.085, zs + 0.06), (0.15, 0.04, 0.10), mat=D)
    return mb


def build_foot_thruster_R():
    """flared thruster nozzle ring + glowing disc under the heel; emits along -Z."""
    mb = MB()
    hx, zs = X_HIP, Z_SOLE
    mb.cyl((hx, -0.055, zs + 0.006), 0.078, 0.022, seg=16, axis="Z", mat=M.D, r_top=0.064)
    mb.cyl((hx, -0.055, zs - 0.004), 0.052, 0.012, seg=16, axis="Z", mat=M.C)
    mb.cyl((hx, -0.055, zs - 0.012), 0.034, 0.008, seg=16, axis="Z", mat=M.W)
    return mb


# ----------------------------------------------------------------------------------------------
# assembly
# ----------------------------------------------------------------------------------------------
def make_side(builder_R, name_L, name_R, pivot_R, parent_L, parent_R, parent_pivot_R, bevel=(0.006, 2), sharp=32.0):
    mbR = builder_R()
    mbL = mbR.mirrored_x()
    pR = Vector(pivot_R)
    pL = Vector((-pR.x, pR.y, pR.z))
    ppR = Vector(parent_pivot_R)
    ppL = Vector((-ppR.x, ppR.y, ppR.z))
    objR = add_part(name_R, mbR, pR, parent=parent_R, parent_pivot_world=ppR, bevel=bevel, sharp_angle=sharp)
    objL = add_part(name_L, mbL, pL, parent=parent_L, parent_pivot_world=ppL, bevel=bevel, sharp_angle=sharp)
    return objL, objR


def emp(name, world, direction, parent, parent_pivot, disp="SINGLE_ARROW", size=0.1):
    e = add_empty(name, (0, 0, 0), parent=parent, rot=aim_rot_for_direction(direction), display=disp, size=size)
    e.location = Vector(world) - Vector(parent_pivot)
    return e


def build_rig():
    init_materials()
    root = add_empty("PlayerRoot", (0, 0, 0), display="PLAIN_AXES", size=0.3)
    common._PIVOTS["PlayerRoot"] = Vector((0, 0, 0))
    pelvis = add_empty("Pelvis", (0, 0, 0), parent=root, display="SPHERE", size=0.08)
    common._PIVOTS["Pelvis"] = Vector((0, 0, 0))

    torso = add_part("Torso", build_torso(), (0, 0, Z_WAIST), parent=pelvis, parent_pivot_world=(0, 0, 0),
                     bevel=(0.005, 2), sharp_angle=30.0)
    helmet = add_part("Helmet", build_helmet(), (0, 0, Z_NECK), parent=torso, bevel=(0.005, 2), sharp_angle=30.0)
    add_part("ChestReactor", build_chest_reactor(), (0, 0.22, 0.50), parent=torso, bevel=None)

    arm_L, arm_R = make_side(build_arm_R, "Arm_L", "Arm_R", (X_SHOULDER, 0, Z_SHOULDER), torso, torso, (0, 0, Z_WAIST))
    fore_L, fore_R = make_side(build_forearm_R, "Forearm_L", "Forearm_R", (X_SHOULDER, 0, Z_SHOULDER - UPPER_ARM), arm_L, arm_R,
                               (X_SHOULDER, 0, Z_SHOULDER))
    wz = Z_SHOULDER - UPPER_ARM - FOREARM
    hand_L, hand_R = make_side(build_hand_R, "Hand_L", "Hand_R", (X_SHOULDER, 0, wz), fore_L, fore_R,
                               (X_SHOULDER, 0, Z_SHOULDER - UPPER_ARM))
    make_side(build_palm_reactor_R, "PalmReactor_L", "PalmReactor_R", (X_SHOULDER, -0.07, wz - 0.055), hand_L, hand_R,
              (X_SHOULDER, 0, wz), bevel=None)

    leg_L, leg_R = make_side(build_leg_R, "Leg_L", "Leg_R", (X_HIP, 0, Z_HIP), pelvis, pelvis, (0, 0, 0))
    shin_L, shin_R = make_side(build_shin_R, "Shin_L", "Shin_R", (X_HIP, 0, Z_KNEE), leg_L, leg_R, (X_HIP, 0, Z_HIP))
    boot_L, boot_R = make_side(build_boot_R, "Boot_L", "Boot_R", (X_HIP, 0, Z_ANKLE), shin_L, shin_R, (X_HIP, 0, Z_KNEE))
    make_side(build_foot_thruster_R, "FootThruster_L", "FootThruster_R", (X_HIP, -0.055, Z_SOLE), boot_L, boot_R,
              (X_HIP, 0, Z_ANKLE), bevel=None)

    # ---- empties: emission axis = local +Y
    for sgn, hand, nm in ((1, hand_R, "Muzzle_R"), (-1, hand_L, "Muzzle_L")):
        emp(nm, (sgn * X_SHOULDER, -0.09, wz - 0.055), (0, -1, 0), hand, (sgn * X_SHOULDER, 0, wz))
    emp("Nozzle_FootR", (X_HIP, -0.055, Z_SOLE - 0.005), (0, 0, -1), boot_R, (X_HIP, 0, Z_ANKLE))
    emp("Nozzle_FootL", (-X_HIP, -0.055, Z_SOLE - 0.005), (0, 0, -1), boot_L, (-X_HIP, 0, Z_ANKLE))
    tpv = Vector((0, 0, Z_WAIST))
    for sgn, side in ((1, "R"), (-1, "L")):
        rot = (30, 0, sgn * -14)
        R = rot_matrix(rot)
        base = Vx(sgn * 0.235, -0.15, 0.72)
        axis = R @ Vx(0, 1, 0)
        e = add_empty(f"Launcher_Missile_{side}", (0, 0, 0), parent=torso, rot=aim_rot_for_direction(axis), display="SINGLE_ARROW", size=0.12)
        e.location = base + R @ Vx(0, 0.2, 0) - tpv
        pod = Vx(sgn * 0.335, -0.165, 0.64)
        prot = (18, 0, sgn * -34)
        PR = rot_matrix(prot)
        for k, (ox, oz) in enumerate(((-0.026, 0.027), (0.026, 0.027), (0.0, -0.027)), start=1):
            d = PR @ Vx(ox * 6, 1.0, oz * 6)
            e = add_empty(f"Launcher_Mini_{side}_{k}", (0, 0, 0), parent=torso, rot=aim_rot_for_direction(d), display="SINGLE_ARROW", size=0.07)
            e.location = pod + PR @ Vx(ox, 0.12, oz) - tpv
    return dict(root=root, pelvis=pelvis, torso=torso, helmet=helmet)


# ----------------------------------------------------------------------------------------------
# poses  (degrees, Euler XYZ).  Pitching forward = NEGATIVE X on Pelvis.
# ----------------------------------------------------------------------------------------------
def pose_tables():
    def mirror(d, name, rot):
        d[name + "_R"] = dict(rot=rot)
        d[name + "_L"] = dict(rot=(rot[0], -rot[1], -rot[2]))

    standing, flight, hover = {}, {}, {}
    standing["Pelvis"] = dict(rot=(0, 0, 0))
    standing["Torso"] = dict(rot=(0, 0, 0))
    standing["Helmet"] = dict(rot=(0, 0, 0))
    mirror(standing, "Arm", (2, -5, 0))
    mirror(standing, "Forearm", (9, 0, 0))
    mirror(standing, "Hand", (0, 0, -60))
    mirror(standing, "Leg", (0, 0, 0))
    mirror(standing, "Shin", (0, 0, 0))
    mirror(standing, "Boot", (0, 0, 0))

    flight["Pelvis"] = dict(rot=(-82, 0, 0))
    flight["Torso"] = dict(rot=(-4, 0, 0))
    flight["Helmet"] = dict(rot=(56, 0, 0))
    mirror(flight, "Arm", (-4, -8, 0))
    mirror(flight, "Forearm", (4, 0, 0))
    mirror(flight, "Hand", (82, 0, 0))
    mirror(flight, "Leg", (3, 2, 0))
    mirror(flight, "Shin", (2, 0, 0))
    mirror(flight, "Boot", (18, 0, 0))

    hover["Pelvis"] = dict(rot=(-9, 0, 0))
    hover["Torso"] = dict(rot=(3, 0, 0))
    hover["Helmet"] = dict(rot=(6, 0, 0))
    mirror(hover, "Arm", (32, -16, 0))
    mirror(hover, "Forearm", (68, 0, 0))
    mirror(hover, "Hand", (72, 0, 0))
    mirror(hover, "Leg", (9, 3, 0))
    mirror(hover, "Shin", (-20, 0, 0))
    mirror(hover, "Boot", (14, 0, 0))
    return {"Pose_Standing": standing, "Pose_Flight": flight, "Pose_Hover": hover}


ANIM_NODES = ["Pelvis", "Torso", "Helmet", "Arm_L", "Arm_R", "Forearm_L", "Forearm_R", "Hand_L", "Hand_R",
              "Leg_L", "Leg_R", "Shin_L", "Shin_R", "Boot_L", "Boot_R"]


def hash_str(s):
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) % 1000003
    return h


def idle(clip, node, phase):
    """Subtle looping motion (+-1..3 degrees).  EVERY node gets a little motion in every clip because the glTF exporter
    drops constant channels (which would silently remove e.g. the flight lean of the Pelvis)."""
    s = math.sin(phase + (hash_str(node) % 7) * 0.5)
    c = math.cos(phase + (hash_str(node) % 5) * 0.4)
    amp = {
        "Pose_Standing": {"Torso": (1.0, 0, 0.6), "Arm": (1.5, 0, 0), "Helmet": (0.8, 0.8, 0), "Leg": (0.3, 0, 0)},
        "Pose_Flight": {"Arm": (2.0, 1.5, 0), "Leg": (1.5, 0, 0), "Hand": (2.5, 0, 0), "Torso": (0.8, 0, 0), "Helmet": (1.0, 0, 0)},
        "Pose_Hover": {"Pelvis": (1.6, 0, 0.8), "Arm": (2.0, 0, 0), "Forearm": (2.0, 0, 0), "Leg": (2.0, 0, 0), "Shin": (2.5, 0, 0)},
    }[clip]
    key = node.split("_")[0]
    a = amp.get(key, (0.4, 0.3, 0))
    return (a[0] * s, a[1] * c, a[2] * c)


def check_poses(poses):
    """assert the pose intentions from the spec (palm jets back in flight, forward in hover ...)"""
    objs = {n: bpy.data.objects[n] for n in ANIM_NODES}
    rest = {n: o.location.copy() for n, o in objs.items()}
    out = {}
    for name, table in poses.items():
        apply_pose_static(objs, table, rest)
        muz = {s: bpy.data.objects["Muzzle_" + s] for s in "LR"}
        axes = {s: (m.matrix_world.to_quaternion() @ Vector((0, 1, 0))).normalized() for s, m in muz.items()}
        helmet_y = bpy.data.objects["Helmet"].matrix_world.translation.y
        pelvis_y = bpy.data.objects["Pelvis"].matrix_world.translation.y
        out[name] = (axes, helmet_y - pelvis_y)
        log(f"  {name}: muzzle axes L={tuple(round(v, 2) for v in axes['L'])} R={tuple(round(v, 2) for v in axes['R'])} "
            f"helmet-pelvis Y={helmet_y - pelvis_y:.2f}")
    apply_pose_static(objs, {}, rest)
    fa, ha = out["Pose_Flight"][0], out["Pose_Hover"][0]
    assert fa["L"].y < -0.5 and fa["R"].y < -0.5, "flight: palms must face backward"
    assert ha["L"].y > 0.4 and ha["R"].y > 0.4, "hover: palms must face forward"
    assert out["Pose_Flight"][1] > 0.4, "flight: helmet must be well in front of the pelvis"
    return objs, rest


def build():
    reset_scene()
    rig = build_rig()
    root = rig["root"]
    poses = pose_tables()
    args = script_args()

    objs, rest = check_poses(poses)
    if "--preview" in args:
        only = [a for a in args if a.startswith("--pose=")]
        for name, table in poses.items():
            if only and name.lower() != only[0].split("=")[1].lower():
                continue
            apply_pose_static(objs, table, rest)
            tag = name.replace("Pose_", "player_").lower()
            views = ("front", "three_quarter", "three_quarter_back", "right") if name == "Pose_Standing" else ("three_quarter", "three_quarter_back", "right")
            render_views(tag, [root], views=views, size=(800, 800), samples=24, ground=False)
        apply_pose_static(objs, {}, rest)

    build_pose_clips(objs, poses, idle=idle, frames=60, fps=30)
    path = export_glb("player.glb", [root], animations=True)
    report(path)


build()

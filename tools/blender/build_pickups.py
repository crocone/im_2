"""Supply pickups (dropped by destroyed enemies) -> public/assets/pickups.glb

Four floating canisters, ~0.8 m, each a top-level mesh node with its pivot at the centre:
  Pickup_Armor    - pearl hex repair plate with a glowing green cross
  Pickup_Energy   - dark cell with a glowing cyan tube and fins
  Pickup_Missiles - crate with two red-banded missile noses and orange strips
  Pickup_Mini     - crate with a cluster of three amber mini-missile tips
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa: E402,F401
import common  # noqa: E402


def mats():
    return dict(
        P=pal("armor_primary"), S=pal("armor_secondary"), A=pal("armor_accent"), D=pal("armor_dark"),
        C=pal("glow_cyan"), W=pal("glow_white"),
        G=make_material("glow_green", "#0A2A14", 0.0, 0.3, emission="#48FF8C", emission_strength=6.0),
        O=pal("glow_orange"), R=pal("missile_band"), MB=pal("missile_body"), MI=pal("mini_body"), MA=pal("mini_band"),
        EX=pal("exhaust"),
    )


def halo(mb, r, mat, z=0.0, thick=0.02, w=0.028):
    """thin glowing ring (readability at distance), lying in the XY plane"""
    prof = [(r - w, -thick / 2), (r, -thick / 2 - 0.004), (r + w, -thick / 2), (r + w, thick / 2), (r, thick / 2 + 0.004), (r - w, thick / 2)]
    prof.append(prof[0])   # close the profile loop (no end caps: it is a ring)
    mb.revolve(prof, center=(0, 0, z), seg=28, axis="Z", mat=mat, caps=False)


def build_armor(M):
    mb = MB()
    # hex plate housing + navy face + glowing plus sign
    mb.cyl((0, 0, 0), 0.34, 0.16, seg=6, axis="Y", mat=M["P"], r_top=0.30)
    mb.cyl((0, 0.085, 0), 0.26, 0.03, seg=6, axis="Y", mat=M["S"])
    mb.cyl((0, -0.085, 0), 0.26, 0.03, seg=6, axis="Y", mat=M["S"])
    mb.box((0, 0.108, 0), (0.30, 0.02, 0.085), mat=M["G"])
    mb.box((0, 0.108, 0), (0.085, 0.02, 0.30), mat=M["G"])
    mb.box((0, -0.108, 0), (0.30, 0.02, 0.085), mat=M["G"])
    mb.box((0, -0.108, 0), (0.085, 0.02, 0.30), mat=M["G"])
    for i in range(6):
        a = math.radians(60 * i + 30)
        mb.box((math.cos(a) * 0.335, 0, math.sin(a) * 0.335), (0.06, 0.12, 0.06), mat=M["A"], rot=(0, -math.degrees(a), 0))
    halo(mb, 0.46, M["G"], z=0.0)
    return mb


def build_energy(M):
    mb = MB()
    mb.cyl((0, 0, 0), 0.15, 0.62, seg=16, axis="Z", mat=M["C"])                       # glowing tube
    for z in (-0.33, 0.33):
        mb.cyl((0, 0, z), 0.21, 0.10, seg=12, axis="Z", mat=M["D"], r_top=0.19)
        mb.cyl((0, 0, z * 1.13), 0.17, 0.03, seg=12, axis="Z", mat=M["A"])
    for i in range(4):
        a = 90 * i + 45
        mb.box((math.cos(math.radians(a)) * 0.17, math.sin(math.radians(a)) * 0.17, 0), (0.03, 0.03, 0.66), mat=M["S"], rot=(0, 0, a))
    mb.cyl((0, 0, 0), 0.20, 0.03, seg=16, axis="Z", mat=M["P"])
    halo(mb, 0.44, M["C"], z=0.0)
    return mb


def build_missiles(M):
    mb = MB()
    mb.box((0, 0, 0), (0.62, 0.30, 0.34), mat=M["D"], taper=(0.96, 0.96))
    mb.box((0, 0, 0.175), (0.6, 0.28, 0.02), mat=M["S"])
    for x in (-0.15, 0.15):
        mb.cyl((x, 0.27, 0), 0.075, 0.30, seg=12, axis="Y", mat=M["MB"], r_top=0.05)                # missile body
        mb.cyl((x, 0.43, 0), 0.05, 0.10, seg=12, axis="Y", mat=M["R"], r_top=0.001)                 # nose cone
        mb.cyl((x, 0.31, 0), 0.078, 0.04, seg=12, axis="Y", mat=M["R"])
    mb.box((0, 0, 0.176), (0.5, 0.06, 0.012), mat=M["O"])
    mb.box((0, 0, -0.176), (0.5, 0.06, 0.012), mat=M["O"])
    halo(mb, 0.50, M["O"], z=0.0)
    return mb


def build_mini(M):
    mb = MB()
    mb.box((0, 0, 0), (0.56, 0.28, 0.32), mat=M["D"], taper=(0.96, 0.96))
    mb.box((0, 0, 0.165), (0.54, 0.26, 0.02), mat=M["S"])
    for (x, z) in ((-0.13, -0.05), (0.13, -0.05), (0.0, 0.08)):
        mb.cyl((x, 0.24, z), 0.05, 0.22, seg=10, axis="Y", mat=M["MI"], r_top=0.04)
        mb.cyl((x, 0.36, z), 0.04, 0.07, seg=10, axis="Y", mat=M["MA"], r_top=0.001)
    mb.box((0, 0, 0.166), (0.42, 0.05, 0.012), mat=M["A"])
    halo(mb, 0.48, M["MA"], z=0.0)
    return mb


def build():
    reset_scene()
    M = mats()
    objs = []
    # the halo rings lie in the XY plane of the mesh; for the hex plate the axis is Y, so rotate the whole pickup upright
    for name, fn in (("Pickup_Armor", build_armor), ("Pickup_Energy", build_energy), ("Pickup_Missiles", build_missiles), ("Pickup_Mini", build_mini)):
        mb = fn(M)
        o = mb.to_object(name, bevel=(0.008, 2), sharp_angle=32.0)
        objs.append(o)
    for i, o in enumerate(objs):
        o.location = (i * 1.6, 0, 0)
    path = export_glb("pickups.glb", objs, animations=False)
    report(path)
    if "--preview" in script_args():
        for o in objs:
            common.log(o.name)
        render_views("pickups", objs, views=("three_quarter", "front"), size=(1000, 500), samples=24, custom_views=None)


import math  # noqa: E402

build()

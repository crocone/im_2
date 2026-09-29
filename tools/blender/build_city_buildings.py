"""City building modules -> public/assets/city_buildings.glb

12 genuinely different building modules (Blender +Z up, footprint centred on the origin, base at z = 0):

  Bld_01_GlassTower       30x30 notched-corner blue curtain-wall tower, silver fins, glass lantern, mast      ~152 m
  Bld_02_SetbackTower     42/30/18 m Art-Deco limestone setbacks, piers + pinnacles, copper crown, spire      ~166 m
  Bld_03_OfficeSlab       60x24 ribbon-window slab on pilotis, brise-soleil ledges, penthouse, cooling towers  ~80 m
  Bld_04_ApartmentBlock   54x42 U-shaped limestone block, balconies, zinc mansard + dormers, water tank        ~42 m
  Bld_05_LShapeTower      54x54 L: bronze glass tower + wing, office wing, helipad                              ~106 m
  Bld_06_Warehouse        60x36 brick hall with sawtooth north-light roof, office annex, loading docks, chimney  ~34 m
  Bld_07_ResidentialTower 24x24 brick tower with staggered balconies, glass pavilion, timber water tank         ~110 m
  Bld_08_RoundTower       34 m round bronze glass tower with floor rings and a cantilevered helipad             ~119 m
  Bld_09_MidriseOffice    42x30 concrete egg-crate frame office with recessed penthouse + overhanging roof      ~55 m
  Bld_10_Landmark         54x54 podium + chamfered blue tower, sky-lobby band, setback, gold tiara crown, spire ~170 m
  Bld_11_ParkingGarage    54x36 open-deck garage with scissor ramps, lit ceilings, stair cores, rooftop lamps   ~23 m
  Bld_12_PodiumTower      60x48 brick retail podium with roof garden + offset office tower with sloped crown    ~116 m

Each module root (Empty) has one mesh child `<name>_Geo`, collider Empties `COL_<n>_B<NN>` (display CUBE, location = box
centre, scale = half extents) and `Roof_Slot_<n>_B<NN>` Empties (flat roof spots, >= 4x4 m clear, z = roof surface).
A top-level sibling `<name>_LOD1` holds the low-poly massing with the same materials / UV density.
(The helper names carry a `_B<NN>` suffix so every node name in the file is unique; the prefixes stay `COL_` / `Roof_Slot_`.)
Facade walls are split every 28.8 m (one texture tile) and each height band gets its own whole-bay U offset, so the
lit-window pattern of the 8-floor tile does not visibly repeat up tall towers.

Materials (whole file, 8): bld_glass_blue, bld_glass_gold, bld_office, bld_brick, bld_panel (procedural tiling facades,
city_facades.py: 24 m x 28.8 m tile = 8 bays of 3.0 m x 8 floors of 3.6 m; albedo JPEG 1024 + ORM / emissive lit windows /
normal PNG 512), bld_concrete (roof / structure, 16 m tile), bld_trim (256 px palette atlas: metals, paints, lights -
constant-UV swatches), beacon_red.  Geometry helpers, UV pass and rooftop props live in city_kit.py.

  node tools/run-blender.mjs tools/blender/build_city_buildings.py [-- --preview [--closeup] [--only=01,05]]
  (previews: tools/.cache/previews/bld_*.png, rendered with a sky / sun setup matching src/world/sky.ts)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa: E402,F401,F403
import city_facades as cf  # noqa: E402
from city_kit import (Bld, MatLib, ac_unit, beacon, cooling_tower, helipad, mast, octagon, offset_outline,  # noqa: E402
                      penthouse, rect, roof_clutter, solar_array, stair_bulkhead, vent_stack, water_tank)

SMALL = ["acs", "vent", "hatch", "dish", "cabinet", "mush"]

FLOOR = cf.FLOOR
R_ROUND = 1.5 / math.sin(math.pi / 36)       # 36 facets of exactly 3.0 m -> one bay per facet (17.21 m)


# ----------------------------------------------------------------------------------------------------
# small shared helpers
# ----------------------------------------------------------------------------------------------------
def fins_on_edge(kb, p0, p1, z0, z1, step, dep, w, mat, ends=False, start=None):
    """Vertical fins on an axis-aligned facade edge of a CCW outline (outward = right of p0->p1)."""
    (x0, y0), (x1, y1) = p0, p1
    ln = math.hypot(x1 - x0, y1 - y0)
    tx, ty = (x1 - x0) / ln, (y1 - y0) / ln
    nx, ny = ty, -tx
    n = int(round(ln / step))
    ks = range(0, n + 1) if ends else range(1, n)
    for k in ks:
        s = k * step if start is None else start + k * step
        if s > ln + 1e-6:
            break
        cx, cy = x0 + tx * s, y0 + ty * s
        if abs(tx) > 0.5:
            kb.box(cx - w / 2, cx + w / 2, cy, cy + ny * dep, z0, z1, mat, skip=("-z", "+y" if ny < 0 else "-y"))
        else:
            kb.box(cx, cx + nx * dep, cy - w / 2, cy + w / 2, z0, z1, mat, skip=("-z", "+x" if nx < 0 else "-x"))


def outline_edges(outline):
    n = len(outline)
    return [(outline[i], outline[(i + 1) % n]) for i in range(n)]


def face_box(kb, face, a, b, h0, h1, z0, z1, mat, skip_back=True, extra_skip=()):
    """Box attached to a rectangular facade.  face = ('-y', y) etc.: a..b along the face, h0..h1 = distance
    outward from the facade plane, z0..z1 vertical."""
    side, plane = face
    back = {"-y": "+y", "+y": "-y", "-x": "+x", "+x": "-x"}[side]
    skip = tuple(extra_skip) + ((back,) if skip_back and h0 == 0 else ())
    if side == "-y":
        kb.box(a, b, plane - h1, plane - h0, z0, z1, mat, skip=skip)
    elif side == "+y":
        kb.box(a, b, plane + h0, plane + h1, z0, z1, mat, skip=skip)
    elif side == "-x":
        kb.box(plane - h1, plane - h0, a, b, z0, z1, mat, skip=skip)
    else:
        kb.box(plane + h0, plane + h1, a, b, z0, z1, mat, skip=skip)


def rect_faces(x0, x1, y0, y1):
    """The 4 faces of an axis-aligned rectangle as (face, (a, b)) with a..b the extent along the face."""
    return [(("-y", y0), (x0, x1)), (("+y", y1), (x0, x1)), (("-x", x0), (y0, y1)), (("+x", x1), (y0, y1))]


def tree(b, kb, x, y, z, s=1.0):
    W, G = b.sw("wood"), b.sw("green")
    kb.cylinder(x, y, 0.22 * s, 0.16 * s, z, z + 2.2 * s, 6, W)
    kb.sphere((x, y, z + 3.4 * s), 1.9 * s, seg=8, rings=5, mat=G, scale=(1.0, 1.0, 0.85))


def planter(b, kb, x0, x1, y0, y1, z, h=0.8):
    kb.box(x0, x1, y0, y1, z, z + h, b.m("bld_concrete"), skip=("-z",), mats={"+z": b.sw("green")})


def lamp_pole(b, kb, x, y, z, h=6.0):
    G, L = b.sw("graphite"), b.sw("light_warm")
    kb.box(x - 0.1, x + 0.1, y - 0.1, y + 0.1, z, z + h, G, skip=("-z",))
    kb.box(x - 0.7, x + 0.7, y - 0.2, y + 0.2, z + h, z + h + 0.18, G)
    kb.box(x - 0.6, x + 0.6, y - 0.15, y + 0.15, z + h - 0.06, z + h, L, skip=("+z",))


# ----------------------------------------------------------------------------------------------------
# 01  Glass tower
# ----------------------------------------------------------------------------------------------------
def m01_glass_tower(lib):
    b = Bld(lib, 1, "GlassTower", 1101)
    M, D, L = b.mass, b.det, b.lod
    G, C = b.m("bld_glass_blue"), b.m("bld_concrete")
    SIL, GRA, GRN, LW = b.sw("silver"), b.sw("graphite"), b.sw("granite"), b.sw("light_warm")
    cross = [(-12, -15), (12, -15), (12, -12), (15, -12), (15, 12), (12, 12), (12, 15), (-12, 15), (-12, 12), (-15, 12),
             (-15, -12), (-12, -12)]
    Z0, Z1, ZC, Z2 = 7.2, 118.8, 119.4, 126.0
    lobby = offset_outline(cross, 3.0)
    lantern = offset_outline(cross, 0.9)
    M.prism(lobby, 0.0, Z0, G)
    M.prism(cross, Z0, Z1, G, bottom=SIL)
    M.prism(offset_outline(cross, -0.35), Z1, ZC, SIL, top=C, bottom=SIL)
    M.prism(lantern, ZC, Z2, G, top=C)
    # arcade columns on the four long facades, lobby doors, entrance canopy
    for (p0, p1) in outline_edges(cross):
        ln = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if ln < 20:
            continue
        tx, ty = (p1[0] - p0[0]) / ln, (p1[1] - p0[1]) / ln
        nx, ny = ty, -tx
        for s in (0.6, 6.0, 12.0, 18.0, 23.4):
            cx, cy = p0[0] + tx * s - nx * 0.55, p0[1] + ty * s - ny * 0.55
            D.box(cx - 0.45, cx + 0.45, cy - 0.45, cy + 0.45, 0.0, Z0, GRN, skip=("-z", "+z"))
        fins_on_edge(D, p0, p1, Z0, ZC + 0.25, 3.0, 0.55, 0.16, SIL, ends=True)
    D.box(-6, 6, 12, 19, 5.4, 5.8, SIL)
    D.box(-5.5, 5.5, 13.0, 18.6, 5.3, 5.4, LW, skip=("+z",))
    D.box(-3, 3, 12, 12.08, 0, 3.4, GRA, skip=("-y", "-z"))
    D.box(-3, 3, -12.08, -12, 0, 3.4, GRA, skip=("+y", "-z"))
    # lantern light band + parapet
    D.ring_slab(lantern, Z2 - 0.5, Z2 - 0.25, 0.05, LW, bottom=True)
    D.ring_wall(lantern, Z2, Z2 + 1.2, 0.3, SIL, inner_mat=C, top_mat=SIL)
    D.ring_slab(cross, Z1 - 0.2, Z1, 0.05, LW, bottom=False)
    # roof: penthouse, cooling towers, AC, mast
    penthouse(b, D, -6, 6, -4.5, 4.5, Z2, Z2 + 5.4, louvres=("-y", "+y"), door="+x")
    cooling_tower(b, D, -8.5, 8.5, Z2)
    cooling_tower(b, D, 8.5, -8.5, Z2)
    ac_unit(b, D, -3.2, 2.0, Z2 + 5.4)
    ac_unit(b, D, 3.2, -2.0, Z2 + 5.4)
    vent_stack(b, D, 4.0, 2.8, Z2 + 5.4)
    mast(b, D, 0.0, 0.0, Z2 + 5.4, 20.0, 0.4)
    top = Z2 + 5.4 + 20.0
    for s in ((0, 11.2), (0, -11.2), (11.2, 0), (-11.2, 0), (8.4, 8.4), (-8.4, -8.4)):
        b.slot(s[0], s[1], Z2)
    roof_clutter(b, D, (-10.8, 10.8, -10.8, 10.8), Z2, 111, n=6, kinds=SMALL + ["pipe"],
                 avoid=[(-6.6, 6.6, -5.1, 5.1), (-10.9, -6.1, 6.1, 10.9), (6.1, 10.9, -10.9, -6.1)])
    b.col(-15, 15, -15, 15, 0, Z2)
    b.col(-6, 6, -4.5, 4.5, Z2, Z2 + 5.4)
    b.col(-0.7, 0.7, -0.7, 0.7, Z2 + 5.4, top)
    # LOD
    L.prism(cross, 0, Z2, G, top=C)
    L.box(-6, 6, -4.5, 4.5, Z2, Z2 + 5.4, C, skip=("-z",))
    L.box(-0.3, 0.3, -0.3, 0.3, Z2 + 5.4, top, SIL, skip=("-z",))
    return b


# ----------------------------------------------------------------------------------------------------
# 02  Art-Deco setback tower with spire
# ----------------------------------------------------------------------------------------------------
def m02_setback_tower(lib):
    b = Bld(lib, 2, "SetbackTower", 1202)
    M, D, L = b.mass, b.det, b.lod
    P, C = b.m("bld_panel"), b.m("bld_concrete")
    ST, GRN, COP, SIL, GLD, LW, BRZ = (b.sw(n) for n in ("stone", "granite", "copper_patina", "silver", "gold",
                                                         "light_warm", "bronze"))
    tiers = [(21.0, 0.0, 54.0), (15.0, 54.0, 97.2), (9.0, 97.2, 122.4)]
    for i, (h, z0, z1) in enumerate(tiers):
        M.box(-h, h, -h, h, z0, z1, P, skip=("-z",), mats={"+z": C})
    M.box(-21.2, 21.2, -21.2, 21.2, 0.0, 4.5, GRN, skip=("-z",), mats={"+z": ST})
    # piers every 6 m + chunky corner piers, all rising above each setback as pinnacles
    for i, (h, z0, z1) in enumerate(tiers):
        zb = 4.5 if i == 0 else z0
        for face, (a, bb) in rect_faces(-h, h, -h, h):
            p = -h + 3.0
            while p < h - 1.0:
                if abs(round(p / 6.0) * 6.0 - p) < 1e-6:
                    face_box(D, face, p - 0.45, p + 0.45, 0.0, 0.55, zb, z1 + 2.4, ST)
                    face_box(D, face, p - 0.3, p + 0.3, 0.0, 0.4, z1 + 2.4, z1 + 3.3, ST, extra_skip=("-z",))
                p += 3.0
            # string course below the parapet
        D.ring_slab(rect(-h, h, -h, h), z1 - 0.9, z1 - 0.5, 0.25, ST)
        D.ring_wall(rect(-h, h, -h, h), z1, z1 + 1.2, 0.35, ST)
        for sx in (-1, 1):
            for sy in (-1, 1):
                cx, cy = sx * h, sy * h
                D.box(cx - 0.7, cx + 0.7, cy - 0.7, cy + 0.7, zb, z1 + 4.2, ST, skip=("-z",))
                D.box(cx - 0.45, cx + 0.45, cy - 0.45, cy + 0.45, z1 + 4.2, z1 + 5.4, ST, skip=("-z",))
                D.box(cx - 0.2, cx + 0.2, cy - 0.2, cy + 0.2, z1 + 5.4, z1 + 6.4, GLD, skip=("-z",))
    # entrance portal on +Y
    D.box(-5.6, -4.2, 21.2, 22.3, 0.0, 11.4, ST, skip=("-z",))
    D.box(4.2, 5.6, 21.2, 22.3, 0.0, 11.4, ST, skip=("-z",))
    D.box(-4.2, 4.2, 21.2, 22.1, 10.0, 11.4, ST)
    D.box(-3.2, 3.2, 21.2, 21.9, 11.4, 12.9, ST, skip=("-z",))
    D.box(-4.2, 4.2, 21.2, 21.3, 0.0, 10.0, BRZ, skip=("-y", "-z"))
    D.box(-3.6, 3.6, 21.3, 21.36, 5.6, 9.4, LW, skip=("-y", "-z"))
    for x in (-2.4, 0.0, 2.4):
        D.box(x - 0.08, x + 0.08, 21.36, 21.45, 5.6, 9.4, BRZ, skip=("-y", "-z"))
    # crown: stepped copper tiers with gold ribs, uplight strips, spire with beacons
    c1, c2, c3 = 7.5, 5.4, 3.3
    zc0, zc1, zc2, zc3 = 122.4, 126.6, 130.8, 136.2
    M.box(-c1, c1, -c1, c1, zc0, zc1, COP, skip=("-z",))
    M.box(-c2, c2, -c2, c2, zc1, zc2, COP, skip=("-z",))
    M.frustum(rect(-c3, c3, -c3, c3), zc2, zc3, 1.8, COP, top=GLD)
    for face, (a, bb) in rect_faces(-c1, c1, -c1, c1):
        for p in (-4.5, -1.5, 1.5, 4.5):
            face_box(D, face, p - 0.18, p + 0.18, 0.0, 0.3, zc0, zc1 + 0.6, GLD, extra_skip=("-z",))
    for face, (a, bb) in rect_faces(-c2, c2, -c2, c2):
        for p in (-3.0, 0.0, 3.0):
            face_box(D, face, p - 0.15, p + 0.15, 0.0, 0.25, zc1, zc2 + 0.5, GLD, extra_skip=("-z",))
    D.ring_slab(rect(-c1, c1, -c1, c1), zc0, zc0 + 0.3, 0.22, LW)
    D.ring_slab(rect(-c2, c2, -c2, c2), zc1, zc1 + 0.3, 0.3, LW)
    ztip = 165.5
    D.cylinder(0, 0, 1.3, 0.05, zc3, ztip, 8, b.sw("zinc"), bottom=SIL, phase=math.pi / 8)
    for zz, r in ((140.0, 1.2), (146.0, 0.95), (152.0, 0.7)):
        k = (zz - zc3) / (ztip - zc3)
        rr = 1.3 + (0.05 - 1.3) * k
        D.annulus(0, 0, rr * 0.9, rr + 0.25, zz, zz + 0.5, 8, GLD, faces=("top", "outer", "bottom"), phase=math.pi / 8)
    beacon(b, D, 0, 0, ztip, 0.28)
    beacon(b, D, 0.9, 0, 146.5, 0.2)
    beacon(b, D, -0.9, 0, 146.5, 0.2)
    # roof props on the terraces (outside the slots)
    ac_unit(b, D, -17.8, -17.8, 54.0, rot90=True)
    ac_unit(b, D, 17.8, 17.8, 54.0, rot90=True)
    vent_stack(b, D, 17.5, -17.5, 54.0)
    vent_stack(b, D, -12.2, 12.2, 97.2)
    for s in ((0, 18.2, 54.0), (0, -18.2, 54.0), (18.2, 0, 54.0), (-18.2, 0, 54.0), (0, 12.1, 97.2), (0, -12.1, 97.2)):
        b.slot(*s)
    av = [(-19.6, -16.0, -19.2, -16.4), (16.0, 19.6, 16.4, 19.2), (16.8, 18.2, -18.2, -16.8)]
    for i, area in enumerate(((-20.4, 20.4, 16.0, 20.4), (-20.4, 20.4, -20.4, -16.0), (16.0, 20.4, -15.0, 15.0),
                              (-20.4, -16.0, -15.0, 15.0))):
        roof_clutter(b, D, area, 54.0, 220 + i, n=3, kinds=SMALL + ["ac", "htank"], avoid=av)
    for i, area in enumerate(((-14.4, 14.4, 9.8, 14.4), (-14.4, 14.4, -14.4, -9.8), (9.8, 14.4, -9.0, 9.0),
                              (-14.4, -9.8, -9.0, 9.0))):
        roof_clutter(b, D, area, 97.2, 230 + i, n=2, kinds=SMALL, avoid=[(-13.0, -11.4, 11.4, 13.0)])
    b.col(-21.2, 21.2, -21.2, 21.2, 0, 54.0)
    b.col(-15, 15, -15, 15, 54.0, 97.2)
    b.col(-9, 9, -9, 9, 97.2, 122.4)
    b.col(-c1, c1, -c1, c1, 122.4, zc3)
    b.col(-1.3, 1.3, -1.3, 1.3, zc3, ztip + 0.5)
    for (h, z0, z1) in tiers:
        L.box(-h, h, -h, h, z0, z1, P, skip=("-z",), mats={"+z": C})
    L.box(-c1, c1, -c1, c1, zc0, zc1, COP, skip=("-z",))
    L.frustum(rect(-c2, c2, -c2, c2), zc1, zc3, 3.6, COP, top=COP)
    L.cylinder(0, 0, 1.0, 0.0, zc3, ztip, 4, SIL)
    return b


# ----------------------------------------------------------------------------------------------------
# 03  Office slab on pilotis
# ----------------------------------------------------------------------------------------------------
def m03_office_slab(lib):
    b = Bld(lib, 3, "OfficeSlab", 1303)
    M, D, L = b.mass, b.det, b.lod
    O, C, G = b.m("bld_office"), b.m("bld_concrete"), b.m("bld_glass_blue")
    WH, GRA, SIL, LW = b.sw("white"), b.sw("graphite"), b.sw("silver"), b.sw("light_warm")
    Z0, Z1 = 7.2, 64.8
    M.box(-30, 30, -12, 12, Z0, Z1, O, mats={"+x": C, "-x": C, "+z": C, "-z": C})
    M.box(-24, 24, -6, 6, 0.0, Z0, G, skip=("-z", "+z"))
    for sx in (-1, 1):
        D.box(sx * 30, sx * 30.4, -1.5, 1.5, Z0, Z1, O, skip=("-x" if sx > 0 else "+x",))
    for x in range(-27, 28, 6):
        for y in (-10.8, 10.8):
            D.box(x - 0.45, x + 0.45, y - 0.6, y + 0.6, 0, Z0, C, skip=("-z", "+z"))
    for sx in (-1, 1):
        D.box(sx * 28.8 - 0.6, sx * 28.8 + 0.6, -0.6, 0.6, 0, Z0, C, skip=("-z", "+z"))
    # brise-soleil ledges at every window head + vertical fins (egg crate on the long faces)
    for k in range(1, 16):
        z = Z0 + FLOOR * k - 0.2
        D.box(-30, 30, 12, 12.85, z - 0.12, z + 0.12, WH, skip=("-y",))
        D.box(-30, 30, -12.85, -12, z - 0.12, z + 0.12, WH, skip=("+y",))
    for x in range(-24, 25, 6):
        D.box(x - 0.08, x + 0.08, 12, 13.0, Z0, Z1, GRA, skip=("-y", "-z"))
        D.box(x - 0.08, x + 0.08, -13.0, -12, Z0, Z1, GRA, skip=("+y", "-z"))
    # entrance canopies
    for sy in (-1, 1):
        D.box(-7.5, 7.5, sy * 6, sy * 16, 4.2, 4.5, SIL)
        D.box(-7.0, 7.0, sy * 7, sy * 15.5, 4.1, 4.2, LW, skip=("+z",))
    # roof
    D.ring_wall(rect(-30, 30, -12, 12), Z1, Z1 + 1.1, 0.3, C, top_mat=SIL)
    penthouse(b, D, -9, 9, -5, 5, Z1, Z1 + 4.8, louvres=("-y", "+y"), door="+x")
    for x in (15.5, 20.5, 25.5):
        cooling_tower(b, D, x, -6.5, Z1)
    ac_unit(b, D, -4.5, 7.8, Z1)
    ac_unit(b, D, 4.5, 7.8, Z1)
    mast(b, D, 6.0, 0.0, Z1 + 4.8, 10.0, 0.25, arms=1, beacons=(1.0,))
    stair_bulkhead(b, D, 12.5, 7.0, Z1)
    for s in ((-24, -6), (-24, 6), (-15, 0), (20, 6), (26, 6)):
        b.slot(s[0], s[1], Z1)
    roof_clutter(b, D, (-29.4, 29.4, -11.4, 11.4), Z1, 303, n=11,
                 avoid=[(-9.6, 9.6, -5.6, 5.6), (13.0, 28.0, -9.0, -4.0), (-6.4, -2.6, 6.4, 9.2), (2.6, 6.4, 6.4, 9.2),
                        (10.6, 14.4, 5.0, 9.0)])
    b.col(-30.4, 30.4, -13, 13, 0, Z1)
    b.col(-9, 9, -5, 5, Z1, Z1 + 4.8)
    b.col(13.4, 27.6, -8.6, -4.4, Z1, Z1 + 4.4)
    L.box(-30, 30, -12, 12, 0, Z1, O, skip=("-z",), mats={"+x": C, "-x": C, "+z": C})
    L.box(-9, 9, -5, 5, Z1, Z1 + 4.8, C, skip=("-z",))
    L.box(13.4, 27.6, -8.6, -4.4, Z1, Z1 + 4.4, SIL, skip=("-z",))
    return b


# ----------------------------------------------------------------------------------------------------
# 04  U-shaped apartment block with mansard roof
# ----------------------------------------------------------------------------------------------------
def dormer(b, kb, face, p, z_eave, win_mat):
    """Dormer on a mansard slope.  face = ('-y', plane) ... plane = facade line at the eave."""
    Z, W = b.sw("zinc"), b.sw("white")
    side, plane = face
    s = {"-y": -1, "+y": 1, "-x": -1, "+x": 1}[side]
    fz0, fz1 = z_eave + 0.7, z_eave + 2.9
    front = plane - s * 0.25              # dormer front face sits just in front of the mansard slope
    back = plane - s * 2.6
    if side in ("-y", "+y"):
        kb.box(p - 0.85, p + 0.85, min(front, back), max(front, back), fz0, fz1, W, skip=("-z",))
        kb.box(p - 0.55, p + 0.55, front, front + s * 0.05, fz0 + 0.3, fz1 - 0.3, win_mat, skip=("-y" if s > 0 else "+y",))
        y0, y1 = min(front + s * 0.25, back), max(front + s * 0.25, back)
        kb.xz_prism([(p - 1.05, fz1), (p + 1.05, fz1), (p, fz1 + 0.9)], y0, y1, [None, Z, Z], Z)
    else:
        kb.box(min(front, back), max(front, back), p - 0.85, p + 0.85, fz0, fz1, W, skip=("-z",))
        kb.box(front, front + s * 0.05, p - 0.55, p + 0.55, fz0 + 0.3, fz1 - 0.3, win_mat, skip=("-x" if s > 0 else "+x",))
        x0, x1 = min(front + s * 0.25, back), max(front + s * 0.25, back)
        yz_roof(kb, p, fz1, x0, x1, Z)


def yz_roof(kb, p, z, x0, x1, mat):
    """Gable roof whose ridge runs along X (triangle in the YZ plane)."""
    pts = [(p - 1.05, z), (p + 1.05, z), (p, z + 0.9)]
    a = [kb.bm.verts.new((x0, y, zz)) for y, zz in pts]
    bb = [kb.bm.verts.new((x1, y, zz)) for y, zz in pts]
    kb._f([a[1], a[2], bb[2], bb[1]], mat)
    kb._f([a[2], a[0], bb[0], bb[2]], mat)
    kb._f(list(bb), mat)
    kb._f(list(reversed(a)), mat)


def m04_apartment_block(lib):
    b = Bld(lib, 4, "ApartmentBlock", 1404)
    M, D, L = b.mass, b.det, b.lod
    P, C = b.m("bld_panel"), b.m("bld_concrete")
    ST, GRA, Z, BR, LIT, GD, RED, GRNS, BRZ = (b.sw(n) for n in ("stone", "graphite", "zinc", "brick_red", "window_lit",
                                                                "glass_dark", "red", "green", "bronze"))
    U = [(-27, -21), (-12, -21), (-12, 6), (12, 6), (12, -21), (27, -21), (27, 21), (-27, 21)]
    ZE = 28.8
    M.prism(U, 0.0, 3.6, ST)
    M.prism(U, 3.6, ZE, P)
    # rusticated base band + cornices
    D.ring_slab(U, 3.4, 3.8, 0.2, ST)
    D.ring_slab(U, ZE - 0.7, ZE - 0.2, 0.55, ST)
    D.ring_slab(U, ZE - 0.2, ZE, 0.75, ST)
    # continuous wrought-iron balconies on the 2nd and 6th floor
    for zb in (7.2, 21.6):
        D.ring_slab(U, zb - 0.22, zb, 0.9, ST)
        rail = offset_outline(U, -0.86)
        D.ring_wall(rail, zb + 0.88, zb + 0.98, 0.07, GRA)
        D.ring_wall(rail, zb + 0.12, zb + 0.18, 0.04, GRA)
        for (p0, p1) in outline_edges(rail):
            ln = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            n = max(1, int(round(ln / 1.0)))
            for i in range(n):
                t = i / n
                x, y = p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t
                D.box(x - 0.025, x + 0.025, y - 0.025, y + 0.025, zb, zb + 0.88, GRA, skip=("-z", "+z"))
    # shopfronts + awnings on the street faces
    rng = np.random.default_rng(404)
    street = [(("+y", 21.0), (-27, 27)), (("-x", -27.0), (-21, 21)), (("+x", 27.0), (-21, 21)),
              (("-y", -21.0), (-27, -12)), (("-y", -21.0), (12, 27))]
    awn = [RED, GRNS, BRZ, GRA]
    for face, (a, bb) in street:
        p = a + 3.0
        while p <= bb - 3.0 + 1e-6:
            lit = rng.random() < 0.6
            face_box(D, face, p - 2.2, p + 2.2, 0.0, 0.06, 0.3, 3.0, LIT if lit else GD, extra_skip=("-z",))
            face_box(D, face, p - 2.4, p + 2.4, 0.0, 1.5, 3.05, 3.3, awn[int(rng.integers(0, 4))])
            p += 6.0
    # mansard roofs (zinc) with flat tops, dormers, chimneys
    bars = [rect(-27, 27, 6, 21), rect(-27, -12, -21, 6), rect(12, 27, -21, 6)]
    ZT = ZE + 4.5
    for r in bars:
        M.frustum(r, ZE, ZT, 1.8, Z, top=C)
    wins = [LIT, GD, GD]
    k = 0
    for x in range(-24, 25, 6):
        dormer(b, D, ("+y", 21.0), x, ZE, wins[k % 3]); k += 1
    for x in (-6.0, 0.0, 6.0):
        dormer(b, D, ("-y", 6.0), x, ZE, wins[k % 3]); k += 1
    for sx in (-1, 1):
        for y in (-18, -12, -6, 0):
            dormer(b, D, ("+x" if sx > 0 else "-x", sx * 27.0), y, ZE, wins[k % 3]); k += 1
            dormer(b, D, ("-x" if sx > 0 else "+x", sx * 12.0), y, ZE, wins[(k + 1) % 3]); k += 1
        for x in (sx * 22.5, sx * 16.5):
            dormer(b, D, ("-y", -21.0), x, ZE, wins[k % 3]); k += 1
    for (cx, cy) in ((-13.0, 17.5), (-1.0, 17.8), (9.5, 17.8), (-19.5, 1.5), (19.5, 1.5), (-16.5, -17.5), (22.5, -17.5)):
        D.box(cx - 0.7, cx + 0.7, cy - 0.45, cy + 0.45, ZT, ZT + 2.2, BR, skip=("-z",))
        D.box(cx - 0.85, cx + 0.85, cy - 0.6, cy + 0.6, ZT + 2.2, ZT + 2.45, GRA)
        for dx in (-0.35, 0.35):
            D.cylinder(cx + dx, cy, 0.14, 0.14, ZT + 2.45, ZT + 2.9, 6, BR, top=GRA)
    ztank = water_tank(b, D, 15.0, 13.5, ZT)
    stair_bulkhead(b, D, -22.0, 13.5, ZT, rot90=True)
    for s in ((-16.5, 13.5), (-6.0, 13.5), (4.5, 13.5), (-19.5, -10.0), (19.5, -10.0)):
        b.slot(s[0], s[1], ZT)
    chim = [(cx - 1.2, cx + 1.2, cy - 1.0, cy + 1.0) for (cx, cy) in ((-13.0, 17.5), (-1.0, 17.8), (9.5, 17.8),
                                                                      (-19.5, 1.5), (19.5, 1.5), (-16.5, -17.5), (22.5, -17.5))]
    chim += [(11.8, 18.2, 10.3, 16.7), (-24.0, -20.0, 11.5, 15.5)]
    for i, area in enumerate(((-24.8, 24.8, 8.2, 18.8), (-24.8, -14.2, -18.8, 3.8), (14.2, 24.8, -18.8, 3.8))):
        roof_clutter(b, D, area, ZT, 404 + i, n=4, kinds=["vent", "mush", "dish", "hatch", "acs"], avoid=chim)
    b.col(-27, 27, 6, 21, 0, ZT)
    b.col(-27, -12, -21, 6, 0, ZT)
    b.col(12, 27, -21, 6, 0, ZT)
    b.col(12.5, 17.5, 11.0, 16.0, ZT, ztank)
    L.prism(U, 0.0, ZE, P)
    for r in bars:
        L.frustum(r, ZE, ZT, 1.8, Z, top=C)
    L.box(13.0, 17.0, 11.5, 15.5, ZT, ztank - 2.0, b.sw("wood"), skip=("-z",))
    return b


# ----------------------------------------------------------------------------------------------------
# 05  L-shaped tower (gold glass tower + wing, office wing, helipad)
# ----------------------------------------------------------------------------------------------------
def m05_lshape_tower(lib):
    b = Bld(lib, 5, "LShapeTower", 1505)
    M, D, L = b.mass, b.det, b.lod
    GG, O, C = b.m("bld_glass_gold"), b.m("bld_office"), b.m("bld_concrete")
    BRZ, GRA, RD, SIL, LW, GRNS = (b.sw(n) for n in ("bronze", "graphite", "roof_dark", "silver", "light_warm", "green"))
    ZT, ZB, ZA = 100.8, 79.2, 57.6
    # corner tower T (x -27..-9, y 9..27), wing B (x -27..-9, y -27..9), wing A (x -9..27, y 9..27)
    M.box(-27, -9, 9, 27, 0, ZT, GG, skip=("-z", "-y", "+x"), mats={"+z": C})
    D.quad([(-27, 9, ZB), (-9, 9, ZB), (-9, 9, ZT), (-27, 9, ZT)], GG)
    D.quad([(-9, 9, ZA), (-9, 27, ZA), (-9, 27, ZT), (-9, 9, ZT)], GG)
    M.box(-27, -9, -27, 9, 0, ZB, GG, skip=("-z", "+y"), mats={"+z": C})
    M.box(-9, 27, 9, 27, 0, ZA, O, skip=("-z", "-x"), mats={"+z": C})
    # bronze fins every 3 m on the gold glass (corners get chunkier posts)
    fins_on_edge(D, (-27, 27), (-27, -27), 3.6, ZB, 3.0, 0.7, 0.2, BRZ)
    for y in range(12, 27, 3):
        D.box(-27.7, -27, y - 0.1, y + 0.1, ZB, ZT, BRZ, skip=("+x", "-z"))
    D.box(-27.7, -27, 8.9, 9.1, ZB, ZT, BRZ, skip=("+x", "-z"))
    fins_on_edge(D, (-9, 27), (-27, 27), 3.6, ZT, 3.0, 0.7, 0.2, BRZ)
    fins_on_edge(D, (-27, -27), (-9, -27), 3.6, ZB, 3.0, 0.7, 0.2, BRZ)
    fins_on_edge(D, (-9, -27), (-9, 9), 3.6, ZB, 3.0, 0.7, 0.2, BRZ)
    for y in range(12, 27, 3):
        D.box(-9, -8.3, y - 0.1, y + 0.1, ZA, ZT, BRZ, skip=("-x", "-z"))
    for x in range(-24, -9, 3):
        D.box(x - 0.1, x + 0.1, 8.3, 9, ZB, ZT, BRZ, skip=("+y", "-z"))
    for (cx, cy, z1) in ((-27, 27, ZT), (-27, -27, ZB), (-9, -27, ZB), (-9, 9, ZB), (-27, 9, ZT), (-9, 27, ZT)):
        D.box(cx - 0.5, cx + 0.5, cy - 0.5, cy + 0.5, 0, z1 + 1.2, BRZ, skip=("-z",))
    # cap fascias with light lines under them
    for (r, z, m) in ((rect(-27, -9, 9, 27), ZT, BRZ), (rect(-27, -9, -27, 9), ZB, BRZ), (rect(-9, 27, 9, 27), ZA, SIL)):
        D.ring_slab(r, z - 1.1, z, 0.85, m)
        D.ring_slab(r, z - 1.3, z - 1.1, 0.7, LW, bottom=True)
    D.box(-30.5, -27.7, -6.0, 6.0, 4.2, 4.5, SIL)
    D.box(-30.2, -27.8, -5.5, 5.5, 4.1, 4.2, LW, skip=("+z",))
    # parapets
    D.ring_wall(rect(-27, -9, 9, 27), ZT, ZT + 1.2, 0.3, BRZ, inner_mat=C)
    D.ring_wall(rect(-27, -9, -27, 9), ZB, ZB + 1.2, 0.3, BRZ, inner_mat=C)
    D.ring_wall(rect(-9, 27, 9, 27), ZA, ZA + 1.1, 0.3, C, top_mat=SIL)
    # lobby canopy in the inner corner + light
    D.box(-9, 3, -3, 9, 4.5, 4.8, SIL)
    D.box(-8.5, 2.5, -2.5, 8.6, 4.4, 4.5, LW, skip=("+z",))
    # helipad on the tower: deck on posts
    zd = ZT + 0.9
    for sx in (-1, 1):
        for sy in (-1, 1):
            D.box(-18 + sx * 5 - 0.2, -18 + sx * 5 + 0.2, 18 + sy * 5 - 0.2, 18 + sy * 5 + 0.2, ZT, zd - 0.3, GRA, skip=("-z",))
    D.box(-25.2, -10.8, 10.8, 25.2, zd - 0.3, zd, RD, mats={"-z": GRA})
    helipad(b, D, -18, 18, zd, 14.0, light_r=6.9)
    mast(b, D, -26.0, 26.0, ZT, 5.0, 0.15, arms=0, beacons=(1.0,))
    mast(b, D, -10.0, 10.0, ZT, 5.0, 0.15, arms=0, beacons=(1.0,))
    # wing B roof: mechanicals;  wing A roof: garden planters + AC
    cooling_tower(b, D, -18.0, 3.0, ZB)
    ac_unit(b, D, -13.0, -13.0, ZB, rot90=True)
    stair_bulkhead(b, D, -22.5, -12.5, ZB)
    for x in (-5.0, 8.0, 13.5):
        planter(b, D, x - 1.6, x + 1.6, 11.0, 12.2, ZA)
    for x in (-4.0, 12.5):
        tree(b, D, x, 23.5, ZA, 0.8)
    ac_unit(b, D, 25.0, 12.0, ZA, rot90=True)
    for s in ((-18.0, 18.0, zd), (-18.0, -20.0, ZB), (-18.0, -5.5, ZB), (2.0, 18.5, ZA), (19.0, 19.5, ZA)):
        b.slot(*s)
    roof_clutter(b, D, (-26.4, -9.6, -26.4, 8.4), ZB, 505, n=5,
                 avoid=[(-20.6, -15.4, 0.4, 5.6), (-14.6, -11.4, -15.0, -11.0), (-24.5, -20.5, -14.7, -10.3)])
    roof_clutter(b, D, (-8.4, 26.4, 9.6, 26.4), ZA, 506, n=5, kinds=SMALL,
                 avoid=[(-6.8, -3.2, 10.6, 12.6), (6.2, 15.3, 10.6, 12.6), (-6.4, -1.6, 21.1, 25.9), (10.1, 14.9, 21.1, 25.9),
                        (23.8, 26.2, 10.2, 13.8)])
    b.col(-27.7, -8.3, 8.3, 27.7, 0, zd)
    b.col(-27.7, -8.3, -27.7, 9, 0, ZB)
    b.col(-9, 27, 9, 27, 0, ZA)
    L.box(-27, -9, 9, 27, 0, ZT, GG, skip=("-z",), mats={"+z": RD})
    L.box(-27, -9, -27, 9, 0, ZB, GG, skip=("-z", "+y"), mats={"+z": C})
    L.box(-9, 27, 9, 27, 0, ZA, O, skip=("-z", "-x"), mats={"+z": C})
    return b


# ----------------------------------------------------------------------------------------------------
# 06  Warehouse with sawtooth roof
# ----------------------------------------------------------------------------------------------------
def m06_warehouse(lib):
    b = Bld(lib, 6, "Warehouse", 1606)
    M, D, L = b.mass, b.det, b.lod
    BRK, O, C = b.m("bld_brick"), b.m("bld_office"), b.m("bld_concrete")
    Z, GRA, SD, YEL, LW, BR, ST, RD = (b.sw(n) for n in ("zinc", "graphite", "steel_dark", "yellow", "light_warm",
                                                         "brick_red", "stone", "roof_dark"))
    ZW, ZR = 10.8, 15.0
    M.box(-30, 18, -18, 18, 0, ZW, BRK, skip=("-z", "+z", "+x"))
    for i in range(4):
        x0 = -30 + 12 * i
        M.xz_prism([(x0, ZW), (x0 + 12, ZW), (x0, ZR)], -18, 18, [None, Z, O], BRK)
    # annex (offices)
    ZA = 14.4
    M.box(18, 30, -18, 18, 0, ZA, BRK, skip=("-z",), mats={"+z": C})
    D.ring_wall(rect(18, 30, -18, 18), ZA, ZA + 1.0, 0.3, BRK, inner_mat=C, top_mat=ST)
    D.ring_slab(rect(18, 30, -18, 18), ZA - 0.5, ZA - 0.2, 0.2, ST)
    D.ring_slab([(-30, -18), (18, -18), (18, 18), (-30, 18)], ZW - 0.4, ZW - 0.1, 0.25, ST)
    # loading docks on -Y
    for x in (-24.0, -14.0, -4.0, 6.0):
        D.box(x - 2.0, x + 2.0, -18.08, -18.0, 0.0, 4.6, SD, skip=("+y", "-z"))
        for k in range(6):
            zz = 0.5 + k * 0.7
            D.box(x - 1.95, x + 1.95, -18.12, -18.08, zz, zz + 0.08, GRA, skip=("+y", "-z"))
        for dx in (-2.3, 2.0):
            D.box(x + dx, x + dx + 0.3, -18.4, -18.0, 0.0, 1.3, YEL, skip=("-z", "+y"))
        D.box(x - 1.0, x + 1.0, -20.4, -20.2, 5.25, 5.4, LW, skip=("+z",))
        D.beam((x, -18.0, 8.4), (x, -21.2, 5.7), 0.1, 0.1, GRA)
    D.box(-27.5, 9.0, -21.6, -18.0, 5.4, 5.7, GRA)
    D.box(-27.5, 9.0, -19.6, -18.0, 0.0, 1.2, C, skip=("-z", "+y"))
    # personnel doors + small canopies on the annex
    D.box(22.5, 25.5, -18.06, -18.0, 0.0, 3.0, GRA, skip=("+y", "-z"))
    D.box(21.5, 26.5, -19.6, -18.0, 3.3, 3.5, SD)
    # chimney
    cx, cy = -22.0, 12.0
    D.cylinder(cx, cy, 1.75, 1.15, 0.0, 34.0, 12, BR, top=None)
    D.annulus(cx, cy, 0.85, 1.2, 33.4, 34.0, 12, SD, faces=("top", "outer", "inner", "bottom"))
    for zz in (24.0, 29.0):
        k = zz / 34.0
        r = 1.75 + (1.15 - 1.75) * k
        D.annulus(cx, cy, r - 0.05, r + 0.12, zz, zz + 0.35, 12, SD, faces=("top", "outer", "bottom"))
    D.cylinder(cx, cy, 0.86, 0.86, 32.8, 33.4, 12, RD, top=RD, side=False)
    beacon(b, D, cx + 1.25, cy, 34.0, 0.22)
    beacon(b, D, cx - 1.25, cy, 34.0, 0.22)
    # roof ventilators on the sawtooth slopes
    for i in range(4):
        x0 = -30 + 12 * i
        for y in (-9.0, 9.0):
            xv = x0 + 6.0
            zv = ZR - (ZR - ZW) * (6.0 / 12.0)
            vent_stack(b, D, xv, y, zv - 0.3, h=1.6, r=0.45)
    # annex roof: water tank, AC
    ztank = water_tank(b, D, 24.0, 12.0, ZA)
    ac_unit(b, D, 24.0, 6.0, ZA)
    for s in ((24.0, -13.0), (24.0, -6.5), (24.0, 0.0)):
        b.slot(s[0], s[1], ZA)
    b.col(-30, 18, -18, 18, 0, ZR)
    b.col(18, 30, -18, 18, 0, ZA)
    b.col(cx - 1.75, cx + 1.75, cy - 1.75, cy + 1.75, 0, 34.0)
    b.col(21.5, 26.5, 9.5, 14.5, ZA, ztank)
    L.box(-30, 18, -18, 18, 0, ZW, BRK, skip=("-z", "+z", "+x"))
    for i in range(4):
        x0 = -30 + 12 * i
        L.xz_prism([(x0, ZW), (x0 + 12, ZW), (x0, ZR)], -18, 18, [None, Z, O], BRK)
    L.box(18, 30, -18, 18, 0, ZA, BRK, skip=("-z",), mats={"+z": C})
    L.cylinder(cx, cy, 1.75, 1.15, 0, 34.0, 6, BR)
    return b


# ----------------------------------------------------------------------------------------------------
# 07  Residential tower with staggered balconies
# ----------------------------------------------------------------------------------------------------
def m07_residential_tower(lib):
    b = Bld(lib, 7, "ResidentialTower", 1707)
    M, D, L = b.mass, b.det, b.lod
    BRK, G, C = b.m("bld_brick"), b.m("bld_glass_blue"), b.m("bld_concrete")
    WH, GD, GRA, LW, SIL = (b.sw(n) for n in ("white", "glass_dark", "graphite", "light_warm", "silver"))
    h, Z0, Z1 = 12.0, 7.2, 93.6
    M.box(-h, h, -h, h, 0.0, Z0, G, skip=("-z", "+z"))
    M.box(-h, h, -h, h, Z0, Z1, BRK, skip=("-z",), mats={"+z": C})
    D.ring_slab(rect(-h, h, -h, h), Z0 - 0.35, Z0, 1.8, WH)
    D.ring_slab(rect(-h, h, -h, h), Z0 - 0.5, Z0 - 0.35, 1.6, LW, bottom=True)
    dep = 1.7
    for k in range(1, 24):
        z = Z0 + FLOOR * k
        for fi, (face, (a, bb)) in enumerate(rect_faces(-h, h, -h, h)):
            half = (k + fi) % 2
            lo, hi = (a, 0.0) if half == 0 else (0.0, bb)
            face_box(D, face, lo, hi, 0.0, dep, z - 0.22, z, WH)
            face_box(D, face, lo, hi, dep - 0.06, dep, z, z + 1.05, GD, skip_back=False, extra_skip=("-z",))
            for e in (lo, hi):
                face_box(D, face, e - 0.03 if e == lo else e - 0.03, e + 0.03, 0.0, dep - 0.06, z, z + 1.05, GD,
                         extra_skip=("-z",))
    # vertical corner piers (white) tie the balconies together
    for sx in (-1, 1):
        for sy in (-1, 1):
            D.box(sx * h - 0.35, sx * h + 0.35, sy * h - 0.35, sy * h + 0.35, Z0, Z1 + 1.2, WH, skip=("-z",))
    D.ring_wall(rect(-h, h, -h, h), Z1, Z1 + 1.1, 0.25, GD, inner_mat=GD, top_mat=SIL)
    # rooftop glass pavilion with overhanging roof, water tank, mast
    ZP = Z1 + 7.2
    M.box(-6, 6, -6, 6, Z1, ZP, G, skip=("-z",), mats={"+z": C})
    D.box(-7.5, 7.5, -7.5, 7.5, ZP, ZP + 0.5, WH)
    D.box(-7.2, 7.2, -7.2, 7.2, ZP - 0.1, ZP, LW, skip=("+z",))
    ztank = water_tank(b, D, 0.0, 0.0, ZP + 0.5, r=2.5)
    mast(b, D, 5.8, 5.8, ZP + 0.5, 8.0, 0.2, arms=1, beacons=(1.0,))
    for s in ((9.0, 9.0), (-9.0, 9.0), (9.0, -9.0), (-9.0, -9.0)):
        b.slot(s[0], s[1], Z1)
    for i, area in enumerate(((-6.5, 6.5, 7.6, 11.4), (-6.5, 6.5, -11.4, -7.6), (7.6, 11.4, -6.5, 6.5), (-11.4, -7.6, -6.5, 6.5))):
        roof_clutter(b, D, area, Z1, 707 + i, n=2, kinds=["vent", "hatch", "acs", "mush", "cabinet"])
    b.col(-13, 13, -13, 13, 0, Z1)
    b.col(-7.5, 7.5, -7.5, 7.5, Z1, ZP + 0.5)
    b.col(-2.8, 2.8, -2.8, 2.8, ZP + 0.5, ztank)
    L.box(-h, h, -h, h, 0, Z0, G, skip=("-z", "+z"))
    L.box(-h, h, -h, h, Z0, Z1, BRK, skip=("-z",), mats={"+z": C})
    L.box(-6, 6, -6, 6, Z1, ZP, G, skip=("-z",), mats={"+z": C})
    L.cylinder(0, 0, 2.6, 2.6, ZP, ztank - 1.6, 8, b.sw("wood"), top=b.sw("zinc"))
    return b


# ----------------------------------------------------------------------------------------------------
# 08  Round tower with helipad
# ----------------------------------------------------------------------------------------------------
def m08_round_tower(lib):
    b = Bld(lib, 8, "RoundTower", 1808)
    M, D, L = b.mass, b.det, b.lod
    GC, C = lib.cyl("bld_glass_gold"), b.m("bld_concrete")
    BRZ, GRN, SD, SIL, RD, GRA, LW = (b.sw(n) for n in ("bronze", "granite", "steel_dark", "silver", "roof_dark",
                                                        "graphite", "light_warm"))
    R = R_ROUND
    Z0, Z1, ZN, ZD = 7.2, 108.0, 111.6, 112.4
    M.cylinder(0, 0, R - 3.0, R - 3.0, 0.0, Z0, 36, GC)
    M.cylinder(0, 0, R, R, Z0, Z1, 36, GC, bottom=SIL)
    D.annulus(0, 0, R - 3.1, R, Z1 - 0.1, Z1, 36, C, faces=("top",))
    for k in range(1, 28):
        z = Z0 + FLOOR * k
        D.annulus(0, 0, R - 0.05, R + 0.45, z - 0.13, z + 0.13, 36, BRZ, faces=("top", "outer", "bottom"))
    D.annulus(0, 0, R - 0.05, R + 0.6, Z0 - 0.3, Z0 + 0.2, 36, BRZ, faces=("top", "outer", "bottom"))
    D.annulus(0, 0, R - 2.0, R - 0.05, Z0 - 0.45, Z0 - 0.3, 36, LW, faces=("bottom",))
    for k in range(0, 36, 2):
        a = 2 * math.pi * k / 36
        D.cylinder((R - 0.8) * math.cos(a), (R - 0.8) * math.sin(a), 0.5, 0.5, 0.0, Z0 - 0.3, 8, GRN)
    # mechanical neck with louvre fins, cantilevered helipad deck
    rn = R - 2.4
    D.cylinder(0, 0, rn, rn, Z1, ZN, 36, SD)
    for k in range(36):
        a = 2 * math.pi * (k + 0.5) / 36
        c, s = math.cos(a), math.sin(a)
        D.beam((c * (rn + 0.25), s * (rn + 0.25), Z1), (c * (rn + 0.25), s * (rn + 0.25), ZN), 0.12, 0.5, GRA)
    rd = R + 1.8
    M.cylinder(0, 0, rd, rd, ZN, ZD, 36, SIL, top=RD, bottom=SIL)
    D.annulus(0, 0, rd - 0.12, rd, ZD, ZD + 0.9, 36, GRA, faces=("top", "outer", "inner"))
    helipad(b, D, 0, 0, ZD, 26.0, light_r=rd - 0.8, round_=True)
    for sx in (-1, 1):
        mast(b, D, sx * (rd - 1.2), 0.0, ZD, 6.0, 0.18, arms=0, beacons=(1.0,))
    for s in ((0, 0), (11.5, 0), (-11.5, 0), (0, 11.5), (0, -11.5)):
        b.slot(s[0], s[1], ZD)
    k = 0.62
    b.col(-R, R, -k * R, k * R, 0, ZN)
    b.col(-k * R, k * R, -R, R, 0, ZN)
    b.col(-rd, rd, -k * rd, k * rd, ZN, ZD)
    b.col(-k * rd, k * rd, -rd, rd, ZN, ZD)
    L.cylinder(0, 0, R, R, 0, Z1, 16, GC)
    L.cylinder(0, 0, rn, rn, Z1, ZN, 8, SD)
    L.cylinder(0, 0, rd, rd, ZN, ZD, 16, SIL, top=RD, bottom=SIL)
    return b


# ----------------------------------------------------------------------------------------------------
# 09  Mid-rise office: concrete egg-crate frame, recessed penthouse, overhanging roof
# ----------------------------------------------------------------------------------------------------
def m09_midrise_office(lib):
    b = Bld(lib, 9, "MidriseOffice", 1909)
    M, D, L = b.mass, b.det, b.lod
    O, G, C = b.m("bld_office"), b.m("bld_glass_blue"), b.m("bld_concrete")
    GRA, SIL, LW = b.sw("graphite"), b.sw("silver"), b.sw("light_warm")
    hx, hy, Z1 = 21.0, 15.0, 39.6
    M.box(-hx, hx, -hy, hy, 0, Z1, O, skip=("-z",), mats={"+z": C})
    for face, (a, bb) in rect_faces(-hx, hx, -hy, hy):
        p = a + 6.0
        while p < bb - 1.0:
            face_box(D, face, p - 0.35, p + 0.35, 0.0, 1.0, 0.0, Z1 + 0.6, C, extra_skip=("-z",))
            p += 6.0
        for k in range(1, 11):
            z = FLOOR * k
            face_box(D, face, a, bb, 0.0, 0.8, z - 0.25, z + 0.25, C)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x0, x1 = (hx - 0.7, hx + 1.0) if sx > 0 else (-hx - 1.0, -hx + 0.7)
            y0, y1 = (hy - 0.7, hy + 1.0) if sy > 0 else (-hy - 1.0, -hy + 0.7)
            D.box(x0, x1, y0, y1, 0, Z1 + 0.6, C, skip=("-z",))
    D.ring_wall(rect(-hx, hx, -hy, hy), Z1, Z1 + 1.1, 0.3, C, top_mat=SIL)
    D.box(-6, 6, hy + 0.8, hy + 4.0, 3.6, 3.9, GRA)
    D.box(-5.6, 5.6, hy + 1.2, hy + 3.7, 3.5, 3.6, LW, skip=("+z",))
    # penthouse + hat roof
    ZP, ZH = Z1 + 7.2, Z1 + 7.8
    M.box(-15, 15, -9, 9, Z1, ZP, G, skip=("-z", "+z"))
    M.box(-17.4, 17.4, -11.4, 11.4, ZP, ZH, GRA)
    for face, (a, bb) in rect_faces(-17.0, 17.0, -11.0, 11.0):
        face_box(D, face, a + 0.5, bb - 0.5, -0.35, -0.1, ZP - 0.12, ZP, LW, skip_back=False, extra_skip=("+z",))
    ac_unit(b, D, 0.0, -6.0, ZH)
    ac_unit(b, D, 0.0, 6.0, ZH)
    ac_unit(b, D, -15.0, 0.0, ZH, rot90=True)
    mast(b, D, 14.5, 7.5, ZH, 7.0, 0.2, arms=1, beacons=(1.0,))
    solar_array(b, D, 3.0, 13.0, -10.0, -3.0, ZH, rows=2)
    for s in ((18.0, 12.0, Z1), (-18.0, 12.0, Z1), (18.0, -12.0, Z1), (-18.0, -12.0, Z1), (-8.0, 0.0, ZH), (8.0, 2.5, ZH)):
        b.slot(*s)
    for i, area in enumerate(((-14.5, 14.5, 9.6, 14.3), (-14.5, 14.5, -14.3, -9.6), (15.6, 20.3, -8.5, 8.5),
                              (-20.3, -15.6, -8.5, 8.5))):
        roof_clutter(b, D, area, Z1, 909 + i, n=3, kinds=SMALL + ["ac", "pipe"])
    b.col(-hx - 1.0, hx + 1.0, -hy - 1.0, hy + 1.0, 0, Z1)
    b.col(-15, 15, -9, 9, Z1, ZP)
    b.col(-17.4, 17.4, -11.4, 11.4, ZP, ZH)
    L.box(-hx, hx, -hy, hy, 0, Z1, O, skip=("-z",), mats={"+z": C})
    L.box(-15, 15, -9, 9, Z1, ZP, G, skip=("-z", "+z"))
    L.box(-17.4, 17.4, -11.4, 11.4, ZP, ZH, GRA)
    return b


# ----------------------------------------------------------------------------------------------------
# 10  Landmark skyscraper
# ----------------------------------------------------------------------------------------------------
def m10_landmark(lib):
    b = Bld(lib, 10, "Landmark", 2010)
    M, D, L = b.mass, b.det, b.lod
    P, G, GG, C = b.m("bld_panel"), b.m("bld_glass_blue"), b.m("bld_glass_gold"), b.m("bld_concrete")
    GLD, SIL, ST, LW, GRNS, GRA = (b.sw(n) for n in ("gold", "silver", "stone", "light_warm", "green", "graphite"))
    ZP, Z1, Z2, ZL = 18.0, 118.8, 147.6, 157.2
    pod = [(-27, -27), (27, -27), (27, 27), (9, 27), (9, 21), (-9, 21), (-9, 27), (-27, 27)]
    em = [P] * 8
    em[4] = G
    ZB = 14.4
    M.prism(pod, 0.0, ZB, P, edge_mats=em)
    M.prism(rect(-27, 27, -27, 27), ZB, ZP, P, top=C, bottom=C)
    D.ring_wall(rect(-27, 27, -27, 27), ZP, ZP + 1.1, 0.3, P, inner_mat=C, top_mat=ST)
    D.ring_slab(rect(-27, 27, -27, 27), ZB - 0.3, ZB, 0.35, ST)
    for x in (-4.5, 0.0, 4.5):
        D.box(x - 0.4, x + 0.4, 26.2, 27.0, 0.0, ZB, ST, skip=("-z", "+z"))
    D.box(-9, 9, 21, 27.8, 7.0, 7.4, SIL)
    D.box(-8.5, 8.5, 21.5, 27.4, 6.9, 7.0, LW, skip=("+z",))
    oct1 = octagon(18.0, 18.0, 6.0)
    oct2 = octagon(15.0, 15.0, 6.0)
    ZS0, ZS1 = 64.8, 72.0
    M.prism(oct1, ZP, ZS0, G, top=C)
    M.prism(octagon(16.5, 16.5, 5.5), ZS0, ZS1, GG)
    M.prism(oct1, ZS1, Z1, G, top=C, bottom=C)
    M.prism(oct2, Z1, Z2, G, top=C)
    D.ring_slab(octagon(16.5, 16.5, 5.5), ZS1 - 0.35, ZS1 - 0.2, 0.15, LW, bottom=True)
    # silver fins on the main faces, gold posts on the chamfer corners
    for (outl, z0, z1) in ((oct1, ZP, Z1), (oct2, Z1, Z2)):
        for (p0, p1) in outline_edges(outl):
            if abs(p0[0] - p1[0]) < 1e-6 or abs(p0[1] - p1[1]) < 1e-6:
                if outl is oct1:
                    fins_on_edge(D, p0, p1, z0, ZS0, 3.0, 0.5, 0.14, SIL)
                    fins_on_edge(D, p0, p1, ZS1, z1 + 0.4, 3.0, 0.5, 0.14, SIL)
                else:
                    fins_on_edge(D, p0, p1, z0, z1 + 0.4, 3.0, 0.5, 0.14, SIL)
        for (x, y) in outl:
            ux, uy = (1 if x > 0 else -1), (1 if y > 0 else -1)
            cx, cy = x + ux * 0.18, y + uy * 0.18
            D.box(cx - 0.4, cx + 0.4, cy - 0.4, cy + 0.4, z0, z1 + 1.2, GLD, skip=("-z",))
        D.ring_slab(outl, z1 - 0.35, z1, 0.3, GLD)
        D.ring_wall(outl, z1, z1 + 1.0, 0.25, G, inner_mat=C, top_mat=GLD)
    # crown: gold glass lantern + 8 gold ribs converging on the spire, lit edges
    lan = octagon(10.5, 10.5, 4.0)
    ZL = 159.6
    M.frustum(lan, Z2, ZL, 3.6, GG, top=C)
    ztip = 169.4
    for (x, y) in oct2:
        a = (x * 1.0, y * 1.0, Z2)
        bpt = (x * 0.06, y * 0.06, 166.0)
        D.beam(a, bpt, 0.75, 0.55, GLD)
        D.beam((x * 1.045, y * 1.045, Z2 + 0.5), (x * 0.1, y * 0.1, 165.4), 0.2, 0.2, LW)
    D.cylinder(0, 0, 1.4, 0.05, ZL, ztip, 8, SIL, bottom=SIL, phase=math.pi / 8)
    D.annulus(0, 0, 0.7, 1.4, 164.6, 165.3, 8, GLD, faces=("top", "outer", "bottom"), phase=math.pi / 8)
    beacon(b, D, 0, 0, ztip, 0.28)
    beacon(b, D, 1.1, 0, 165.3, 0.2)
    beacon(b, D, -1.1, 0, 165.3, 0.2)
    # podium roof garden
    for (x, y) in ((-22.5, -13.5), (22.5, 13.5), (-13.5, 23.5), (13.5, -23.5)):
        planter(b, D, x - 1.5, x + 1.5, y - 1.5, y + 1.5, ZP, 0.7)
        tree(b, D, x, y, ZP + 0.7, 0.9)
    stair_bulkhead(b, D, 22.5, -13.0, ZP, rot90=True)
    ac_unit(b, D, -22.5, 13.0, ZP, rot90=True)
    for s in ((-22.5, 22.5), (22.5, 22.5), (-22.5, -22.5), (22.5, -22.5), (0.0, -22.5), (22.5, 0.0)):
        b.slot(s[0], s[1], ZP)
    av = [(-24.5, -20.5, -15.5, -11.5), (20.5, 24.5, 11.5, 15.5), (-15.5, -11.5, 21.5, 25.5), (11.5, 15.5, -25.5, -21.5),
          (20.7, 24.3, -15.1, -10.9), (-24.2, -20.8, 11.2, 14.8)]
    for i, area in enumerate(((-26.4, 26.4, 18.8, 26.4), (-26.4, 26.4, -26.4, -18.8), (18.8, 26.4, -18.0, 18.0),
                              (-26.4, -18.8, -18.0, 18.0))):
        roof_clutter(b, D, area, ZP, 1010 + i, n=3, kinds=SMALL + ["ac"], avoid=av)
    b.col(-27, 27, -27, 27, 0, ZP)
    b.col(-18.6, 18.6, -18.6, 18.6, ZP, Z1)
    b.col(-15.6, 15.6, -15.6, 15.6, Z1, Z2)
    b.col(-10.5, 10.5, -10.5, 10.5, Z2, ZL)
    b.col(-1.6, 1.6, -1.6, 1.6, ZL, ztip + 0.5)
    L.prism(pod, 0, ZP, P, top=C, edge_mats=em)
    L.prism(oct1, ZP, Z1, G, top=C)
    L.prism(oct2, Z1, Z2, G, top=C)
    L.frustum(lan, Z2, 166.0, 9.5, GG, top=None)
    L.cylinder(0, 0, 1.0, 0.0, 160.0, ztip, 4, SIL)
    return b


# ----------------------------------------------------------------------------------------------------
# 11  Parking garage
# ----------------------------------------------------------------------------------------------------
def m11_parking_garage(lib):
    b = Bld(lib, 11, "ParkingGarage", 2111, bevel=0.06)
    M, D, L = b.mass, b.det, b.lod
    C, P = b.m("bld_concrete"), b.m("bld_panel")
    GRA, LC, WH, YEL, BRZ, GD, RUB = (b.sw(n) for n in ("graphite", "light_cool", "white", "yellow", "bronze",
                                                        "glass_dark", "rubber"))
    hx, hy, T = 27.0, 18.0, 0.35
    levels = [3.2 * k for k in range(1, 6)]
    pieces = [(-hx, hx, -hy, -9), (-hx, hx, 9, hy), (-hx, -21, -9, -3.4), (-hx, -21, 3.4, 9), (-21, -15, -9, 9),
              (15, 21, -9, 9), (21, hx, -9, -3.4), (21, hx, 3.4, 9), (-15, 15, -3, 3)]
    for li, z in enumerate(levels):
        for (x0, x1, y0, y1) in pieces:
            D.box(x0, x1, y0, y1, z - T, z, C)
        if li == len(levels) - 1:
            D.box(-15, 15, 3, 9, z - T, z, C)          # roof: close the north ramp hole
        # parapet walls + ceiling light strips
        D.ring_wall(rect(-hx, hx, -hy, hy), z, z + 1.05, 0.2, C)
        for y in (-13.5, 13.5):
            D.box(-25.0, 25.0, y - 0.12, y + 0.12, z - T - 0.08, z - T, LC, skip=("+z",))
        for x in (-18.0, 18.0):
            D.box(x - 0.12, x + 0.12, -7.5, 7.5, z - T - 0.08, z - T, LC, skip=("+z",))
    # scissor ramps: odd levels in the south hole rising +x, even levels in the north hole rising -x
    zs = [0.0] + levels
    for L_ in range(1, 6):
        za, zb = zs[L_ - 1], zs[L_]
        if L_ % 2 == 1:
            D.xz_prism([(-15, max(za - T, 0.0)), (15, zb - T), (15, zb), (-15, za + 0.01)], -9, -3, [C, None, C, None], C)
        else:
            D.xz_prism([(-15, zb - T), (15, za - T), (15, za), (-15, zb)], 3, 9, [C, None, C, None], C)
    # columns
    cols = [(x, y) for x in (-22.5, -13.5, -4.5, 4.5, 13.5, 22.5) for y in (-17.5, 17.5)]
    cols += [(sx * 26.5, sy * 13.5) for sx in (-1, 1) for sy in (-1, 1)]
    cols += [(sx * 15.3, sy * 9.3) for sx in (-1, 1) for sy in (-1, 1)]
    cols += [(sx * 15.3, sy * 3.3) for sx in (-1, 1) for sy in (-1, 1)]
    for (x, y) in cols:
        D.box(x - 0.3, x + 0.3, y - 0.3, y + 0.3, 0.0, levels[-1] - T, C, skip=("-z", "+z"))
    # stair / lift cores on the short ends
    ZC = levels[-1] + 4.8
    for sx in (-1, 1):
        x0, x1 = (20.8, 27.4) if sx > 0 else (-27.4, -20.8)
        M.box(x0, x1, -3.4, 3.4, 0.0, ZC, P, skip=("-z",), mats={"+z": C})
        xo = x1 if sx > 0 else x0
        face_box(D, ("+x" if sx > 0 else "-x", xo), -1.2, 1.2, 0.0, 0.08, 1.0, ZC - 1.0, GD, extra_skip=("-z",))
        D.ring_wall(rect(x0, x1, -3.4, 3.4), ZC, ZC + 0.8, 0.2, C)
        D.box(x0 + 1.5, x1 - 1.5, -2.0, 2.0, ZC, ZC + 2.2, C, skip=("-z",))
    # bronze screen slats on the north facade
    x = -19.5
    while x <= 19.5:
        D.box(x - 0.06, x + 0.06, hy, hy + 0.35, 3.2, levels[-1] + 1.05, BRZ, skip=("-y", "-z"))
        x += 1.5
    # roof deck: stall lines, lamp poles
    z = levels[-1]
    for y0, y1 in ((-17.4, -12.2), (12.2, 17.4)):
        x = -24.0
        while x <= 24.0 + 1e-6:
            D.box(x - 0.06, x + 0.06, y0, y1, z, z + 0.06, WH, skip=("-z",))
            x += 2.5
    for (x, y) in ((-9.0, 0.0), (0.0, 0.0), (9.0, 0.0), (-18.0, 0.0), (18.0, 0.0)):
        lamp_pole(b, D, x, y, z, 6.0)
    for i in range(10):
        xa = -15.0 + 3.0 * i
        D.box(xa, xa + 3.0, -9.3, -9.0, z, z + 0.55, YEL if i % 2 == 0 else GRA, skip=("-z",))
    for s in ((-22.0, 14.8), (-10.0, 14.8), (10.0, -14.8), (22.0, -14.8), (5.0, 14.8)):
        b.slot(s[0], s[1], z)
    b.col(-hx, hx, -hy, hy, 0.0, z)
    b.col(-27.4, -20.8, -3.4, 3.4, 0.0, ZC)
    b.col(20.8, 27.4, -3.4, 3.4, 0.0, ZC)
    # LOD: alternating solid (slab + parapet) and open (dark) bands
    zz = [0.0]
    for z in levels:
        zz += [z - T, z + 1.05]
    for i in range(len(zz) - 1):
        L.prism(rect(-hx, hx, -hy, hy), zz[i], zz[i + 1], RUB if i % 2 == 0 else C)
    L.box(-hx, hx, -hy, hy, levels[-1] + 1.05, levels[-1] + 1.05, C, skip=("-z", "-x", "+x", "-y", "+y"))
    L.box(-27.4, -20.8, -3.4, 3.4, 0.0, ZC, P, skip=("-z",), mats={"+z": C})
    L.box(20.8, 27.4, -3.4, 3.4, 0.0, ZC, P, skip=("-z",), mats={"+z": C})
    return b


# ----------------------------------------------------------------------------------------------------
# 12  Podium + tower
# ----------------------------------------------------------------------------------------------------
def m12_podium_tower(lib):
    b = Bld(lib, 12, "PodiumTower", 2212)
    M, D, L = b.mass, b.det, b.lod
    BRK, O, C = b.m("bld_brick"), b.m("bld_office"), b.m("bld_concrete")
    ST, GRA, SIL, LW, LC, GD, LIT, NP, NC, WAT, WOOD = (b.sw(n) for n in (
        "stone", "graphite", "silver", "light_warm", "light_cool", "glass_dark", "window_lit", "neon_pink", "neon_cyan",
        "water", "wood"))
    ZP, ZT, ZC = 18.0, 104.4, 115.2
    M.box(-30, 30, -24, 24, 0, ZP, BRK, skip=("-z",), mats={"+z": C})
    D.ring_wall(rect(-30, 30, -24, 24), ZP, ZP + 1.1, 0.3, BRK, inner_mat=C, top_mat=ST)
    D.ring_slab(rect(-30, 30, -24, 24), ZP - 0.6, ZP - 0.2, 0.3, ST)
    # retail ground floor: shop windows, continuous canopy with lights, neon blade signs
    rng = np.random.default_rng(1212)
    for face, (a, bb) in rect_faces(-30, 30, -24, 24):
        p = a + 3.0
        while p < bb - 1.0:
            face_box(D, face, p - 2.3, p + 2.3, 0.0, 0.08, 0.2, 3.4, LIT if rng.random() < 0.65 else GD, extra_skip=("-z",))
            p += 6.0
    D.ring_slab(rect(-30, 30, -24, 24), 3.8, 4.1, 2.2, GRA)
    D.ring_slab(rect(-30, 30, -24, 24), 3.7, 3.8, 1.9, LW)
    for (x, y, m, sx, sy) in ((-29.5, -20.0, NP, -1, 0), (29.5, 20.0, NC, 1, 0), (20.0, -23.5, NC, 0, -1), (-20.0, 23.5, NP, 0, 1)):
        if sx:
            D.box(x + sx * 0.2, x + sx * 1.4, y - 0.15, y + 0.15, 5.5, 12.5, m)
            D.box(x, x + sx * 0.25, y - 0.1, y + 0.1, 6.0, 12.0, GRA, skip=("+x" if sx < 0 else "-x",))
        else:
            D.box(x - 0.15, x + 0.15, y + sy * 0.2, y + sy * 1.4, 5.5, 12.5, m)
            D.box(x - 0.1, x + 0.1, y, y + sy * 0.25, 6.0, 12.0, GRA, skip=("+y" if sy < 0 else "-y",))
    # tower + sloped glass crown
    x0, x1, y0, y1 = -27.0, 3.0, -18.0, 6.0
    M.box(x0, x1, y0, y1, ZP, ZT, O, skip=("-z", "+z"))
    M.xz_prism([(x0, ZT), (x1, ZT), (x1, ZC), (x0, ZT + 1.2)], y0, y1, [None, O, GD, O], O)
    for y in range(-15, 6, 3):
        D.beam((x1 + 0.05, y, ZC + 0.08), (x0 - 0.05, y, ZT + 1.28), 0.14, 0.14, SIL)
    D.beam((x1 + 0.1, y0 - 0.1, ZC + 0.12), (x1 + 0.1, y1 + 0.1, ZC + 0.12), 0.22, 0.22, LC)
    for yb in (y0 + 0.4, y1 - 0.4):
        beacon(b, D, x1 - 0.4, yb, ZC + 0.25, 0.24)
    for (cx, cy) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        z1 = ZC if cx == x1 else ZT + 1.2
        D.box(cx - 0.35, cx + 0.35, cy - 0.35, cy + 0.35, ZP, z1 + 0.3, SIL, skip=("-z",))
    ZM = ZP + FLOOR * 12
    D.ring_slab(rect(x0, x1, y0, y1), ZM, ZM + FLOOR, 0.12, GRA)
    for k in range(5):
        zz = ZM + 0.35 + k * 0.62
        D.ring_slab(rect(x0, x1, y0, y1), zz, zz + 0.16, 0.42, SIL)
    for face, (a, bb) in rect_faces(x0, x1, y0, y1):
        p = a + 6.0
        while p < bb - 1.0:
            face_box(D, face, p - 0.1, p + 0.1, 0.0, 0.6, ZP + 3.6, ZT, SIL, extra_skip=("-z",))
            p += 6.0
    # roof garden on the podium: pool + deck, planters, trees
    D.box(7.0, 23.0, -17.0, -3.0, ZP, ZP + 0.12, WOOD, skip=("-z",))
    D.box(9.0, 21.0, -15.0, -5.0, ZP + 0.12, ZP + 0.2, WAT, skip=("-z",))
    D.ring_wall(rect(8.6, 21.4, -15.4, -4.6), ZP + 0.12, ZP + 0.35, 0.4, ST)
    for (x, y) in ((12.0, 3.0), (26.0, -19.0), (26.0, 8.0), (6.0, 20.0), (-26.0, 20.0), (-2.0, -21.0)):
        planter(b, D, x - 1.4, x + 1.4, y - 1.4, y + 1.4, ZP, 0.7)
        tree(b, D, x, y, ZP + 0.7, 0.9)
    ac_unit(b, D, 26.0, -3.0, ZP, rot90=True)
    stair_bulkhead(b, D, 18.0, 20.0, ZP)
    for s in ((-19.0, 15.0), (-8.0, 15.0), (26.0, 18.0), (15.0, 9.0), (-26.0, -21.0)):
        b.slot(s[0], s[1], ZP)
    roof_clutter(b, D, (-29.4, 2.4, 6.6, 23.4), ZP, 1201, n=4, kinds=["ac", "acs", "vent", "hatch", "cabinet"],
                 avoid=[(-27.9, -24.1, 18.1, 21.9), (4.1, 7.9, 18.1, 21.9), (16.0, 20.0, 17.8, 22.2)])
    b.col(-30, 30, -24, 24, 0, ZP)
    b.col(x0, x1, y0, y1, ZP, ZT)
    b.col(-12.0, x1, y0, y1, ZT, ZC)
    b.col(x0, -12.0, y0, y1, ZT, ZT + 5.4)
    L.box(-30, 30, -24, 24, 0, ZP, BRK, skip=("-z",), mats={"+z": C})
    L.box(x0, x1, y0, y1, ZP, ZT, O, skip=("-z", "+z"))
    L.xz_prism([(x0, ZT), (x1, ZT), (x1, ZC), (x0, ZT + 1.2)], y0, y1, [None, O, GD, O], O)
    return b


MODULES = [m01_glass_tower, m02_setback_tower, m03_office_slab, m04_apartment_block, m05_lshape_tower, m06_warehouse,
           m07_residential_tower, m08_round_tower, m09_midrise_office, m10_landmark, m11_parking_garage,
           m12_podium_tower]


# ----------------------------------------------------------------------------------------------------
# checks + previews
# ----------------------------------------------------------------------------------------------------
def module_stats(root, lod):
    geo = [c for c in root.children if c.type == "MESH"]
    mn, mx = world_bbox(geo)
    return dict(tris=tri_count(geo), lod_tris=tri_count([lod]), size=tuple(round(v, 2) for v in (mx - mn)),
                min=tuple(round(v, 2) for v in mn), max=tuple(round(v, 2) for v in mx))


def check_module(root, lod, st):
    name = root.name
    sx, sy, sz = st["size"]
    assert sx <= 66.5 and sy <= 66.5, f"{name}: footprint {sx} x {sy} exceeds 66 x 66"
    assert 14.0 <= sz <= 170.5, f"{name}: height {sz}"
    assert abs(st["min"][2]) < 0.05, f"{name}: base not at z=0 ({st['min'][2]})"
    assert 600 <= st["tris"] <= 28000, f"{name}: {st['tris']} triangles"
    assert 12 <= st["lod_tris"] <= 1500, f"{name}: LOD {st['lod_tris']} triangles"
    cols = [c for c in root.children if c.name.startswith("COL_")]
    slots = [c for c in root.children if c.name.startswith("Roof_Slot_")]
    assert 1 <= len(cols) <= 5, f"{name}: {len(cols)} colliders"
    assert len(slots) >= 1, f"{name}: no roof slots"
    # footprint centred on the origin
    cx = (st["min"][0] + st["max"][0]) / 2
    cy = (st["min"][1] + st["max"][1]) / 2
    assert abs(cx) < 3.5 and abs(cy) < 3.5, f"{name}: footprint centre ({cx:.1f}, {cy:.1f}) not at origin"


def arrange(pairs, spacing=110.0, per_row=4):
    rows = (len(pairs) + per_row - 1) // per_row
    for i, (root, lod) in enumerate(pairs):
        r, c = divmod(i, per_row)
        p = Vector(((c - (per_row - 1) / 2) * spacing, -(r - (rows - 1) / 2) * spacing, 0.0))
        root.location = p
        lod.location = p


def set_visible(objs, visible):
    for o in objs:
        o.hide_render = not visible
        for c in descendants(o):
            c.hide_render = not visible


# game look (src/world/sky.ts): sun 0xffb27a x 3.6 at elevation 11 deg / azimuth 235 deg, sky gradient dome, ACES-ish
SUN_EL, SUN_AZ = 11.0, 235.0


def sun_dir_blender(el=SUN_EL, az=SUN_AZ):
    e, a = math.radians(el), math.radians(az)
    three = (math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e))
    return Vector((three[0], -three[2], three[1])).normalized()


def game_preview_scene(night=False):
    scene = bpy.context.scene
    world = bpy.data.worlds.get("BLD_Sky") or bpy.data.worlds.new("BLD_Sky")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    mr = nt.nodes.new("ShaderNodeMapRange")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    mr.inputs["From Min"].default_value = -0.3
    mr.inputs["From Max"].default_value = 1.0
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    k = 2.1
    stops = [(-0.3, (0.22, 0.15, 0.16)), (0.0, (2.1, 0.95, 0.42)), (0.06, (1.55, 0.62, 0.26)), (0.22, (0.78, 0.30, 0.36)),
             (0.5, (0.20, 0.13, 0.42)), (1.0, (0.045, 0.06, 0.24))]
    els = ramp.color_ramp.elements
    while len(els) < len(stops):
        els.new(0.5)
    for el, (z, c) in zip(els, stops):
        el.position = (z + 0.3) / 1.3
        el.color = (c[0] / k, c[1] / k, c[2] / k, 1.0)
    bg.inputs["Strength"].default_value = k * (0.25 if night else 1.0)
    sun = bpy.data.lights.new("BLD_Sun", "SUN")
    sun.energy = 0.6 if night else 3.6
    sun.color = hexc("#ffb27a")[:3]
    sun.angle = math.radians(1.2)
    so = bpy.data.objects.new("BLD_Sun", sun)
    scene.collection.objects.link(so)
    so.rotation_euler = sun_dir_blender().to_track_quat("Z", "Y").to_euler()
    gp_mesh = bpy.data.meshes.new("BLD_Ground")
    gs = 1500.0
    gp_mesh.from_pydata([(-gs, -gs, 0), (gs, -gs, 0), (gs, gs, 0), (-gs, gs, 0)], [], [(0, 1, 2, 3)])
    gp = bpy.data.objects.new("BLD_Ground", gp_mesh)
    scene.collection.objects.link(gp)
    gp.data.materials.append(make_material("BLD_GroundMat", "#35363b", 0.0, 0.85))
    r = scene.render
    r.engine = "BLENDER_EEVEE_NEXT"
    try:
        scene.eevee.taa_render_samples = 24
    except Exception:
        pass
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "None"
    except Exception:
        pass
    # bloom-ish glow for emissive windows (compositor)
    scene.use_nodes = True
    ct = scene.node_tree
    for n in list(ct.nodes):
        ct.nodes.remove(n)
    rl = ct.nodes.new("CompositorNodeRLayers")
    gl = ct.nodes.new("CompositorNodeGlare")
    gl.glare_type = "FOG_GLOW"
    gl.quality = "MEDIUM"
    try:
        gl.threshold = 1.0
        gl.mix = -0.55
        gl.size = 7
    except Exception:
        pass
    co = ct.nodes.new("CompositorNodeComposite")
    ct.links.new(rl.outputs["Image"], gl.inputs["Image"])
    ct.links.new(gl.outputs["Image"], co.inputs["Image"])
    return [so, gp]


def game_render(tag, objs, views, size=(760, 960), lens=45, night=False):
    """views: dict name -> (azimuth deg, elevation deg, distance multiplier); azimuth 180 = camera on +Y."""
    ensure_dir(PREVIEW_DIR)
    scene = bpy.context.scene
    extra = game_preview_scene(night)
    meshes = [c for o in objs for c in [o] + descendants(o) if c.type == "MESH"]
    mn, mx = world_bbox(meshes)
    center = (mn + mx) / 2
    radius = max((mx - mn).length / 2, 1.0)
    cam_data = bpy.data.cameras.new("BLD_Cam")
    cam_data.lens = lens
    cam_data.clip_end = 6000.0
    cam = bpy.data.objects.new("BLD_Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    r = scene.render
    r.resolution_x, r.resolution_y = size
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    fov = 2 * math.atan((cam_data.sensor_width / 2) / lens)
    fov = 2 * math.atan(math.tan(fov / 2) * min(size) / max(size))      # smaller of the two frame angles
    paths = []
    for name, (az, el, dm) in views.items():
        d = radius / math.sin(fov / 2) * 1.02 * dm
        a, e = math.radians(az), math.radians(el)
        cam.location = center + Vector((math.sin(a) * math.cos(e) * d, -math.cos(a) * math.cos(e) * d, math.sin(e) * d))
        cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
        path = os.path.join(PREVIEW_DIR, f"{tag}_{name}.png")
        r.filepath = path
        bpy.ops.render.render(write_still=True)
        paths.append(path)
    for o in [cam] + extra:
        bpy.data.objects.remove(o)
    log("previews:", ", ".join(os.path.basename(p) for p in paths))
    return paths


def previews(pairs, only, closeup=False):
    everything = [r for r, _ in pairs] + [l for _, l in pairs]
    views = {"sun": (215, 16, 1.0), "shade": (40, 12, 1.0), "high": (160, 45, 1.0)}
    if closeup:
        views = {"close_sun": (230, 4, 0.33), "close_shade": (35, 6, 0.33)}
    for root, lod in pairs:
        if only and not any(root.name.startswith(f"Bld_{o}") for o in only):
            continue
        set_visible(everything, False)
        set_visible([root], True)
        game_render("bld_" + root.name[4:].lower(), [root], views)
    if only:
        set_visible(everything, True)
        return
    arrange(pairs, spacing=110.0, per_row=6)
    set_visible(everything, False)
    set_visible([r for r, _ in pairs], True)
    roots = [r for r, _ in pairs]
    game_render("bld_kit", roots, {"a": (200, 22, 0.6), "b": (20, 26, 0.6), "top": (180, 70, 0.55)}, size=(1600, 900), lens=40)
    game_render("bld_kit_dusk", roots, {"b": (20, 18, 0.6)}, size=(1600, 900), lens=40, night=True)
    set_visible(roots, False)
    set_visible([l for _, l in pairs], True)
    game_render("bld_kit_lod1", [l for _, l in pairs], {"a": (200, 22, 0.6)}, size=(1600, 900), lens=40)
    set_visible(everything, True)


# ----------------------------------------------------------------------------------------------------
def build():
    reset_scene()
    args = script_args()
    only = []
    for a in args:
        if a.startswith("--only="):
            only = [s.strip() for s in a.split("=", 1)[1].split(",") if s.strip()]
    lib = MatLib(seed=7100).build()
    pairs = []
    total = 0
    for fn in MODULES:
        b = fn(lib)
        root, lod = b.finish()
        st = module_stats(root, lod)
        check_module(root, lod, st)
        total += st["tris"] + st["lod_tris"]
        log(f"{root.name:26s} size {st['size'][0]:5.1f} x {st['size'][1]:5.1f} x {st['size'][2]:6.1f} m  "
            f"tris {st['tris']:6d}  LOD1 {st['lod_tris']:5d}  cols {len([c for c in root.children if c.name.startswith('COL_')])}"
            f"  slots {len([c for c in root.children if c.name.startswith('Roof_Slot_')])}")
        pairs.append((root, lod))
    lib.cleanup()
    log(f"total triangles {total}, materials {sorted(m.name for m in bpy.data.materials if m.users)}")
    roots = []
    for root, lod in pairs:
        roots += [root, lod]
    path = export_glb("city_buildings.glb", roots, animations=False)
    info = report(path)
    assert len(info["materials"]) <= 8, info["materials"]
    if "--preview" in args:
        previews(pairs, only, closeup="--closeup" in args)


build()

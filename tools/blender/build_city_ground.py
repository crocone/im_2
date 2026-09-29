"""Armored Flight - street kit ground tiles  ->  public/assets/city_ground.glb

Tiles (Blender axes: X right, Y forward = glTF -Z, Z up; every tile is centred on its origin, exact sizes from the contract):
  Road_Straight      20 x 80 m  top y=0      textured asphalt (HALF tile texture mirrored about the middle => 2x texel density),
                                             dashed yellow centre line, dashed white lane lines, solid edge lines, gutter pans,
                                             wear / patches / trenches / cracks / oil / wheel tracks, real manhole covers + kerb grates.
  Road_Intersection  20 x 20 m  top y=0      4 zebra crossings + stop lines (4-fold rotationally symmetric), wear, manholes.
  Sidewalk_Straight   4 x 72 m  top y=0.15   1 m concrete flags (albedo/ORM/normal), real kerb (rounded top) on the -X side with
                                             two kerb inlets (drains) and a utility cover.  Rotate it so that -X faces the road.
  Sidewalk_Corner     4 x  4 m  top y=0.15   same paving, rounded OUTER corner at (-X, -Z glTF) (= -X,+Y Blender), kerb around it and an
                                             asphalt filler patch (y=0) so the rounded corner never leaves a hole next to the junction.
  Lot_Ground         72 x 72 m  top y=0.15   plaza slabs (albedo/ORM/normal, 5x5 texture regions with rotated/mirrored variants to hide
                                             repetition), granite border, raised planters with low hedges, trench drains, covers.

Run:   node tools/run-blender.mjs tools/blender/build_city_ground.py [-- --preview]
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *          # noqa: F401,F403  (bpy, MB, make_material, export_glb, ...)
import ground_texlib as T
from street_geo import *      # noqa: F401,F403

FILE = "city_ground.glb"
SEED = 20240611

Z_SIDEWALK = 0.15             # kerb height (top of sidewalks / lot)


def box(mb, c, s, mat, rot=None, **kw):
    """Detail box that sits on a surface (its hidden underside is dropped)."""
    add_box(mb, c, s, mat, rot=rot, bottom=False, **kw)


# ----------------------------------------------------------------------------------------------------
# textures & materials
# ----------------------------------------------------------------------------------------------------
def png_image(name, arr_vup, srgb=True):
    """Encode with the tight deterministic PNG writer, load + pack (the glTF exporter re-uses the packed bytes)."""
    ensure_dir(TEXTURE_DIR)
    path = os.path.join(TEXTURE_DIR, name + ".png")
    T.save_png(path, arr_vup)
    img = bpy.data.images.load(path)
    img.name = name
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    img.pack()
    return img


def textured(name, maps, prefix, clamp=False, normal_strength=1.0):
    alb = png_image(f"{prefix}_albedo", maps["albedo"], True)
    orm = png_image(f"{prefix}_orm", T.downsample2(maps["orm"]), False)      # roughness / AO are low frequency: half resolution
    nrm = png_image(f"{prefix}_normal", maps["normal"], False) if "normal" in maps else None
    mat = make_textured_material(name, albedo=alb, orm=orm, normal=nrm, normal_strength=normal_strength)
    if clamp:
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE":
                n.extension = "EXTEND"
    return mat


def make_materials():
    M = {}
    log("generating textures ...")
    road = T.make_road_straight()
    junction = T.make_road_junction()
    M["road"] = textured("ground_road_straight", road, "ground_road", clamp=True)
    M["junction"] = textured("ground_road_junction", junction, "ground_junction", clamp=True)
    M["sidewalk"] = textured("ground_sidewalk", T.make_sidewalk(), "ground_sidewalk", normal_strength=1.0)
    M["plaza"] = textured("ground_plaza", T.make_plaza(), "ground_plaza", normal_strength=1.0)
    m = junction["asphalt_mean"]
    k = 1.12
    M["asphalt"] = make_material("ground_asphalt_plain", ((m[0] * k) ** 2.2, (m[1] * k) ** 2.2, (m[2] * k) ** 2.2, 1.0), 0.0, 0.93)
    M["curb"] = make_material("ground_curb", "#A3A199", 0.0, 0.86)
    M["granite"] = make_material("ground_granite", "#5A5A58", 0.0, 0.72)
    M["curb_yellow"] = make_material("ground_curb_paint", "#C9982A", 0.0, 0.72)
    M["iron"] = make_material("ground_iron", "#2B2E33", 0.45, 0.66)
    M["dark"] = make_material("ground_drain_dark", "#08090B", 0.0, 0.92)
    M["planter"] = make_material("ground_planter", "#9A978E", 0.0, 0.88)
    M["soil"] = make_material("ground_soil", "#3A2B20", 0.0, 1.0)
    foliage = T.make_foliage()
    fol = png_image("ground_foliage_albedo", foliage["albedo"], True)
    M["foliage"] = make_textured_material("ground_foliage", albedo=fol, roughness=0.85)
    grass = png_image("ground_grass_albedo", T.make_grass()["albedo"], True)
    M["grass"] = make_textured_material("ground_grass", albedo=grass, roughness=0.92)
    return M


# ----------------------------------------------------------------------------------------------------
# small real-geometry details
# ----------------------------------------------------------------------------------------------------
def add_manhole(mb, cx, cy, z0, M, seg=12):
    """Cast iron manhole cover: rim, groove, plate (raised 2.6 cm above the surface z0 so it never z-fights)."""
    prof = [(0.46, -0.006), (0.46, 0.013), (0.405, 0.024), (0.35, 0.026)]
    sub = MB()
    sub.revolve(prof, center=(cx, cy, z0), seg=seg, axis="Z", mat=M["iron"], caps=True)
    add_closed(mb, sub, drop_bottom_z=z0 - 0.002)
    # two crossing ribs on the plate
    for a in (0.0, 90.0):
        box(mb, (cx, cy, z0 + 0.029), (0.60, 0.035, 0.010), M["iron"], rot=(0, 0, a + 20.0))


def add_grate(mb, cx, cy, sx, sy, z0, M, bars=4, along="y", simple=False):
    """Raised drain grate (frame + bars) over a dark opening.  sx x sy footprint, bars run along `along`.
    simple=True: side rails + bars only (no end frames) - cheaper, for the many trench drains of the lot."""
    h = 0.020
    box(mb, (cx, cy, z0 + 0.007), (sx - 0.02, sy - 0.02, 0.014), M["dark"])          # opening (dark)
    fw = 0.045
    if simple:
        if along == "x":
            for sgn in (-1, 1):
                box(mb, (cx, cy + sgn * (sy / 2 - fw / 2), z0 + h / 2), (sx, fw, h), M["iron"])
            for i in range(bars):
                x = cx - sx / 2 + sx * (i + 0.5) / bars
                box(mb, (x, cy, z0 + h / 2 - 0.002), (0.024, sy - 2 * fw, h - 0.004), M["iron"])
        else:
            for sgn in (-1, 1):
                box(mb, (cx + sgn * (sx / 2 - fw / 2), cy, z0 + h / 2), (fw, sy, h), M["iron"])
            for i in range(bars):
                y = cy - sy / 2 + sy * (i + 0.5) / bars
                box(mb, (cx, y, z0 + h / 2 - 0.002), (sx - 2 * fw, 0.024, h - 0.004), M["iron"])
        return
    if along == "y":
        box(mb, (cx - sx / 2 + fw / 2, cy, z0 + h / 2), (fw, sy, h), M["iron"])
        box(mb, (cx + sx / 2 - fw / 2, cy, z0 + h / 2), (fw, sy, h), M["iron"])
        box(mb, (cx, cy - sy / 2 + fw / 2, z0 + h / 2), (sx, fw, h), M["iron"])
        box(mb, (cx, cy + sy / 2 - fw / 2, z0 + h / 2), (sx, fw, h), M["iron"])
        inner = sx - 2 * fw
        for i in range(bars):
            x = cx - inner / 2 + inner * (i + 1) / (bars + 1)
            box(mb, (x, cy, z0 + h / 2 - 0.002), (0.022, sy - 2 * fw, h - 0.004), M["iron"])
    else:
        box(mb, (cx, cy - sy / 2 + fw / 2, z0 + h / 2), (sx, fw, h), M["iron"])
        box(mb, (cx, cy + sy / 2 - fw / 2, z0 + h / 2), (sx, fw, h), M["iron"])
        box(mb, (cx - sx / 2 + fw / 2, cy, z0 + h / 2), (fw, sy, h), M["iron"])
        box(mb, (cx + sx / 2 - fw / 2, cy, z0 + h / 2), (fw, sy, h), M["iron"])
        inner = sy - 2 * fw
        for i in range(bars):
            y = cy - inner / 2 + inner * (i + 1) / (bars + 1)
            box(mb, (cx, y, z0 + h / 2 - 0.002), (sx - 2 * fw, 0.022, h - 0.004), M["iron"])


def add_cover(mb, cx, cy, s, z0, M):
    """Square utility cover: frame + plate + two ribs."""
    box(mb, (cx, cy, z0 + 0.007), (s + 0.08, s + 0.08, 0.014), M["iron"])
    box(mb, (cx, cy, z0 + 0.0135), (s, s, 0.023), M["dark"])
    for k in (-1, 0, 1):
        box(mb, (cx, cy + k * s * 0.28, z0 + 0.0265), (s * 0.86, 0.03, 0.007), M["iron"])


# ----------------------------------------------------------------------------------------------------
# Road_Straight
# ----------------------------------------------------------------------------------------------------
def build_road_straight(M):
    mb = GMB()
    W, L, zt, zb = 10.0, 40.0, 0.0, -0.05
    # top: two mirrored halves (v = distance from the tile end / 40 m)
    mb.poly([(-W, -L, zt), (W, -L, zt), (W, 0, zt), (-W, 0, zt)], M["road"], uv=lambda x, y, z: ((x + 10.0) / 20.0, (y + 40.0) / 40.0))
    mb.poly([(-W, 0, zt), (W, 0, zt), (W, L, zt), (-W, L, zt)], M["road"], uv=lambda x, y, z: ((x + 10.0) / 20.0, (40.0 - y) / 40.0))
    # skirt (never visible, keeps the tile closed)
    for (y0, y1) in ((-L, 0.0), (0.0, L)):
        box_face(mb, "+x", -W, W, y0, y1, zb, zt, M["asphalt"])
        box_face(mb, "-x", -W, W, y0, y1, zb, zt, M["asphalt"])
        box_face(mb, "-z", -W, W, y0, y1, zb, zt, M["asphalt"])
    box_face(mb, "-y", -W, W, -L, L, zb, zt, M["asphalt"])
    box_face(mb, "+y", -W, W, -L, L, zb, zt, M["asphalt"])
    # manholes + kerb grates (mirrored about the middle like the texture)
    for (mx, mz) in T.ROAD_MANHOLES:
        for s in (-1, 1):
            add_manhole(mb, mx, s * mz, 0.0, M)
    for (gx, gz) in T.ROAD_GRATES:
        for s in (-1, 1):
            add_grate(mb, gx, s * gz, 0.44, 0.86, 0.0, M, bars=4, along="y")
    return mb.to_object("Road_Straight", smooth=True, sharp_angle=40.0)


# ----------------------------------------------------------------------------------------------------
# Road_Intersection
# ----------------------------------------------------------------------------------------------------
def build_road_junction(M):
    mb = GMB()
    W, zt, zb = 10.0, 0.0, -0.05
    mb.poly([(-W, -W, zt), (W, -W, zt), (W, W, zt), (-W, W, zt)], M["junction"], uv=lambda x, y, z: ((x + 10.0) / 20.0, (y + 10.0) / 20.0))
    for which in ("+x", "-x", "+y", "-y", "-z"):
        box_face(mb, which, -W, W, -W, W, zb, zt, M["asphalt"])
    for (mx, my) in T.JUNCTION_MANHOLES:
        add_manhole(mb, mx, my, 0.0, M)
    return mb.to_object("Road_Intersection", smooth=True, sharp_angle=40.0)


# ----------------------------------------------------------------------------------------------------
# kerb profile (a = inward offset from the road-side face, b = height)
# ----------------------------------------------------------------------------------------------------
def curb_profile(z_bottom=0.0, top=Z_SIDEWALK, width=0.20, radius=0.04):
    pts = [(0.0, z_bottom), (width, z_bottom), (width, top), (radius, top)]
    for th in (90 + 45, 180):
        r = math.radians(th)
        pts.append((radius + radius * math.cos(r), top - radius + radius * math.sin(r)))
    # (0, top - radius) is the last point; the polygon closes back to (0, z_bottom)
    if z_bottom > top - radius - 0.01:
        raise ValueError("kerb segment too thin for the rounded top")
    return pts


def add_curb_straight(mb, x_face, y0, y1, M, z_bottom=0.0):
    """Kerb block whose road-side face is at x = x_face (kerb extends towards +X), from y0 to y1."""
    prof = curb_profile(z_bottom)
    frames = [((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))] * 2
    sub = sweep_mb([(x_face, y0, 0.0), (x_face, y1, 0.0)], prof, M["curb"], frames)
    mb.merge_into(sub)
    sub.bm.free()


# ----------------------------------------------------------------------------------------------------
# Sidewalk_Straight   (x -2..2, y -36..36; kerb on -X)
# ----------------------------------------------------------------------------------------------------
INLETS = (-18.0, 18.0)
INLET_HALF = 0.45


def build_sidewalk_straight(M):
    mb = GMB()
    zt = Z_SIDEWALK
    x0, x1 = -1.8, 2.0
    uv = lambda x, y, z: ((x + 2.0) / 4.0, (y + 36.0) / 8.0)
    cuts = [-36.0]
    for c in INLETS:
        cuts += [c - INLET_HALF, c + INLET_HALF]
    cuts.append(36.0)
    segs = list(zip(cuts[:-1], cuts[1:]))
    for k, (y0, y1) in enumerate(segs):
        mb.poly([(x0, y0, zt), (x1, y0, zt), (x1, y1, zt), (x0, y1, zt)], M["sidewalk"], uv=uv)
        if k % 2 == 1:      # inlet: dark opening in the kerb face
            box_face(mb, "-x", x0, x1, y0, y1, 0.0, zt - 0.05, M["dark"])          # back wall (below the lintel)
            mb.poly([(-2.0, y0, 0.002), (-2.0, y1, 0.002), (x0, y1, 0.002), (x0, y0, 0.002)][::-1], M["dark"])  # floor
    # kerb blocks between / around the inlets
    for k, (y0, y1) in enumerate(segs):
        if k % 2 == 0:
            add_curb_straight(mb, -2.0, y0, y1, M)
        else:
            add_curb_straight(mb, -2.0, y0, y1, M, z_bottom=zt - 0.055)          # lintel above the opening
    add_cover(mb, 0.5, -8.5, 0.55, zt, M)
    add_cover(mb, 1.5, 9.5, 0.40, zt, M)
    return mb.to_object("Sidewalk_Straight", smooth=True, sharp_angle=40.0)


# ----------------------------------------------------------------------------------------------------
# Sidewalk_Corner  (x -2..2, y -2..2; rounded outer corner at (-X,+Y) = glTF (-X,-Z))
# ----------------------------------------------------------------------------------------------------
CORNER_R = 3.5


def build_sidewalk_corner(M):
    mb = GMB()
    zt = Z_SIDEWALK
    R = CORNER_R
    cx, cy = -2.0 + R, 2.0 - R            # arc centre (1.5, -1.5)
    n_arc = 12
    uv = lambda x, y, z: ((x + 2.0) / 4.0, (y + 2.0) / 8.0)
    # paving: inset 0.2 from the kerb
    ri = R - 0.2
    inner_arc = [(cx + ri * math.cos(math.pi / 2 + (math.pi / 2) * i / n_arc), cy + ri * math.sin(math.pi / 2 + (math.pi / 2) * i / n_arc), zt)
                 for i in range(n_arc + 1)]
    poly = [(-1.8, -2.0, zt), (2.0, -2.0, zt), (2.0, 1.8, zt)] + inner_arc + [(-1.8, -2.0 + 0.0, zt)]
    # arc ends at (-1.8, -1.5); polygon closes down to (-1.8,-2)
    mb.poly(poly, M["sidewalk"], uv=uv)
    # kerb along the outer edge: straight west part, arc, straight north part
    path, frames = [], []
    up = (0.0, 0.0, 1.0)
    path.append((-2.0, -2.0, 0.0)); frames.append(((1.0, 0.0, 0.0), up))
    outer_arc = []
    for i in range(n_arc + 1):
        th = math.pi + (-math.pi / 2) * i / n_arc         # 180deg -> 90deg
        px, py = cx + R * math.cos(th), cy + R * math.sin(th)
        nx, ny = math.cos(th), math.sin(th)
        outer_arc.append((px, py))
        path.append((px, py, 0.0))
        frames.append(((-nx, -ny, 0.0), up))
    path.append((2.0, 2.0, 0.0)); frames.append(((0.0, -1.0, 0.0), up))
    sub = sweep_mb(path, curb_profile(), M["curb_yellow"], frames)
    mb.merge_into(sub)
    sub.bm.free()
    # asphalt filler in the spandrel outside the rounded kerb (keeps the 4x4 tile hole-free next to the junction);
    # outer_arc runs 180deg -> 90deg, i.e. from (-2,-1.5) to (1.5, 2): CCW together with the outer corner point.
    mb.poly([(px, py, 0.0) for (px, py) in outer_arc] + [(-2.0, 2.0, 0.0)], M["asphalt"])
    return mb.to_object("Sidewalk_Corner", smooth=True, sharp_angle=40.0)


# ----------------------------------------------------------------------------------------------------
# Lot_Ground  (72 x 72)
# ----------------------------------------------------------------------------------------------------
def add_planter(mb, cx, cy, sx, sy, ang, M):
    z0 = Z_SIDEWALK
    r = (0, 0, ang)
    box(mb, (cx, cy, z0 + 0.11), (sx, sy, 0.22), M["planter"], rot=r)
    box(mb, (cx, cy, z0 + 0.1875), (sx - 0.26, sy - 0.26, 0.075), M["soil"], rot=r)
    box(mb, (cx, cy, z0 + 0.2325), (sx - 0.52, sy - 0.52, 0.11), M["foliage"], rot=r, taper=(0.9, 0.86))


def build_lot(M):
    rng = random.Random(SEED + 5)
    mb = GMB()
    zt = Z_SIDEWALK
    H = 36.0
    B = 0.40                                   # granite border
    R = 14.4                                   # texture region (2 texture periods)
    edges = [-36.0 + R * i for i in range(6)]
    # regions of the plaza (clipped by the border), each with its own texture variant
    for j in range(5):
        for i in range(5):
            x0, x1 = edges[i], edges[i + 1]
            y0, y1 = edges[j], edges[j + 1]
            rot = rng.randrange(4)
            mir = rng.randrange(2)
            ou = rng.randrange(4) * 0.25
            ov = rng.randrange(4) * 0.25

            def uvf(x, y, z, x0=x0, y0=y0, rot=rot, mir=mir, ou=ou, ov=ov):
                u = (x - x0) / 7.2
                v = (y - y0) / 7.2
                if mir:
                    u = 2.0 - u
                for _ in range(rot):
                    u, v = v, 2.0 - u
                return (u + ou, v + ov)

            cx0 = max(x0, -H + B)
            cx1 = min(x1, H - B)
            cy0 = max(y0, -H + B)
            cy1 = min(y1, H - B)
            mb.poly([(cx0, cy0, zt), (cx1, cy0, zt), (cx1, cy1, zt), (cx0, cy1, zt)], M["plaza"], uv=uvf)
    # border frame (4 strips incl. corners)
    mb.poly([(-H, -H, zt), (H, -H, zt), (H, -H + B, zt), (-H, -H + B, zt)], M["granite"])
    mb.poly([(-H, H - B, zt), (H, H - B, zt), (H, H, zt), (-H, H, zt)], M["granite"])
    mb.poly([(-H, -H + B, zt), (-H + B, -H + B, zt), (-H + B, H - B, zt), (-H, H - B, zt)], M["granite"])
    mb.poly([(H - B, -H + B, zt), (H, -H + B, zt), (H, H - B, zt), (H - B, H - B, zt)], M["granite"])
    # -- planters along the four edges (kept clear of the 66 m building footprint limit) ---------------------
    pos = 34.55
    slots = [-28.5, -20.5, -12.5, -4.5, 4.5, 12.5, 20.5, 28.5]
    for side in range(4):
        for k, t in enumerate(slots):
            if rng.random() < 0.18:
                continue
            length = rng.choice([3.6, 4.2, 4.8])
            w = 1.25
            tt = t + rng.uniform(-0.6, 0.6)
            if side == 0:
                add_planter(mb, tt, -pos, length, w, 0.0, M)
            elif side == 1:
                add_planter(mb, tt, pos, length, w, 0.0, M)
            elif side == 2:
                add_planter(mb, -pos, tt, w, length, 0.0, M)
            else:
                add_planter(mb, pos, tt, w, length, 0.0, M)
    # -- lawns (raised, stone edged) at the middle of each side --------------------------------------------------
    for (lx, ly, sx, sy) in ((0.0, -28.6, 12.0, 3.6), (0.0, 28.6, 12.0, 3.6), (-28.6, 0.0, 3.6, 12.0), (28.6, 0.0, 3.6, 12.0)):
        add_rbox(mb, (lx, ly, zt + 0.0425), (sx + 0.34, sy + 0.34, 0.085), M["planter"], r=0.02, seg=1, bottom=False)
        zg = zt + 0.100
        mb.poly([(lx - sx / 2, ly - sy / 2, zg), (lx + sx / 2, ly - sy / 2, zg), (lx + sx / 2, ly + sy / 2, zg), (lx - sx / 2, ly + sy / 2, zg)],
                M["grass"], uv=lambda x, y, z: (x / 4.0, y / 4.0))
    # -- trench drains between the planters + area drains and covers --------------------------------------
    for side, (cx_, cy_, along) in enumerate([(0.0, -pos, "x"), (0.0, pos, "x"), (-pos, 0.0, "y"), (pos, 0.0, "y")]):
        for off in (-16.5, 16.5):
            gx, gy = (cx_ + off, cy_) if along == "x" else (cx_, cy_ + off)
            # place the drain in front of the planter row (towards the middle) so nothing overlaps
            if along == "x":
                gy += 1.35 if cy_ < 0 else -1.35
                add_grate(mb, gx, gy, 3.2, 0.34, zt, M, bars=9, along="x", simple=True)
            else:
                gx += 1.35 if cx_ < 0 else -1.35
                add_grate(mb, gx, gy, 0.34, 3.2, zt, M, bars=9, along="y", simple=True)
    for (mx, my) in ((-19.5, -8.2), (11.0, 21.5), (22.5, -14.0), (-9.0, 26.5)):
        add_manhole(mb, mx, my, zt, M)
    for (cxx, cyy, s) in ((-24.0, 14.0, 0.7), (16.0, -24.0, 0.6), (24.0, 9.0, 0.5), (-13.0, -22.0, 0.5)):
        add_cover(mb, cxx, cyy, s, zt, M)
    # foliage UVs: box projection (1 m per tile)
    uvl = mb.uv_layer()
    fol_idx = mb.mats.index(M["foliage"]) if M["foliage"] in mb.mats else -1
    for f in mb.bm.faces:
        if f.material_index != fol_idx:
            continue
        n = f.normal
        for lp in f.loops:
            p = lp.vert.co
            if abs(n.z) >= max(abs(n.x), abs(n.y)):
                lp[uvl].uv = (p.x, p.y)
            elif abs(n.x) >= abs(n.y):
                lp[uvl].uv = (p.y, p.z)
            else:
                lp[uvl].uv = (p.x, p.z)
    return mb.to_object("Lot_Ground", smooth=True, sharp_angle=40.0)


# ----------------------------------------------------------------------------------------------------
# preview: assemble a small district out of linked duplicates
# ----------------------------------------------------------------------------------------------------
def link_dup(src, name, loc, rot_deg=0.0):
    o = bpy.data.objects.new(name, src.data)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (0.0, 0.0, math.radians(rot_deg))
    return o


def assemble_district(objs, blocks=((-50, -50), (50, -50), (-50, 50), (50, 50))):
    rs, ri, ss, sc, lot = objs
    out = []
    n = 0
    for (bx, by) in blocks:
        out.append(link_dup(lot, f"pv_lot{n}", (bx, by, 0)))
        out.append(link_dup(ss, f"pv_sw_w{n}", (bx - 38, by, 0), 0))
        out.append(link_dup(ss, f"pv_sw_e{n}", (bx + 38, by, 0), 180))
        out.append(link_dup(ss, f"pv_sw_n{n}", (bx, by + 38, 0), -90))
        out.append(link_dup(ss, f"pv_sw_s{n}", (bx, by - 38, 0), 90))
        out.append(link_dup(sc, f"pv_c_nw{n}", (bx - 38, by + 38, 0), 0))
        out.append(link_dup(sc, f"pv_c_ne{n}", (bx + 38, by + 38, 0), -90))
        out.append(link_dup(sc, f"pv_c_se{n}", (bx + 38, by - 38, 0), 180))
        out.append(link_dup(sc, f"pv_c_sw{n}", (bx - 38, by - 38, 0), 90))
        n += 1
    out.append(link_dup(ri, "pv_int0", (0, 0, 0)))
    out.append(link_dup(rs, "pv_road_n", (0, 50, 0), 0))
    out.append(link_dup(rs, "pv_road_s", (0, -50, 0), 0))
    out.append(link_dup(rs, "pv_road_e", (50, 0, 0), 90))
    out.append(link_dup(rs, "pv_road_w", (-50, 0, 0), 90))
    return out


def focus_box(center, size, name="PV_Focus"):
    """Invisible proxy that defines the framing (bounding box) for render_views."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    o.hide_render = True
    return o


def preview(objs):
    dbg = "--debug-ground" in script_args()
    suffix = ""
    if "--sunset" in script_args():
        import street_preview
        street_preview.use_sunset()
        suffix = "_sunset"
    rs, ri, ss, sc, lot = objs
    dist_objs = assemble_district(objs)
    bpy.ops.mesh.primitive_plane_add(size=600, location=(0, 0, -0.3))
    fl = bpy.context.active_object
    fl.name = "PV_DebugFloor"
    fl.data.materials.append(make_material("PV_DebugMat", "#FF00FF" if dbg else "#1B1B1F", 0.0, 0.9))
    for o in objs:
        o.hide_render = True
        o.hide_viewport = True
    args = script_args()
    if "--closeups" in args:
        spots = {
            # name: (center, size, custom view (az, el, dist_mult))
            "grate": ((9.3, 68.0, 0.0), (5, 5, 1), (250, 34, 1.0)),
            "manhole": ((-5.6, 73.0, 0.0), (5, 5, 1), (200, 45, 1.0)),
            "curb_road": ((10.0, 50.0, 0.1), (9, 9, 1), (270, 22, 1.0)),
            "curb_inlet": ((10.0, 68.0, 0.1), (5, 5, 1), (280, 24, 1.0)),
            "corner": ((12.0, 12.0, 0.1), (12, 12, 1), (235, 40, 1.0)),
            "planter": ((50.0, 15.5, 0.2), (9, 5, 1), (200, 30, 1.0)),
            "plaza": ((50.0, 30.0, 0.15), (16, 16, 1), (215, 32, 1.0)),
            "sidewalk_flags": ((11.5, 62.0, 0.1), (6, 6, 1), (245, 40, 1.0)),
        }
        for name, (c, sz, cv) in spots.items():
            fb = focus_box(c, sz, "PV_Focus_" + name)
            render_views("ground_close_" + name + suffix, [fb], views=("v",), size=(1000, 700), samples=24,
                         custom_views={"v": cv}, lens=40)
        return dist_objs
    render_views("ground_district" + suffix, dist_objs, views=("top", "three_quarter", "low", "near"), size=(1280, 800), samples=32,
                 custom_views={"top": (180, 89, 1.02), "three_quarter": (200, 38, 0.72), "low": (215, 16, 0.42), "near": (235, 32, 0.20)},
                 lens=50)
    return dist_objs


def build():
    reset_scene()
    M = make_materials()
    rs = build_road_straight(M)
    ri = build_road_junction(M)
    ss = build_sidewalk_straight(M)
    sc = build_sidewalk_corner(M)
    lot = build_lot(M)
    objs = [rs, ri, ss, sc, lot]
    path = export_glb(FILE, objs, animations=False)
    info = report(path)
    for o in objs:
        mn, mx = world_bbox([o])
        log(f"  {o.name}: x={mx.x - mn.x:.3f} z(glTF)={mx.y - mn.y:.3f} y(glTF)={mx.z - mn.z:.3f}  tris={tri_count([o])}")
        if "--qa" in script_args():
            isl, cl, neg, deg = qa_islands(o)
            bad = 0
            for poly in o.data.polygons:
                mat = o.data.materials[poly.material_index] if poly.material_index < len(o.data.materials) else None
                if mat is not None and mat.name in ("ground_road_straight", "ground_road_junction", "ground_sidewalk", "ground_plaza")                         and poly.normal.z < 0.99:
                    bad += 1
            log(f"      QA {o.name}: islands={isl} closed={cl} inverted={neg} degenerate_faces={deg} textured_faces_not_up={bad}")
    if "--preview" in script_args():
        preview(objs)


build()

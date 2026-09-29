"""Optional street-furniture extras: hydrant, bench, bus shelter, traffic light, planter, dumpster."""
from props_common import *          # noqa: F401,F403
from props_rooftop import T, to_axis


# ----------------------------------------------------------------------------------------------------
# Prop_Hydrant  (0.86 m)
# ----------------------------------------------------------------------------------------------------
def build_hydrant(M):
    r = new_root("Prop_Hydrant")
    g = GMB(weld=False)
    red, galv, dark = M["hydrant"], M["galv"], M["steel_dark"]
    prof = [(0.0, 0.0), (0.185, 0.0), (0.185, 0.04), (0.145, 0.07), (0.116, 0.11), (0.108, 0.50), (0.136, 0.54), (0.136, 0.60),
            (0.112, 0.63), (0.112, 0.66), (0.136, 0.685), (0.126, 0.76), (0.082, 0.83), (0.0, 0.85)]
    sub = MB()
    sub.revolve(prof, center=(0, 0, 0), seg=12, axis="Z", mat=red, caps=False)
    add_closed(g, sub, drop_bottom_z=0.01)
    for sx in (-1, 1):                                                                           # side outlets with caps
        add_cyl(g, (sx * 0.20, 0, 0.36), 0.056, 0.20, red, seg=10, axis="X")
        add_cyl(g, (sx * 0.30, 0, 0.36), 0.068, 0.06, galv, seg=10, axis="X")
        add_cyl(g, (sx * 0.335, 0, 0.36), 0.03, 0.02, dark, seg=6, axis="X")
        add_strut(g, (sx * 0.14, 0.02, 0.60), (sx * 0.25, 0.10, 0.28), 0.008, dark, 4)               # cap chain
    add_cyl(g, (0, 0.20, 0.31), 0.078, 0.22, red, seg=10, axis="Y")                               # pumper nozzle
    add_cyl(g, (0, 0.32, 0.31), 0.095, 0.06, galv, seg=10, axis="Y")
    add_cyl(g, (0, 0.355, 0.31), 0.04, 0.02, dark, seg=6, axis="Y")
    add_cyl(g, (0, 0, 0.865), 0.038, 0.05, galv, seg=6)                                           # operating nut
    add_cyl(g, (0, 0, 0.60), 0.15, 0.03, galv, seg=12)                                            # collar band
    finish(g, "Hydrant_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_Bench  (1.8 m slatted park bench facing +Y)
# ----------------------------------------------------------------------------------------------------
def bench_geometry(g, M, length=1.8):
    wood, dark = M["wood"], M["steel_dark"]
    half = length / 2.0
    for k, y in enumerate((-0.03, 0.07, 0.17, 0.27)):                                             # seat slats
        add_rbox(g, (0, y, 0.44), (length, 0.085, 0.035), wood, r=0.008)
    for k, z in enumerate((0.60, 0.72, 0.84)):                                                    # back slats (leaning back)
        add_rbox(g, (0, -0.19 - (z - 0.60) * 0.22, z), (length, 0.03, 0.10), wood, r=0.008, rot=(-12.0, 0, 0))
    for x in (-half + 0.10, 0.0, half - 0.10):                                                    # cast frames
        add_rbox(g, (x, 0.26, 0.21), (0.05, 0.06, 0.42), dark, r=0.008, bottom=False)
        add_rbox(g, (x, -0.08, 0.21), (0.05, 0.06, 0.42), dark, r=0.008, bottom=False)
        add_rbox(g, (x, 0.09, 0.405), (0.05, 0.40, 0.035), dark, r=0.008)
        add_beam(g, (x, -0.10, 0.42), (x, -0.31, 0.90), 0.05, 0.03, dark)
        add_rbox(g, (x, 0.26, 0.01), (0.09, 0.14, 0.02), dark, r=0.004, bottom=False)
        add_rbox(g, (x, -0.08, 0.01), (0.09, 0.14, 0.02), dark, r=0.004, bottom=False)
    for x in (-half + 0.10, half - 0.10):                                                         # arm rests
        add_rbox(g, (x, 0.08, 0.66), (0.05, 0.44, 0.04), dark, r=0.01)
        add_rbox(g, (x, 0.27, 0.55), (0.04, 0.04, 0.22), dark, r=0.006)


def build_bench(M):
    r = new_root("Prop_Bench")
    g = GMB(weld=False)
    bench_geometry(g, M, 1.8)
    finish(g, "Bench_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_BusShelter  (3.4 x 1.5 x 2.6 m, open towards +Y, illuminated ad panel, stop sign)
# ----------------------------------------------------------------------------------------------------
def build_bus_shelter(M):
    r = new_root("Prop_BusShelter")
    g = GMB(weld=False)
    dark, glass, alu = M["steel_dark"], M["shelter_glass"], M["alu"]
    hx, hy = 1.65, 0.65
    for (px, py) in ((-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy)):
        add_rbox(g, (px, py, 1.22), (0.09, 0.09, 2.44), dark, r=0.012, bottom=False)
    # roof with drip edge, gutter and a slight fall to the back
    add_rbox(g, (0, 0.0, 2.52), (3.70, 1.70, 0.09), alu, r=0.02, rot=(2.5, 0, 0))
    add_rbox(g, (0, 0.0, 2.585), (3.50, 1.50, 0.04), dark, r=0.01, rot=(2.5, 0, 0))
    add_rbox(g, (0, 0.86, 2.47), (3.66, 0.05, 0.10), dark, r=0.01)
    # glazing: back wall (3 panes), left side, ad lightbox on the right side
    for k in range(3):
        x = -1.1 + k * 1.1
        add_rbox(g, (x, -hy, 1.30), (1.04, 0.025, 1.85), glass, r=0.008)
        add_box(g, (x, -hy, 0.34), (1.08, 0.04, 0.08), dark)
        add_box(g, (x, -hy, 2.24), (1.08, 0.04, 0.06), dark)
    add_rbox(g, (-hx, 0.0, 1.30), (0.025, 1.20, 1.85), glass, r=0.008)
    add_box(g, (-hx, 0.0, 0.34), (0.04, 1.24, 0.08), dark)
    add_rbox(g, (hx + 0.03, 0.0, 1.32), (0.10, 1.26, 1.86), dark, r=0.012)                       # ad panel frame
    add_box(g, (hx + 0.085, 0.0, 1.32), (0.012, 1.10, 1.68), M["lightbox"])                       # back-lit poster
    # bench inside + schedule board
    sub = GMB(weld=False)
    bench_geometry(sub, M, 2.3)
    sub.finish()
    g.merge_into(sub, T(-0.3, -0.20, 0.0))
    sub.bm.free()
    add_rbox(g, (-1.60, -0.30, 1.35), (0.04, 0.45, 0.55), dark, r=0.008)
    add_box(g, (-1.575, -0.30, 1.35), (0.006, 0.38, 0.48), M["paint_white"])
    # bus stop pole + sign
    px, py = -2.05, 0.75
    add_cyl(g, (px, py, 1.55), 0.045, 3.1, M["pole"], seg=8)
    add_cyl(g, (px, py, 0.05), 0.09, 0.10, dark, seg=8)
    add_cyl(g, (px, py + 0.03, 2.85), 0.28, 0.03, M["sign_blue"], seg=16, axis="Y")
    add_rbox(g, (px, py + 0.05, 2.88), (0.26, 0.012, 0.12), M["paint_white"], r=0.004)
    add_rbox(g, (px, py + 0.05, 2.76), (0.16, 0.012, 0.05), M["paint_white"], r=0.004)
    finish(g, "BusShelter_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_TrafficLight  (5.7 m pole, mast arm over the road towards +Y, signal heads facing +X, pedestrian signal)
# ----------------------------------------------------------------------------------------------------
def signal_head(g, M, cx, cy, cz, lit=0, facing=1):
    """Vertical three-lens head; lens axis along +/-X.  lit: 0 red, 1 amber, 2 green (only red is emissive here)."""
    dark = M["steel_dark"]
    add_rbox(g, (cx, cy, cz), (0.30, 0.32, 0.96), dark, r=0.02)
    mats = (M["tl_red"], M["tl_amber_off"], M["tl_green_off"])
    for i in range(3):
        z = cz + 0.31 - i * 0.31
        add_cyl(g, (cx + facing * 0.16, cy, z), 0.105, 0.05, mats[i], seg=12, axis="X")
        add_rbox(g, (cx + facing * 0.20, cy, z + 0.085), (0.13, 0.26, 0.03), dark, r=0.008)          # visor


def build_traffic_light(M):
    r = new_root("Prop_TrafficLight")
    g = GMB(weld=False)
    pole, dark = M["pole"], M["steel_dark"]
    add_rbox(g, (0, 0, 0.02), (0.44, 0.44, 0.04), dark, r=0.006, bottom=False)
    add_cyl(g, (0, 0, 0.40), 0.16, 0.72, pole, seg=10, r_top=0.115)
    add_cyl(g, (0, 0, 3.05), 0.115, 5.30, pole, seg=10, r_top=0.085)
    add_cyl(g, (0, 0, 0.78), 0.14, 0.06, dark, seg=10)
    # mast arm
    arm = bezier((0, 0, 5.05), (0, 0.4, 5.55), (0, 1.4, 5.55), (0, 3.6, 5.50), 10)
    add_tube(g, arm, 0.075, pole, seg=8, r_end=0.05)
    add_rbox(g, (0, 0.05, 5.05), (0.24, 0.30, 0.34), dark, r=0.02)
    add_strut(g, (0, 0.08, 4.50), (0, 1.55, 5.42), 0.03, pole, 6)
    # heads: on the arm (hanging), on the pole
    signal_head(g, M, 0.0, 2.85, 5.0, 0, 1)
    add_rbox(g, (0, 2.85, 5.53), (0.10, 0.10, 0.10), dark, r=0.01)
    signal_head(g, M, 0.0, 0.0, 3.85, 0, 1)
    add_rbox(g, (0.0, 0.0, 4.40), (0.20, 0.20, 0.10), dark, r=0.01)
    # pedestrian signal + push button + controller cabinet
    add_rbox(g, (0.0, 0.17, 2.70), (0.34, 0.16, 0.38), dark, r=0.02)
    add_box(g, (0.0, 0.255, 2.78), (0.24, 0.012, 0.22), M["tl_red"])
    add_box(g, (0.0, 0.255, 2.60), (0.24, 0.012, 0.10), M["tl_green_off"])
    add_rbox(g, (0.10, -0.16, 1.15), (0.08, 0.10, 0.14), M["paint_yellow"], r=0.01)
    add_rbox(g, (-0.32, 0.0, 0.55), (0.34, 0.42, 1.10), M["unit_a"], r=0.02, bottom=False)
    add_box(g, (-0.32, 0.215, 0.60), (0.24, 0.012, 0.82), dark)
    finish(g, "TrafficLight_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_Planter  (concrete box planter with a clipped shrub)
# ----------------------------------------------------------------------------------------------------
def build_planter(M):
    r = new_root("Prop_Planter")
    g = GMB(weld=False)
    add_rbox(g, (0, 0, 0.34), (1.50, 0.70, 0.68), M["concrete"], r=0.03, seg=1, bottom=False)
    add_rbox(g, (0, 0, 0.71), (1.62, 0.82, 0.07), M["concrete_dark"], r=0.015)
    add_box(g, (0, 0, 0.745), (1.34, 0.54, 0.02), M["soil"])
    for k, (x, s) in enumerate(((-0.42, 0.30), (0.05, 0.36), (0.50, 0.27))):
        add_sphere(g, (x, 0.0, 0.76 + s * 0.62), s, M["foliage"], seg=12, rings=8, scale=(1.2, 1.0, 0.85), jitter=0.10, seed=11 + k)
    uv_box_for_material(g, M["foliage"], (0.8, 0.8))
    finish(g, "Planter_Body", r)
    return r


# ----------------------------------------------------------------------------------------------------
# Prop_Dumpster  (green front-loader dumpster, lids slightly open)
# ----------------------------------------------------------------------------------------------------
def build_dumpster(M):
    r = new_root("Prop_Dumpster")
    g = GMB(weld=False)
    green, dark = M["green"], M["steel_dark"]
    add_rbox(g, (0, 0, 0.66), (1.90, 1.10, 0.86), green, r=0.03, taper=(1.0, 1.0), bottom_scale=(0.94, 0.90))
    add_rbox(g, (0, 0, 0.21), (1.80, 1.00, 0.10), dark, r=0.01, bottom=False)                # base frame
    for sx in (-0.86, 0.0, 0.86):                                                             # vertical ribs
        add_rbox(g, (sx, 0.545, 0.68), (0.07, 0.03, 0.80), dark, r=0.006)
        add_rbox(g, (sx, -0.545, 0.68), (0.07, 0.03, 0.80), dark, r=0.006)
    add_rbox(g, (0, 0, 1.115), (1.96, 1.16, 0.06), dark, r=0.012)                             # top rim
    for sx in (-1, 1):                                                                        # lids (one propped open)
        ang = 0.0 if sx < 0 else 38.0
        add_rbox(g, (sx * 0.49, -0.02 if sx < 0 else -0.10, 1.16 if sx < 0 else 1.30), (0.94, 1.10, 0.05), green, r=0.01,
                 rot=(0, 0, 0) if sx < 0 else (-ang, 0, 0))
    for sx in (-0.55, 0.55):                                                                  # fork pockets
        add_rbox(g, (sx, 0.56, 0.34), (0.30, 0.04, 0.16), dark, r=0.008)
    for sx in (-0.8, 0.8):
        for sy in (-0.35, 0.35):
            add_cyl(g, (sx, sy, 0.10), 0.10, 0.06, M["rubber"], seg=10, axis="X")
    add_rbox(g, (0.0, 0.575, 0.90), (0.5, 0.012, 0.16), M["paint_white"], r=0.004)
    finish(g, "Dumpster_Body", r)
    return r



# ----------------------------------------------------------------------------------------------------
# Prop_Tree  (deciduous street tree, ~7 m: trunk + branches + clipped crown blobs, iron tree grate at the foot)
# ----------------------------------------------------------------------------------------------------
def build_tree(M):
    r = new_root("Prop_Tree")
    g = GMB(weld=False)
    dark, bark = M["steel_dark"], M["bark"]
    add_rbox(g, (0, 0, 0.03), (1.30, 1.30, 0.06), M["concrete_dark"], r=0.012, bottom=False)          # tree pit frame
    add_box(g, (0, 0, 0.065), (1.14, 1.14, 0.02), M["soil"], bottom=False)
    for k in range(5):                                                                                # grate bars
        add_box(g, (-0.44 + k * 0.22, 0, 0.08), (0.05, 1.10, 0.03), dark, bottom=False)
        add_box(g, (0, -0.44 + k * 0.22, 0.08), (1.10, 0.05, 0.03), dark, bottom=False)
    add_cyl(g, (0, 0, 1.30), 0.185, 2.5, bark, seg=9, r_top=0.115)                                    # trunk
    add_cyl(g, (0, 0, 0.14), 0.27, 0.16, bark, seg=9, r_top=0.19)                                     # root flare
    blobs = ((0.0, 0.0, 4.75, 1.55), (1.05, 0.55, 4.0, 1.15), (-1.05, 0.30, 4.1, 1.20), (0.25, -1.05, 4.3, 1.10),
             (-0.35, 0.95, 5.35, 1.00), (0.75, -0.55, 5.45, 0.95), (0.05, 0.05, 6.15, 0.90))
    for k, (bx, by, bz, br) in enumerate(blobs):
        add_tube(g, [(0, 0, 2.30), (bx * 0.45, by * 0.45, 2.30 + (bz - 2.30) * 0.5), (bx * 0.8, by * 0.8, bz - 0.3)], 0.055, bark, seg=6, r_end=0.03)
        add_sphere(g, (bx, by, bz), br, M["foliage"], seg=9, rings=6, scale=(1.0, 1.0, 0.86), jitter=0.16, seed=100 + k)
    uv_box_for_material(g, M["foliage"], (1.6, 1.6))
    finish(g, "Tree_Body", r)
    return r



# ----------------------------------------------------------------------------------------------------
# Prop_TrafficCone (0.72 m) and Prop_TrashBin (street litter bin)
# ----------------------------------------------------------------------------------------------------
def build_cone(M):
    r = new_root("Prop_TrafficCone")
    g = GMB(weld=False)
    orange = M["cone_orange"]
    add_rbox(g, (0, 0, 0.02), (0.40, 0.40, 0.04), M["rubber"], r=0.012, bottom=False)
    add_cyl(g, (0, 0, 0.09), 0.16, 0.10, orange, seg=12, r_top=0.13)
    add_cyl(g, (0, 0, 0.40), 0.128, 0.52, orange, seg=12, r_top=0.045)
    for (z0, z1) in ((0.29, 0.41), (0.45, 0.53)):                            # reflective collars
        rz0 = 0.128 - (0.128 - 0.045) * (z0 - 0.14) / 0.52
        rz1 = 0.128 - (0.128 - 0.045) * (z1 - 0.14) / 0.52
        add_cyl(g, (0, 0, (z0 + z1) / 2), rz0 + 0.004, z1 - z0, M["paint_white"], seg=12, r_top=rz1 + 0.004)
    add_cyl(g, (0, 0, 0.675), 0.03, 0.05, orange, seg=8)
    finish(g, "TrafficCone_Body", r)
    return r


def build_trash_bin(M):
    r = new_root("Prop_TrashBin")
    g = GMB(weld=False)
    dark, green = M["steel_dark"], M["green"]
    add_cyl(g, (0, 0, 0.55), 0.26, 0.90, green, seg=12, r_top=0.29)                        # drum, slightly flared
    add_cyl(g, (0, 0, 0.055), 0.28, 0.11, dark, seg=12)                                    # base ring
    add_cyl(g, (0, 0, 0.995), 0.32, 0.04, dark, seg=12)                                    # rim
    add_cyl(g, (0, 0, 1.06), 0.30, 0.10, dark, seg=12, r_top=0.22)                          # dome lid
    add_rbox(g, (0, 0.30, 0.90), (0.26, 0.05, 0.14), dark, r=0.008)                        # flap opening
    add_box(g, (0, 0.328, 0.90), (0.20, 0.012, 0.08), M["under"])
    for sx in (-1, 1):
        add_rbox(g, (sx * 0.27, 0, 0.56), (0.03, 0.10, 0.40), dark, r=0.006)              # side straps
    add_cyl(g, (0, 0, 0.40), 0.29, 0.03, M["paint_yellow"], seg=12)                        # hazard band
    finish(g, "TrashBin_Body", r)
    return r


BUILDERS = [
    ("Prop_Hydrant", build_hydrant),
    ("Prop_Bench", build_bench),
    ("Prop_BusShelter", build_bus_shelter),
    ("Prop_TrafficLight", build_traffic_light),
    ("Prop_Planter", build_planter),
    ("Prop_Dumpster", build_dumpster),
    ("Prop_Tree", build_tree),
    ("Prop_TrafficCone", build_cone),
    ("Prop_TrashBin", build_trash_bin),
]

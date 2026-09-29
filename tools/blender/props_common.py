"""Shared plumbing for the city props modules (node naming, image packing, shared materials)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *          # noqa: F401,F403  (bpy, MB, make_material, pal, ...)
import ground_texlib as T
from street_geo import *      # noqa: F401,F403

_used = set()


def unique(name):
    assert name not in _used, "duplicate node name " + name
    _used.add(name)
    return name


def new_root(name):
    unique(name)
    return add_empty(name, (0, 0, 0), display="PLAIN_AXES", size=0.6)


UV_SCALE = {}        # material -> metres per texture repeat (metric box-projection UVs are generated for these in finish())


def finish(mb, name, parent, bevel=None, sharp=40.0, loc=(0, 0, 0)):
    """Turn the accumulated MB into a mesh node below `parent`."""
    for mat in list(mb.mats):
        if mat in UV_SCALE:
            uv_box_for_material(mb, mat, (UV_SCALE[mat], UV_SCALE[mat]))
    return mb.to_object(unique(name), parent=parent, location=loc, bevel=bevel, sharp_angle=sharp)


def png_image(name, arr_vup, srgb=True):
    """Tight deterministic PNG (see ground_texlib.encode_png), packed so the glTF exporter embeds the bytes as they are."""
    ensure_dir(TEXTURE_DIR)
    path = os.path.join(TEXTURE_DIR, name + ".png")
    T.save_png(path, arr_vup)
    img = bpy.data.images.load(path)
    img.name = name
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    img.pack()
    return img


def make_mats():
    M = {}
    for k in ("steel", "steel_dark", "rubber", "paint_white", "paint_yellow", "paint_red"):
        M[k] = pal(k)
    M["lamp_glow"] = pal("lamp_glow", emission_strength=8.0)
    M["beacon_red"] = pal("beacon_red", emission_strength=9.0)
    M["bark"] = make_material("tree_bark", "#4D3A2A", 0.0, 0.95)
    M["cone_orange"] = make_material("cone_orange", "#F0621A", 0.0, 0.5)
    # ---- cars (3 body colours, everything else shared) ---------------------------------------------------------
    M["paint_a"] = make_material("car_paint_red", "#B01F2B", 0.35, 0.32)
    M["paint_b"] = make_material("car_paint_slate", "#7D8FA6", 0.35, 0.32)
    M["paint_c"] = make_material("car_paint_amber", "#E8A317", 0.30, 0.36)
    M["glass"] = make_material("car_glass", "#14263A", 0.6, 0.06)
    M["trim"] = make_material("car_trim", "#1A1B1F", 0.0, 0.55)
    M["chrome"] = make_material("car_chrome", "#C8CCD2", 1.0, 0.18)
    M["under"] = make_material("car_underbody", "#0B0C0E", 0.0, 0.92)
    M["tyre"] = make_material("car_tyre", "#121316", 0.0, 0.88)
    M["alloy"] = make_material("car_alloy", "#AEB4BC", 0.92, 0.28)
    M["headlight"] = make_material("car_headlight", "#EFE7D2", 0.0, 0.2, emission="#FFF1CF", emission_strength=6.0)
    M["taillight"] = make_material("car_taillight", "#3A0A08", 0.0, 0.25, emission="#FF2418", emission_strength=4.5)
    M["amber_lens"] = make_material("lamp_amber", "#3A2000", 0.0, 0.25, emission="#FFA21A", emission_strength=9.0)
    M["plate"] = make_textured_material("car_plate", albedo=png_image("ground_prop_plate_albedo", T.make_plate()["albedo"]), roughness=0.5)
    # ---- street furniture / rooftop ------------------------------------------------------------------------------
    M["pole"] = make_material("lamp_pole", "#5C636B", 0.85, 0.42)
    M["galv"] = make_material("galvanized", "#98A0A8", 0.9, 0.38)
    M["stripes"] = make_textured_material("barrier_stripes", albedo=png_image("ground_prop_stripes_albedo", T.make_stripes()["albedo"]),
                                          roughness=0.55)
    M["solar"] = make_textured_material("solar_cells", albedo=png_image("ground_prop_solar_albedo", T.make_solar_cells()["albedo"]),
                                        roughness=0.22, metallic=0.25)
    M["alu"] = make_material("aluminium", "#B4B9BF", 0.9, 0.36)
    M["fan_dark"] = make_material("fan_dark", "#1B1E22", 0.6, 0.5)
    M["foliage"] = make_textured_material("prop_foliage", albedo=png_image("ground_prop_foliage_albedo", T.make_foliage()["albedo"]),
                                          roughness=0.85)
    M["soil"] = make_material("prop_soil", "#3A2B20", 0.0, 1.0)
    # ---- extras: traffic signal lenses (red lit, the others dim), shelter glass, back-lit ad panel, blue sign
    M["tl_red"] = pal("glow_red", "tl_red_lit")
    M["tl_amber_off"] = make_material("tl_amber_off", "#5A3A05", 0.0, 0.3)
    M["tl_green_off"] = make_material("tl_green_off", "#0B3A1E", 0.0, 0.3)
    M["shelter_glass"] = make_material("shelter_glass", "#5F8598", 0.45, 0.06)
    M["lightbox"] = make_material("lightbox_glow", "#DDEFFF", 0.0, 0.4, emission="#CFE9FF", emission_strength=2.6)
    M["sign_blue"] = make_material("sign_blue", "#1C4FA0", 0.1, 0.45)
    # ---- weathered (grunge textured, tinted) versions of the big painted / concrete surfaces ----------------------------
    grunge = png_image("ground_prop_grunge_albedo", T.make_grunge()["albedo"])

    def tint(key, name, color, metallic, rough, scale=2.0):
        m = tinted_material(name, grunge, color, metallic, rough)
        UV_SCALE[m] = scale
        M[key] = m

    tint("concrete", "concrete", "#8A8D92", 0.0, 0.9)
    tint("concrete_dark", "concrete_dark", "#5A5D63", 0.0, 0.92)
    tint("plaster", "plaster", "#B7B1A3", 0.0, 0.9)
    tint("unit_a", "unit_paint_a", "#C7CBCC", 0.35, 0.5)
    tint("unit_b", "unit_paint_b", "#D2CBB8", 0.3, 0.55)
    tint("tower", "tower_body", "#6F8092", 0.15, 0.6)
    tint("asphalt", "roof_membrane", "#3A3C41", 0.0, 0.95)
    tint("green", "dumpster_green", "#2F5D3E", 0.2, 0.55)
    tint("hydrant", "hydrant_red", "#C21F1A", 0.3, 0.42)
    wood_img = png_image("ground_prop_wood_albedo", T.make_wood()["albedo"])
    M["wood"] = make_textured_material("wood", albedo=wood_img, roughness=0.75)
    UV_SCALE[M["wood"]] = 0.8
    return M


def tinted_material(name, image, tint, metallic=0.0, roughness=0.8, scale_note=None):
    """Principled material whose base colour = image (weathering / grunge, neutral grey) x tint colour ('#rrggbb').
    The glTF exporter writes the image as baseColorTexture and the tint as baseColorFactor (Mix node, MULTIPLY)."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.interpolation = "Linear"
    tex.extension = "REPEAT"
    tex.location = (-700, 200)
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    mix.location = (-400, 200)
    nt.links.new(tex.outputs["Color"], mix.inputs["A"])
    mix.inputs["B"].default_value = hexc(tint)
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    mat.use_backface_culling = True
    return mat

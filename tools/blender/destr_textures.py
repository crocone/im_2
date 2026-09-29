"""destr_textures.py - tileable procedural textures for the destructible props (numpy only, deterministic).

All generators return float arrays (H, W, 3) in 0..1 (sRGB albedo), row 0 = TOP of the picture, and tile seamlessly
(FFT-filtered noise and periodic Worley distances are periodic by construction).  `jpeg_image` packs them as JPEG
(`destr_*.jpg` - the glTF image name is taken from the file name, so every image name starts with `destr_`).
"""
import os

import bpy
import numpy as np

from common import TEXTURE_DIR, ensure_dir


# ----------------------------------------------------------------------------------------------------------------------
# noise primitives
# ----------------------------------------------------------------------------------------------------------------------
def fbm(size, rng, beta=2.0, aniso=(1.0, 1.0), fmin=1.0, fmax=None):
    """Tileable fractal noise, zero mean / unit std.  Power spectrum ~ 1/f^beta.  aniso=(ax, ay): larger ay makes the
    features longer vertically (streaks).  size = n or (height, width); frequencies are in cycles per WIDTH so a
    (2w, w) field has square features."""
    h, w = (size, size) if np.isscalar(size) else size
    white = rng.standard_normal((h, w))
    F = np.fft.fft2(white)
    fy = np.fft.fftfreq(h)[:, None] * w
    fx = np.fft.fftfreq(w)[None, :] * w
    f = np.sqrt((fx * aniso[0]) ** 2 + (fy * aniso[1]) ** 2)
    f[0, 0] = 1.0
    amp = f ** (-beta / 2.0)
    amp[f < fmin] = 0.0
    if fmax is not None:
        amp[f > fmax] = 0.0
    n = np.real(np.fft.ifft2(F * amp))
    n -= n.mean()
    n /= (n.std() + 1e-9)
    return n


def worley(size, rng, npts, warp=None):
    """Periodic Worley noise: returns (F1, F2, nearest_index) with distances in texture widths.
    size = n or (height, width) (the domain is then width x height/width, periodic in both directions).
    warp = (du, dv) arrays added to the lookup coordinates (domain warping, keeps tiling if periodic)."""
    h, w = (size, size) if np.isscalar(size) else size
    ry = h / w
    pts = rng.random((npts, 2)) * np.array([1.0, ry])
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64) / w
    if warp is not None:
        xs = (xs + warp[0]) % 1.0
        ys = (ys + warp[1]) % ry
    d1 = np.full((h, w), 9.0)
    d2 = np.full((h, w), 9.0)
    idx = np.zeros((h, w), np.int32)
    for i, (px, py) in enumerate(pts):
        dx = np.abs(xs - px)
        dx = np.minimum(dx, 1.0 - dx)
        dy = np.abs(ys - py)
        dy = np.minimum(dy, ry - dy)
        d = np.sqrt(dx * dx + dy * dy)
        closer = d < d1
        d2 = np.where(closer, d1, np.minimum(d2, d))
        idx = np.where(closer, i, idx)
        d1 = np.where(closer, d, d1)
    return d1, d2, idx


def crack_mask(size, rng, cells=14, width=0.0022, keep=0.45, warp_amt=0.035):
    """Irregular crack network (0..1, 1 = crack) - warped Worley cell borders, only a fraction of them kept."""
    wu = fbm(size, rng, beta=2.2) * warp_amt * 0.35
    wv = fbm(size, rng, beta=2.2) * warp_amt * 0.35
    if not np.isscalar(size):
        cells = int(round(cells * size[0] / size[1]))
    d1, d2, idx = worley(size, rng, cells, warp=(wu, wv))
    edge = d2 - d1
    line = np.clip(1.0 - edge / width, 0.0, 1.0)
    sel = fbm(size, rng, beta=2.6)
    gate = np.clip((sel - (1.0 - 2.0 * keep)) * 2.0, 0.0, 1.0)
    return line * gate


def _col(hexstr):
    h = hexstr.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def _mix(a, b, t):
    return a * (1.0 - t[..., None]) + b * t[..., None]


# ----------------------------------------------------------------------------------------------------------------------
# material textures
# ----------------------------------------------------------------------------------------------------------------------
def stone_albedo(size=512, seed=101, base="#CFC6B6"):
    """Weathered limestone / cast stone: mottling, fine grain, rain streaks, dirt patches, pits and hairline cracks."""
    rng = np.random.default_rng(seed)
    c = np.broadcast_to(_col(base), (size, size, 3)).copy()
    mott = fbm(size, rng, beta=2.8)
    grain = fbm(size, rng, beta=0.6)
    streak = fbm(size, rng, beta=2.0, aniso=(1.0, 7.0))
    patch = fbm(size, rng, beta=3.2)
    c *= (1.0 + 0.055 * mott[..., None] + 0.035 * grain[..., None])
    dirt = np.clip((streak - 0.35) * 0.55, 0.0, 1.0)
    c = _mix(c, c * _col("#8E8577") / _col(base).max() * 0.95, dirt * 0.55)
    warm = np.clip((patch - 0.6) * 0.8, 0.0, 1.0)
    c = _mix(c, c * np.array([0.93, 0.88, 0.80]), warm * 0.6)
    pits = (rng.random((size, size)) > 0.9965).astype(np.float64)
    pits = np.maximum(pits, np.roll(pits, 1, axis=1) * 0.6)
    c *= (1.0 - 0.35 * pits[..., None])
    cr = crack_mask(size, rng, cells=11, width=0.0026, keep=0.42)
    cr2 = crack_mask(size, rng, cells=26, width=0.0014, keep=0.25)
    crack = np.maximum(cr, cr2 * 0.7)
    c = _mix(c, c * 0.38, crack * 0.9)
    return np.clip(c, 0.0, 1.0)


def column_stone_albedo(w=512, h=2048, seed=111, height=12.0, base="#CDBA98"):
    """Weathered limestone for the column, tileable horizontally only: u = half the circumference (2 tiles around),
    v = 0..1 covers the full height (z = 0..`height` m), row 0 = top.  Height dependent weathering: dark damp grime and
    lichen at the base, drip streaks below the capital and the base mouldings, bedding bands, crack network, pits."""
    rng = np.random.default_rng(seed)
    shape = (h, w)
    z = (1.0 - (np.arange(h) + 0.5) / h)[:, None] * height          # metres, per row
    c = np.broadcast_to(_col(base), (h, w, 3)).copy()
    mott = fbm(shape, rng, beta=2.7)
    grain = fbm(shape, rng, beta=0.6)
    bed_n = fbm(shape, rng, beta=2.8)
    c *= (1.0 + 0.06 * mott[..., None] + 0.035 * grain[..., None])
    bands = np.sin(z * 9.0 + bed_n * 1.2) * 0.5 + 0.5
    c *= (1.0 - 0.035 * bands[..., None])
    # drip streaks: strongest right below the capital (z 9..11.4), fading towards mid height
    streak = fbm(shape, rng, beta=1.9, aniso=(1.0, 9.0))
    top_w = np.clip((z - 6.5) / 4.5, 0.0, 1.0) * (z < 11.42)
    drip = np.clip((streak + 0.2) * 0.6, 0.0, 1.0) * top_w
    c = _mix(c, c * np.array([0.62, 0.60, 0.57]), drip * 0.75)
    cap_dirt = np.clip((z - 11.38) / 0.2, 0.0, 1.0) * np.clip(fbm(shape, rng, beta=2.2) * 0.4 + 0.6, 0.0, 1.0)
    c = _mix(c, c * 0.72, cap_dirt * 0.6)
    # damp grime + lichen at the base (ragged upper edge)
    edge = 1.25 + 0.35 * fbm(shape, rng, beta=2.4)
    grime = np.clip((edge - z) / 0.5, 0.0, 1.0)
    c = _mix(c, c * np.array([0.52, 0.52, 0.46]), grime * 0.8)
    lich = np.clip((fbm(shape, rng, beta=2.2) - 1.0) * 1.5, 0.0, 1.0) * np.clip((2.2 - z) / 1.2, 0.0, 1.0)
    c = _mix(c, np.broadcast_to(_col("#6F7446"), c.shape), lich * 0.55)
    # drum joints of the shaft (thin dark mortar lines with a lighter worn lip), slightly wavy
    wob = fbm(shape, rng, beta=2.5) * 0.008
    for zj in (2.35, 3.80, 5.25, 6.70, 8.15, 9.55):
        d = np.abs(z + wob - zj)
        c = _mix(c, c * 0.42, np.clip(1.0 - d / 0.0075, 0.0, 1.0) * 0.85)
        lip = np.clip(1.0 - np.abs(z + wob - zj - 0.016) / 0.008, 0.0, 1.0)
        c = _mix(c, np.minimum(c * 1.08, 1.0), lip * 0.5)
    # cracks + crazing, pits
    cr = crack_mask(shape, rng, cells=9, width=0.0022, keep=0.40)
    cr2 = crack_mask(shape, rng, cells=24, width=0.0012, keep=0.22)
    crack = np.maximum(cr, cr2 * 0.65)
    c = _mix(c, c * 0.35, crack * 0.9)
    pits = np.clip((rng.random((h, w)) - 0.9955) * 300.0, 0.0, 1.0)
    c *= (1.0 - 0.4 * pits[..., None])
    return np.clip(c, 0.0, 1.0)


def debris_metal_albedo(size=512, seed=212, base="#56514B"):
    """Raw torn steel / sheet-metal core for cut faces of metal props: dark grey, grinding scratches, rust bloom."""
    rng = np.random.default_rng(seed)
    c = np.broadcast_to(_col(base), (size, size, 3)).copy()
    mott = fbm(size, rng, beta=2.4)
    scratch = fbm(size, rng, beta=1.2, aniso=(8.0, 1.0))
    grain = fbm(size, rng, beta=0.5)
    c *= (1.0 + 0.10 * mott[..., None] + 0.08 * scratch[..., None] + 0.05 * grain[..., None])
    rust = np.clip((fbm(size, rng, beta=2.6) - 0.6) * 0.9, 0.0, 1.0)
    c = _mix(c, np.broadcast_to(_col("#7A4322"), c.shape), rust * 0.7)
    return np.clip(c, 0.0, 1.0)


def debris_albedo(size=512, seed=202, base="#8C857B"):
    """Exposed concrete / rubble for cut faces: aggregate pebbles, pores, dust."""
    rng = np.random.default_rng(seed)
    c = np.broadcast_to(_col(base), (size, size, 3)).copy()
    mott = fbm(size, rng, beta=2.4)
    grain = fbm(size, rng, beta=0.4)
    c *= (1.0 + 0.09 * mott[..., None] + 0.07 * grain[..., None])
    wu = fbm(size, rng, beta=2.0) * 0.004
    wv = fbm(size, rng, beta=2.0) * 0.004
    d1, d2, idx = worley(size, rng, 170, warp=(wu, wv))
    tones = rng.random(170)
    radius = 0.011 + 0.016 * rng.random(170)
    peb = np.clip((radius[idx] - d1) / 0.0035, 0.0, 1.0)
    pal = np.array([_col("#B9B2A6"), _col("#6E675F"), _col("#A18E78"), _col("#D0CAC0"), _col("#57524D")])
    pc = pal[(tones[idx] * len(pal)).astype(int) % len(pal)]
    pc = pc * (0.9 + 0.2 * grain[..., None] * 0.5)
    c = _mix(c, pc, peb * 0.85)
    pores = np.clip((rng.random((size, size)) - 0.992) * 120.0, 0.0, 1.0)
    c *= (1.0 - 0.5 * pores[..., None])
    dust = np.clip(fbm(size, rng, beta=3.0) * 0.5, 0.0, 1.0)
    c = _mix(c, np.broadcast_to(_col("#B4ACA0"), c.shape), dust * 0.25)
    return np.clip(c, 0.0, 1.0)


def stucco_albedo(size=512, seed=303, base="#D8C8AA"):
    """Painted render / stucco: soft mottling, trowel grain, faint dirt streaks, hairline cracks."""
    rng = np.random.default_rng(seed)
    c = np.broadcast_to(_col(base), (size, size, 3)).copy()
    mott = fbm(size, rng, beta=2.6)
    grain = fbm(size, rng, beta=0.5)
    trowel = fbm(size, rng, beta=1.6, aniso=(2.5, 1.0))
    streak = fbm(size, rng, beta=2.0, aniso=(1.0, 8.0))
    c *= (1.0 + 0.045 * mott[..., None] + 0.03 * grain[..., None] + 0.02 * trowel[..., None])
    dirt = np.clip((streak - 0.5) * 0.5, 0.0, 1.0)
    c = _mix(c, c * np.array([0.78, 0.75, 0.72]), dirt * 0.6)
    crack = crack_mask(size, rng, cells=9, width=0.0018, keep=0.3)
    c = _mix(c, c * 0.55, crack * 0.8)
    return np.clip(c, 0.0, 1.0)


def stucco_facade_albedo(w=512, h=1024, seed=313, height=6.0, base="#D3A07A"):
    """Painted render for the shop walls, tileable horizontally only (u = 3 m), v = 0..1 over `height` metres:
    splash dirt + damp at the base, dark run-off streaks below the coping / string course, soft mottling, hairlines."""
    rng = np.random.default_rng(seed)
    shape = (h, w)
    z = (1.0 - (np.arange(h) + 0.5) / h)[:, None] * height
    c = np.broadcast_to(_col(base), (h, w, 3)).copy()
    mott = fbm(shape, rng, beta=2.6)
    grain = fbm(shape, rng, beta=0.5)
    trowel = fbm(shape, rng, beta=1.6, aniso=(2.5, 1.0))
    c *= (1.0 + 0.05 * mott[..., None] + 0.035 * grain[..., None] + 0.02 * trowel[..., None])
    streak = fbm(shape, rng, beta=1.8, aniso=(1.0, 10.0))
    runoff = (np.clip(1.0 - (5.45 - z) / 1.6, 0.0, 1.0) * (z < 5.46) +
              np.clip(1.0 - (4.27 - z) / 1.1, 0.0, 1.0) * (z < 4.28) * 0.8)
    c = _mix(c, c * np.array([0.66, 0.62, 0.60]), np.clip((streak + 0.1) * 0.55, 0.0, 1.0) * runoff * 0.8)
    edge = 0.75 + 0.22 * fbm(shape, rng, beta=2.3)
    splash = np.clip((edge - z) / 0.45, 0.0, 1.0)
    c = _mix(c, c * np.array([0.60, 0.56, 0.52]), splash * 0.7)
    crack = crack_mask(shape, rng, cells=10, width=0.0016, keep=0.25)
    c = _mix(c, c * 0.55, crack * 0.75)
    return np.clip(c, 0.0, 1.0)


def concrete_albedo(size=512, seed=505, base="#A8A398"):
    """Weathered cast concrete (footings, copings, bands, sills): mottling, formwork pores, water stains."""
    rng = np.random.default_rng(seed)
    c = np.broadcast_to(_col(base), (size, size, 3)).copy()
    mott = fbm(size, rng, beta=2.5)
    grain = fbm(size, rng, beta=0.5)
    c *= (1.0 + 0.07 * mott[..., None] + 0.05 * grain[..., None])
    stain = np.clip((fbm(size, rng, beta=2.0, aniso=(1.0, 5.0)) - 0.4) * 0.6, 0.0, 1.0)
    c = _mix(c, c * np.array([0.72, 0.70, 0.66]), stain * 0.6)
    pores = np.clip((rng.random((size, size)) - 0.994) * 160.0, 0.0, 1.0)
    pores = np.maximum(pores, np.roll(pores, 1, axis=0) * 0.5)
    c *= (1.0 - 0.45 * pores[..., None])
    crack = crack_mask(size, rng, cells=8, width=0.0018, keep=0.3)
    c = _mix(c, c * 0.5, crack * 0.8)
    return np.clip(c, 0.0, 1.0)


def painted_steel_albedo(size=512, seed=404, base="#6E8E86", rust="#8A4A26"):
    """Painted steel plate (water tank): faded paint mottling, vertical rust runs, paint chips showing dark steel."""
    rng = np.random.default_rng(seed)
    c = np.broadcast_to(_col(base), (size, size, 3)).copy()
    mott = fbm(size, rng, beta=2.5)
    grain = fbm(size, rng, beta=0.7)
    c *= (1.0 + 0.06 * mott[..., None] + 0.025 * grain[..., None])
    fade = np.clip(fbm(size, rng, beta=3.0) * 0.5, 0.0, 1.0)
    c = _mix(c, c * 1.12 + 0.03, fade * 0.5)
    runs = fbm(size, rng, beta=1.8, aniso=(1.0, 10.0))
    runs_mask = np.clip((runs - 0.9) * 0.9, 0.0, 1.0) * np.clip(fbm(size, rng, beta=2.5) + 0.3, 0.0, 1.0)
    c = _mix(c, np.broadcast_to(_col(rust), c.shape) * (0.85 + 0.2 * grain[..., None] * 0.3), runs_mask * 0.75)
    wu = fbm(size, rng, beta=2.0) * 0.01
    wv = fbm(size, rng, beta=2.0) * 0.01
    d1, d2, idx = worley(size, rng, 90, warp=(wu, wv))
    rad = 0.004 + 0.012 * rng.random(90) ** 2
    chip = np.clip((rad[idx] - d1) / 0.002, 0.0, 1.0)
    c = _mix(c, np.broadcast_to(_col("#3B3430"), c.shape), chip * 0.85)
    return np.clip(c, 0.0, 1.0)


# ----------------------------------------------------------------------------------------------------------------------
# packing
# ----------------------------------------------------------------------------------------------------------------------
def jpeg_image(name, arr, quality=88):
    """Save `arr` as TEXTURE_DIR/<name>.jpg and return a PACKED sRGB image (exported as image/jpeg)."""
    assert name.startswith("destr_"), name
    arr = np.asarray(arr, dtype=np.float32)
    h, w = arr.shape[:2]
    ensure_dir(TEXTURE_DIR)
    path = os.path.join(TEXTURE_DIR, name + ".jpg")
    img = bpy.data.images.new(name + "_gen", w, h, alpha=False, float_buffer=False)
    rgba = np.concatenate([arr, np.ones((h, w, 1), np.float32)], axis=2)
    img.pixels.foreach_set(np.clip(rgba[::-1], 0.0, 1.0).ravel())
    img.filepath_raw = path
    img.file_format = "JPEG"
    img.save(filepath=path, quality=quality)
    bpy.data.images.remove(img)
    img = bpy.data.images.load(path)
    img.name = name
    img.colorspace_settings.name = "sRGB"
    img.pack()
    return img

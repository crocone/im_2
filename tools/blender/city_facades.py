"""Armored Flight - procedural facade / roof / trim textures for city_buildings.glb (pure numpy, NO bpy).

Every FACADE map covers exactly one tile of 24.0 m x 28.8 m = 8 bays (3.0 m) x 8 floors (3.6 m), so UVs of
metres / (24.0, 28.8) tile seamlessly and window columns / floor lines match geometry that is built on the same
grid (building corners on multiples of 3 m, floor levels on multiples of 3.6 m above the ground).

Layout of all arrays: float32 (H, W, 3), values 0..1, "v-up" (row 0 = bottom of the tile = v 0).  Colours are the
sRGB values that end up in the image files.  ORM = (R: unused/1, G: roughness, B: metallic) as glTF expects.

Everything is deterministic (numpy Generators with fixed seeds, no clocks, stable ordering).
"""
import numpy as np

F32 = np.float32
TILE_W, TILE_H = 24.0, 28.8
BAY, FLOOR = 3.0, 3.6
NB, NF = 8, 8


# ----------------------------------------------------------------------------------------------------
# maths helpers
# ----------------------------------------------------------------------------------------------------
def smooth(t):
    return t * t * (3.0 - 2.0 * t)


def sstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def cov(t, a, b, aa):
    """Exact 1-D box-filter coverage of the interval [a, b] by a pixel of width aa centred on t."""
    return np.clip((np.minimum(t + 0.5 * aa, b) - np.maximum(t - 0.5 * aa, a)) / aa, 0.0, 1.0).astype(F32)


def pline(t, pitch, width, aa, offset=0.0):
    """Anti-aliased periodic lines (every `pitch` metres, centred on offset + k*pitch)."""
    u = np.mod(t - offset + 0.5 * pitch, pitch) - 0.5 * pitch
    return cov(u, -0.5 * width, 0.5 * width, aa)


def pnoise(h, w, cy, cx, rng):
    """Periodic (tileable) smooth value noise in 0..1 on a cy x cx lattice spanning the canvas."""
    lat = rng.random((cy, cx)).astype(F32)
    ys = (np.arange(h) + 0.5) * (cy / h)
    xs = (np.arange(w) + 0.5) * (cx / w)
    y0 = np.floor(ys).astype(np.int64)
    x0 = np.floor(xs).astype(np.int64)
    ty = smooth(ys - y0).astype(F32)[:, None]
    tx = smooth(xs - x0).astype(F32)[None, :]
    y0m, y1m = y0 % cy, (y0 + 1) % cy
    x0m, x1m = x0 % cx, (x0 + 1) % cx
    r0 = lat[np.ix_(y0m, x0m)] + (lat[np.ix_(y0m, x1m)] - lat[np.ix_(y0m, x0m)]) * tx
    r1 = lat[np.ix_(y1m, x0m)] + (lat[np.ix_(y1m, x1m)] - lat[np.ix_(y1m, x0m)]) * tx
    return (r0 + (r1 - r0) * ty).astype(F32)


def fbm(h, w, tw, th, feature, octaves, rng, gain=0.5, aniso=(1.0, 1.0)):
    """Tileable fractal noise (mean ~0.5).  feature = first-octave wavelength in metres; aniso stretches x/z."""
    tot = np.zeros((h, w), F32)
    amp, norm, f = 1.0, 0.0, float(feature)
    for _ in range(octaves):
        cx = max(1, int(round(tw / (f * aniso[0]))))
        cy = max(1, int(round(th / (f * aniso[1]))))
        tot += amp * pnoise(h, w, cy, cx, rng)
        norm += amp
        amp *= gain
        f *= 0.5
    return tot / norm


def vmax(*arrs):
    """Element-wise maximum of broadcastable arrays."""
    out = arrs[0]
    for a in arrs[1:]:
        out = np.maximum(out, a)
    return out


def rgb(c):
    return np.array(c, F32).reshape(1, 1, 3)


def mix3(base, col, m):
    """base (H,W,3), col (H,W,3) or (1,1,3), m (H,W) coverage -> blended."""
    return base + (col - base) * m[..., None]


def downsample2(a):
    """2x2 box downsample (keeps tiling exact)."""
    return 0.25 * (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2])


class Grid:
    def __init__(self, w=1024, h=1024, tw=TILE_W, th=TILE_H):
        self.w, self.h, self.tw, self.th = w, h, tw, th
        self.x = ((np.arange(w) + 0.5) * (tw / w)).astype(F32)[None, :]
        self.z = ((np.arange(h) + 0.5) * (th / h)).astype(F32)[:, None]
        self.ax = tw / w
        self.az = th / h

    def full(self, v=0.0):
        return np.full((self.h, self.w), v, F32)


# ----------------------------------------------------------------------------------------------------
# lit windows ("rooms": runs of neighbouring lit panes share colour temperature + brightness)
# ----------------------------------------------------------------------------------------------------
TEMPS = {
    "warm": (1.00, 0.70, 0.40),
    "warmwhite": (1.00, 0.83, 0.60),
    "neutral": (1.00, 0.93, 0.82),
    "cool": (0.80, 0.91, 1.00),
    "tv": (0.55, 0.68, 1.00),
}


def lit_table(rng, nf, n, frac=0.33, stay=0.7, temps=(("warm", 0.4), ("warmwhite", 0.3), ("neutral", 0.2), ("cool", 0.1)),
              bright=(0.55, 1.0), tol=0.035):
    """Markov chain along each floor: P(lit) ~= frac with room-sized runs.  Returns lit(bool), rgb, brightness.
    Re-rolls (deterministically) until the realised lit fraction is within frac +- tol."""
    for _ in range(40):
        res = _lit_table_once(rng, nf, n, frac, stay, temps, bright)
        if abs(res[0].mean() - frac) <= tol:
            break
    return res


def _lit_table_once(rng, nf, n, frac, stay, temps, bright):
    turn_on = frac * (1.0 - stay) / max(1e-6, 1.0 - frac)
    names = [t[0] for t in temps]
    probs = np.array([t[1] for t in temps], np.float64)
    probs /= probs.sum()
    lit = np.zeros((nf, n), bool)
    col = np.zeros((nf, n, 3), F32)
    br = np.zeros((nf, n), F32)

    def pick():
        return np.array(TEMPS[names[int(rng.choice(len(names), p=probs))]], F32), float(rng.uniform(*bright))

    for f in range(nf):
        state = rng.random() < frac
        c, b = pick()
        for i in range(n):
            if i > 0:
                if state:
                    state = rng.random() < stay
                else:
                    state = rng.random() < turn_on
                    if state:
                        c, b = pick()
            lit[f, i] = state
            col[f, i] = c
            br[f, i] = b * float(rng.uniform(0.88, 1.06))
    return lit, col, br


def blur_wrap(a, passes=1):
    """Tileable [1 2 1]/4 blur along both axes."""
    a = a.astype(F32, copy=True)
    for _ in range(passes):
        for ax_ in (0, 1):
            a = 0.25 * np.roll(a, 1, ax_) + 0.5 * a + 0.25 * np.roll(a, -1, ax_)
    return a


def normal_from_height(h, px_w, px_h, strength=1.0):
    """Height field in metres (v-up rows, tileable) -> OpenGL tangent-space normal map (RGB 0..1)."""
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) / (2.0 * px_w)
    dz = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) / (2.0 * px_h)
    nx, ny = -dx * strength, -dz * strength
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + 1.0)
    return np.stack([nx * inv, ny * inv, inv], axis=-1).astype(F32)


class Maps:
    """Accumulates albedo / roughness / metallic / emissive / relief height for one tile."""

    def __init__(self, g, base, rough, metal):
        self.g = g
        self.alb = np.broadcast_to(rgb(base), (g.h, g.w, 3)).astype(F32).copy()
        self.rough = g.full(rough)
        self.metal = g.full(metal)
        self.emis = np.zeros((g.h, g.w, 3), F32)
        self.h = g.full(0.0)

    def height(self, m, value):
        """Relief in metres (+ = toward the viewer) for the normal map."""
        self.h = self.h + (value - self.h) * m

    def paint(self, m, col=None, rough=None, metal=None):
        """Blend a material zone with coverage m (H,W) (col may be a (H,W,3) array or an rgb triple)."""
        if col is not None:
            c = col if isinstance(col, np.ndarray) and col.ndim == 3 else rgb(col)
            self.alb = mix3(self.alb, c, m)
        if rough is not None:
            self.rough = self.rough + (rough - self.rough) * m
        if metal is not None:
            self.metal = self.metal + (metal - self.metal) * m

    def result(self, emis_size=512, orm_size=512, normal_size=512, normal_strength=1.0):
        alb = np.clip(self.alb, 0.0, 1.0)
        orm = np.stack([np.ones_like(self.rough), np.clip(self.rough, 0.02, 1.0), np.clip(self.metal, 0.0, 1.0)], axis=-1)
        emis = np.clip(self.emis, 0.0, 1.0)
        nrm = normal_from_height(blur_wrap(self.h, 1), self.g.ax, self.g.az, normal_strength)
        while orm.shape[0] > orm_size:
            orm = downsample2(orm)
        while emis.shape[0] > emis_size:
            emis = downsample2(emis)
        while nrm.shape[0] > normal_size:
            nrm = downsample2(nrm)
        nrm = nrm / np.linalg.norm(nrm, axis=-1, keepdims=True)
        return dict(albedo=alb.astype(F32), orm=orm.astype(F32), emissive=emis.astype(F32),
                    normal=(nrm * 0.5 + 0.5).astype(F32))


def _window_light(lz_rel, t_desk, furn, prof_top=0.28):
    """Brightness profile inside a lit window: ceiling lights at the top, furniture silhouettes at the bottom.
    lz_rel: 0 (bottom of glass) .. 1 (top)."""
    p = 0.72 + prof_top * sstep(0.70, 0.93, lz_rel) + 0.10 * sstep(0.25, 0.6, lz_rel)
    desk = 1.0 - (0.30 + 0.35 * furn) * (1.0 - sstep(t_desk - 0.04, t_desk + 0.04, lz_rel))
    return p * desk


# ----------------------------------------------------------------------------------------------------
# 1) GLASS CURTAIN WALL  (style 'blue': vertical silver mullions + spandrel glass,
#                         style 'gold': bronze grid, fritted lower pane, strong floor bands)
# ----------------------------------------------------------------------------------------------------
GLASS_STYLES = {
    "blue": dict(tint=(0.30, 0.43, 0.52), lit_tint=(0.50, 0.52, 0.52), spandrel=(0.19, 0.26, 0.32), frame=(0.64, 0.67, 0.70),
                 frame_metal=0.9, frame_rough=0.32, glass_metal=0.86, main_w=0.10, pane_w=0.05, floor_w=0.09, sp_top=0.95,
                 tr_w=0.07, spandrel_rough=0.22, spandrel_metal=0.8, frac=0.31,
                 temps=(("warmwhite", 0.45), ("neutral", 0.35), ("cool", 0.2))),
    "gold": dict(tint=(0.47, 0.44, 0.39), lit_tint=(0.50, 0.47, 0.42), spandrel=(0.36, 0.33, 0.29), frame=(0.22, 0.19, 0.16),
                 frame_metal=0.85, frame_rough=0.36, glass_metal=0.9, main_w=0.13, pane_w=0.06, floor_w=0.30, sp_top=1.05,
                 tr_w=0.06, spandrel_rough=0.34, spandrel_metal=0.75, frac=0.3,
                 temps=(("warmwhite", 0.45), ("neutral", 0.35), ("warm", 0.2))),
}


def facade_glass(seed, style="blue", size=1024):
    S = GLASS_STYLES[style]
    g = Grid(size, size)
    rng = np.random.default_rng(seed)
    x, z, ax, az = g.x, g.z, g.ax, g.az
    npb = 2
    pw = BAY / npb
    NP = NB * npb
    pane = np.floor(x / pw).astype(np.int64) % NP
    fl = np.floor(z / FLOOR).astype(np.int64) % NF
    lz = z - np.floor(z / FLOOR) * FLOOR

    lit, tcol, br = lit_table(rng, NF, NP, frac=S["frac"], stay=0.72, temps=S["temps"])
    tint_j = rng.uniform(0.84, 1.14, (NF, NP)).astype(F32)
    hue_j = rng.uniform(-0.035, 0.035, (NF, NP)).astype(F32)
    rough_j = rng.uniform(0.05, 0.17, (NF, NP)).astype(F32)
    blind = np.where(rng.random((NF, NP)) < 0.3, rng.uniform(0.12, 0.8, (NF, NP)), 0.0).astype(F32)
    desk = rng.uniform(0.18, 0.32, (NF, NP)).astype(F32)
    P = lambda tab: tab[fl, pane]

    M = Maps(g, S["tint"], 0.1, S["glass_metal"])
    v0 = S["sp_top"] + S["tr_w"] * 0.5
    v1 = FLOOR - S["floor_w"] * 0.5
    t = np.clip((lz - v0) / (v1 - v0), 0.0, 1.0)

    # --- vision glass (unlit): per-pane tint + soft low-frequency reflection variation
    lowf = fbm(g.h, g.w, g.tw, g.th, 7.0, 3, rng)
    tj = P(tint_j) * (0.92 + 0.16 * lowf) * (0.96 + 0.08 * t)
    base = rgb(S["tint"]) * tj[..., None]
    base = base + P(hue_j)[..., None] * rgb((-0.6, 0.2, 0.8))
    M.alb = base.astype(F32)
    M.rough = P(rough_j)
    # --- lit interiors
    L = P(lit.astype(F32))
    furn = pnoise(g.h, g.w, 8, 48, rng)
    prof = _window_light(t, P(desk), furn)
    lit_alb = lerp(M.alb, rgb(S["lit_tint"]) * (0.75 + 0.25 * prof)[..., None], 0.35)
    M.paint(L, lit_alb, rough=0.1, metal=0.55)
    E = P(tcol) * (P(br) * prof)[..., None]
    # --- blinds (lowered from the top of the pane)
    bf = P(blind)
    bm = cov(t, 1.0 - bf, 2.0, az / (v1 - v0)) * (bf > 0)
    slats = 0.9 + 0.1 * np.cos(2 * np.pi * lz / 0.11)
    blind_col = lerp(M.alb, rgb((0.78, 0.76, 0.70)) * slats[..., None], 0.45) * (0.8 + 0.2 * L)[..., None]
    M.paint(bm, blind_col, rough=0.25, metal=0.6)
    E = E * (1.0 - bm * 0.58)[..., None] * (1.0 - bm * 0.12 * (1 - slats))[..., None]
    E = E * L[..., None]
    # --- spandrel zone
    sp = cov(lz, S["floor_w"] * 0.5, S["sp_top"] - S["tr_w"] * 0.5, az)
    sp_n = fbm(g.h, g.w, g.tw, g.th, 3.0, 3, rng)
    streak = pnoise(g.h, g.w, 16, 240, rng)
    sp_col = rgb(S["spandrel"]) * (0.9 + 0.2 * sp_n)[..., None] * (1.0 - 0.18 * streak * sstep(0.2, S["sp_top"], lz))[..., None]
    M.paint(sp, sp_col, rough=S["spandrel_rough"], metal=S["spandrel_metal"])
    E = E * (1.0 - sp)[..., None]
    # --- frame: mullions + transoms
    m_main = pline(x, BAY, S["main_w"], ax)
    m_pane = pline(x, pw, S["pane_w"], ax)
    m_floor = pline(z, FLOOR, S["floor_w"], az)
    m_tr = cov(lz, S["sp_top"] - S["tr_w"] * 0.5, S["sp_top"] + S["tr_w"] * 0.5, az)
    frame = vmax(m_main, m_pane, m_floor, m_tr)
    fcol = rgb(S["frame"]) * (0.92 + 0.12 * sp_n)[..., None]
    M.paint(frame, fcol, rough=S["frame_rough"], metal=S["frame_metal"])
    M.height(sp, -0.015)
    M.height(frame, 0.07)
    E = E * (1.0 - frame)[..., None]
    # thin shadow line under each transom / floor band (depth cue)
    sh = cov(lz, v0, v0 + 0.05, az)
    M.alb = M.alb * (1.0 - 0.35 * sh * (1 - frame))[..., None]
    M.emis = E.astype(F32)
    out = M.result()
    out["lit_fraction"] = float(lit.mean())
    return out


# ----------------------------------------------------------------------------------------------------
# 2) OFFICE RIBBON WINDOWS  (white aluminium spandrel bands + continuous dark glass ribbons)
# ----------------------------------------------------------------------------------------------------
def facade_office(seed, size=1024):
    g = Grid(size, size)
    rng = np.random.default_rng(seed)
    x, z, ax, az = g.x, g.z, g.ax, g.az
    pw = 1.5
    NP = 16
    pane = np.floor(x / pw).astype(np.int64) % NP
    fl = np.floor(z / FLOOR).astype(np.int64) % NF
    lz = z - np.floor(z / FLOOR) * FLOOR
    s0, s1 = 1.12, 3.40      # glass ribbon between s0 and s1 (spandrel band spans the floor line)
    lit, tcol, br = lit_table(rng, NF, NP, frac=0.32, stay=0.74,
                              temps=(("neutral", 0.4), ("cool", 0.35), ("warmwhite", 0.25)), bright=(0.5, 0.95))
    rough_j = rng.uniform(0.06, 0.15, (NF, NP)).astype(F32)
    tint_j = rng.uniform(0.85, 1.15, (NF, NP)).astype(F32)
    blind = np.where(rng.random((NF, NP)) < 0.38, rng.uniform(0.1, 0.8, (NF, NP)), 0.0).astype(F32)
    desk = rng.uniform(0.22, 0.36, (NF, NP)).astype(F32)
    P = lambda tab: tab[fl, pane]
    t = np.clip((lz - s0) / (s1 - s0), 0.0, 1.0)

    lowf = fbm(g.h, g.w, g.tw, g.th, 6.0, 3, rng)
    M = Maps(g, (0.16, 0.20, 0.215), 0.1, 0.72)
    M.alb = (rgb((0.16, 0.20, 0.215)) * (P(tint_j) * (0.9 + 0.2 * lowf) * (0.9 + 0.2 * t))[..., None]).astype(F32)
    M.rough = P(rough_j)
    L = P(lit.astype(F32))
    furn = pnoise(g.h, g.w, 8, 48, rng)
    prof = _window_light(t, P(desk), furn)
    M.paint(L, lerp(M.alb, rgb((0.46, 0.47, 0.46)) * (0.7 + 0.3 * prof)[..., None], 0.4), rough=0.1, metal=0.55)
    E = P(tcol) * (P(br) * prof)[..., None]
    bf = P(blind)
    bm = cov(t, 1.0 - bf, 2.0, az / (s1 - s0)) * (bf > 0)
    vert = 0.9 + 0.1 * np.cos(2 * np.pi * x / 0.09)            # vertical blinds
    M.paint(bm, lerp(M.alb, rgb((0.80, 0.79, 0.74)) * vert[..., None], 0.55) * (0.78 + 0.22 * L)[..., None],
            rough=0.3, metal=0.5)
    E = E * (1.0 - 0.55 * bm)[..., None] * L[..., None]
    # head shadow just below the spandrel band
    hs = sstep(s1 - 0.22, s1, lz) * cov(lz, s0, s1, az)
    M.alb = M.alb * (1.0 - 0.45 * hs)[..., None]
    E = E * (1.0 - 0.3 * hs)[..., None]
    # mullions
    mul = np.maximum(pline(x, pw, 0.05, ax), pline(x, BAY, 0.08, ax))
    ribbon = cov(lz, s0, s1, az)
    M.paint(mul * ribbon, (0.30, 0.31, 0.32), rough=0.35, metal=0.85)
    M.height(ribbon, -0.08)
    M.height(mul * ribbon, -0.045)
    E = E * (1.0 - mul)[..., None]
    # spandrel band: white aluminium panels with seams, sill flashing and rain streaks below each mullion
    band = 1.0 - ribbon
    pn = fbm(g.h, g.w, g.tw, g.th, 2.5, 4, rng)
    cell_j = rng.uniform(0.95, 1.04, (NF, NP)).astype(F32)
    band_col = rgb((0.58, 0.585, 0.58)) * (P(cell_j) * (0.95 + 0.08 * pn))[..., None]
    below = np.where(lz <= s0, s0 - lz, s0 + FLOOR - lz)       # metres below the nearest ribbon sill above
    streak_n = pnoise(g.h, g.w, 12, 320, rng)
    st_len = rng.uniform(0.35, 1.1, (NF, NP)).astype(F32)
    st_i = rng.uniform(0.15, 0.55, (NF, NP)).astype(F32)
    fl_above = np.where(lz <= s0, fl, (fl + 1) % NF)
    sl = st_len[fl_above, pane]
    si = st_i[fl_above, pane]
    near_mull = np.maximum(pline(x, pw, 0.28, ax), 0.35 * pline(x, pw * 0.5, 0.2, ax, offset=0.375))
    streaks = si * np.exp(-below / sl) * (0.35 + 0.65 * streak_n) * near_mull
    band_col = band_col * (1.0 - 0.45 * streaks)[..., None]
    M.paint(band, band_col, rough=0.5, metal=0.25)
    seams = np.maximum(pline(x, pw, 0.018, ax), pline(z, FLOOR, 0.02, az, offset=0.5))
    M.paint(seams * band, (0.36, 0.36, 0.36), rough=0.6, metal=0.2)
    sill = cov(lz, s0 - 0.05, s0, az)
    M.paint(sill, (0.88, 0.88, 0.86), rough=0.35, metal=0.5)
    M.height(seams * band, -0.008)
    M.height(sill, 0.025)
    M.emis = E.astype(F32)
    out = M.result()
    out["lit_fraction"] = float(lit.mean())
    return out


# ----------------------------------------------------------------------------------------------------
# helpers shared by the punched-window facades
# ----------------------------------------------------------------------------------------------------
CURTAINS = [(0.72, 0.62, 0.45), (0.58, 0.24, 0.19), (0.32, 0.42, 0.33), (0.83, 0.80, 0.72), (0.36, 0.38, 0.52),
            (0.70, 0.52, 0.30), (0.86, 0.84, 0.80)]


def _punched_tables(rng, frac, temps):
    lit, tcol, br = lit_table(rng, NF, NB, frac=frac, stay=0.45, temps=temps, bright=(0.55, 1.0))
    cur_kind = rng.choice(4, size=(NF, NB), p=[0.38, 0.32, 0.18, 0.12])   # 0 none, 1 side curtains, 2 roller blind, 3 net
    cur_col = np.array(CURTAINS, F32)[rng.integers(0, len(CURTAINS), size=(NF, NB))]
    cur_l = rng.uniform(0.18, 0.42, (NF, NB)).astype(F32)
    cur_r = rng.uniform(0.18, 0.42, (NF, NB)).astype(F32)
    roll = rng.uniform(0.2, 0.7, (NF, NB)).astype(F32)
    desk = rng.uniform(0.2, 0.34, (NF, NB)).astype(F32)
    return dict(lit=lit, tcol=tcol, br=br, cur_kind=cur_kind, cur_col=cur_col, cur_l=cur_l, cur_r=cur_r, roll=roll,
                desk=desk)


def _glazing(M, g, T, P, gx, gz, x0, x1, z0, z1, glass_col, rng, furn, E):
    """Fill the glass area [x0,x1]x[z0,z1] (cell-local metres) with glass, curtains and lit interiors.
    gx, gz: cell-local coordinates (H,W).  Returns emissive array."""
    ax, az = g.ax, g.az
    gm = cov(gx, x0, x1, ax) * cov(gz, z0, z1, az)
    tz = np.clip((gz - z0) / (z1 - z0), 0.0, 1.0)
    tx = np.clip((gx - x0) / (x1 - x0), 0.0, 1.0)
    L = P(T["lit"].astype(F32))
    refl = 0.85 + 0.3 * tz
    M.paint(gm, rgb(glass_col) * refl[..., None], rough=0.07, metal=0.55)
    prof = _window_light(tz, P(T["desk"]), furn)
    M.paint(gm * L, rgb((0.30, 0.28, 0.25)) * (0.7 + 0.3 * prof)[..., None], rough=0.1, metal=0.35)
    e = P(T["tcol"]) * (P(T["br"]) * prof)[..., None]
    kind = P(T["cur_kind"])
    ccol = P(T["cur_col"])
    folds = 0.86 + 0.14 * np.cos(2 * np.pi * gx / 0.13)
    # side curtains
    side = ((cov(tx, -1.0, P(T["cur_l"]), ax / (x1 - x0)) + cov(tx, 1.0 - P(T["cur_r"]), 2.0, ax / (x1 - x0))) *
            (kind == 1)).astype(F32)
    # roller blind from the top
    rollm = (cov(tz, 1.0 - P(T["roll"]), 2.0, az / (z1 - z0)) * (kind == 2)).astype(F32)
    # net curtain: whole window, translucent
    net = (kind == 3).astype(F32) * 0.55
    cm = np.clip(side + rollm, 0.0, 1.0)
    grey = ccol.mean(axis=-1, keepdims=True)
    cl = lerp(grey, ccol, 0.7) * folds[..., None] * (0.55 + 0.35 * L)[..., None]
    M.paint(gm * cm, cl, rough=0.8, metal=0.0)
    M.paint(gm * net * (1 - cm), rgb((0.80, 0.80, 0.77)) * (0.55 + 0.45 * L)[..., None], rough=0.7, metal=0.1)
    trans = (1.0 - cm) + cm * 0.5 * (ccol.mean(axis=-1) + 0.15)       # light through fabric
    trans = trans * (1.0 - 0.3 * net)
    e = e * (trans * L * gm)[..., None]
    e = np.where(cm[..., None] > 0.01, e * lerp(np.ones_like(ccol), ccol * 1.3 + 0.1, cm[..., None]), e)
    return E + e, gm


# ----------------------------------------------------------------------------------------------------
# 3) BRICK with punched segmental-arch windows, stone sills, soldier-course lintels, curtains
# ----------------------------------------------------------------------------------------------------
def facade_brick(seed, size=1024):
    g = Grid(size, size)
    rng = np.random.default_rng(seed)
    x, z, ax, az = g.x, g.z, g.ax, g.az
    bx = np.floor(x / BAY).astype(np.int64) % NB
    fl = np.floor(z / FLOOR).astype(np.int64) % NF
    lx = x - np.floor(x / BAY) * BAY
    lz = z - np.floor(z / FLOOR) * FLOOR
    T = _punched_tables(rng, 0.34, (("warm", 0.52), ("warmwhite", 0.3), ("tv", 0.04), ("neutral", 0.14)))
    P = lambda tab: tab[fl, bx]

    # --- brick field (running bond, 0.24 m module x 0.075 m course -> exactly tileable)
    course_h, brick_l = 0.075, 0.24
    course = np.floor(z / course_h).astype(np.int64)
    off = (course % 2) * (brick_l * 0.5)
    bid = np.floor((x + off) / brick_l).astype(np.int64) % 100
    hsh = ((course % 384) * 7919 + bid * 104729) % 1000003
    jit = (np.sin(hsh * 12.9898) * 43758.5453) % 1.0
    jit2 = (np.sin(hsh * 78.233) * 12543.123) % 1.0
    brick = rgb((0.47, 0.245, 0.185)) * (0.80 + 0.30 * jit)[..., None]
    brick = brick + (jit2 - 0.5)[..., None] * rgb((0.06, 0.02, -0.01))
    clinker = (jit2 > 0.94).astype(F32)
    brick = brick * (1.0 - 0.35 * clinker)[..., None]
    mort_h = cov(np.mod(z, course_h), -1.0, 0.011, az) + cov(np.mod(z, course_h), course_h - 0.0, course_h + 1, az)
    mort_v = pline(x + off, brick_l, 0.010, ax)
    mortar = np.clip(mort_h + mort_v, 0.0, 1.0)
    brick = mix3(brick, rgb((0.60, 0.56, 0.50)), mortar * 0.8)
    big = fbm(g.h, g.w, g.tw, g.th, 5.0, 4, rng)
    brick = brick * (0.86 + 0.24 * big)[..., None]
    M = Maps(g, (0.5, 0.3, 0.2), 0.86, 0.0)
    M.alb = brick.astype(F32)
    M.rough = (0.82 + 0.1 * big).astype(F32)
    M.h = (0.003 * (jit - 0.5) - 0.007 * mortar).astype(F32)

    # --- window opening with segmental arch
    wx0, wx1, wz0 = 0.80, 2.20, 0.90
    half = 0.5 * (wx1 - wx0)
    ctr = 0.5 * (wx0 + wx1)
    arch = 3.02 + 0.13 * np.clip(1.0 - ((lx - ctr) / half) ** 2, 0.0, 1.0)
    # soldier-course lintel (darker bricks radiating) above the arch
    lint = cov(lx, wx0 - 0.12, wx1 + 0.12, ax) * cov(lz - arch, 0.0, 0.2, az)
    lint_col = rgb((0.40, 0.20, 0.15)) * (0.85 + 0.3 * pline(lx - ctr, 0.075, 0.04, ax) * 0 + 0.25 * jit)[..., None]
    M.paint(lint, lint_col, rough=0.85)
    M.height(lint, 0.012)
    M.paint(lint * pline(lx - ctr, 0.075, 0.012, ax), (0.58, 0.54, 0.48))
    # stone sill + shadow under it
    sill = cov(lx, wx0 - 0.1, wx1 + 0.1, ax) * cov(lz, wz0 - 0.12, wz0, az)
    M.paint(sill, rgb((0.76, 0.72, 0.64)) * (0.9 + 0.2 * big)[..., None], rough=0.7)
    M.height(sill, 0.05)
    ssh = cov(lx, wx0 - 0.1, wx1 + 0.1, ax) * cov(lz, wz0 - 0.20, wz0 - 0.12, az)
    M.alb = M.alb * (1.0 - 0.45 * ssh)[..., None]
    # soot / rain streaks below the sills
    below = np.where(lz <= wz0, wz0 - lz, wz0 + FLOOR - lz)
    fl_above = np.where(lz <= wz0, fl, (fl + 1) % NF)
    st_len = rng.uniform(0.3, 1.6, (NF, NB)).astype(F32)
    st_i = rng.uniform(0.1, 0.5, (NF, NB)).astype(F32)
    sn = pnoise(g.h, g.w, 10, 260, rng)
    streak = st_i[fl_above, bx] * np.exp(-below / st_len[fl_above, bx]) * (0.3 + 0.7 * sn) * \
        cov(lx, wx0 - 0.05, wx1 + 0.05, ax) * (below > 0.12)
    M.alb = M.alb * (1.0 - 0.5 * streak)[..., None]
    # opening: reveal (brick in shadow), frame, glazing
    opening = cov(lx, wx0, wx1, ax) * cov(lz, wz0, 10.0, az) * cov(lz - arch, -10.0, 0.0, az)
    rev = 0.09
    rev_top = cov(lz - arch, -rev - 0.03, 0.0, az) * opening
    rev_l = cov(lx, wx0, wx0 + rev, ax) * opening
    rev_r = cov(lx, wx1 - rev, wx1, ax) * opening
    rev_b = cov(lz, wz0, wz0 + 0.04, az) * opening
    M.paint(opening, brick * 0.55, rough=0.9)
    M.height(opening, -0.15)
    M.alb = M.alb * (1.0 - 0.35 * np.clip(rev_top + rev_l, 0, 1))[..., None]
    M.paint(rev_r * 0.6, brick * 0.75)
    M.paint(rev_b, (0.7, 0.67, 0.6))
    fx0, fx1, fz0 = wx0 + rev, wx1 - rev, wz0 + 0.04
    ftop = arch - rev
    frame_zone = cov(lx, fx0, fx1, ax) * cov(lz, fz0, 10.0, az) * cov(lz - ftop, -10.0, 0.0, az)
    dark_frame = (rng.random((NF, NB)) < 0.28)
    fcol = np.where(P(dark_frame)[..., None], rgb((0.20, 0.21, 0.22)), rgb((0.86, 0.84, 0.77)))
    M.paint(frame_zone, fcol, rough=0.45, metal=0.1)
    M.height(frame_zone, -0.10)
    fw = 0.055
    gx0, gx1, gz0 = fx0 + fw, fx1 - fw, fz0 + fw
    gz1 = ftop - fw          # (arched: approximate with the arch curve)
    furn = pnoise(g.h, g.w, 8, 64, rng)
    E = np.zeros((g.h, g.w, 3), F32)
    E, gm = _glazing(M, g, T, P, lx, lz, gx0, gx1, gz0, 3.05, (0.075, 0.085, 0.095), rng, furn, E)
    arch_glass = cov(lx, gx0, gx1, ax) * cov(lz, 3.05 - 0.01, 10.0, az) * cov(lz - gz1, -10.0, 0.0, az)
    M.paint(arch_glass, (0.09, 0.10, 0.11), rough=0.07, metal=0.55)
    M.height(np.clip(gm + arch_glass, 0, 1), -0.13)
    E = E + (P(T["tcol"]) * (P(T["br"]) * 0.95 * P(T["lit"].astype(F32)))[..., None]) * arch_glass[..., None]
    # sash bars: meeting rail + central muntin
    bars = (cov(lz, 2.05, 2.10, az) + cov(lx, 1.48, 1.52, ax) * cov(lz, gz0, 3.2, az)) * frame_zone
    bars = np.clip(bars, 0, 1)
    M.paint(bars, fcol, rough=0.45, metal=0.1)
    M.height(bars, -0.10)
    E = E * (1.0 - bars)[..., None]
    M.emis = E.astype(F32)
    out = M.result()
    out["lit_fraction"] = float(T["lit"].mean())
    return out


# ----------------------------------------------------------------------------------------------------
# 4) PRECAST CONCRETE / LIMESTONE PANELS with deep punched windows and rain streaks
# ----------------------------------------------------------------------------------------------------
def facade_panel(seed, size=1024):
    g = Grid(size, size)
    rng = np.random.default_rng(seed)
    x, z, ax, az = g.x, g.z, g.ax, g.az
    bx = np.floor(x / BAY).astype(np.int64) % NB
    fl = np.floor(z / FLOOR).astype(np.int64) % NF
    lx = x - np.floor(x / BAY) * BAY
    lz = z - np.floor(z / FLOOR) * FLOOR
    T = _punched_tables(rng, 0.32, (("warm", 0.35), ("warmwhite", 0.35), ("neutral", 0.2), ("cool", 0.1)))
    P = lambda tab: tab[fl, bx]

    tone = rng.uniform(0.94, 1.05, (NF, NB)).astype(F32)
    big = fbm(g.h, g.w, g.tw, g.th, 6.0, 3, rng)
    fine = fbm(g.h, g.w, g.tw, g.th, 0.6, 3, rng)
    grain = pnoise(g.h, g.w, 400, 340, rng)
    base = rgb((0.54, 0.51, 0.47)) * (P(tone) * (0.9 + 0.16 * big) * (0.95 + 0.08 * fine) * (0.97 + 0.06 * grain))[..., None]
    M = Maps(g, (0.7, 0.7, 0.7), 0.82, 0.0)
    M.alb = base.astype(F32)
    M.rough = (0.78 + 0.12 * fine).astype(F32)

    wx0, wx1, wz0, wz1 = 0.52, 2.48, 0.92, 3.12
    # rain streaks from the window corners down over the spandrel (continuing across the floor line)
    below = np.where(lz <= wz0, wz0 - lz, wz0 + FLOOR - lz)
    fl_above = np.where(lz <= wz0, fl, (fl + 1) % NF)
    st_len = rng.uniform(0.4, 1.4, (NF, NB)).astype(F32)
    st_i = rng.uniform(0.2, 0.65, (NF, NB)).astype(F32)
    sn = pnoise(g.h, g.w, 10, 300, rng)
    corners = np.maximum(cov(lx, wx0 - 0.02, wx0 + 0.16, ax), cov(lx, wx1 - 0.16, wx1 + 0.02, ax))
    mid = 0.5 * cov(lx, wx0 + 0.3, wx1 - 0.3, ax) * sn
    streak = st_i[fl_above, bx] * np.exp(-below / st_len[fl_above, bx]) * (0.25 + 0.75 * sn) * np.clip(corners + mid, 0, 1) \
        * (below > 0.03)
    M.alb = M.alb * (1.0 - 0.42 * streak)[..., None]
    # grime under the panel joint / window head (slight darkening)
    head = sstep(wz1 + 0.35, wz1 + 0.05, lz) * cov(lz, wz1, FLOOR, az)
    M.alb = M.alb * (1.0 - 0.12 * head)[..., None]
    # panel joints: vertical at bay lines, horizontal at floor lines and window heads
    joints = vmax(pline(x, BAY, 0.022, ax), pline(z, FLOOR, 0.022, az, offset=0.35), cov(lz, 3.40, 3.42, az))
    M.alb = M.alb * (1.0 - 0.5 * joints)[..., None]
    M.rough = M.rough + (0.95 - M.rough) * joints
    M.height(joints, -0.012)
    # deep reveals (sun from the upper left in the texture: shadow on top + left)
    opening = cov(lx, wx0, wx1, ax) * cov(lz, wz0, wz1, az)
    rv = 0.13
    top = cov(lz, wz1 - rv, wz1, az) * opening
    left = cov(lx, wx0, wx0 + rv * 0.7, ax) * opening
    right = cov(lx, wx1 - rv * 0.7, wx1, ax) * opening
    bot = cov(lz, wz0, wz0 + 0.05, az) * opening
    M.paint(opening, base * 0.62, rough=0.85)
    M.height(opening, -0.17)
    M.alb = M.alb * (1.0 - 0.45 * np.clip(top + left, 0, 1))[..., None]
    M.paint(right, base * 0.8)
    M.paint(bot, base * 1.08)
    fx0, fx1, fz0, fz1 = wx0 + rv * 0.7, wx1 - rv * 0.7, wz0 + 0.05, wz1 - rv
    frame = cov(lx, fx0, fx1, ax) * cov(lz, fz0, fz1, az)
    M.paint(frame, (0.17, 0.17, 0.18), rough=0.4, metal=0.7)
    M.height(frame, -0.12)
    fw = 0.05
    furn = pnoise(g.h, g.w, 8, 64, rng)
    E = np.zeros((g.h, g.w, 3), F32)
    E, gm = _glazing(M, g, T, P, lx, lz, fx0 + fw, fx1 - fw, fz0 + fw, fz1 - fw, (0.085, 0.10, 0.115), rng, furn, E)
    bars = np.clip(cov(lx, 1.5 - 0.025, 1.5 + 0.025, ax) * cov(lz, fz0, fz1, az) +
                   cov(lz, 2.52, 2.57, az) * cov(lx, fx0, fx1, ax), 0, 1)
    M.height(gm, -0.15)
    M.paint(bars, (0.17, 0.17, 0.18), rough=0.4, metal=0.7)
    M.height(bars, -0.12)
    E = E * (1.0 - bars)[..., None]
    M.emis = E.astype(F32)
    out = M.result()
    out["lit_fraction"] = float(T["lit"].mean())
    return out


# ----------------------------------------------------------------------------------------------------
# 5) CONCRETE (roofs, parapets, podium walls, garage decks) - tile 16 x 16 m
# ----------------------------------------------------------------------------------------------------
CONCRETE_TILE = 16.0


def concrete(seed, size=1024):
    g = Grid(size, size, CONCRETE_TILE, CONCRETE_TILE)
    rng = np.random.default_rng(seed)
    x, z, ax, az = g.x, g.z, g.ax, g.az
    big = fbm(g.h, g.w, g.tw, g.th, 8.0, 3, rng)
    mid = fbm(g.h, g.w, g.tw, g.th, 1.6, 3, rng)
    fine = pnoise(g.h, g.w, 600, 600, rng)
    col = rgb((0.43, 0.42, 0.41)) * ((0.82 + 0.3 * big) * (0.93 + 0.12 * mid) * (0.95 + 0.1 * fine))[..., None]
    # slab / formwork joints on a 2 m grid with slightly stained edges
    jx = pline(x, 2.0, 0.025, ax)
    jz = pline(z, 2.0, 0.025, az)
    j = np.maximum(jx, jz)
    near = np.maximum(pline(x, 2.0, 0.25, ax), pline(z, 2.0, 0.25, az))
    col = col * (1.0 - 0.1 * near * mid)[..., None]
    col = mix3(col, rgb((0.30, 0.30, 0.29)), j * 0.7)
    # tie holes (formwork) - small dark dots on a 1 m grid
    tie = cov(np.mod(x + 0.5, 1.0), 0.47, 0.53, ax) * cov(np.mod(z + 0.5, 1.0), 0.47, 0.53, az)
    col = col * (1.0 - 0.4 * tie)[..., None]
    # a few tar repair strips + water stains
    stains = sstep(0.62, 0.8, fbm(g.h, g.w, g.tw, g.th, 3.0, 4, rng))
    col = col * (1.0 - 0.22 * stains)[..., None]
    tar = np.zeros((g.h, g.w), F32)
    for _ in range(4):
        cx, cz = rng.uniform(0, g.tw), rng.uniform(0, g.th)
        horiz = rng.random() < 0.5
        ln, wd = rng.uniform(1.5, 4.0), rng.uniform(0.06, 0.14)
        dx = np.mod(x - cx + g.tw / 2, g.tw) - g.tw / 2
        dz = np.mod(z - cz + g.th / 2, g.th) - g.th / 2
        if horiz:
            tar = np.maximum(tar, cov(dx, -ln / 2, ln / 2, ax) * cov(dz, -wd / 2, wd / 2, az))
        else:
            tar = np.maximum(tar, cov(dz, -ln / 2, ln / 2, az) * cov(dx, -wd / 2, wd / 2, ax))
    col = mix3(col, rgb((0.25, 0.25, 0.25)), tar * 0.6)
    M = Maps(g, (0.6, 0.6, 0.6), 0.9, 0.0)
    M.alb = col.astype(F32)
    M.rough = (0.84 + 0.1 * mid - 0.25 * tar).astype(F32)
    return M.result()


# ----------------------------------------------------------------------------------------------------
# 6) TRIM PALETTE (flat swatches addressed by constant UVs: metals, paints, woods, emissive lights)
# ----------------------------------------------------------------------------------------------------
TRIM_N = 8          # 8 x 8 swatches
TRIM_SIZE = 256     # 32 px per swatch
# name: (albedo sRGB, roughness, metallic, emissive sRGB or None)
TRIM_SWATCHES = [
    ("graphite", (0.20, 0.21, 0.23), 0.38, 0.85, None),
    ("silver", (0.70, 0.72, 0.75), 0.30, 0.90, None),
    ("bronze", (0.42, 0.34, 0.25), 0.38, 0.85, None),
    ("gold", (0.78, 0.61, 0.34), 0.30, 0.92, None),
    ("copper_patina", (0.35, 0.60, 0.51), 0.62, 0.25, None),
    ("white", (0.74, 0.74, 0.72), 0.55, 0.00, None),
    ("yellow", (0.90, 0.70, 0.12), 0.50, 0.00, None),
    ("roof_dark", (0.11, 0.11, 0.12), 0.90, 0.00, None),
    ("brick_red", (0.47, 0.22, 0.16), 0.85, 0.00, None),
    ("wood", (0.44, 0.31, 0.20), 0.85, 0.00, None),
    ("glass_dark", (0.09, 0.12, 0.15), 0.08, 0.70, None),
    ("solar", (0.07, 0.11, 0.24), 0.14, 0.60, None),
    ("green", (0.22, 0.34, 0.15), 0.90, 0.00, None),
    ("stone", (0.68, 0.64, 0.57), 0.62, 0.00, None),
    ("steel_dark", (0.11, 0.115, 0.125), 0.50, 0.80, None),
    ("concrete", (0.50, 0.49, 0.47), 0.88, 0.00, None),
    ("zinc", (0.33, 0.35, 0.38), 0.45, 0.70, None),
    ("red", (0.62, 0.12, 0.10), 0.50, 0.00, None),
    ("granite", (0.24, 0.23, 0.23), 0.40, 0.05, None),
    ("water", (0.10, 0.30, 0.38), 0.05, 0.20, None),
    ("rubber", (0.06, 0.06, 0.065), 0.90, 0.00, None),
    ("light_warm", (1.00, 0.92, 0.75), 0.40, 0.00, (0.80, 0.62, 0.40)),
    ("light_cool", (0.90, 0.96, 1.00), 0.40, 0.00, (0.55, 0.68, 0.80)),
    ("light_green", (0.60, 1.00, 0.60), 0.40, 0.00, (0.35, 1.00, 0.45)),
    ("neon_pink", (1.00, 0.55, 0.85), 0.40, 0.00, (1.00, 0.25, 0.70)),
    ("neon_cyan", (0.55, 0.95, 1.00), 0.40, 0.00, (0.20, 0.85, 1.00)),
    ("light_amber", (1.00, 0.80, 0.45), 0.40, 0.00, (1.00, 0.58, 0.18)),
    ("window_lit", (0.60, 0.55, 0.46), 0.20, 0.00, (0.52, 0.40, 0.26)),
]
TRIM_INDEX = {s[0]: i for i, s in enumerate(TRIM_SWATCHES)}


def trim_uv(name):
    """UV (u, v) of the centre of a swatch (v-up)."""
    i = TRIM_INDEX[name]
    r, c = divmod(i, TRIM_N)
    return ((c + 0.5) / TRIM_N, (r + 0.5) / TRIM_N)


def trim_palette():
    n = TRIM_SIZE
    s = n // TRIM_N
    alb = np.zeros((n, n, 3), F32)
    orm = np.zeros((n, n, 3), F32)
    emi = np.zeros((n, n, 3), F32)
    orm[..., 0] = 1.0
    orm[..., 1] = 0.6
    alb[:] = 0.5
    for i, (name, a, rough, metal, e) in enumerate(TRIM_SWATCHES):
        r, c = divmod(i, TRIM_N)
        sl = (slice(r * s, (r + 1) * s), slice(c * s, (c + 1) * s))
        alb[sl] = a
        orm[sl[0], sl[1], 1] = rough
        orm[sl[0], sl[1], 2] = metal
        if e is not None:
            emi[sl] = e
    return dict(albedo=alb, orm=orm, emissive=emi)


def rows_top_down(arr):
    """v-up -> image rows (row 0 = top), as expected by image writers."""
    return np.ascontiguousarray(arr[::-1])

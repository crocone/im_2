"""Street-kit procedural texture library (pure numpy - NO bpy import, so it can also be run standalone).

Used by build_city_ground.py / build_city_props.py.  Everything is deterministic (fixed numpy Generator seeds).

Conventions
  * All maps are float32 arrays (H, W, 3) with values 0..1, in "v-up" layout: row index j grows with texture v
    (i.e. row 0 = bottom of the picture).  `to_image_rows()` flips them for `image_from_array` (row 0 = top).
  * Colours are written as sRGB byte values / 255 (what a designer would type), exactly what ends up in the PNG.
  * ORM maps: R = ambient occlusion, G = roughness, B = metallic (glTF packing).
  * Normal maps are OpenGL style (+Y up), tangent space.
"""
import math
import struct
import zlib

import numpy as np

F32 = np.float32


# ----------------------------------------------------------------------------------------------------
# small maths helpers
# ----------------------------------------------------------------------------------------------------
def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def _quintic(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def value_noise(h, w, cy, cx, rng):
    """Periodic (tileable) smooth value noise in 0..1 with a cy x cx lattice."""
    lat = rng.random((cy, cx)).astype(F32)
    ys = (np.arange(h, dtype=np.float64) + 0.5) * (cy / h)
    xs = (np.arange(w, dtype=np.float64) + 0.5) * (cx / w)
    y0 = np.floor(ys).astype(np.int64)
    x0 = np.floor(xs).astype(np.int64)
    ty = _quintic(ys - y0).astype(F32)
    tx = _quintic(xs - x0).astype(F32)
    y0m, y1m = y0 % cy, (y0 + 1) % cy
    x0m, x1m = x0 % cx, (x0 + 1) % cx
    a = lat[np.ix_(y0m, x0m)]
    b = lat[np.ix_(y0m, x1m)]
    c = lat[np.ix_(y1m, x0m)]
    d = lat[np.ix_(y1m, x1m)]
    top = a + (b - a) * tx[None, :]
    bot = c + (d - c) * tx[None, :]
    return top + (bot - top) * ty[:, None]


def fbm(h, w, size_m, feature_m, octaves, rng, gain=0.5, lac=2.0):
    """Periodic fractal noise (~0..1, mean 0.5).  `size_m` = (width_m, height_m) of the canvas, `feature_m` the
    wavelength of the first octave in metres, so the noise is roughly isotropic in WORLD space."""
    wm, hm = size_m
    total = np.zeros((h, w), F32)
    amp, norm, f = 1.0, 0.0, float(feature_m)
    for _ in range(octaves):
        cx = max(1, int(round(wm / f)))
        cy = max(1, int(round(hm / f)))
        total += amp * value_noise(h, w, cy, cx, rng)
        norm += amp
        amp *= gain
        f /= lac
    return total / norm


def contrast(n, k, mid=0.5):
    return np.clip((n - mid) * k + 0.5, 0.0, 1.0)


def blur_wrap(a, passes=1, axes=(0, 1)):
    """Cheap tileable blur ([1 2 1]/4 per pass and axis)."""
    a = a.astype(F32, copy=True)
    for _ in range(passes):
        for ax in axes:
            a = 0.25 * np.roll(a, 1, ax) + 0.5 * a + 0.25 * np.roll(a, -1, ax)
    return a


def blur_edge(a, passes=1):
    """Same as blur_wrap but clamps at the borders (for non-tileable maps)."""
    a = a.astype(F32, copy=True)
    for _ in range(passes):
        for ax in (0, 1):
            p = np.pad(a, [(1, 1) if i == ax else (0, 0) for i in range(a.ndim)], mode="edge")
            sl_lo = [slice(None)] * a.ndim
            sl_hi = [slice(None)] * a.ndim
            sl_lo[ax] = slice(0, -2)
            sl_hi[ax] = slice(2, None)
            sl_mid = [slice(None)] * a.ndim
            sl_mid[ax] = slice(1, -1)
            a = 0.25 * p[tuple(sl_lo)] + 0.5 * p[tuple(sl_mid)] + 0.25 * p[tuple(sl_hi)]
    return a


# ----------------------------------------------------------------------------------------------------
# Canvas: world-space (metres) <-> pixel helpers with analytic anti-aliased primitives
# ----------------------------------------------------------------------------------------------------
class Canvas:
    """A w x h pixel canvas covering [x0, x0+wm] x [y0, y0+hm] metres.  Row j <-> y (v-up)."""

    def __init__(self, w, h, wm, hm, x0=0.0, y0=0.0):
        self.w, self.h, self.wm, self.hm, self.x0, self.y0 = w, h, float(wm), float(hm), float(x0), float(y0)
        self.px = w / self.wm            # pixels per metre (x)
        self.py = h / self.hm            # pixels per metre (y)
        self.xs = (self.x0 + (np.arange(w) + 0.5) / self.px).astype(F32)
        self.ys = (self.y0 + (np.arange(h) + 0.5) / self.py).astype(F32)
        self.X = self.xs[None, :]
        self.Y = self.ys[:, None]
        self.size = (self.wm, self.hm)

    def zeros(self):
        return np.zeros((self.h, self.w), F32)

    def window(self, xmin, xmax, ymin, ymax, pad=2):
        i0 = max(0, int(math.floor((xmin - self.x0) * self.px)) - pad)
        i1 = min(self.w, int(math.ceil((xmax - self.x0) * self.px)) + pad)
        j0 = max(0, int(math.floor((ymin - self.y0) * self.py)) - pad)
        j1 = min(self.h, int(math.ceil((ymax - self.y0) * self.py)) + pad)
        return i0, i1, j0, j1

    def _pw(self):
        return max(1.0 / self.px, 1.0 / self.py)

    # -- primitives ---------------------------------------------------------------------------------
    def rect(self, layer, x0, x1, y0, y1, value=1.0, op="max"):
        """Axis aligned rectangle with exact area-coverage anti-aliasing."""
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        i0, i1, j0, j1 = self.window(x0, x1, y0, y1, pad=1)
        if i1 <= i0 or j1 <= j0:
            return
        ex = self.x0 + np.arange(i0, i1) / self.px
        ey = self.y0 + np.arange(j0, j1) / self.py
        cx = np.clip(np.minimum(x1, ex + 1.0 / self.px) - np.maximum(x0, ex), 0.0, None) * self.px
        cy = np.clip(np.minimum(y1, ey + 1.0 / self.py) - np.maximum(y0, ey), 0.0, None) * self.py
        cov = (cy[:, None] * cx[None, :]).astype(F32)
        self._apply(layer, j0, j1, i0, i1, cov, value, op)

    @staticmethod
    def _apply(layer, j0, j1, i0, i1, cov, value, op):
        sub = layer[j0:j1, i0:i1]
        if op == "max":
            np.maximum(sub, cov * value, out=sub)
        elif op == "add":
            sub += cov * value
        elif op == "set":
            sub[:] = sub * (1.0 - cov) + value * cov
        elif op == "mul":
            sub *= 1.0 - cov * (1.0 - value)
        else:
            raise ValueError(op)

    def disc(self, layer, cx, cy, r, value=1.0, op="max", ring=None):
        """Disc (or ring: pass ring=(r_inner, r_outer))."""
        rr = r if ring is None else ring[1]
        i0, i1, j0, j1 = self.window(cx - rr, cx + rr, cy - rr, cy + rr)
        if i1 <= i0 or j1 <= j0:
            return
        X = self.xs[i0:i1][None, :]
        Y = self.ys[j0:j1][:, None]
        d = np.hypot(X - cx, Y - cy)
        pw = self._pw()
        if ring is None:
            cov = np.clip(0.5 + (r - d) / pw, 0.0, 1.0)
        else:
            cov = np.clip(0.5 + (ring[1] - d) / pw, 0.0, 1.0) * np.clip(0.5 + (d - ring[0]) / pw, 0.0, 1.0)
        self._apply(layer, j0, j1, i0, i1, cov.astype(F32), value, op)

    def capsule(self, layer, x0, y0, x1, y1, width, value=1.0, op="max"):
        r = width / 2.0
        i0, i1, j0, j1 = self.window(min(x0, x1) - r, max(x0, x1) + r, min(y0, y1) - r, max(y0, y1) + r)
        if i1 <= i0 or j1 <= j0:
            return
        X = self.xs[i0:i1][None, :]
        Y = self.ys[j0:j1][:, None]
        dx, dy = x1 - x0, y1 - y0
        l2 = dx * dx + dy * dy
        if l2 > 0:
            t = np.clip(((X - x0) * dx + (Y - y0) * dy) / l2, 0.0, 1.0)
        else:
            t = 0.0
        d = np.hypot(X - (x0 + t * dx), Y - (y0 + t * dy))
        cov = np.clip(0.5 + (r - d) / self._pw(), 0.0, 1.0).astype(F32)
        self._apply(layer, j0, j1, i0, i1, cov, value, op)

    def polyline(self, layer, pts, width, value=1.0, op="max"):
        for (a, b) in zip(pts[:-1], pts[1:]):
            self.capsule(layer, a[0], a[1], b[0], b[1], width, value, op)

    def blob(self, layer, cx, cy, rx, ry, noise, amount=0.6, value=1.0, op="max", edge=0.35, wrap=False):
        """Irregular soft blob (stains / oil): elliptical falloff distorted by the `noise` field (canvas sized).
        wrap=True draws the periodic copies as well so blobs crossing the edge stay seamless in tileable textures."""
        if wrap:
            for ox in (-self.wm, 0.0, self.wm):
                for oy in (-self.hm, 0.0, self.hm):
                    self._blob(layer, cx + ox, cy + oy, rx, ry, noise, amount, value, op, edge)
            return
        self._blob(layer, cx, cy, rx, ry, noise, amount, value, op, edge)

    def _blob(self, layer, cx, cy, rx, ry, noise, amount=0.6, value=1.0, op="max", edge=0.35):
        i0, i1, j0, j1 = self.window(cx - rx * 1.6, cx + rx * 1.6, cy - ry * 1.6, cy + ry * 1.6)
        if i1 <= i0 or j1 <= j0:
            return
        X = self.xs[i0:i1][None, :]
        Y = self.ys[j0:j1][:, None]
        d = np.sqrt(((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2)
        d = d + (noise[j0:j1, i0:i1] - 0.5) * amount * 2.0
        cov = smoothstep(1.0, 1.0 - edge, d).astype(F32)
        self._apply(layer, j0, j1, i0, i1, cov, value, op)


# ----------------------------------------------------------------------------------------------------
# periodic helpers for paving joints
# ----------------------------------------------------------------------------------------------------
def joint_1d(coords, pitch, width, px, offset=0.0):
    """Anti-aliased line mask (0..1) along one axis for joints every `pitch` metres, `width` metres wide."""
    u = np.mod(coords - offset + pitch * 0.5, pitch) - pitch * 0.5      # signed distance to the nearest joint
    d = np.abs(u)
    return np.clip(0.5 + (width * 0.5 - d) * px, 0.0, 1.0).astype(F32)


def cell_ids(coords, pitch, offset=0.0):
    return np.floor((coords - offset) / pitch).astype(np.int64)


def frac_in_cell(coords, pitch, offset=0.0):
    return (np.mod(coords - offset, pitch) / pitch).astype(F32)


# ----------------------------------------------------------------------------------------------------
# normal maps / packing / PNG
# ----------------------------------------------------------------------------------------------------
def normal_from_height(hgt, px, py, strength=1.0, wrap=True):
    """hgt in metres (v-up rows).  Returns RGB (0..1) OpenGL tangent-space normal map."""
    if wrap:
        dx = (np.roll(hgt, -1, 1) - np.roll(hgt, 1, 1)) * (0.5 * px)
        dy = (np.roll(hgt, -1, 0) - np.roll(hgt, 1, 0)) * (0.5 * py)
    else:
        p = np.pad(hgt, 1, mode="edge")
        dx = (p[1:-1, 2:] - p[1:-1, :-2]) * (0.5 * px)
        dy = (p[2:, 1:-1] - p[:-2, 1:-1]) * (0.5 * py)
    nx, ny = -dx * strength, -dy * strength
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + 1.0)
    out = np.stack([nx * inv, ny * inv, inv], axis=-1)
    return (out * 0.5 + 0.5).astype(F32)


def downsample2(a):
    """2x2 box filter (H, W, C) -> (H/2, W/2, C)."""
    h, w = a.shape[:2]
    return (a[0:h:2, 0:w:2] + a[1:h:2, 0:w:2] + a[0:h:2, 1:w:2] + a[1:h:2, 1:w:2]) * 0.25


def pack_orm(ao, rough, metal=None):
    if metal is None:
        metal = np.zeros_like(ao)
    return np.stack([ao, rough, metal], axis=-1).astype(F32)


def to_image_rows(arr):
    """v-up (row 0 = v 0) -> picture rows (row 0 = top) as expected by common.image_from_array."""
    return np.ascontiguousarray(arr[::-1])


def to_bytes(arr):
    return np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _paeth(a, b, c):
    p = a.astype(np.int16) + b.astype(np.int16) - c.astype(np.int16)
    pa, pb, pc = np.abs(p - a), np.abs(p - b), np.abs(p - c)
    return np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c)).astype(np.uint8)


def encode_png(rgb_u8, level=9):
    """Deterministic PNG encoder with per-row adaptive filtering (much smaller than Blender's default writer)."""
    h, w, c = rgb_u8.shape
    assert c in (3, 4)
    raw = np.ascontiguousarray(rgb_u8).reshape(h, w * c)
    left = np.zeros_like(raw)
    left[:, c:] = raw[:, :-c]
    up = np.zeros_like(raw)
    up[1:] = raw[:-1]
    ul = np.zeros_like(raw)
    ul[1:, c:] = raw[:-1, :-c]
    cand = [
        raw,
        (raw - left).astype(np.uint8),
        (raw - up).astype(np.uint8),
        (raw - ((left.astype(np.uint16) + up.astype(np.uint16)) // 2).astype(np.uint8)).astype(np.uint8),
        (raw - _paeth(left, up, ul)).astype(np.uint8),
    ]
    scores = np.stack([np.abs(x.view(np.int8).astype(np.int32)).sum(axis=1) for x in cand], axis=0)
    best = scores.argmin(axis=0)
    out = np.empty((h, w * c + 1), np.uint8)
    for k in range(5):
        rows = best == k
        if rows.any():
            out[rows, 0] = k
            out[rows, 1:] = cand[k][rows]

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2 if c == 3 else 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(out.tobytes(), level))
            + chunk(b"IEND", b""))


def save_png(path, arr_vup, level=9):
    """Save a v-up float image (H,W,3|4) as PNG (picture rows top-first)."""
    data = encode_png(to_bytes(to_image_rows(arr_vup)), level)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


# ----------------------------------------------------------------------------------------------------
# shared colours (sRGB byte values / 255)
# ----------------------------------------------------------------------------------------------------
ASPHALT = np.array([0.208, 0.215, 0.232], F32)
ASPHALT_NEW = np.array([0.120, 0.125, 0.138], F32)
CONCRETE_GUTTER = np.array([0.43, 0.42, 0.40], F32)
PAINT_W = np.array([0.88, 0.87, 0.82], F32)
PAINT_Y = np.array([0.95, 0.76, 0.17], F32)
SIDEWALK = np.array([0.548, 0.538, 0.515], F32)
PLAZA = np.array([0.602, 0.592, 0.568], F32)
PLAZA_DARK = np.array([0.575, 0.570, 0.555], F32)


def _mix(a, b, t):
    """Mix colour a (…,3) towards colour b using mask t (H,W)."""
    return a + (b - a) * t[..., None]


def noisy_rect(cv, x0, x1, y0, y1, noise, amt=0.07, edge_w=0.03):
    """Rectangle with irregular (noise distorted) borders.  Returns (window, inside_mask, edge_mask)."""
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    hx, hy = (x1 - x0) / 2.0, (y1 - y0) / 2.0
    i0, i1, j0, j1 = cv.window(x0 - 0.35, x1 + 0.35, y0 - 0.35, y1 + 0.35)
    X = cv.xs[i0:i1][None, :]
    Y = cv.ys[j0:j1][:, None]
    sd = np.maximum(np.abs(X - cx) - hx, np.abs(Y - cy) - hy) + (noise[j0:j1, i0:i1] - 0.5) * amt
    pw = cv._pw()
    inside = np.clip(0.5 - sd / pw, 0.0, 1.0).astype(F32)
    edge = np.clip(0.5 - (np.abs(sd) - edge_w / 2.0) / pw, 0.0, 1.0).astype(F32)
    return (j0, j1, i0, i1), inside, edge


def add_patches(cv, rng, patches, tone, edge_layer, mask_layer, noise):
    """patches: (x0, x1, y0, y1, tone) -> tone_layer (multiplicative offset), edge_layer, mask_layer."""
    for (x0, x1, y0, y1, t) in patches:
        (j0, j1, i0, i1), inside, edge = noisy_rect(cv, x0, x1, y0, y1, noise, 0.08, 0.035)
        sl = (slice(j0, j1), slice(i0, i1))
        mask_layer[sl] = np.maximum(mask_layer[sl], inside)
        tone[sl] = tone[sl] * (1.0 - inside) + (t - 1.0) * inside
        edge_layer[sl] = np.maximum(edge_layer[sl], edge)


# ----------------------------------------------------------------------------------------------------
# ASPHALT common machinery
# ----------------------------------------------------------------------------------------------------
def _crack_points(rng, x, y, heading, length, step=0.45, wobble=0.35, drift=0.05):
    pts = [(x, y)]
    n = max(2, int(length / step))
    for _ in range(n):
        heading += rng.normal(0.0, wobble) * 0.5 + rng.normal(0.0, drift)
        x += math.cos(heading) * step
        y += math.sin(heading) * step
        pts.append((x, y))
    return pts


def _asphalt_base(cv, rng):
    """Luminance multiplier field + roughness noise + speckle for a fresh asphalt surface."""
    h, w, size = cv.h, cv.w, cv.size
    n1 = fbm(h, w, size, 10.0, 3, rng)
    n2 = fbm(h, w, size, 1.9, 3, rng)
    n3 = fbm(h, w, size, 0.32, 3, rng)
    lum = 1.0 + 0.34 * (n1 - 0.5) + 0.26 * (n2 - 0.5) + 0.20 * (n3 - 0.5)
    speck = rng.random((h, w)).astype(F32)
    lum = lum + (speck > 0.986) * 0.16 - (speck < 0.010) * 0.10
    return lum.astype(F32), n2, n3


def _paint_wear(cv, rng, near_track):
    """Paint alpha multiplier (0 = paint fully worn away) - chips, scuffs and wheel abrasion."""
    h, w, size = cv.h, cv.w, cv.size
    a = fbm(h, w, size, 1.3, 4, rng)
    b = fbm(h, w, size, 0.22, 3, rng)
    wear = smoothstep(0.55, 0.85, a * 0.7 + b * 0.3) * (0.45 + 0.55 * near_track)
    chips = smoothstep(0.72, 0.90, b)
    return np.clip(1.0 - 0.62 * wear - 0.22 * chips, 0.10, 1.0).astype(F32)


# ----------------------------------------------------------------------------------------------------
# ROAD STRAIGHT   (20 m wide x 80 m long tile, texture = HALF tile, mirrored about the middle)
# ----------------------------------------------------------------------------------------------------
ROAD_LANES = (-5.625, -1.875, 1.875, 5.625)      # travel-lane centres (4 x 3.75 m), parking lanes 2.5 m either side
ROAD_MANHOLES = ((-5.62, 23.0), (3.40, 6.0))      # (x, |z|) - real geometry is placed at +-z by the builder
ROAD_GRATES = ((-9.72, 18.0), (9.72, 18.0))       # storm drain grates in the gutter, (x, |z|)


def make_road_straight(seed=71011, size=1024):
    rng = np.random.default_rng(seed)
    cv = Canvas(size, size, 20.0, 40.0, -10.0, 0.0)      # y = d = distance from the tile END towards the middle
    X, Y = cv.X, cv.Y
    h, w = cv.h, cv.w
    lum, n2, n3 = _asphalt_base(cv, rng)

    # ---- wheel tracks ------------------------------------------------------------------------------------
    tracks = cv.zeros()
    lane_mod = fbm(h, w, cv.size, 6.0, 3, rng)
    for lc in ROAD_LANES:
        for off in (-0.82, 0.82):
            tracks = np.maximum(tracks, np.exp(-((X - (lc + off)) ** 2) / (2 * 0.17 ** 2)).astype(F32))
    tracks = tracks * (0.45 + 0.75 * lane_mod)
    tracks *= 1.0 + 0.6 * smoothstep(10.0, 0.0, Y)
    tracks = np.clip(tracks, 0, 1)
    centre_dust = cv.zeros()
    for lc in ROAD_LANES:
        centre_dust = np.maximum(centre_dust, np.exp(-((X - lc) ** 2) / (2 * 0.22 ** 2)).astype(F32))
    parking = np.exp(-((np.abs(X) - 8.75) ** 2) / (2 * 0.7 ** 2)).astype(F32)     # parking lanes

    # ---- repair patches / trenches -----------------------------------------------------------------------
    patch = cv.zeros()
    patch_tone = cv.zeros()
    patch_edge = cv.zeros()
    patch_noise = fbm(h, w, cv.size, 0.55, 3, rng)
    add_patches(cv, rng, [
        (-9.3, -2.6, 14.05, 14.85, 0.86),      # utility trench across left lanes
        (-7.15, -4.25, 5.0, 9.6, 0.84),
        (1.5, 5.6, 21.5, 28.6, 1.10),
        (-3.6, -0.5, 26.0, 31.0, 0.86),
        (0.4, 9.4, 33.55, 34.35, 0.86),        # trench right side
        (5.7, 7.0, 9.8, 11.9, 0.82),
        (-2.6, 0.9, 36.2, 38.8, 1.08),
    ], patch_tone, patch_edge, patch, patch_noise)

    # ---- cracks -------------------------------------------------------------------------------------------
    cracks = cv.zeros()
    for _ in range(7):
        x = rng.uniform(-8.8, 8.8)
        y = rng.uniform(1.0, 30.0)
        pts = _crack_points(rng, x, y, math.pi / 2 + rng.normal(0, 0.06), rng.uniform(3.0, 9.0), wobble=0.22, drift=0.03)
        cv.polyline(cracks, pts, rng.uniform(0.018, 0.034))
        if rng.random() < 0.5:      # a branch
            k = rng.integers(2, len(pts) - 1)
            bp = _crack_points(rng, pts[k][0], pts[k][1], math.pi / 2 + rng.choice([-1, 1]) * rng.uniform(0.5, 1.1),
                               rng.uniform(0.8, 2.2), wobble=0.5)
            cv.polyline(cracks, bp, 0.016)
    for _ in range(4):
        x = rng.uniform(-8.5, 5.0)
        y = rng.uniform(2.0, 38.0)
        pts = _crack_points(rng, x, y, rng.normal(0, 0.12), rng.uniform(1.2, 3.8), wobble=0.5)
        cv.polyline(cracks, pts, rng.uniform(0.016, 0.028))

    # ---- oil stains (parking lanes + a few in traffic lanes) ---------------------------------------------
    oil = cv.zeros()
    big = fbm(h, w, cv.size, 0.9, 3, rng)
    for sgn in (-1, 1):
        for _ in range(4):
            cv.blob(oil, sgn * rng.uniform(8.3, 9.2), rng.uniform(2.0, 38.0), rng.uniform(0.25, 0.5), rng.uniform(0.35, 0.7),
                    big, 0.45, rng.uniform(0.5, 0.9))
    for _ in range(4):
        cv.blob(oil, rng.uniform(-7, 7), rng.uniform(1.0, 38.0), rng.uniform(0.2, 0.4), rng.uniform(0.3, 0.6), big, 0.5,
                rng.uniform(0.3, 0.6))

    # ---- braking streaks near the tile ends --------------------------------------------------------------
    streak = cv.zeros()
    for lc in ROAD_LANES:
        for off in (-0.82, 0.82):
            for _ in range(2):
                xo = lc + off + rng.normal(0, 0.05)
                y0 = rng.uniform(0.3, 2.0)
                cv.capsule(streak, xo, y0, xo + rng.normal(0, 0.04), y0 + rng.uniform(3.0, 8.0), rng.uniform(0.05, 0.09),
                           rng.uniform(0.3, 0.7))

    # ---- gutter pans (concrete strips along both kerbs) ---------------------------------------------------
    gutter = np.clip(0.5 + (np.abs(X) - 9.55) * cv.px, 0.0, 1.0) * np.ones_like(Y)
    gutter = gutter.astype(F32)
    g_joint = np.maximum(joint_1d(Y, 2.5, 0.03, cv.py, 0.6), np.exp(-((np.abs(X) - 9.55) ** 2) / (2 * 0.02 ** 2)).astype(F32))
    g_dirt = fbm(h, w, cv.size, 0.8, 3, rng)

    # ---- markings -------------------------------------------------------------------------------------------
    paint_w = cv.zeros()
    paint_y = cv.zeros()
    for xe in (-7.5, 7.5):                               # solid edge lines
        cv.rect(paint_w, xe - 0.11, xe + 0.11, 0.0, 40.0)
    for xl in (-3.75, 3.75):                             # dashed lane lines (period 10 m: gap 3 / dash 4 / gap 3)
        for k in range(4):
            cv.rect(paint_w, xl - 0.11, xl + 0.11, 3.0 + 10 * k, 7.0 + 10 * k)
    for k in range(4):                                   # dashed yellow centre line
        cv.rect(paint_y, -0.13, 0.13, 3.0 + 10 * k, 7.0 + 10 * k)
    near_track = np.clip(tracks + 0.15, 0, 1)
    wear = _paint_wear(cv, rng, near_track)
    paint_w *= wear
    paint_y *= wear

    # ---- drains & manholes (dirt / dark openings baked, real geometry added by the builder) --------------
    dark_hole = cv.zeros()
    halo = cv.zeros()
    for (gx, gz) in ROAD_GRATES:
        d = 40.0 - gz
        cv.rect(dark_hole, gx - 0.21, gx + 0.21, d - 0.38, d + 0.38)
        cv.blob(halo, gx * 0.97, d, 0.75, 1.3, big, 0.3, 0.7)
    manhole_dirt = cv.zeros()
    for (mx, mz) in ROAD_MANHOLES:
        d = 40.0 - mz
        cv.disc(manhole_dirt, mx, d, 0.42, 0.0, "set")      # keep painted-over centre clean
        cv.blob(halo, mx, d, 0.85, 0.85, big, 0.25, 0.55)

    # ---- compose albedo ---------------------------------------------------------------------------------------
    alb = ASPHALT[None, None, :] * lum[..., None]
    dust = 0.05 * centre_dust
    alb = alb * (1.0 - 0.30 * tracks[..., None]) + dust[..., None]
    alb = alb * (1.0 - 0.34 * oil[..., None])
    alb = alb * (1.0 - 0.28 * halo[..., None])
    alb = alb * (1.0 - 0.45 * streak[..., None])
    alb = alb * (1.0 + patch_tone[..., None] * patch[..., None])
    alb = alb * (1.0 - 0.42 * patch_edge[..., None])
    alb = alb * (1.0 - 0.55 * np.clip(cracks, 0, 1)[..., None])
    alb = alb * (1.0 - 0.60 * dark_hole[..., None]) * (1.0 - 0.35 * dark_hole[..., None])
    gcol = CONCRETE_GUTTER[None, None, :] * (1.0 + 0.32 * (g_dirt[..., None] - 0.5)) * (1.0 - 0.45 * g_joint[..., None])
    alb = _mix(alb, gcol, gutter)
    alb = _mix(alb, PAINT_W[None, None, :] * (1.0 + 0.10 * (n3[..., None] - 0.5)), np.clip(paint_w * 0.94, 0, 1))
    alb = _mix(alb, PAINT_Y[None, None, :] * (1.0 + 0.10 * (n3[..., None] - 0.5)), np.clip(paint_y * 0.94, 0, 1))
    # slight vignette darkening of the very edges of the pavement near kerbs (dirt collects there)
    edge_dirt = smoothstep(9.0, 9.9, np.abs(X)).astype(F32) * (1.0 - gutter)
    alb = alb * (1.0 - 0.20 * edge_dirt[..., None])

    # ---- ORM ---------------------------------------------------------------------------------------------------
    rough = 0.88 + 0.10 * (n2 - 0.5) + 0.05 * (n3 - 0.5)
    rough = rough - 0.30 * tracks - 0.42 * np.clip(oil, 0, 1) - 0.06 * patch
    rough = rough + 0.06 * np.clip(cracks, 0, 1)
    rough = _mixs(rough, 0.84 + 0.06 * (g_dirt - 0.5), gutter)
    rough = _mixs(rough, 0.58 + 0.10 * (n3 - 0.5), np.clip(paint_w * 0.9, 0, 1))
    rough = _mixs(rough, 0.55 + 0.10 * (n3 - 0.5), np.clip(paint_y * 0.9, 0, 1))
    ao = 1.0 - 0.55 * np.clip(cracks, 0, 1) - 0.30 * g_joint * gutter - 0.5 * dark_hole - 0.10 * halo
    orm = pack_orm(np.clip(ao, 0, 1), np.clip(rough, 0.05, 1.0))
    return dict(albedo=np.clip(alb, 0, 1).astype(F32), orm=orm)


def _mixs(a, b, t):
    return a + (b - a) * t


# ----------------------------------------------------------------------------------------------------
# ROAD INTERSECTION  (20 x 20)
# ----------------------------------------------------------------------------------------------------
JUNCTION_MANHOLES = ((-3.2, 2.6), (4.6, -3.9))


def make_road_junction(seed=71021, size=1024):
    rng = np.random.default_rng(seed)
    cv = Canvas(size, size, 20.0, 20.0, -10.0, -10.0)
    X, Y = cv.X, cv.Y
    h, w = cv.h, cv.w
    lum, n2, n3 = _asphalt_base(cv, rng)
    big = fbm(h, w, cv.size, 0.9, 3, rng)

    # ---- markings of the approach from -Y (traffic runs +Y on the +X half), then rotated 4x -----------------
    side_w = cv.zeros()
    cv.rect(side_w, 0.15, 7.35, -10.0 + 0.20, -10.0 + 0.68)                    # stop line (approach half)
    for i in range(14):                                                          # zebra crossing (bars parallel to the traffic)
        cv.rect(side_w, -6.75 + i, -6.25 + i, -10.0 + 0.98, -10.0 + 3.10)
    paint_w = cv.zeros()
    for k in range(4):
        paint_w = np.maximum(paint_w, np.rot90(side_w, k))
    # guide dashes through the junction (short white ticks marking lane continuation) - keep it clean: none

    # ---- wheel tracks (plus shaped, fading towards the middle) ---------------------------------------------
    tracks = cv.zeros()
    for lc in ROAD_LANES:
        for off in (-0.82, 0.82):
            band = np.exp(-((X - (lc + off)) ** 2) / (2 * 0.17 ** 2)).astype(F32)
            tracks = np.maximum(tracks, band * smoothstep(3.5, 8.5, np.abs(Y)))
            band2 = np.exp(-((Y - (lc + off)) ** 2) / (2 * 0.17 ** 2)).astype(F32)
            tracks = np.maximum(tracks, band2 * smoothstep(3.5, 8.5, np.abs(X)))
    tracks = tracks * (0.5 + 0.7 * fbm(h, w, cv.size, 5.0, 3, rng))
    tracks = np.clip(tracks, 0, 1)

    # ---- turning skid arcs around the four corners -----------------------------------------------------------
    skid = cv.zeros()
    for cxn, cyn, a0 in ((10.0, 10.0, math.pi), (-10.0, 10.0, 1.5 * math.pi), (-10.0, -10.0, 0.0), (10.0, -10.0, 0.5 * math.pi)):
        for r, wd, amp in ((6.4, 0.16, 0.6), (7.1, 0.12, 0.45), (5.7, 0.10, 0.35)):
            steps = 26
            a_s = a0 + rng.uniform(0.05, 0.18)
            a_e = a0 + math.pi / 2 - rng.uniform(0.05, 0.18)
            pts = [(cxn + r * math.cos(a_s + (a_e - a_s) * t / steps), cyn + r * math.sin(a_s + (a_e - a_s) * t / steps))
                   for t in range(steps + 1)]
            cv.polyline(skid, pts, wd, amp)
    skid *= smoothstep(0.35, 0.65, fbm(h, w, cv.size, 1.1, 3, rng))

    # ---- patches, cracks, oil -----------------------------------------------------------------------------
    patch = cv.zeros()
    patch_tone = cv.zeros()
    patch_edge = cv.zeros()
    patch_noise = fbm(h, w, cv.size, 0.55, 3, rng)
    add_patches(cv, rng, [(-6.8, -3.2, -1.5, 2.3, 0.78), (2.5, 4.3, 3.0, 8.2, 0.74), (-2.0, 5.5, -7.6, -6.9, 0.80),
                          (-0.4, 0.5, 4.0, 8.0, 1.10), (5.5, 8.2, -2.5, -0.6, 1.08)], patch_tone, patch_edge, patch, patch_noise)
    cracks = cv.zeros()
    for _ in range(9):
        pts = _crack_points(rng, rng.uniform(-9, 9), rng.uniform(-9, 9), rng.uniform(0, 2 * math.pi), rng.uniform(2.0, 6.0),
                            wobble=0.45)
        cv.polyline(cracks, pts, rng.uniform(0.016, 0.03))
    oil = cv.zeros()
    for _ in range(9):
        cv.blob(oil, rng.uniform(-8.5, 8.5), rng.uniform(-8.5, 8.5), rng.uniform(0.25, 0.55), rng.uniform(0.3, 0.6), big, 0.45,
                rng.uniform(0.4, 0.85))
    # dirt in the four corners (where the kerb corner tiles join)
    corner = np.zeros((h, w), F32)
    for cxn in (-10.0, 10.0):
        for cyn in (-10.0, 10.0):
            corner = np.maximum(corner, np.exp(-np.hypot(X - cxn, Y - cyn) / 1.6).astype(F32))
    halo = cv.zeros()
    for (mx, my) in JUNCTION_MANHOLES:
        cv.blob(halo, mx, my, 0.9, 0.9, big, 0.25, 0.55)

    wear = _paint_wear(cv, rng, np.clip(tracks + 0.2, 0, 1))
    paint_w = paint_w * wear

    alb = ASPHALT[None, None, :] * lum[..., None]
    alb = alb * (1.0 - 0.30 * tracks[..., None])
    alb = alb * (1.0 - 0.34 * oil[..., None])
    alb = alb * (1.0 - 0.28 * halo[..., None])
    alb = alb * (1.0 - 0.40 * skid[..., None])
    alb = alb * (1.0 + patch_tone[..., None] * patch[..., None])
    alb = alb * (1.0 - 0.42 * patch_edge[..., None])
    alb = alb * (1.0 - 0.55 * np.clip(cracks, 0, 1)[..., None])
    alb = alb * (1.0 - 0.22 * corner[..., None])
    alb = _mix(alb, PAINT_W[None, None, :] * (1.0 + 0.10 * (n3[..., None] - 0.5)), np.clip(paint_w * 0.94, 0, 1))

    rough = 0.88 + 0.10 * (n2 - 0.5) + 0.05 * (n3 - 0.5)
    rough = rough - 0.30 * tracks - 0.42 * np.clip(oil, 0, 1) - 0.06 * patch - 0.12 * skid + 0.06 * np.clip(cracks, 0, 1)
    rough = _mixs(rough, 0.58 + 0.10 * (n3 - 0.5), np.clip(paint_w * 0.9, 0, 1))
    ao = 1.0 - 0.55 * np.clip(cracks, 0, 1) - 0.10 * halo - 0.12 * corner
    return dict(albedo=np.clip(alb, 0, 1).astype(F32), orm=pack_orm(np.clip(ao, 0, 1), np.clip(rough, 0.05, 1.0)),
                asphalt_mean=(ASPHALT * float(lum.mean())))


# ----------------------------------------------------------------------------------------------------
# SIDEWALK  (tileable 4 m x 8 m, 1 m x 1 m concrete flags)
# ----------------------------------------------------------------------------------------------------
def make_sidewalk(seed=71031, w=512, h=1024):
    rng = np.random.default_rng(seed)
    cv = Canvas(w, h, 4.0, 8.0, 0.0, 0.0)
    X, Y = cv.X, cv.Y
    size = cv.size
    jw = 0.022
    jx = joint_1d(cv.xs, 1.0, jw, cv.px)
    jy = joint_1d(cv.ys, 1.0, jw, cv.py)
    joint = np.maximum(jx[None, :], jy[:, None])
    # soft dirt haze along joints
    haze = np.maximum(joint_1d(cv.xs, 1.0, 0.11, cv.px)[None, :], joint_1d(cv.ys, 1.0, 0.11, cv.py)[:, None])
    haze = blur_wrap(haze, 2)

    fx = cell_ids(cv.xs, 1.0)
    fy = cell_ids(cv.ys, 1.0)
    tone = rng.random((8, 4)).astype(F32)
    tone_map = tone[np.ix_(fy % 8, fx % 4)]
    slope = (rng.random((8, 4, 2)).astype(F32) - 0.5)
    ux = frac_in_cell(cv.xs, 1.0)[None, :] - 0.5
    uy = frac_in_cell(cv.ys, 1.0)[:, None] - 0.5
    sx = slope[..., 0][np.ix_(fy % 8, fx % 4)]
    sy = slope[..., 1][np.ix_(fy % 8, fx % 4)]
    flag_shade = (tone_map - 0.5) * 0.10 + (ux * sx + uy * sy) * 0.06

    n1 = fbm(h, w, size, 3.0, 3, rng)
    n2 = fbm(h, w, size, 0.7, 3, rng)
    n3 = fbm(h, w, size, 0.16, 3, rng)
    speck = rng.random((h, w)).astype(F32)
    lum = 1.0 + flag_shade + 0.22 * (n1 - 0.5) + 0.16 * (n2 - 0.5) + 0.12 * (n3 - 0.5)
    lum = lum + (speck > 0.992) * 0.10 - (speck < 0.008) * 0.14

    stains = cv.zeros()
    big = fbm(h, w, size, 0.8, 3, rng)
    for _ in range(7):
        cv.blob(stains, rng.uniform(0.0, 4.0), rng.uniform(0.0, 8.0), rng.uniform(0.15, 0.4), rng.uniform(0.15, 0.4), big, 0.5,
                rng.uniform(0.3, 0.7), wrap=True)
    stains = np.maximum(stains, 0.0)
    # wrap stains that spill over the tile edge: keep them away from borders (drawn inside 0.3..3.7 above)

    cracks = cv.zeros()
    for _ in range(6):
        x = rng.uniform(0.4, 3.6)
        y = rng.uniform(0.4, 7.4)
        pts = _crack_points(rng, x, y, rng.uniform(0, 2 * math.pi), rng.uniform(0.35, 0.9), step=0.12, wobble=0.9, drift=0.2)
        pts = [(min(max(p[0], 0.15), 3.85), min(max(p[1], 0.15), 7.85)) for p in pts]
        cv.polyline(cracks, pts, rng.uniform(0.006, 0.011))

    gum = cv.zeros()
    for _ in range(9):
        cv.disc(gum, rng.uniform(0.2, 3.8), rng.uniform(0.2, 7.8), rng.uniform(0.008, 0.016), rng.uniform(0.5, 1.0))

    alb = SIDEWALK[None, None, :] * lum[..., None]
    alb = alb * (1.0 - 0.14 * stains[..., None]) * (1.0 - 0.10 * haze[..., None])
    alb = alb * (1.0 - 0.45 * joint[..., None])
    alb = alb * (1.0 - 0.40 * np.clip(cracks, 0, 1)[..., None])
    alb = _mix(alb, np.array([0.30, 0.28, 0.26], F32)[None, None, :], np.clip(gum, 0, 1) * 0.8)

    # height (metres) -> normal map
    hgt = np.zeros((h, w), F32)
    hgt -= 0.0060 * blur_wrap(joint, 1)
    hgt -= 0.0035 * blur_wrap(np.clip(cracks, 0, 1), 1)
    hgt += 0.0007 * (n2 - 0.5) + 0.0004 * (n3 - 0.5) + 0.0010 * flag_shade
    normal = normal_from_height(hgt, cv.px, cv.py, 1.0)
    rough = 0.88 + 0.08 * (n2 - 0.5) + 0.06 * (n3 - 0.5) - 0.12 * stains
    rough = np.clip(rough, 0.3, 1.0)
    ao = 1.0 - 0.45 * joint - 0.15 * haze - 0.4 * np.clip(cracks, 0, 1)
    return dict(albedo=np.clip(alb, 0, 1).astype(F32), orm=pack_orm(np.clip(ao, 0, 1), rough), normal=normal)


# ----------------------------------------------------------------------------------------------------
# PLAZA  (tileable 7.2 m x 7.2 m, 1.8 m concrete slabs, a few darker granite slabs)
# ----------------------------------------------------------------------------------------------------
def make_plaza(seed=71041, size=1024):
    rng = np.random.default_rng(seed)
    P = 7.2
    cv = Canvas(size, size, P, P, 0.0, 0.0)
    X, Y = cv.X, cv.Y
    h, w = cv.h, cv.w
    slab = 1.8
    jw = 0.028
    jx = joint_1d(cv.xs, slab, jw, cv.px)
    jy = joint_1d(cv.ys, slab, jw, cv.py)
    joint = np.maximum(jx[None, :], jy[:, None])
    # finer saw-cut lines every 0.9 m inside each slab (very light)
    cutx = joint_1d(cv.xs, 0.9, 0.008, cv.px, 0.0)
    cuty = joint_1d(cv.ys, 0.9, 0.008, cv.py, 0.0)
    cut = np.maximum(cutx[None, :], cuty[:, None]) * (1.0 - joint)
    haze = blur_wrap(np.maximum(joint_1d(cv.xs, slab, 0.14, cv.px)[None, :], joint_1d(cv.ys, slab, 0.14, cv.py)[:, None]), 2)

    fx = cell_ids(cv.xs, slab)
    fy = cell_ids(cv.ys, slab)
    tone = rng.random((4, 4)).astype(F32)
    tone_map = tone[np.ix_(fy % 4, fx % 4)]
    slope = rng.random((4, 4, 2)).astype(F32) - 0.5
    ux = frac_in_cell(cv.xs, slab)[None, :] - 0.5
    uy = frac_in_cell(cv.ys, slab)[:, None] - 0.5
    sx = slope[..., 0][np.ix_(fy % 4, fx % 4)]
    sy = slope[..., 1][np.ix_(fy % 4, fx % 4)]
    flag_shade = (tone_map - 0.5) * 0.07 + (ux * sx + uy * sy) * 0.04
    # darker granite slabs in a regular rhythm (2 of 16)
    dark_slab = np.zeros((4, 4), F32)
    dark_slab[1, 1] = 1.0
    dark_slab[3, 3] = 1.0
    dark_map = dark_slab[np.ix_(fy % 4, fx % 4)]

    n1 = fbm(h, w, cv.size, 3.6, 3, rng)
    n2 = fbm(h, w, cv.size, 0.8, 3, rng)
    n3 = fbm(h, w, cv.size, 0.18, 3, rng)
    speck = rng.random((h, w)).astype(F32)
    lum = 1.0 + flag_shade + 0.20 * (n1 - 0.5) + 0.16 * (n2 - 0.5) + 0.12 * (n3 - 0.5)
    lum = lum + (speck > 0.993) * 0.10 - (speck < 0.007) * 0.12

    big = fbm(h, w, cv.size, 1.0, 3, rng)
    stains = cv.zeros()
    for _ in range(6):
        cv.blob(stains, rng.uniform(0.0, 7.2), rng.uniform(0.0, 7.2), rng.uniform(0.2, 0.5), rng.uniform(0.2, 0.5), big, 0.5,
                rng.uniform(0.25, 0.6), wrap=True)
    cracks = cv.zeros()
    for _ in range(4):
        pts = _crack_points(rng, rng.uniform(0.6, 6.6), rng.uniform(0.6, 6.6), rng.uniform(0, 2 * math.pi), rng.uniform(0.5, 1.2),
                            step=0.14, wobble=0.9, drift=0.2)
        pts = [(min(max(p[0], 0.3), 6.9), min(max(p[1], 0.3), 6.9)) for p in pts]
        cv.polyline(cracks, pts, rng.uniform(0.007, 0.012))
    moss = cv.zeros()
    mn = fbm(h, w, cv.size, 0.5, 3, rng)
    moss = joint * smoothstep(0.62, 0.8, mn) * 0.7

    base = _mix(PLAZA[None, None, :] * lum[..., None], PLAZA_DARK[None, None, :] * (0.965 + 0.5 * (lum[..., None] - 1.0)),
                dark_map * (1.0 - joint))
    alb = base * (1.0 - 0.13 * stains[..., None]) * (1.0 - 0.10 * haze[..., None])
    alb = alb * (1.0 - 0.10 * cut[..., None])
    alb = alb * (1.0 - 0.48 * joint[..., None])
    alb = alb * (1.0 - 0.40 * np.clip(cracks, 0, 1)[..., None])
    alb = _mix(alb, np.array([0.20, 0.26, 0.14], F32)[None, None, :], moss)

    hgt = np.zeros((h, w), F32)
    hgt -= 0.0070 * blur_wrap(joint, 1)
    hgt -= 0.0015 * blur_wrap(cut, 1)
    hgt -= 0.0035 * blur_wrap(np.clip(cracks, 0, 1), 1)
    hgt += 0.0008 * (n2 - 0.5) + 0.0004 * (n3 - 0.5) + 0.0010 * flag_shade
    normal = normal_from_height(hgt, cv.px, cv.py, 1.0)
    rough = 0.86 + 0.10 * (n2 - 0.5) + 0.06 * (n3 - 0.5) - 0.10 * stains - 0.10 * dark_map
    ao = 1.0 - 0.45 * joint - 0.12 * haze - 0.4 * np.clip(cracks, 0, 1) - 0.05 * cut
    return dict(albedo=np.clip(alb, 0, 1).astype(F32), orm=pack_orm(np.clip(ao, 0, 1), np.clip(rough, 0.3, 1.0)), normal=normal)


# ----------------------------------------------------------------------------------------------------
# SMALL PROP TEXTURES
# ----------------------------------------------------------------------------------------------------
def make_foliage(seed=71051, size=256):
    """Tileable dense low shrub / ground-cover albedo (1 m x 1 m)."""
    rng = np.random.default_rng(seed)
    n = fbm(size, size, (1.0, 1.0), 0.5, 4, rng)
    n2 = fbm(size, size, (1.0, 1.0), 0.12, 3, rng)
    spot = rng.random((size, size)).astype(F32)
    base = np.array([0.105, 0.230, 0.085], F32)
    hi = np.array([0.240, 0.420, 0.130], F32)
    t = smoothstep(0.35, 0.75, n * 0.7 + n2 * 0.5)
    alb = _mix(np.broadcast_to(base, (size, size, 3)).copy(), hi, t)
    alb = alb * (0.75 + 0.5 * n2[..., None])
    alb = _mix(alb, np.array([0.33, 0.50, 0.16], F32)[None, None, :], (spot > 0.985).astype(F32) * 0.7)
    alb = _mix(alb, np.array([0.05, 0.11, 0.05], F32)[None, None, :], (spot < 0.05).astype(F32) * 0.6)
    return dict(albedo=np.clip(alb, 0, 1).astype(F32))


def make_grass(seed=71081, size=512):
    """Tileable lawn albedo (4 m x 4 m): mown grass with lighter / darker patches and a few clover speckles."""
    rng = np.random.default_rng(seed)
    sz = (4.0, 4.0)
    n1 = fbm(size, size, sz, 1.6, 3, rng)
    n2 = fbm(size, size, sz, 0.35, 3, rng)
    n3 = fbm(size, size, sz, 0.08, 2, rng)
    spot = rng.random((size, size)).astype(F32)
    base = np.array([0.20, 0.34, 0.11], F32)
    hi = np.array([0.34, 0.50, 0.17], F32)
    t = smoothstep(0.30, 0.75, n1 * 0.55 + n2 * 0.45)
    alb = base[None, None, :] + (hi - base)[None, None, :] * t[..., None]
    alb = alb * (0.86 + 0.28 * n3[..., None])
    alb = _mix(alb, np.array([0.42, 0.55, 0.22], F32)[None, None, :], (spot > 0.992).astype(F32) * 0.6)
    alb = _mix(alb, np.array([0.10, 0.20, 0.07], F32)[None, None, :], (spot < 0.010).astype(F32) * 0.5)
    return dict(albedo=np.clip(alb, 0, 1).astype(F32))


def make_grunge(seed=71091, size=512):
    """Neutral weathering albedo (tileable 2 m x 2 m): mottling, vertical dirt streaks, specks and a few stains.  Values ~0.80-1.0 so it
    can be multiplied by a paint / concrete tint (glTF baseColorFactor)."""
    rng = np.random.default_rng(seed)
    sz = (2.0, 2.0)
    n1 = fbm(size, size, sz, 1.0, 3, rng)
    n2 = fbm(size, size, sz, 0.22, 3, rng)
    streak = value_noise(size, size, 2, 40, rng)                  # long vertical streaks (v is up, texture rows)
    streak = np.clip(streak + 0.5 * value_noise(size, size, 3, 90, rng) - 0.25, 0.0, 1.0)
    spot = rng.random((size, size)).astype(F32)
    v = 0.94 + 0.08 * (n1 - 0.5) + 0.06 * (n2 - 0.5) - 0.07 * smoothstep(0.55, 0.9, streak)
    v = v - 0.10 * (spot < 0.012) + 0.05 * (spot > 0.992)
    stains = smoothstep(0.62, 0.85, fbm(size, size, sz, 0.6, 3, rng))
    v = v - 0.06 * stains
    v = np.clip(v, 0.55, 1.0).astype(F32)
    return dict(albedo=np.repeat(v[..., None], 3, axis=2).astype(F32) * np.array([1.0, 0.995, 0.985], F32))


def make_wood(seed=71092, size=256):
    """Tileable timber slat albedo (grain runs along u): warm brown with dark grain lines and knots (1 m x 1 m)."""
    rng = np.random.default_rng(seed)
    n = fbm(size, size, (1.0, 1.0), 0.5, 3, rng)
    grain = value_noise(size, size, 40, 2, rng)                     # many thin lines along u
    fine = value_noise(size, size, 120, 3, rng)
    wave = 0.5 + 0.5 * np.sin((np.arange(size)[:, None] / size * 26.0 + n * 3.0) * 2 * math.pi)
    tone = 0.80 + 0.22 * (grain - 0.5) + 0.10 * (fine - 0.5) + 0.06 * (wave - 0.5)
    tone = np.clip(tone, 0.5, 1.0).astype(F32)
    base = np.array([0.66, 0.45, 0.28], F32)
    return dict(albedo=np.clip(base[None, None, :] * tone[..., None] * 1.15, 0, 1).astype(F32))


def make_stripes(seed=0, size=256):
    """Tileable diagonal red / white hazard stripes (albedo)."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    tri = np.mod((xx + yy) / size * 4.0, 1.0)         # 4 stripe pairs across the tile
    edge = 4.0 / size * 1.2
    red_amt = np.clip((tri - 0.5) / edge + 0.5, 0.0, 1.0) * np.clip((1.0 - tri) / edge + 0.5, 0.0, 1.0)
    red_amt = np.where(tri < 0.5, np.clip(tri / edge + 0.5 - 0.5 * 0, 0.0, 1.0) * 0 + 0, red_amt)
    red = np.array([0.80, 0.09, 0.07], F32)
    white = np.array([0.90, 0.88, 0.82], F32)
    alb = white[None, None, :] + (red - white)[None, None, :] * red_amt[..., None].astype(F32)
    return dict(albedo=alb.astype(F32))


def make_solar_cells(seed=71061, w=256, h=512):
    """Solar panel face: dark blue cells (6 x 10) with silver bus bars and a white grid; 1.0 m x 1.65 m."""
    rng = np.random.default_rng(seed)
    cv = Canvas(w, h, 1.0, 1.65, 0.0, 0.0)
    cols, rows = 6, 10
    cw, rh = 1.0 / cols, 1.65 / rows
    cx = cell_ids(cv.xs, cw)
    cy = cell_ids(cv.ys, rh)
    tone = rng.random((rows, cols)).astype(F32)
    tm = tone[np.ix_(np.clip(cy, 0, rows - 1), np.clip(cx, 0, cols - 1))]
    gx = joint_1d(cv.xs, cw, 0.006, cv.px)
    gy = joint_1d(cv.ys, rh, 0.006, cv.py)
    grid = np.maximum(gx[None, :], gy[:, None])
    bus = np.zeros((h, w), F32)
    for k in range(cols):
        for off in (-0.028, 0.0, 0.028):
            cv.rect(bus, (k + 0.5) * cw + off - 0.0012, (k + 0.5) * cw + off + 0.0012, 0.0, 1.65)
    fine = np.zeros((h, w), F32)
    fx = np.mod(cv.xs / 0.008, 1.0)
    fine += (np.abs(fx - 0.5) < 0.12)[None, :] * 0.03
    cell = np.array([0.045, 0.085, 0.20], F32)[None, None, :] * (0.85 + 0.35 * tm[..., None])
    cell = cell + fine[..., None] * 0.6
    cell = _mix(cell, np.array([0.55, 0.58, 0.62], F32)[None, None, :], np.clip(bus, 0, 1) * 0.55)
    cell = _mix(cell, np.array([0.70, 0.72, 0.76], F32)[None, None, :], grid * 0.85)
    return dict(albedo=np.clip(cell, 0, 1).astype(F32))


def make_plate(seed=71071, w=256, h=64):
    """Abstract licence plate (blocks that read as characters - no real text)."""
    rng = np.random.default_rng(seed)
    cv = Canvas(w, h, 0.52, 0.13, 0.0, 0.0)
    plate = np.ones((h, w, 3), F32) * np.array([0.90, 0.90, 0.86], F32)
    blue = cv.zeros()
    cv.rect(blue, 0.0, 0.05, 0.0, 0.13)
    chars = cv.zeros()
    x = 0.075
    for i in range(7):
        cw = 0.045
        if i == 3:
            cv.rect(chars, x + 0.004, x + 0.028, 0.055, 0.075)     # dash
            x += 0.034
            continue
        # a glyph made of 2-4 bars
        for _ in range(int(rng.integers(2, 5))):
            if rng.random() < 0.5:
                y0 = rng.uniform(0.02, 0.085)
                cv.rect(chars, x, x + cw * rng.uniform(0.6, 1.0), y0, y0 + 0.014)
            else:
                xx = x + rng.uniform(0.0, cw * 0.75)
                cv.rect(chars, xx, xx + 0.012, 0.02, 0.11)
        x += cw + 0.012
    plate = _mix(plate, np.array([0.05, 0.06, 0.08], F32)[None, None, :], np.clip(chars, 0, 1) * 0.92)
    plate = _mix(plate, np.array([0.10, 0.20, 0.55], F32)[None, None, :], blue)
    border = cv.zeros()
    cv.rect(border, 0.0, 0.52, 0.0, 0.008)
    cv.rect(border, 0.0, 0.52, 0.122, 0.13)
    cv.rect(border, 0.0, 0.008, 0.0, 0.13)
    cv.rect(border, 0.512, 0.52, 0.0, 0.13)
    plate = _mix(plate, np.array([0.05, 0.06, 0.08], F32)[None, None, :], border * 0.8)
    return dict(albedo=np.clip(plate, 0, 1).astype(F32))

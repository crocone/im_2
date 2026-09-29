"""fracture.py - procedural Voronoi / power-diagram fracture for bpy meshes (Blender 4.4, no add-ons needed).

Cell Fracture is not available in our Blender build, so this module implements the whole pipeline with bmesh:

  1. SOURCE   `part_from_objects()` turns authored objects (evaluated: bevels applied, WeightedNormal skipped) into one
              bmesh in the fracture-root space.  Material indices are remapped into a shared `MaterialTable`; a part
              may consist of several CLOSED components (e.g. a sign panel with embedded neon glyphs, a tank with
              rivets) - components that interpenetrate stay together in the same chunk (see step 4).
  2. SEEDS    deterministic seed points (numpy Generator with a fixed seed):
                * candidate samplers: `sample_volume` (inside a closed mesh, ray parity test), `sample_surface`
                  (area weighted on selected faces, optionally inset to the mid-surface of shells / slabs),
                  `seeds_along` (rods, masts, legs: points along an axis with lateral jitter -> angled breaks)
                * `pick_seeds`: density bias (`density_impact` near an impact point, `density_base` towards the base),
                  size mix (a few far-apart "big" seeds with power weights + many small ones, Poisson-disk spacing)
                * `lloyd_relax`: optional (partial) Lloyd relaxation with Monte-Carlo cell centroids.
  3. CELLS    every seed's cell is the source clipped by the power-bisector planes of all other seeds (nearest first):
              `bmesh.ops.bisect_plane(clear_outer=True)` + cap fill, so the mesh is CLOSED again after every single
              cut.  Caps are filled per SOLID component (labels taken before any cut, see `label_components`) with
              `triangle_fill` (scanfill: concave outlines and nested loops such as a tank's annulus), `holes_fill` as
              fallback, then coplanar cap triangles are dissolved back into n-gons.  Cut faces get the interior
              material, flat shading and sharp borders.  Planes that miss the (AABB of the) current cell are skipped;
              a cut that does not yield a closed 2-manifold is retried with a tiny deterministic plane perturbation.
  4. ISLANDS  a cell can fall apart (openings in walls, shells, multi-component parts): connected components are
              grouped again when they interpenetrate (BVH overlap), every group is a chunk candidate.  Cells whose main
              chunk is below `min_volume` or thinner than `min_thickness` (3V/A) remove their seed - the neighbours absorb
              the volume (only the affected cells are recomputed).  Small extra islands are MERGED into the chunk they
              touch (no holes in the reassembled object); only degenerate slivers are dropped (logged).
  5. CHUNKS   `make_chunk_objects()` numbers all chunks of all parts contiguously chunk_001..NNN, box-projects UVs on the
              cut faces, re-centres every chunk on its volume centroid (object origin = centroid) and adds a
              WeightedNormal modifier (applied by the glTF exporter) so the outer surface shades like the intact mesh
              (optional `edge_bevel` chamfers the cut borders).  `verify_chunk_objects()` checks closedness (no boundary
              / non-manifold edges), volume > 0, centroid at the origin and convexity (volume / convex-hull volume).

Minimal use (see build_destructibles.py for the full pipeline):

    mt = MaterialTable(); cap = mt.index(debris_material)
    bm = part_from_objects([obj], mt)                       # closed source mesh in root space
    rng = np.random.default_rng(1234)
    cands = sample_volume(bm, 2000, rng)                     # or sample_surface(..., inset=half_thickness)
    seeds, w = pick_seeds(cands, 20, rng, spacing, density=[density_impact(p, 1.0, 3.0)], big_frac=0.3)
    chunks = fracture_parts([dict(name="part", bm=bm, seeds=seeds, weights=w, min_volume=0.02)], cap)
    objs = make_chunk_objects(chunks, fractured_root, mt, cap)
    rows, ok = verify_chunk_objects(objs)

Everything is deterministic: seeded numpy generators, sorted iteration, no set-order dependence.  (Avoid
bmesh.ops.create_uvsphere in sources: its element order differs between Blender processes.)
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

EPS = 1e-4            # plane side classification / bisect snapping distance (metres)
WELD = 1e-5           # weld distance used when cleaning cells


def flog(*args):
    print("[FRACTURE]", *args, flush=True)


# ======================================================================================================================
# Materials + mesh extraction
# ======================================================================================================================
class MaterialTable:
    """Ordered material list shared by all parts of one fractured object (face.material_index -> mats[i])."""

    def __init__(self):
        self.mats = []

    def index(self, mat):
        for i, m in enumerate(self.mats):
            if m == mat:
                return i
        self.mats.append(mat)
        return len(self.mats) - 1


def _uv_layer(bm, create=True):
    lay = bm.loops.layers.uv.get("UVMap")
    if lay is None:
        lay = bm.loops.layers.uv.active
    if lay is None and create:
        lay = bm.loops.layers.uv.new("UVMap")
    return lay


def copy_faces(src, faces, dst=None, matrix=None, mat_remap=None):
    """Copy `faces` of bmesh `src` (verts, UVs, material, smooth flags, edge sharpness) into `dst` (new bmesh if None).
    Only these data layers are carried over, so stale custom-normal data can never leak into chunks."""
    if dst is None:
        dst = bmesh.new()
    suv = _uv_layer(src, create=False)
    duv = _uv_layer(dst)
    vmap = {}
    for f in faces:
        for v in f.verts:
            if v not in vmap:
                vmap[v] = dst.verts.new(v.co if matrix is None else matrix @ v.co)
    for f in faces:
        try:
            nf = dst.faces.new([vmap[v] for v in f.verts])
        except ValueError:
            continue
        mi = f.material_index
        nf.material_index = mat_remap[mi] if (mat_remap is not None and mi < len(mat_remap)) else mi
        nf.smooth = f.smooth
        if suv is not None:
            for ls, ld in zip(f.loops, nf.loops):
                ld[duv].uv = ls[suv].uv
    for f in faces:
        for e in f.edges:
            ne = dst.edges.get((vmap[e.verts[0]], vmap[e.verts[1]]))
            if ne is not None:
                ne.smooth = e.smooth
    return dst


def part_from_objects(objs, mtable, root_inv=None, triangulate_ngons=True):
    """Evaluated geometry of `objs` (all modifiers except WeightedNormal; bevel `harden_normals` off) merged into ONE
    bmesh in fracture-root space.  Material indices are remapped into `mtable`."""
    out = bmesh.new()
    _uv_layer(out)
    root_inv = root_inv or Matrix.Identity(4)
    for obj in objs:
        saved = []
        for m in obj.modifiers:
            if m.type == "WEIGHTED_NORMAL":
                saved.append((m, "show_viewport", m.show_viewport))
                m.show_viewport = False
            elif m.type == "BEVEL":
                saved.append((m, "harden_normals", m.harden_normals))
                m.harden_normals = False
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        tmp = bmesh.new()
        tmp.from_mesh(me)
        ev.to_mesh_clear()
        remap = [mtable.index(s.material) for s in obj.material_slots] or [0]
        copy_faces(tmp, list(tmp.faces), out, root_inv @ obj.matrix_world, remap)
        tmp.free()
        for m, attr, val in saved:
            setattr(m, attr, val)
    bpy.context.view_layer.update()
    if triangulate_ngons:
        ngons = [f for f in out.faces if len(f.verts) > 4]
        if ngons:
            bmesh.ops.triangulate(out, faces=ngons, quad_method="BEAUTY", ngon_method="BEAUTY")
    out.normal_update()
    return out


# ======================================================================================================================
# Small geometry utilities
# ======================================================================================================================
def aabb(bm):
    if not bm.verts:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))


def _support(lo, hi, co, no):
    """max over the AABB of (x - co) . no"""
    s = 0.0
    for k in range(3):
        s += max(no[k] * lo[k], no[k] * hi[k])
    return s - co.dot(no)


def mesh_stats(bm):
    """volume (signed), area, centroid (volume), triangle count, thickness (3V/A), aabb."""
    vol = 0.0
    cx = cy = cz = 0.0
    area = 0.0
    tris = 0
    for f in bm.faces:
        vs = [v.co for v in f.verts]
        tris += len(vs) - 2
        area += f.calc_area()
        a = vs[0]
        for i in range(1, len(vs) - 1):
            b, c = vs[i], vs[i + 1]
            v6 = a.dot(b.cross(c))
            vol += v6
            cx += v6 * (a.x + b.x + c.x)
            cy += v6 * (a.y + b.y + c.y)
            cz += v6 * (a.z + b.z + c.z)
    vol /= 6.0
    if abs(vol) > 1e-12:
        cen = Vector((cx, cy, cz)) / (24.0 * vol)
    else:
        lo, hi = aabb(bm)
        cen = (lo + hi) * 0.5
    lo, hi = aabb(bm)
    return dict(volume=vol, area=area, centroid=cen, tris=tris, thickness=(3.0 * vol / area if area > 0 else 0.0),
                lo=lo, hi=hi)


def topology_errors(bm):
    """(boundary_edges, non_manifold_edges)"""
    b = n = 0
    for e in bm.edges:
        k = len(e.link_faces)
        if k == 1:
            b += 1
        elif k != 2:
            n += 1
    return b, n


def hull_volume(bm):
    h = bmesh.new()
    for v in bm.verts:
        h.verts.new(v.co)
    if len(h.verts) < 4:
        h.free()
        return 0.0
    try:
        ret = bmesh.ops.convex_hull(h, input=list(h.verts), use_existing_faces=False)
        junk = []
        for g in ret["geom_interior"] + ret["geom_unused"]:
            if isinstance(g, bmesh.types.BMVert) and g not in junk:
                junk.append(g)
        if junk:
            bmesh.ops.delete(h, geom=junk, context="VERTS")
        vol = abs(h.calc_volume(signed=True))
    except Exception:
        vol = 0.0
    h.free()
    return vol


def _cleanup_loose(bm):
    wires = [e for e in bm.edges if not e.link_faces]
    if wires:
        bmesh.ops.delete(bm, geom=wires, context="EDGES")
    loose = [v for v in bm.verts if not v.link_edges]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")


# ======================================================================================================================
# Half-space clipping with capping
# ======================================================================================================================
class ClipFailure(Exception):
    pass


def classify(bm, co, no, eps=EPS):
    """'inside' (all verts on the kept side), 'empty' (all on the removed side) or 'cross'."""
    dmin, dmax = 1e30, -1e30
    for v in bm.verts:
        d = (v.co - co).dot(no)
        if d < dmin:
            dmin = d
        if d > dmax:
            dmax = d
    if not bm.verts or dmax <= eps:
        return "inside"
    if dmin >= -eps:
        return "empty"
    return "cross"


COMP_LAYER = "fr_comp"


def label_components(bm):
    """Store the id of the closed solid component every face belongs to in an int face layer.  The labels are taken
    BEFORE any cut and survive bisect (face data is copied to split faces) and bm.copy(), so the loops of one solid are
    always capped together - even when a cut removes the only surface connection between its outer and inner skin
    (e.g. the rim of a tank: the outer and the inner wall loops must form ONE annulus cap, not two overlapping discs)."""
    lay = bm.faces.layers.int.get(COMP_LAYER) or bm.faces.layers.int.new(COMP_LAYER)
    seen = set()
    cid = 0
    for f in bm.faces:
        if f in seen:
            continue
        cid += 1
        stack = [f]
        seen.add(f)
        while stack:
            g = stack.pop()
            g[lay] = cid
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
    return lay


def _edges_by_component(bm, edges, lay):
    """Group boundary edges by the (pre-cut) solid component label of their face."""
    groups = {}
    for e in edges:
        groups.setdefault(e.link_faces[0][lay], []).append(e)
    return [(cid, groups[cid]) for cid in sorted(groups)]


def clip_halfspace(bm, co, no, cap_mat, eps=EPS, cap_smooth=False):
    """Keep the part of the CLOSED mesh `bm` where (x - co) . no <= 0 and cap the cut so it stays closed.
    Cap faces get `cap_mat`.  Returns 'inside' (unchanged), 'empty' (nothing left) or 'cut'.  Raises ClipFailure when
    the result is not a closed 2-manifold (the caller retries with a perturbed plane).
    Caps are filled PER CONNECTED COMPONENT with triangle_fill (scanfill: concave outlines and nested loops such as a
    shell's annulus work), holes_fill is the fallback."""
    co = Vector(co)
    no = Vector(no).normalized()
    c = classify(bm, co, no, eps)
    if c != "cross":
        return c
    lay = bm.faces.layers.int.get(COMP_LAYER) or label_components(bm)
    b0, n0 = topology_errors(bm)
    bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces), dist=eps,
                           plane_co=co, plane_no=no, clear_outer=True, clear_inner=False)
    _cleanup_loose(bm)
    if not bm.faces:
        return "empty"
    bnd = [e for e in bm.edges if len(e.link_faces) == 1]
    caps = []
    if bnd:
        for cid, es in _edges_by_component(bm, bnd, lay):
            ret = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=es, normal=no)
            new = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMFace)]
            for f in new:
                f[lay] = cid
            caps += new
        left = [e for e in bm.edges if len(e.link_faces) == 1]
        if left:
            ret2 = bmesh.ops.holes_fill(bm, edges=left, sides=0)
            for f in ret2["faces"]:
                nb = [g for e in f.edges for g in e.link_faces if g is not f]
                f[lay] = nb[0][lay] if nb else 0
            caps += list(ret2["faces"])
    for f in caps:
        f.material_index = cap_mat
        f.smooth = cap_smooth
        f.normal_update()
        if f.normal.dot(no) < 0.0:
            f.normal_flip()
    b1, n1 = topology_errors(bm)
    if b1 > b0 or n1 > n0:
        raise ClipFailure(f"open={b1} nonmanifold={n1}")
    return "cut"


def dissolve_caps(bm, cap_mat, angle_deg=0.25):
    """Merge coplanar cap triangles back into n-gons and drop collinear helper verts on the caps."""
    cap_edges = [e for e in bm.edges if e.link_faces and all(f.material_index == cap_mat for f in e.link_faces)]
    cap_verts = [v for v in bm.verts if v.link_faces and all(f.material_index == cap_mat for f in v.link_faces)]
    if cap_edges or cap_verts:
        try:
            bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(angle_deg), use_dissolve_boundaries=False,
                                     verts=cap_verts, edges=cap_edges, delimit={"NORMAL"})
        except Exception as exc:     # pragma: no cover - defensive
            flog("dissolve_limit failed:", exc)


# ======================================================================================================================
# Power diagram cells
# ======================================================================================================================
def power_plane(pi, wi, pj, wj):
    """Bisector plane of seeds i, j with power weights (w = r^2).  Cell i keeps (x - co) . no <= 0."""
    d = pj - pi
    L = d.length
    n = d / L
    t = (L * L + wi - wj) / (2.0 * L)
    return pi + n * t, n


def _perturb(co, no, k):
    """Deterministic tiny perturbation of a plane for retry #k."""
    if k == 0:
        return co, no
    s = 1.7e-3 * k
    t = Vector((0.577 * s, -0.408 * s, 0.707 * s))
    n2 = (no + Vector((0.31, -0.23, 0.17)) * (0.004 * k)).normalized()
    return co + t, n2


def compute_cell(src, seeds, weights, i, others, cap_mat):
    """Clip a copy of `src` to the power cell of seed i (planes of the nearest seeds first).
    Returns (bmesh or None when the cell misses the part, used_seed_indices = planes that actually cut)."""
    bm = src.copy()
    used = []
    lo, hi = aabb(bm)
    order = sorted(others, key=lambda j: ((seeds[j] - seeds[i]).length_squared, j))
    for j in order:
        co, no = power_plane(seeds[i], weights[i], seeds[j], weights[j])
        if _support(lo, hi, co, no) <= EPS:
            continue                                   # plane misses the current cell (AABB test)
        c = classify(bm, co, no)
        if c == "inside":
            continue
        if c == "empty":
            used.append(j)
            bm.free()
            return None, used
        res = None
        for k in range(4):
            c2, n2 = _perturb(co, no, k)
            work = bm.copy()
            try:
                res = clip_halfspace(work, c2, n2, cap_mat)
            except ClipFailure:
                work.free()
                res = None
                continue
            bm.free()
            bm = work
            break
        if res is None:
            flog(f"  ! plane {i}|{j} could not be cut cleanly - skipped")
            continue
        used.append(j)
        if res == "empty":
            bm.free()
            return None, used
        lo, hi = aabb(bm)
    return bm, used


def split_groups(bm, overlap_tol=1e-3):
    """Split a cell into connected components and re-group components that interpenetrate (embedded details).
    Returns a list of new bmeshes (the input is not freed)."""
    faces = list(bm.faces)
    idx = {f: k for k, f in enumerate(faces)}
    comp = [-1] * len(faces)
    comps = []
    for k, f in enumerate(faces):
        if comp[k] >= 0:
            continue
        cid = len(comps)
        stack = [f]
        comp[k] = cid
        members = []
        while stack:
            g = stack.pop()
            members.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    hk = idx[h]
                    if comp[hk] < 0:
                        comp[hk] = cid
                        stack.append(h)
        members.sort(key=lambda x: idx[x])
        comps.append(members)
    if len(comps) == 1:
        return [copy_faces(bm, comps[0])]
    # AABBs + BVH per component
    boxes = []
    trees = []
    for members in comps:
        vs = {}
        polys = []
        for f in members:
            poly = []
            for v in f.verts:
                if v not in vs:
                    vs[v] = len(vs)
                poly.append(vs[v])
            polys.append(poly)
        coords = [v.co.copy() for v in vs]
        lo = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
        hi = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
        boxes.append((lo, hi))
        trees.append(BVHTree.FromPolygons(coords, polys, all_triangles=False, epsilon=0.0))
    parent = list(range(len(comps)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a in range(len(comps)):
        la, ha = boxes[a]
        for b in range(a + 1, len(comps)):
            lb, hb = boxes[b]
            if (la.x > hb.x + overlap_tol or lb.x > ha.x + overlap_tol or la.y > hb.y + overlap_tol or
                    lb.y > ha.y + overlap_tol or la.z > hb.z + overlap_tol or lb.z > ha.z + overlap_tol):
                continue
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            if trees[a].overlap(trees[b]):
                parent[max(ra, rb)] = min(ra, rb)
    groups = {}
    for c in range(len(comps)):
        groups.setdefault(find(c), []).append(c)
    out = []
    for r in sorted(groups):
        fs = []
        for c in groups[r]:
            fs.extend(comps[c])
        fs.sort(key=lambda x: idx[x])
        out.append(copy_faces(bm, fs))
    return out


def _finish_cell(bm, cap_mat):
    """Weld near-duplicate verts and merge coplanar cap triangles; each step is kept only if it does not make the
    mesh less closed."""
    b0, n0 = topology_errors(bm)
    for step in ("weld", "dissolve"):
        trial = bm.copy()
        if step == "weld":
            bmesh.ops.remove_doubles(trial, verts=list(trial.verts), dist=WELD)
        else:
            dissolve_caps(trial, cap_mat)
        _cleanup_loose(trial)
        b1, n1 = topology_errors(trial)
        if b1 <= b0 and n1 <= n0 and trial.faces:
            bm.clear()
            copy_faces(trial, list(trial.faces), bm)
        trial.free()
    return bm


def is_closed(bm):
    b, n = topology_errors(bm)
    return b == 0 and n == 0


# ======================================================================================================================
# Seeds
# ======================================================================================================================
def mesh_bvh(bm):
    return BVHTree.FromBMesh(bm, epsilon=0.0)


_RAY_DIRS = [Vector((0.5773, 0.5783, 0.5763)).normalized(), Vector((-0.6201, 0.2113, 0.7555)).normalized(),
             Vector((0.1234, -0.8765, 0.4652)).normalized()]


def inside_mesh(bvh, p, dirs=_RAY_DIRS, max_hits=64):
    """Ray-parity inside test (majority vote over 3 skewed directions) for closed meshes."""
    votes = 0
    for d in dirs:
        hits = 0
        o = Vector(p)
        for _ in range(max_hits):
            loc, nrm, idx, dist = bvh.ray_cast(o, d)
            if loc is None:
                break
            hits += 1
            o = loc + d * 1e-5
        votes += hits & 1
    return votes >= 2


def sample_volume(bm, n, rng, max_rounds=40):
    """~n uniformly distributed points inside the closed mesh `bm` (numpy array (n, 3))."""
    lo, hi = aabb(bm)
    bvh = mesh_bvh(bm)
    pts = []
    rounds = 0
    while len(pts) < n and rounds < max_rounds:
        rounds += 1
        cand = lo[:] + rng.random((max(64, n), 3)) * (np.array(hi[:]) - np.array(lo[:]))
        for c in cand:
            if inside_mesh(bvh, Vector(c)):
                pts.append(c)
                if len(pts) >= n:
                    break
    return np.array(pts, dtype=np.float64).reshape(-1, 3)


def sample_surface(bm, n, rng, face_filter=None, inset=0.0):
    """~n area-weighted random points on the faces of `bm` accepted by `face_filter(face)`, moved `inset` metres
    against the face normal (inset = half the wall thickness -> points on the mid-surface of a shell/slab).
    Returns (points (n,3), total_area)."""
    tris = []
    for f in bm.faces:
        if face_filter is not None and not face_filter(f):
            continue
        vs = [v.co.copy() for v in f.verts]
        nrm = f.normal.copy()
        for i in range(1, len(vs) - 1):
            a, b, c = vs[0], vs[i], vs[i + 1]
            ar = (b - a).cross(c - a).length * 0.5
            if ar > 1e-9:
                tris.append((a, b, c, nrm, ar))
    if not tris:
        return np.zeros((0, 3)), 0.0
    areas = np.array([t[4] for t in tris])
    total = float(areas.sum())
    cdf = np.cumsum(areas) / total
    pick = np.searchsorted(cdf, rng.random(n))
    r1 = rng.random(n)
    r2 = rng.random(n)
    pts = []
    for k in range(n):
        a, b, c, nrm, _ = tris[min(int(pick[k]), len(tris) - 1)]
        s = math.sqrt(r1[k])
        p = a * (1.0 - s) + b * (s * (1.0 - r2[k])) + c * (s * r2[k]) - nrm * inset
        pts.append(p[:])
    return np.array(pts, dtype=np.float64), total


def seeds_along(p0, p1, n, rng, lateral=0.3, jitter=0.18):
    """n seeds along the segment p0->p1 (rods, masts, legs, ladders) with lateral offsets so the bisector planes
    between neighbours are TILTED (angled breaks instead of flat slices)."""
    p0, p1 = Vector(p0), Vector(p1)
    ax = p1 - p0
    L = ax.length
    d = ax.normalized()
    ref = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))
    u = d.cross(ref).normalized()
    v = d.cross(u).normalized()
    out = []
    for k in range(n):
        t = (k + 0.5) / n + (rng.random() - 0.5) * 2.0 * jitter / n
        ang = rng.random() * 2.0 * math.pi
        off = (L / n) * lateral * (0.6 + 0.4 * rng.random())
        p = p0 + ax * t + (u * math.cos(ang) + v * math.sin(ang)) * off
        out.append(Vector(p))
    return out


def density_impact(point, radius, gain):
    """Density term: `gain` times more seeds around `point` (gaussian falloff, sigma = radius)."""
    c = np.array(point, dtype=np.float64)

    def f(P):
        d2 = ((P - c) ** 2).sum(axis=1)
        return gain * np.exp(-0.5 * d2 / (radius * radius))
    return f


def density_base(z0, z1, gain, axis=2):
    """Density term: up to `gain` extra density at z0, fading linearly to 0 at z1 (seeds denser towards the base)."""
    def f(P):
        t = np.clip((P[:, axis] - z0) / max(1e-6, (z1 - z0)), 0.0, 1.0)
        return gain * (1.0 - t) ** 2
    return f


def _density(P, terms):
    d = np.ones(len(P))
    for t in terms or ():
        d = d + t(P)
    return d


def pick_seeds(cands, n, rng, spacing, density=None, big_frac=0.25, big_weight=0.45, min_frac=0.55):
    """Pick n seeds from candidate points (numpy (M,3)).
    * n_big = round(n*big_frac) "big" seeds: greedy farthest-point sampling, preferring low-density areas, with power
      weight (big_weight*spacing)^2 so their cells grow -> a few LARGE chunks.
    * the rest are small seeds, accepted with probability ~ density (impact / base bias) and Poisson-disk spacing
      (>= min_frac*spacing to each other, >= 0.8*spacing to big seeds) -> many smaller chunks, clustered where the
      density is high.
    Returns (list[Vector], list[float] weights)."""
    M = len(cands)
    if M == 0 or n <= 0:
        return [], []
    dens = _density(cands, density)
    order = rng.permutation(M)
    n_big = int(round(n * big_frac)) if n >= 3 else 0
    chosen = []
    weights = []
    # --- big seeds: farthest point sampling scored by distance / sqrt(density)
    if n_big:
        inv = 1.0 / np.sqrt(dens)
        first = int(order[int(np.argmax(inv[order]))]) if big_frac > 0 else int(order[0])
        chosen.append(first)
        mind = np.sqrt(((cands - cands[first]) ** 2).sum(axis=1))
        while len(chosen) < n_big:
            score = mind * inv
            nxt = int(np.argmax(score))
            chosen.append(nxt)
            mind = np.minimum(mind, np.sqrt(((cands - cands[nxt]) ** 2).sum(axis=1)))
        weights = [(big_weight * spacing) ** 2] * len(chosen)
    # --- small seeds: density weighted Poisson disk
    small_min = min_frac * spacing
    big_excl = 0.8 * spacing
    dmax = float(dens.max())
    acc_rand = rng.random(M)
    rounds = 0
    while len(chosen) < n and rounds < 12:
        rounds += 1
        for k in order:
            if len(chosen) >= n:
                break
            k = int(k)
            if k in chosen:
                continue
            if acc_rand[k] > dens[k] / dmax:
                continue
            p = cands[k]
            ok = True
            for c_i, c in enumerate(chosen):
                lim = big_excl if c_i < n_big else small_min
                if ((cands[c] - p) ** 2).sum() < lim * lim:
                    ok = False
                    break
            if ok:
                chosen.append(k)
                weights.append(0.0)
        small_min *= 0.85
        big_excl *= 0.85
        acc_rand = np.minimum(acc_rand, rng.random(M))
    return [Vector(cands[c]) for c in chosen], weights


def lloyd_relax(seeds, weights, cands, iters=1, alpha=0.5, movable=None):
    """Partial Lloyd relaxation: move each seed `alpha` of the way to the centroid of the candidate points in its
    power cell, then snap it to the nearest candidate (keeps seeds on shells / mid-planes / inside the part)."""
    if not seeds or iters <= 0 or len(cands) == 0:
        return seeds
    P = np.array([s[:] for s in seeds], dtype=np.float64)
    W = np.array(weights, dtype=np.float64)
    for _ in range(iters):
        d = ((cands[:, None, :] - P[None, :, :]) ** 2).sum(axis=2) - W[None, :]
        own = np.argmin(d, axis=1)
        for i in range(len(P)):
            if movable is not None and not movable[i]:
                continue
            m = own == i
            if not np.any(m):
                continue
            c = cands[m].mean(axis=0)
            tgt = P[i] + (c - P[i]) * alpha
            k = int(np.argmin(((cands - tgt) ** 2).sum(axis=1)))
            P[i] = cands[k]
    return [Vector(p) for p in P]


# ======================================================================================================================
# Fracture of one part
# ======================================================================================================================
class Chunk:
    __slots__ = ("bm", "stats", "part", "seed")

    def __init__(self, bm, stats, part, seed):
        self.bm = bm
        self.stats = stats
        self.part = part
        self.seed = seed


def fracture_bmesh(src, seeds, weights, cap_mat, name="part", min_volume=0.0, min_thickness=0.0,
                   drop_volume=None, max_removals=None):
    """Power-diagram fracture of the closed bmesh `src`.  Returns a list of Chunk (bmesh owned by the chunk).
    Cells whose largest island is smaller than `min_volume` or thinner than `min_thickness` (3V/A) lose their seed
    (the neighbours absorb the region); islands below `drop_volume` are discarded (logged)."""
    n = len(seeds)
    seeds = [Vector(s) for s in seeds]
    weights = [float(w) for w in (weights if weights is not None else [0.0] * n)]
    label_components(src)
    src_stats = mesh_stats(src)
    if drop_volume is None:
        drop_volume = max(2e-4, 0.0005 * abs(src_stats["volume"]))
    if n <= 1:
        bm = src.copy()
        _finish_cell(bm, cap_mat)
        groups = sorted(((g, mesh_stats(g)) for g in split_groups(bm)), key=lambda gs: -abs(gs[1]["volume"]))
        bm.free()
        out = []
        minor = []
        for gi, (g, st) in enumerate(groups):
            if gi == 0 or st["volume"] >= drop_volume:
                out.append(Chunk(g, st, name, 0))
            else:
                minor.append((g, st))
        _merge_minor_islands(out, minor, name)
        return out
    active = list(range(n))
    cache = {}
    max_removals = n - 1 if max_removals is None else max_removals
    removed = []
    for it in range(max_removals + 1):
        for i in active:
            if i in cache:
                continue
            others = [j for j in active if j != i]
            cell, used = compute_cell(src, seeds, weights, i, others, cap_mat)
            groups = []
            if cell is not None:
                _finish_cell(cell, cap_mat)
                for g in split_groups(cell):
                    groups.append((g, mesh_stats(g)))
                cell.free()
            groups.sort(key=lambda gs: -abs(gs[1]["volume"]))
            cache[i] = (groups, set(used))
        worst = None
        for i in active:
            groups = cache[i][0]
            if not groups:
                continue
            st = groups[0][1]
            if st["volume"] < min_volume or st["thickness"] < min_thickness:
                score = (st["volume"], st["thickness"], i)
                if worst is None or score < worst:
                    worst = score
        if worst is None or len(removed) >= max_removals or len(active) <= 1:
            break
        k = worst[2]
        active.remove(k)
        removed.append(k)
        for g, _ in cache.pop(k)[0]:
            g.free()
        for i in list(active):
            if k in cache[i][1]:
                for g, _ in cache.pop(i)[0]:
                    g.free()
    chunks = []
    minor = []
    for i in active:
        groups = cache[i][0]
        for gi, (g, st) in enumerate(groups):
            vol = st["volume"]
            keep = vol > 0.0 and (gi == 0 or (vol >= drop_volume and st["thickness"] >= 0.5 * min_thickness))
            if keep and st["tris"] >= 4:
                chunks.append(Chunk(g, st, name, i))
            else:
                minor.append((g, st))
    merged, dropped = _merge_minor_islands(chunks, minor, name)
    total = sum(c.stats["volume"] for c in chunks)
    flog(f"{name}: seeds {n} -> removed {len(removed)} (slivers/tiny), chunks {len(chunks)}, "
         f"volume {total:.3f}/{src_stats['volume']:.3f} m^3, merged islands {merged}, dropped {dropped:.5f} m^3")
    return chunks


def _merge_minor_islands(chunks, minor, name, touch=0.03):
    """Attach small islands (pieces of a cell cut off by an opening, frame bits...) to the chunk they touch (nearest
    surface within `touch` m) instead of dropping them, so the reassembled fracture has no holes.  Degenerate slivers
    (no volume / nothing to attach to) are dropped and logged."""
    merged = 0
    dropped = 0.0
    if not minor:
        return merged, dropped
    trees = [BVHTree.FromBMesh(c.bm, epsilon=0.0) for c in chunks]
    for g, st in minor:
        vol = st["volume"]
        best = None
        if vol > 1e-7 and chunks:
            for ci, (c, t) in enumerate(zip(chunks, trees)):
                d = 1e9
                for v in g.verts:
                    hit = t.find_nearest(v.co, touch)
                    if hit[0] is not None:
                        d = min(d, hit[3])
                        if d < 1e-4:
                            break
                if d < touch and (best is None or d < best[0]):
                    best = (d, ci)
        if best is None:
            dropped += max(vol, 0.0)
            cc = st["centroid"]
            flog(f"  {name}: dropped island {vol:.6f} m^3 (3V/A {st['thickness']:.3f}) at "
                 f"({cc.x:.2f}, {cc.y:.2f}, {cc.z:.2f})")
            g.free()
            continue
        c = chunks[best[1]]
        copy_faces(g, list(g.faces), c.bm)
        g.free()
        c.stats = mesh_stats(c.bm)
        trees[best[1]] = BVHTree.FromBMesh(c.bm, epsilon=0.0)
        merged += 1
    return merged, dropped


# ======================================================================================================================
# Multi-part fracture + chunk objects
# ======================================================================================================================
def fracture_parts(parts, cap_mat):
    """parts: list of dicts {name, bm, seeds, weights, min_volume, min_thickness, drop_volume}.
    Every part is fractured independently (convex-ish sub-parts), chunks are returned in ONE list ordered by part,
    then bottom-to-top / y / x, ready for contiguous numbering."""
    out = []
    for p in parts:
        chunks = fracture_bmesh(p["bm"], p.get("seeds") or [], p.get("weights"), cap_mat, name=p["name"],
                                min_volume=p.get("min_volume", 0.0), min_thickness=p.get("min_thickness", 0.0),
                                drop_volume=p.get("drop_volume"))
        chunks.sort(key=lambda c: (round(c.stats["centroid"].z, 3), round(c.stats["centroid"].y, 3),
                                   round(c.stats["centroid"].x, 3)))
        out.extend(chunks)
    return out


def _box_uv(bm, faces, scale):
    lay = _uv_layer(bm)
    for f in faces:
        n = f.normal
        ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
        for loop in f.loops:
            p = loop.vert.co
            if az >= ax and az >= ay:
                u, v = p.x, p.y
            elif ax >= ay:
                u, v = p.y, p.z
            else:
                u, v = p.x, p.z
            loop[lay].uv = (u / scale, v / scale)


def make_chunk_objects(chunks, root, mtable, cap_mat, name_fmt="chunk_{:03d}", cap_uv_scale=1.5,
                       sharp_angle=35.0, weighted_normals=True, collection=None, edge_bevel=None):
    """Create chunk_001..NNN mesh objects under `root` (root must sit at the fracture-root origin with identity
    rotation/scale).  Object origin = chunk volume centroid.
    Normal cleanup: cut faces flat with sharp borders + a WeightedNormal modifier (keep_sharp) so bevelled outer
    surfaces shade exactly like the intact mesh.  edge_bevel=(width, segments) optionally chamfers only the borders of
    the cut faces (bevel weight + WEIGHT-limited Bevel modifier, clamped) for crisper broken edges.  Off by default:
    +40..60 % triangles, barely visible at game distances, and the Bevel modifier can open edges on very complex caps
    (fluted column sections) - always run verify_chunk_objects() when enabling it."""
    coll = collection or bpy.context.scene.collection
    objs = []
    lim = math.radians(sharp_angle)
    for k, ch in enumerate(chunks, 1):
        bm = ch.bm
        bm.normal_update()
        caps = [f for f in bm.faces if f.material_index == cap_mat]
        _box_uv(bm, caps, cap_uv_scale)
        for f in caps:
            f.smooth = False
        bw = None
        if edge_bevel:
            bw = bm.edges.layers.float.get("bevel_weight_edge") or bm.edges.layers.float.new("bevel_weight_edge")
        for e in bm.edges:
            lf = e.link_faces
            if len(lf) != 2:
                continue
            if lf[0].material_index == cap_mat or lf[1].material_index == cap_mat:
                e.smooth = False
                if bw is not None and e.calc_face_angle(0.0) > math.radians(20.0):
                    e[bw] = 1.0
            elif e.calc_face_angle(0.0) > lim:
                e.smooth = False
        cen = ch.stats["centroid"]
        bmesh.ops.translate(bm, verts=list(bm.verts), vec=-cen)
        used = sorted({f.material_index for f in bm.faces})
        remap = {m: i for i, m in enumerate(used)}
        for f in bm.faces:
            f.material_index = remap[f.material_index]
        name = name_fmt.format(k)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        for m in used:
            me.materials.append(mtable.mats[m])
        me.update()
        obj = bpy.data.objects.new(name, me)
        coll.objects.link(obj)
        obj.parent = root
        obj.location = cen
        if edge_bevel:
            bv = obj.modifiers.new("ChunkBevel", "BEVEL")
            bv.limit_method = "WEIGHT"
            bv.width = edge_bevel[0]
            bv.segments = edge_bevel[1] if len(edge_bevel) > 1 else 1
            bv.use_clamp_overlap = True
            bv.harden_normals = False
        if weighted_normals:
            wn = obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
            wn.keep_sharp = True
            wn.weight = 50
            wn.mode = "FACE_AREA"
        bm.free()
        ch.bm = None
        objs.append(obj)
    return objs


def verify_chunk_objects(objs):
    """Per-chunk checks on the EVALUATED (exported) meshes: closed (no boundary / non-manifold edges), volume > 0,
    convexity = volume / convex-hull volume.  Returns (rows, all_ok)."""
    dg = bpy.context.evaluated_depsgraph_get()
    rows = []
    ok = True
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        bm = bmesh.new()
        bm.from_mesh(me)
        ev.to_mesh_clear()
        b, nm = topology_errors(bm)
        st = mesh_stats(bm)
        hv = hull_volume(bm)
        conv = st["volume"] / hv if hv > 0 else 0.0
        good = b == 0 and nm == 0 and st["volume"] > 0 and st["tris"] >= 8 and st["centroid"].length < 0.02
        ok = ok and good
        rows.append(dict(name=o.name, tris=st["tris"], volume=st["volume"], boundary=b, nonmanifold=nm,
                         convexity=conv, size=max((st["hi"] - st["lo"])[:]), centroid_err=st["centroid"].length,
                         ok=good))
        bm.free()
    return rows, ok

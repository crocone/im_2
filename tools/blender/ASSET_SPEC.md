# Armored Flight – Blender asset specification

All 3D assets of the game are authored by Blender Python (`bpy`) scripts in `tools/blender/` and exported as
binary glTF (`.glb`) into `public/assets/`. Nothing is downloaded, nothing is hand-made outside the scripts, and the
game contains **no placeholder geometry**. This document is the contract between the scripts and the game code
(`tools/asset-contract.json` is the machine-readable version and is enforced by `npm run assets:validate`).

```
node tools/run-blender.mjs tools/blender/build_<x>.py            # build one asset script (Blender 4.4, background mode)
node tools/run-blender.mjs tools/blender/build_<x>.py -- --preview   # ... and render preview PNGs (tools/.cache/previews)
node tools/validate-assets.mjs <asset_key> [...]                 # check GLBs against tools/asset-contract.json
npm run assets                                                   # everything: build_all.py + validation
```

## 1. Conventions (do not deviate – the game depends on them)

| Thing | Blender (authoring) | glTF / three.js (game) |
|---|---|---|
| unit | 1 unit = 1 metre | 1 = 1 m |
| up | +Z | +Y |
| **forward** (the way a model faces / flies / shoots) | **+Y** | **−Z** |
| right side of the model (`_R`) | **+X** | +X |
| left side (`_L`) | −X | −X |

* Model everything **facing +Y** (so the front of the player, the nose of a missile, the barrel of a turret all point
  along +Y in Blender). The exporter (Y-up) turns that into −Z.
* Rotation about X is the same angle in both systems: **pitching the head forward = NEGATIVE X rotation**
  (e.g. flight lean `Pelvis.rot = (-80°, 0, 0)`).
* **Emission axis:** for every `Muzzle*`, `Nozzle*`, `Launcher*`, `Hardpoint*`, `Exhaust_Point` Empty the **local +Y axis**
  is the direction things leave (bullets, exhaust flames, missiles). Use `aim_rot_for_direction((dx,dy,dz))` from
  `common.py` to create the rotation. (In three.js the game reads it as local −Z.)
* Rest pose = identity rotations on every node. Geometry of rigged parts is authored in rest-pose world coordinates and the
  origin is moved to the joint pivot with `add_part(name, mb, pivot_world, parent, parent_pivot_world)`. Local location is
  therefore `pivot − parent_pivot`. Never use `matrix_parent_inverse` tricks, never leave non-unit scale on mesh nodes,
  never use negative scale (build mirrored geometry with `MB.mirrored_x()`).
* Node names are EXACT (case sensitive) and must be unique. Blender silently renames clashes to `Name.001` – that is a
  bug in your script (the validator warns). Mesh *data* names do not matter.
* Origin conventions per asset are listed below (pelvis/centre of mass for the player, ground centre for buildings...).

## 2. Look & quality bar

Visual target: a polished indie action game with the readability of a modern third-person superhero flight game,
seen at sunset (warm low sun, purple-orange sky, cool fill) with bloom on emissive parts.

* **Not greybox.** Layered plates, panel insets, chamfers/bevels, mechanical joints, vents, bolts, emissive strips,
  silhouette variation. Use `MB.box(... taper=, top_shift=, bottom_scale=)`, `MB.loft`, `MB.revolve`, `MB.prism`, and
  `to_object(bevel=(width, segments))` (Bevel + Weighted Normal modifiers, applied at export) for crisp
  bevelled panel edges with clean shading. Angular low/mid-poly forms, never plain unbevelled cubes or cylinders.
* Coherent PBR palette – use `pal("armor_primary")` etc. from `common.py` (see `PALETTE`). Extend with your own
  `make_material()` when needed, same value ranges (metallic 0.5–0.9 for armour, roughness 0.28–0.6).
  Emissive parts are **materials with Emission Color + Strength** (glTF `KHR_materials_emissive_strength`); use
  the `glow_*` palette entries (cyan for the player, red/orange for hostile machines).
* Armour must read as **metal** (high metallic, moderate roughness) – the game supplies an HDR sky environment, so
  metals look right only if base colours are not too dark: primary plating ≥ 0.4 linear luminance.
* Player = friendly palette (pearl titanium + deep navy + amber trim + cyan glow). Enemies = charcoal steel + red hazard
  trim + red glow. Boss = black steel + brass trim + red-orange core. Never copy an existing commercial character or
  armour design – original angular design language only.
* Budgets are in the contract (triangles per asset). Keep meshes clean: no interior faces that z-fight, no coplanar
  overlaps, no inverted normals, no floating/unattached parts, no hidden geometry. Doubles are welded by `MB.finish()`.
* Textures (only where stated): procedurally generated with numpy (`image_from_array`), packed into the GLB, ≤ 1024².
  Use `make_textured_material` with an ORM map (G = roughness, B = metallic).
* Determinism: `random.Random(<fixed seed>)` / `np.random.default_rng(<fixed seed>)`, sorted iteration, no time, no
  `set` iteration order dependence. Running the script twice must produce byte-identical (or at least
  identical-size and contract-equivalent) GLB files.

## 3. Script template

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

def build():
    reset_scene()
    ...                                   # create objects (MB, add_part, add_empty ...)
    path = export_glb("thing.glb", [root], animations=False)
    report(path)                          # prints nodes / tris / materials / animations
    if "--preview" in script_args():
        render_views("thing", [root], views=("front", "back", "left", "three_quarter"))

build()
```

`export_glb` exports the given root objects and all their descendants. `render_views` renders EEVEE previews of
the objects into `tools/.cache/previews/<tag>_<view>.png` – **look at them** (Read tool) from several angles after
every meaningful change; the first render in a Blender process takes ~40 s (shader compilation), later ones < 1 s.
`views`: front, back, left, right, three_quarter, three_quarter_back, top, low. `custom_views={"name": (azimuth_deg,
elevation_deg, distance_mult)}` for anything else (azimuth 180 = camera in front of a +Y-facing model, 0 = behind it).
To preview a pose, call `apply_pose_static(objects, pose)` before `render_views`.

Helper summary (see the file for details): `reset_scene, pal, make_material, hexc, MB (box, cyl, revolve, sphere, prism, loft,
hexa, face, mirrored_x, merge_into, transform, to_object), add_part, add_empty, aim_rot_for_direction, set_origin_world,
add_bevel, apply_modifiers, box_project_uv, image_from_array, make_textured_material, build_pose_clips, apply_pose_static,
export_glb, glb_info, report, render_views, world_bbox, tri_count`.
You may add script-local helpers. If you need something generally useful in `common.py`, **append** it at the end of the file
(never rewrite existing functions – other people are using them at the same time; re-read the file right before editing).

## 4. Asset contracts

Sizes are glTF-axis extents (x = width, y = height, z = depth) of the whole subtree in the REST pose.

### 4.1 `player.glb` (script `build_player.py`)
Original powered flight armour, 2.0 m tall standing. Root `PlayerRoot` (Empty at the body centre ≈ 1.0 m above the soles,
so the boots' soles are at ≈ −1.0 m). Hierarchy (**all listed names must exist, direct-child relations are validated**):

```
PlayerRoot
└─ Pelvis (Empty at the hip joint)
   ├─ Torso  (mesh; pivot at the waist/hip joint)
   │   ├─ Helmet (mesh; neck pivot)         ├─ ChestReactor (emissive mesh, ≈ 0.17 m disc in a hex housing)
   │   ├─ Arm_L / Arm_R  (mesh: pauldron + upper arm; pivot at shoulder)
   │   │    └─ Forearm_L/R (mesh; pivot at elbow)
   │   │         └─ Hand_L/R (mesh; pivot at wrist)
   │   │              ├─ PalmReactor_L/R (emissive mesh disc on the palm)
   │   │              └─ Muzzle_L/R (Empty at palm centre, +Y = palm normal = repulsor firing / palm jet direction)
   │   ├─ Launcher_Missile_L/R (Empty on top of each shoulder, +Y = launch direction out/up/forward)
   │   └─ Launcher_Mini_L_1..3 / Launcher_Mini_R_1..3 (Empties on the shoulder mini-missile pods, fan out/forward)
   ├─ Leg_L / Leg_R (mesh: thigh + knee guard; pivot at hip)
   │    └─ Shin_L/R (mesh; pivot at knee)
   │         └─ Boot_L/R (mesh; pivot at ankle)
   │              ├─ FootThruster_L/R (emissive mesh: thruster nozzle ring + glowing disc on the sole/heel)
   │              └─ Nozzle_FootL / Nozzle_FootR (Empty at the sole, +Y = exhaust direction: DOWN (−Z Blender) in rest pose)
```
Details: broad heroic proportions, angular layered plates (pearl `armor_primary`, navy `armor_secondary`, amber `armor_accent`
stripes, `armor_dark` joints with visible mechanism), visor slit with `armor_glass`/`glow_white` eyes, shoulder weapon mounts
(a launcher block with two visible tube mouths per shoulder for the homing missile + a small 3-tube mini-missile pod on each
shoulder/upper-back), forearm gauntlets with vents + amber stripe, palm reactors as recessed discs ringed by dark metal, boots with heel
thrusters. Emissive: `glow_cyan` (chest reactor, palm discs, foot thrusters, armour seam strips), `glow_white` for the eye slit.
`_L` parts must be at −X and `_R` at +X (validated). 12k–70k triangles total; 20 000–40 000 is a good target.

**Poses** – three looping glTF animations named exactly `Pose_Standing`, `Pose_Flight`, `Pose_Hover`, built with
`build_pose_clips(objects, poses, idle=...)` (one NLA track per pose; `export_glb(..., animations=True)`). Animate the rotations
of every articulated node (Pelvis, Torso, Helmet, Arm_*, Forearm_*, Hand_*, Leg_*, Shin_*, Boot_*) – ≥ 8 channels per clip (validated) – and give each pose
a subtle idle loop (breathing / sway / limb flutter, ±1–3°). The game blends the three clips with weights (it never plays only one),
so every pose must be a *complete* pose that also looks good half-blended with another:
* `Pose_Standing` – neutral heroic stance on the ground, feet flat (soles at −1.0 m), arms slightly away from the body, palms towards the thighs.
* `Pose_Flight` – streamlined superhero dive: `Pelvis` pitched ≈ −75…−85° about X so head/torso point along the flight direction (+Y), legs
  together trailing behind with the boots' foot thrusters pointing backward, arms swept back alongside the body, **PalmReactor/Muzzle axes pointing
  backward (toward −Y Blender) so the palm jets stream behind the suit**, slight helmet lift so the visor faces forward.
* `Pose_Hover` – upright combat hover: Pelvis leaning ≈ −8…−12°, knees slightly bent, feet together and dangling with thrusters pointing down,
  forearms raised forward in a ready stance with the palms (Muzzle axes) facing forward-down.
Self-check in the script (assert): Muzzle axes in Flight point backward, in Hover point forward/down; Helmet is in front of the pelvis in Flight.

### 4.2 Enemies (script `build_enemies.py` → `drone.glb`, `turret.glb`, `boss.glb`, `boss_shield.glb`)
Hostile machines: charcoal steel (`enemy_*` / `boss_*` palette), red/orange hazard trim, red glow. Must look dangerous, industrial and readable
from 150 m away (strong silhouette, glowing sensor).
* **`drone.glb`** – root `Drone` (origin at the centre of mass). Compact armoured aerial combat drone, ≈ 1.4 m wide with rotors (x 0.9–2.4, z 0.8–2.2, y 0.25–1.0):
  `Drone_Body` (armoured hull: layered plates, intakes, tail fins; nose toward +Y), `Drone_Rotor_FL/FR/RL/RR` (ducted rotor/propulsor units on
  short pylons, pivot on the vertical rotor axis (Blender Z) so the game can spin them about local Y; give them visible blades/fan geometry),
  `Drone_Sensor` (emissive red lens/eye at the front so the facing is obvious), `Muzzle_L`/`Muzzle_R` (Empties at two weapon ports,
  +Y forward; L at −X, R at +X), `Drone_Engine` (emissive rear thruster mesh), `Nozzle_Rear` (Empty, +Y = exhaust direction, i.e. pointing BACK (−Y)).
* **`turret.glb`** – root `Turret` (origin at the centre of the base bottom on the ground). `Turret_Base` (static octagonal armoured pedestal with
  bolted plates, ≈ 2.4 m wide, 1.0–1.3 m high), `Turret_Yaw` (child of the Turret root, not of the base: the rotating assembly, pivot at the top-centre of
  the base on the vertical axis; the game rotates it about local Y), `Turret_Pitch` (child of `Turret_Yaw`, pivot at the trunnion axis, the game rotates
  it about X: positive rotation raises the barrels; carries a missile launcher of 2 pods × 2 tubes = four tube mouths, plus armour), `Turret_Sensor` (emissive red
  targeting sensor, child of Pitch), `Muzzle_1..4` (Empties at the four tube mouths, children of `Turret_Pitch`, +Y forward). At rest the barrels point
  forward (+Y) and horizontally. Total 1.8–4.2 m tall/wide.
* **`boss.glb`** – root `Boss` (origin at the centre of the chest/core). A large armoured aerial combat unit, **≈ 3 × the player's size** (height 5.4–7.6 m,
  width 5–11 m, depth 3–7.5 m) and clearly more menacing than any other enemy. Required nodes: `Boss_Torso` (massive layered armoured torso), `Boss_Head` (small
  sensor head/cowl), `Boss_Arm_L/R` (heavy shoulder + upper arm, pivot at shoulder) with children `Boss_Forearm_L/R` (giant gauntlets/cannons, pivot at elbow),
  `Boss_Core` (emissive `glow_core` reactor in a caged housing on the chest, must be visible from the front), `Boss_Thruster_1..4` (large thruster pods:
  2 big rear/lower pods + 2 side pods; meshes with emissive interiors), `Nozzle_1..4` (Empties at the thruster exits, +Y = exhaust direction), `Hardpoint_L1..L3` /
  `Hardpoint_R1..R3` (weapon hardpoints as Empties, +Y = firing direction; visible cannon/missile-rack geometry at each: L on −X, R on +X, some on shoulders, some on
  forearms) and `Shield_Center` (Empty at the chest core). No legs: it hovers on its thrusters (lower body tapers into a thruster cage). Faces +Y.
* **`boss_shield.glb`** – single mesh `BossShield`: unit-radius (2.0 m diameter, ±0.05) UV sphere-ish dome/geodesic mesh, smooth normals, proper 0..1 UVs, 1 material
  `BossShield_Mat` (translucent cyan, emissive edge, double sided). The game scales it and drives its own shader (pulse, hit flash, dissolve).

### 4.3 Projectiles (script `build_projectiles.py` → `missile.glb`, `mini_missile.glb`)
Nose toward +Y (Blender), origin at mid-length, both with a clear forward axis and a glowing exhaust.
* **`missile.glb`** – root `Missile`, length ≈ 1.6 m, ⌀ ≈ 0.22 m: `Missile_Body` (ogive nose, seeker ring, coloured bands, panel lines), `Missile_Fins` (4 cruciform
  swept fins + small canards), `Missile_Engine` (nozzle bell), `Missile_Exhaust` (emissive `exhaust` glowing disc/cone at the rear – game adds flame FX),
  `Exhaust_Point` (Empty at the tail centre, +Y pointing BACK (−Y) = exhaust direction).
* **`mini_missile.glb`** – root `MiniMissile`, length ≈ 0.75 m, ⌀ ≈ 0.09 m, visually distinct from the big one (amber/cream palette `mini_*`, 3 wedge fins,
  blunt nose): `Mini_Body`, `Mini_Fins`, `Mini_Engine`, `Mini_Exhaust` (emissive), `Exhaust_Point` (Empty).

### 4.4 City kit
The city is a grid: block pitch 100 m, roads 20 m wide, block 80 m square = 4 m sidewalk ring + **72 × 72 m lot**. Origins: buildings at the
**centre of their footprint at ground level (y = 0)**; the game places them on the lot at y = 0.15 (sidewalk/curb height).

**`city_buildings.glb`** (script `build_city_buildings.py`) – at least 10 (target 12) genuinely different building modules, top-level nodes named
`Bld_01_GlassTower`, `Bld_02_SetbackTower`, `Bld_03_OfficeSlab`, `Bld_04_ApartmentBlock`, `Bld_05_LShapeTower`, `Bld_06_Warehouse`, `Bld_07_ResidentialTower`,
`Bld_08_RoundTower`, `Bld_09_MidriseOffice`, `Bld_10_Landmark`, `Bld_11_ParkingGarage`, `Bld_12_PodiumTower` (you may rename the descriptive part but keep the `Bld_NN_` prefix,
and 10+ modules). They must differ in **height (14–170 m), footprint (fits inside 66×66 m; mix of compact ~26×26, slabs ~60×28, L-shapes, round towers),
rooftop shape (flat with mechanicals, setback crowns, spires, sawtooth, pitched/mansard, helipad), facade structure (glass curtain wall, ribbon windows,
punched-window brick, balconies, fins/mullions, cladding panels) and silhouette** – no scaled copies of one cube. Each module is a hierarchy under its root:
visual meshes (a few materials only, shared across modules: the whole file uses ≲ 8 materials; facades are textured, see below), plus **helper Empties without geometry**:
* `COL_1..n` – collision boxes: Empty (display 'CUBE'), rotation 0, **location = box centre relative to the module root, scale = half extents** (Blender axes; the exporter
  converts). Cover the real silhouette (e.g. podium + tower + crown = 3 boxes) with 1–5 boxes, no gaps larger than a player.
* `Roof_Slot_1..n` – ≥ 1 (target 3–6) Empties on flat roof areas (y = roof surface height, ≥ 4×4 m clear) where the game may put turrets, AC units, water towers,
  antennas.
* A low-poly sibling `<same name>_LOD1` top-level node (12–1500 triangles: massing + roof silhouette, same materials/UV density) used for distant districts.
Facade textures: generate 3–5 tiling facade materials procedurally with numpy (albedo + ORM + emissive maps ≤ 512–1024 px; windows on a 3.0 m bay × 3.6 m floor grid so
UVs from `box_project_uv(obj, (24.0, 28.8))` tile seamlessly; 25–40 % of windows lit warm/cool via the emissive map, stronger contrast at night-like brightness).
Total `city_buildings.glb` ≲ 14 MB, 15k–320k triangles overall, each module 600–28 000 triangles.

**`city_ground.glb`** (script `build_city_ground.py`) – flat tiles with exact sizes (x × z in metres, centred on their origin, top at y = 0 for roads, 0.15 for
sidewalk/lot): `Road_Straight` 20×80 (dashed centre line running along the 80 m axis, edge lines, subtle wear/manholes, curbs are part of sidewalks),
`Road_Intersection` 20×20 (crosswalk stripes on all four sides in the 20 m square are fine, stop lines), `Sidewalk_Straight` 4×72 (paving joints, curb edge on the road side = −X…
either side is fine, the game rotates it), `Sidewalk_Corner` 4×4 (rounded outer corner), `Lot_Ground` 72×72 (concrete plaza pavement with tile joints, a few
planters/drains as real geometry). Textured (asphalt / concrete, ≤ 1024²), tileable.

**`city_props.glb`** (script `build_city_props.py`) – top-level roots, origin at the base centre on the ground, facing +Y:
`Prop_StreetLamp` (≈ 9 m pole with curved arm, `lamp_glow` head), `Prop_Car_A` (sedan), `Prop_Car_B` (SUV/van), `Prop_Car_C` (taxi/pickup) – each
≈ 4.2–5.4 m long with body, glass, 4 wheels (tyre + hub), emissive head/tail lights, wheels touching y = 0; `Prop_Barrier_Jersey` (3 m concrete jersey barrier, long axis along
Y), `Prop_Barrier_Striped` (red/white striped traffic barrier with amber warning lamp), `Prop_Antenna` (≈ 16 m lattice mast with cross arms + red `beacon_red` light),
rooftop utilities `Prop_AC_Unit_A`, `Prop_AC_Unit_B`, `Prop_Vent_Stack`, `Prop_Roof_Access` (stair bulkhead ≈ 3×3×2.6 m), `Prop_Cooling_Tower`, `Prop_Solar_Array`.
Dimensions are validated (see contract). Also welcome (optional, extra top-level `Prop_*` roots): hydrant, bench, bus shelter, traffic light, planter.

### 4.5 Destructibles (script `build_destructibles.py`, helper module `fracture.py`)
Four authored objects, each with an **intact** and a **fractured** state in separate GLBs:

| key | intact root | fractured root | files |
|---|---|---|---|
| column | `Column_Intact` (fluted concrete/marble column with base + capital, ≈ 12 m) | `Column_Fractured` | `destructible_column_intact.glb`, `destructible_column_fractured.glb` |
| city sign | `CitySign_Intact` (tall blade sign on a steel mast, emissive neon panels with abstract glyph shapes – no real brands/text, ≈ 10 m) | `CitySign_Fractured` | `destructible_citysign_*.glb` |
| water tower | `WaterTower_Intact` (steel-legged stand with cross bracing, riveted tank, conical roof, ladder, ≈ 9 m) | `WaterTower_Fractured` | `destructible_watertower_*.glb` |
| small building | `SmallBuilding_Intact` (shop / kiosk ≈ 11×9×6 m: walls, door, windows, awning, roof with parapet + AC unit) | `SmallBuilding_Fractured` | `destructible_smallbuilding_*.glb` |

* Origin = centre of the base on the ground (y = 0). Same materials in both states (the fractured meshes additionally use a rough `debris_interior`
  material on the cut faces, e.g. exposed concrete/steel).
* Intact GLB: the visual mesh(es) + `COL_1..n` collider Empties (same convention as buildings: scale = half extents) approximating the shape.
* **Fractured GLB: the root has only children named `chunk_001` … `chunk_NNN`** (contiguous numbering, 10–64 chunks depending on the object), each a real mesh: an
  irregular, closed, roughly convex fragment produced by a **procedural Voronoi fracture in bpy** (Cell Fracture is NOT available in this Blender – implement it in
  `fracture.py`: deterministic random seed points inside the object, per-cell bisect-plane clipping with capped (filled) cut faces, keep the original outer surface
  materials on the outside and `debris_interior` on the cuts). Fragment origin = its centroid (so the game can create a rigid body at the chunk position); chunks must
  reassemble to the intact silhouette (bounding box within 15 %; validated). Fractures must not be axis-aligned boxes: irregular sizes (mix of large and small), angled cut
  faces. For non-convex objects (water tower legs/tank/roof…) fracture the convex sub-parts separately and number all chunks in one sequence. Heavy parts (tank,
  column shaft) get more/larger chunks, thin parts (braces, letters) 1–2 chunks each.
* The game gives every chunk a convex-hull collider from its vertices, so chunks should be closed and reasonably convex.

## 5. Definition of done for every asset script
1. `node tools/run-blender.mjs tools/blender/build_<x>.py` succeeds from a clean checkout, writes only into `public/assets/` (+ `tools/.cache/`), and is deterministic.
2. `node tools/validate-assets.mjs <keys>` prints PASS for all your keys (fix real problems, never edit the contract to make it pass – tell the lead if it is wrong).
3. You looked at previews from ≥ 4 angles (and every pose / state) and fixed what looked wrong: silhouette, proportions, floating or intersecting parts, flat-looking
   surfaces, dull colours, inverted normals, z-fighting, missing emissive parts. Iterate several times – this is the art quality bar.
4. Summarise for the lead: file names, node/animation lists, triangle counts, anything surprising (e.g. deviations with reasons), and how to re-run.

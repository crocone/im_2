"""Master asset build:  blender -b -P tools/blender/build_all.py [-- --only player,city_props] [--skip x]

Runs every build_*.py script in its own fresh Blender process (--factory-startup, so results never depend on
user preferences or leftover scene state) and writes all GLB files to public/assets/.
The whole pipeline is deterministic: fixed seeds, no clocks, stable ordering.

`npm run assets` wraps this through tools/run-blender.mjs and then validates the result.
"""
import os
import subprocess
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))

# (script, outputs) - order matters only for log readability
PIPELINE = [
    ("build_player.py", ["player.glb"]),
    ("build_enemies.py", ["drone.glb", "turret.glb", "boss.glb", "boss_shield.glb"]),
    ("build_projectiles.py", ["missile.glb", "mini_missile.glb"]),
    ("build_pickups.py", ["pickups.glb"]),
    ("build_city_buildings.py", ["city_buildings.glb"]),
    ("build_city_ground.py", ["city_ground.glb"]),
    ("build_city_props.py", ["city_props.glb"]),
    ("build_destructibles.py", [
        "destructible_column_intact.glb", "destructible_column_fractured.glb",
        "destructible_citysign_intact.glb", "destructible_citysign_fractured.glb",
        "destructible_watertower_intact.glb", "destructible_watertower_fractured.glb",
        "destructible_smallbuilding_intact.glb", "destructible_smallbuilding_fractured.glb",
    ]),
]


def parse_args():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    only, skip = None, set()
    i = 0
    while i < len(args):
        if args[i] == "--only" and i + 1 < len(args):
            only = set(args[i + 1].split(","))
            i += 2
        elif args[i] == "--skip" and i + 1 < len(args):
            skip = set(args[i + 1].split(","))
            i += 2
        else:
            i += 1
    return only, skip


def main():
    only, skip = parse_args()
    blender = bpy.app.binary_path
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8")
    failures = []
    t_all = time.time()
    for script, outputs in PIPELINE:
        short = script.replace("build_", "").replace(".py", "")
        if only and short not in only:
            continue
        if short in skip:
            continue
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            print(f"[build_all] !! {script} is missing - skipping", flush=True)
            failures.append(script)
            continue
        print(f"[build_all] === {script} -> {', '.join(outputs)}", flush=True)
        t0 = time.time()
        res = subprocess.run([blender, "-b", "--factory-startup", "--python-exit-code", "1", "-P", path], env=env)
        dt = time.time() - t0
        if res.returncode != 0:
            print(f"[build_all] !! {script} FAILED (exit {res.returncode}) after {dt:.1f}s", flush=True)
            failures.append(script)
        else:
            print(f"[build_all] ok {script} in {dt:.1f}s", flush=True)
    print(f"[build_all] finished in {time.time() - t_all:.1f}s; failures: {failures or 'none'}", flush=True)
    if failures:
        sys.exit(1)


main()

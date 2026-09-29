// Dev-only harness: flies the real Player/ChaseCamera/Sky/FX on a tile of the real city_ground asset.
// Useful while other assets are still being generated.  Open http://localhost:5173/tools/dev/sandbox.html
import * as THREE from 'three';
import { Physics, RAPIER, MASKS } from '../../src/physics/world';
import { Assets } from '../../src/assets/loader';
import { Effects } from '../../src/fx/effects';
import { PostFX } from '../../src/fx/postfx';
import { Sky } from '../../src/world/sky';
import { SpeedLines } from '../../src/fx/speedlines';
import { Input } from '../../src/core/input';
import { Emitter } from '../../src/core/events';
import { AudioEngine } from '../../src/audio/audio';
import { Player } from '../../src/player/player';
import { ChaseCamera } from '../../src/player/camera';
import { DebrisManager } from '../../src/world/debris';
import { ProjectileManager } from '../../src/weapons/projectiles';
import { collectParts } from '../../src/world/city';
import { explode } from '../../src/game/explode';
import { DestructibleManager } from '../../src/world/destructibles';
import { EnemyManager } from '../../src/enemies/manager';
import type { GameCtx, GameEvents, Settings } from '../../src/game/types';
import { Hud } from '../../src/ui/hud';
import '../../src/style.css';

const info = document.getElementById('info')!;
const canvas = document.getElementById('c') as HTMLCanvasElement;

async function main() {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.setSize(Math.max(2, innerWidth), Math.max(2, innerHeight), false);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(68, innerWidth / innerHeight, 0.15, 4200);
  const physics = await Physics.create();
  const assets = new Assets();
  await assets.loadAll(undefined, ['player', 'city_ground', 'pickups', 'drone', 'destructible_column_intact', 'destructible_column_fractured', 'destructible_citysign_intact', 'destructible_citysign_fractured', 'destructible_watertower_intact', 'destructible_watertower_fractured', 'destructible_smallbuilding_intact', 'destructible_smallbuilding_fractured', 'boss', 'boss_shield', 'turret', 'missile', 'mini_missile']);
  const sky = new Sky(scene);
  scene.environment = sky.buildEnvironment(renderer);
  (scene as THREE.Scene & { environmentIntensity: number }).environmentIntensity = 0.85;

  const input = new Input(canvas);
  const settings: Settings = { sensitivity: 1, invertY: false, quality: 'high', volume: 0.5, showHelpOnStart: false };
  const bus = new Emitter<GameEvents>();
  const audio = new AudioEngine();
  const ctx = {
    scene, camera, renderer, physics, assets, bus, input, audio, settings, time: 0,
    explode: (o: never) => explode(ctx, o),
    shake: (a: number) => chase.addShake(a),
    recoil: (a: number) => chase.addRecoil(a),
    addScore: () => undefined,
  } as unknown as GameCtx;
  ctx.fx = new Effects(scene, camera);
  ctx.debris = new DebrisManager(ctx);
  ctx.projectiles = new ProjectileManager(ctx);
  ctx.enemies = new EnemyManager(ctx);
  const destructibles = new DestructibleManager(ctx);
  ctx.world = { destructibles, props: { blast() {} } } as never;
  ctx.pickups = { maybeDrop() {}, drop() {}, items: [] } as never;
  ctx.player = new Player(ctx);

  // ---- ground: 3x3 blocks of the real city_ground tiles
  const gScene = assets.get('city_ground').scene;
  const place = (name: string, x: number, z: number, rot = 0) => {
    const { parts } = collectParts(gScene, name);
    const m = new THREE.Matrix4().compose(new THREE.Vector3(x, 0, z), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), rot), new THREE.Vector3(1, 1, 1));
    for (const p of parts) {
      const mesh = new THREE.Mesh(p.geometry, p.material);
      mesh.matrixAutoUpdate = false;
      mesh.matrix.multiplyMatrices(m, p.matrix);
      mesh.receiveShadow = true;
      scene.add(mesh);
    }
  };
  for (let i = -3; i <= 3; i++) {
    for (let j = -3; j <= 3; j++) {
      const bx = i * 100;
      const bz = j * 100;
      place('Lot_Ground', bx, bz);
      place('Road_Intersection', bx + 50, bz + 50);
      place('Road_Straight', bx + 50, bz, 0);
      place('Road_Straight', bx, bz + 50, Math.PI / 2);
    }
  }
  physics.addCollider(RAPIER.ColliderDesc.cuboid(4000, 5, 4000).setTranslation(0, -5, 0).setCollisionGroups(MASKS.world), undefined, { kind: 'world' });
  // some boxes as "buildings" for collision / camera tests
  for (let k = 0; k < 14; k++) {
    const x = (k % 7 - 3) * 60 + 30;
    const z = -80 - Math.floor(k / 7) * 90;
    const h = 20 + ((k * 37) % 60);
    physics.addCollider(RAPIER.ColliderDesc.cuboid(14, h / 2, 14).setTranslation(x, h / 2, z).setCollisionGroups(MASKS.world), undefined, { kind: 'world' });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(28, h, 28), new THREE.MeshStandardMaterial({ color: 0x556070, roughness: 0.8 }));
    mesh.position.set(x, h / 2, z);
    mesh.castShadow = mesh.receiveShadow = true;
    scene.add(mesh);
  }

  const kinds = ['column', 'citysign', 'watertower', 'smallbuilding'] as const;
  kinds.forEach((k, i) => destructibles.place(k, new THREE.Vector3(-30 + i * 22, 0, 10), i));
  for (let i = 0; i < 3; i++) ctx.enemies.spawnDrone(new THREE.Vector3(-40 + i * 40, 45, -150), true);
  (window as unknown as Record<string, unknown>).__spawnBoss = () => ctx.enemies.spawnBoss(new THREE.Vector3(0, 0, 0));
  (window as unknown as Record<string, unknown>).__spawnTurret = (x: number, z: number) => ctx.enemies.spawnTurret(new THREE.Vector3(x, 0.15, z), 0.5);
  // real HUD: lift the #hud markup out of index.html
  const html = await (await fetch('/index.html')).text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const hudEl = doc.getElementById('hud')!;
  document.body.appendChild(hudEl);
  document.body.classList.add('sandbox');
  const hud = new Hud(ctx);
  hud.setVisible(true);
  (window as unknown as Record<string, unknown>).__hud = hud;
  const chase = new ChaseCamera(camera, physics);
  const postfx = new PostFX(renderer, scene, camera);
  const speedLines = new SpeedLines(scene);
  postfx.setSize(Math.max(2, innerWidth), Math.max(2, innerHeight), Math.min(devicePixelRatio, 1.5));
  ctx.player.spawn(new THREE.Vector3(0, 0, 60), 0);
  chase.reset(ctx.player);
  input.enabled = true;
  canvas.addEventListener('click', () => {
    audio.init();
    input.requestLock();
  });
  addEventListener('resize', () => {
    if (innerWidth < 2 || innerHeight < 2) return;
    renderer.setSize(innerWidth, innerHeight, false);
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    postfx.setSize(innerWidth, innerHeight, Math.min(devicePixelRatio, 1.5));
  });
  (window as unknown as Record<string, unknown>).__sb = { ctx, chase };

  let orbit = false;
  addEventListener('keydown', (e) => { if (e.code === 'KeyO') orbit = !orbit; });
  const advance = (seconds: number) => {
    const n = Math.round(seconds * 60);
    for (let i = 0; i < n; i++) {
      ctx.time += 1 / 60;
      ctx.player.pollInput();
      ctx.player.preStep(1 / 60);
      ctx.enemies.preStep(1 / 60);
      ctx.projectiles.preStep(1 / 60);
      physics.step();
      ctx.player.postStep(1 / 60);
      ctx.enemies.postStep();
      ctx.projectiles.postStep(1 / 60);
      input.endFrame();
      if (i % 4 === 3) {
        ctx.player.updateVisual(4 / 60, 1);
        ctx.enemies.syncVisuals(4 / 60, 1);
        ctx.debris.update(4 / 60);
        ctx.fx.update(4 / 60);
        chase.update(4 / 60, ctx.player);
        camera.updateMatrixWorld(true);
        speedLines.update(camera.position, ctx.player.vel, Math.min(1, ctx.player.speed / 108), ctx.player.flight.boostAmount);
      }
    }
  };
  (window as unknown as Record<string, unknown>).__advance = advance;
  (window as unknown as Record<string, unknown>).__setOrbit = (v: boolean) => (orbit = v);
  let last = performance.now() / 1000;
  let acc = 0;
  let fps = 60;
  let sw = 0;
  let sh = 0;
  const frame = () => {
    requestAnimationFrame(frame);
    if ((innerWidth !== sw || innerHeight !== sh) && innerWidth > 1 && innerHeight > 1) {
      sw = innerWidth;
      sh = innerHeight;
      renderer.setSize(sw, sh, false);
      camera.aspect = sw / sh;
      camera.updateProjectionMatrix();
      postfx.setSize(sw, sh, Math.min(devicePixelRatio, 1.5));
    }
    const now = performance.now() / 1000;
    const dt = Math.min(0.1, now - last);
    last = now;
    fps = fps * 0.95 + (1 / Math.max(dt, 1e-4)) * 0.05;
    ctx.player.pollInput();
    acc += dt;
    let steps = 0;
    while (acc >= 1 / 60 && steps < 5) {
      ctx.time += 1 / 60;
      ctx.player.preStep(1 / 60);
      ctx.enemies.preStep(1 / 60);
      ctx.projectiles.preStep(1 / 60);
      physics.step();
      ctx.player.postStep(1 / 60);
      ctx.enemies.postStep();
      ctx.projectiles.postStep(1 / 60);
      acc -= 1 / 60;
      steps++;
    }
    if (steps === 5) acc = 0;
    const alpha = acc * 60;
    ctx.player.updateVisual(dt, alpha);
    ctx.enemies.syncVisuals(dt, alpha);
    ctx.debris.update(dt);
    ctx.fx.update(dt);
    chase.update(dt, ctx.player);
    if (orbit) {
      const a = now * 0.5;
      camera.position.copy(ctx.player.renderPos).add(new THREE.Vector3(Math.sin(a) * 6, 1.5, Math.cos(a) * 6));
      camera.lookAt(ctx.player.renderPos);
    }
    camera.updateMatrixWorld(true);
    speedLines.update(camera.position, ctx.player.vel, Math.min(1, ctx.player.speed / 108), ctx.player.flight.boostAmount);
    sky.update(dt, camera, ctx.player.renderPos);
    const p = ctx.player;
    postfx.update(now, Math.min(1, p.speed / 108), p.flight.boostAmount, 0, 0);
    postfx.render(dt);
    hud.update(dt);
    input.endFrame();
    info.textContent =
      `fps ${fps.toFixed(0)}  mode ${p.flight.mode}  speed ${(p.speed * 3.6).toFixed(0)} km/h  alt ${p.pos.y.toFixed(1)}\n` +
      `pos ${p.pos.x.toFixed(0)},${p.pos.y.toFixed(0)},${p.pos.z.toFixed(0)}  boost ${p.flight.boostAmount.toFixed(2)} energy ${p.energy.toFixed(0)}\n` +
      `click = capture mouse; WASD/Space/C/QE/Shift/F, LMB repulsor   calls ${renderer.info.render.calls} tris ${renderer.info.render.triangles}`;
  };
  requestAnimationFrame(frame);
}

main().catch((e) => {
  info.textContent = String(e?.stack ?? e);
  console.error(e);
});

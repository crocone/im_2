#!/usr/bin/env node
// Validates the exported GLB assets against tools/asset-contract.json.
//   node tools/validate-assets.mjs            -> every asset in the contract
//   node tools/validate-assets.mjs player boss -> only those keys
// Exit code 1 when any asset is missing or violates its contract.
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const contract = JSON.parse(readFileSync(join(root, 'tools', 'asset-contract.json'), 'utf8'));
const assetDir = join(root, 'public', 'assets');

// ---------- minimal GLB reader ----------
function readGlb(path) {
  const buf = readFileSync(path);
  if (buf.readUInt32LE(0) !== 0x46546c67) throw new Error('not a GLB file');
  const jsonLen = buf.readUInt32LE(12);
  const json = JSON.parse(buf.slice(20, 20 + jsonLen).toString('utf8'));
  return { json, size: buf.length };
}

// ---------- mat4 helpers (column-major, glTF) ----------
const ident = () => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
function mul(a, b) {
  const o = new Array(16).fill(0);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
  return o;
}
function trs(t = [0, 0, 0], q = [0, 0, 0, 1], s = [1, 1, 1]) {
  const [x, y, z, w] = q;
  const xx = x * x, yy = y * y, zz = z * z, xy = x * y, xz = x * z, yz = y * z, wx = w * x, wy = w * y, wz = w * z;
  return [
    (1 - 2 * (yy + zz)) * s[0], 2 * (xy + wz) * s[0], 2 * (xz - wy) * s[0], 0,
    2 * (xy - wz) * s[1], (1 - 2 * (xx + zz)) * s[1], 2 * (yz + wx) * s[1], 0,
    2 * (xz + wy) * s[2], 2 * (yz - wx) * s[2], (1 - 2 * (xx + yy)) * s[2], 0,
    t[0], t[1], t[2], 1,
  ];
}
const apply = (m, p) => [
  m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
  m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
  m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14],
];

function analyse(json) {
  const nodes = json.nodes ?? [];
  const parent = new Array(nodes.length).fill(-1);
  nodes.forEach((n, i) => (n.children ?? []).forEach((c) => (parent[c] = i)));
  const world = new Array(nodes.length);
  const local = (n) => (n.matrix ? n.matrix.slice() : trs(n.translation, n.rotation, n.scale));
  const compute = (i) => {
    if (world[i]) return world[i];
    const l = local(nodes[i]);
    world[i] = parent[i] >= 0 ? mul(compute(parent[i]), l) : l;
    return world[i];
  };
  nodes.forEach((_, i) => compute(i));

  const meshTris = (mi) => {
    let t = 0;
    for (const p of json.meshes[mi].primitives) {
      t += p.indices !== undefined ? json.accessors[p.indices].count / 3 : json.accessors[p.attributes.POSITION].count / 3;
    }
    return t;
  };
  const meshBox = (mi) => {
    let mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
    for (const p of json.meshes[mi].primitives) {
      const a = json.accessors[p.attributes.POSITION];
      if (!a.min || !a.max) continue;
      for (let k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], a.min[k]); mx[k] = Math.max(mx[k], a.max[k]); }
    }
    return [mn, mx];
  };
  const descendants = (i, out = []) => {
    for (const c of nodes[i].children ?? []) { out.push(c); descendants(c, out); }
    return out;
  };
  const subtree = (i) => [i, ...descendants(i)];
  const subtreeTris = (i) => subtree(i).reduce((s, n) => s + (nodes[n].mesh !== undefined ? meshTris(nodes[n].mesh) : 0), 0);
  const subtreeBox = (i) => {
    const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
    for (const n of subtree(i)) {
      if (nodes[n].mesh === undefined) continue;
      const [a, b] = meshBox(nodes[n].mesh);
      if (!isFinite(a[0])) continue;
      for (const cx of [a[0], b[0]]) for (const cy of [a[1], b[1]]) for (const cz of [a[2], b[2]]) {
        const p = apply(world[n], [cx, cy, cz]);
        for (let k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], p[k]); mx[k] = Math.max(mx[k], p[k]); }
      }
    }
    return isFinite(mn[0]) ? { min: mn, max: mx, size: [mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]] } : null;
  };
  const byName = new Map();
  nodes.forEach((n, i) => { if (n.name !== undefined) { if (!byName.has(n.name)) byName.set(n.name, []); byName.get(n.name).push(i); } });
  return { nodes, parent, world, byName, subtree, descendants, subtreeTris, subtreeBox };
}

// ---------- checks ----------
function inRange(v, [lo, hi]) { return v >= lo && v <= hi; }
const fmt = (n) => (Math.round(n * 100) / 100).toString();

function checkAsset(key, spec, cache) {
  const errors = [], warnings = [];
  const path = join(assetDir, spec.file);
  if (!existsSync(path)) return { errors: [`missing file public/assets/${spec.file}`], warnings, info: '' };
  let glb;
  try { glb = readGlb(path); } catch (e) { return { errors: [`unreadable GLB: ${e.message}`], warnings, info: '' }; }
  const A = analyse(glb.json);
  cache[key] = A;
  const json = glb.json;
  const totalTris = A.nodes.reduce((s, n) => s + (n.mesh !== undefined ? A.subtreeTris(A.nodes.indexOf(n)) * 0 : 0), 0);
  let tris = 0;
  A.nodes.forEach((n) => { if (n.mesh !== undefined) tris += json.meshes[n.mesh].primitives.reduce((s, p) => s + (p.indices !== undefined ? json.accessors[p.indices].count : json.accessors[p.attributes.POSITION].count) / 3, 0); });
  const id = (name) => A.byName.get(name)?.[0];

  for (const name of spec.requiredNodes ?? []) if (id(name) === undefined) errors.push(`missing node '${name}'`);
  for (const [name, list] of A.byName) {
    if (list.length > 1) warnings.push(`duplicate node name '${name}' x${list.length}`);
    if (/\.\d{3}$/.test(name)) warnings.push(`node '${name}' looks auto-renamed (name clash in Blender)`);
  }
  for (const name of spec.meshNodes ?? []) {
    const i = id(name);
    if (i !== undefined && A.nodes[i].mesh === undefined) errors.push(`node '${name}' has no mesh`);
  }
  for (const [p, c] of spec.hierarchy ?? []) {
    const ci = id(c), pi = id(p);
    if (ci === undefined || pi === undefined) continue;
    if (A.parent[ci] !== pi) errors.push(`'${c}' must be a direct child of '${p}'`);
  }
  if (spec.animations) {
    const have = new Map((json.animations ?? []).map((a) => [a.name, a.channels?.length ?? 0]));
    for (const a of spec.animations) {
      if (!have.has(a)) errors.push(`missing animation '${a}' (have: ${[...have.keys()].join(', ') || 'none'})`);
      else if (have.get(a) < 8) errors.push(`animation '${a}' has only ${have.get(a)} channels`);
    }
  }
  if (spec.triangles && !inRange(tris, spec.triangles)) errors.push(`triangles ${tris} outside ${JSON.stringify(spec.triangles)}`);
  if (spec.emissiveMaterials !== undefined) {
    const n = (json.materials ?? []).filter((m) => (m.emissiveFactor && m.emissiveFactor.some((v) => v > 0.01)) || m.emissiveTexture).length;
    if (n < spec.emissiveMaterials) errors.push(`need >= ${spec.emissiveMaterials} emissive materials, found ${n}`);
  }
  if (spec.minImages !== undefined && (json.images ?? []).length < spec.minImages) errors.push(`need >= ${spec.minImages} embedded images, found ${(json.images ?? []).length}`);

  const axisNames = ['x', 'y', 'z'];
  const checkSize = (label, box, want) => {
    if (!box) { errors.push(`${label}: no geometry`); return; }
    axisNames.forEach((ax, k) => { if (want[ax] && !inRange(box.size[k], want[ax])) errors.push(`${label} size.${ax}=${fmt(box.size[k])} outside ${JSON.stringify(want[ax])}`); });
  };
  if (spec.bounds) {
    const i = id(spec.bounds.node);
    if (i !== undefined) checkSize(spec.bounds.node, A.subtreeBox(i), spec.bounds.size);
  }
  for (const [name, want] of Object.entries(spec.nodeBounds ?? {})) {
    const i = id(name);
    if (i !== undefined) checkSize(name, A.subtreeBox(i), want);
  }
  for (const [name, sign] of Object.entries(spec.sides ?? {})) {
    const i = id(name);
    if (i === undefined) continue;
    const x = A.world[i][12];
    if (Math.sign(x) !== sign) errors.push(`'${name}' must be on the ${sign < 0 ? 'left (-X)' : 'right (+X)'} side (world x=${fmt(x)})`);
  }
  if (spec.descendantPrefixes) {
    const rootName = spec.requiredNodes?.[0];
    const ri = id(rootName);
    if (ri !== undefined) {
      const names = A.descendants(ri).map((d) => A.nodes[d].name ?? '');
      for (const [pre, min] of Object.entries(spec.descendantPrefixes)) {
        const n = names.filter((x) => x.startsWith(pre)).length;
        if (n < min) errors.push(`'${rootName}' needs >= ${min} descendants named ${pre}*, found ${n}`);
      }
    }
  }
  if (spec.chunks) {
    const ri = id(spec.chunks.root);
    if (ri !== undefined) {
      const kids = (A.nodes[ri].children ?? []).map((c) => A.nodes[c]);
      const chunkKids = kids.filter((k) => /^chunk_\d{3}$/.test(k.name ?? ''));
      if (chunkKids.length !== kids.length) errors.push(`'${spec.chunks.root}' children must all be named chunk_NNN (found ${kids.map((k) => k.name).filter((n) => !/^chunk_\d{3}$/.test(n)).slice(0, 4).join(', ')})`);
      if (!inRange(chunkKids.length, [spec.chunks.min, spec.chunks.max])) errors.push(`chunk count ${chunkKids.length} outside [${spec.chunks.min}, ${spec.chunks.max}]`);
      const names = chunkKids.map((k) => k.name).sort();
      names.forEach((n, i) => { if (n !== `chunk_${String(i + 1).padStart(3, '0')}`) { if (!errors.some((e) => e.startsWith('chunk numbering'))) errors.push(`chunk numbering must be contiguous chunk_001..N (saw ${n} at position ${i + 1})`); } });
      let tiny = 0, sizes = [];
      for (const k of chunkKids) {
        if (k.mesh === undefined) { errors.push(`${k.name} has no mesh`); continue; }
        const t = json.meshes[k.mesh].primitives.reduce((s, p) => s + (p.indices !== undefined ? json.accessors[p.indices].count : json.accessors[p.attributes.POSITION].count) / 3, 0);
        if (t < 8) tiny++;
        const [a, b] = (() => { const p = json.meshes[k.mesh].primitives[0]; const ac = json.accessors[p.attributes.POSITION]; return [ac.min, ac.max]; })();
        sizes.push(Math.max(b[0] - a[0], b[1] - a[1], b[2] - a[2]));
      }
      if (tiny) errors.push(`${tiny} chunks have < 8 triangles`);
      if (sizes.length && Math.max(...sizes) / Math.max(1e-6, Math.min(...sizes)) < 1.6) warnings.push('chunk sizes are suspiciously uniform');
    }
  }
  if (spec.groups) {
    for (const g of spec.groups) {
      const tops = A.nodes.map((n, i) => [n, i]).filter(([n, i]) => A.parent[i] === -1 || A.nodes[A.parent[i]]?.name === undefined ? false : false);
      // group candidates: every node (not only top-level) whose name matches prefix/suffix rules and which has children or a mesh
      const members = A.nodes.map((n, i) => [n, i]).filter(([n, i]) => {
        const nm = n.name ?? '';
        if (!nm.startsWith(g.prefix)) return false;
        if (g.excludeSuffix && nm.endsWith(g.excludeSuffix)) return false;
        if (g.suffix && !nm.endsWith(g.suffix)) return false;
        // only the outermost node of a hierarchy with this prefix
        let p = A.parent[i];
        while (p >= 0) { if ((A.nodes[p].name ?? '').startsWith(g.prefix)) return false; p = A.parent[p]; }
        return true;
      });
      if (members.length < g.min) errors.push(`need >= ${g.min} '${g.prefix}*${g.suffix ?? ''}' modules, found ${members.length}`);
      for (const [n, i] of members) {
        const each = g.each ?? {};
        const nm = n.name;
        const kids = A.descendants(i).map((d) => A.nodes[d].name ?? '');
        for (const [pre, min] of Object.entries(each.descendantPrefixes ?? {})) {
          const c = kids.filter((x) => x.startsWith(pre)).length;
          if (c < min) errors.push(`${nm}: needs >= ${min} '${pre}*' descendants, found ${c}`);
        }
        if (each.needsSibling) {
          const sib = each.needsSibling.replace('{name}', nm);
          if (id(sib) === undefined) errors.push(`${nm}: missing LOD node '${sib}'`);
        }
        if (each.triangles) {
          const t = A.subtreeTris(i);
          if (!inRange(t, each.triangles)) errors.push(`${nm}: ${t} triangles outside ${JSON.stringify(each.triangles)}`);
        }
        if (each.size) {
          // ignore collider/slot helper nodes (they have no mesh), so subtree box == visual box
          checkSize(nm, A.subtreeBox(i), each.size);
        }
      }
    }
  }
  return { errors, warnings, info: `${(glb.size / 1024).toFixed(0)} KB, ${tris} tris, ${A.nodes.length} nodes, ${(json.animations ?? []).length} anims, ${(json.images ?? []).length} images` };
}

// cross-asset check: fractured mesh must match intact size
function crossChecks(key, spec, cache, errors) {
  if (!spec.sameSizeAs) return;
  const [otherKey, nodeA, nodeB] = spec.sameSizeAs;
  const O = cache[otherKey], M = cache[key];
  if (!O || !M) return;
  const ia = O.byName.get(nodeA)?.[0], ib = M.byName.get(nodeB)?.[0];
  if (ia === undefined || ib === undefined) return;
  const a = O.subtreeBox(ia), b = M.subtreeBox(ib);
  if (!a || !b) return;
  ['x', 'y', 'z'].forEach((ax, k) => {
    const ratio = b.size[k] / Math.max(1e-6, a.size[k]);
    if (ratio < 0.85 || ratio > 1.15) errors.push(`${nodeB}.size.${ax}=${fmt(b.size[k])} does not match ${nodeA}.size.${ax}=${fmt(a.size[k])}`);
  });
}

const wanted = process.argv.slice(2).filter((a) => !a.startsWith('--'));
if (process.argv.includes('--list')) { console.log(Object.keys(contract.assets).join('\n')); process.exit(0); }
const keys = wanted.length ? wanted : Object.keys(contract.assets);
const cache = {};
let failed = 0;
// load intact first so cross checks work
const ordered = [...keys].sort((a, b) => (a.includes('intact') ? -1 : 0) - (b.includes('intact') ? -1 : 0));
const results = {};
for (const key of ordered) {
  const spec = contract.assets[key];
  if (!spec) { console.error(`unknown asset key '${key}'`); failed++; continue; }
  if (spec.sameSizeAs && !cache[spec.sameSizeAs[0]] && contract.assets[spec.sameSizeAs[0]]) {
    // make sure the reference asset is analysed even when only the fractured one was requested
    const ref = checkAsset(spec.sameSizeAs[0], contract.assets[spec.sameSizeAs[0]], cache);
    void ref;
  }
  const r = checkAsset(key, spec, cache);
  crossChecks(key, spec, cache, r.errors);
  results[key] = r;
}
for (const key of keys) {
  const r = results[key];
  if (!r) continue;
  const ok = r.errors.length === 0;
  if (!ok) failed++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${key.padEnd(34)} ${r.info}`);
  for (const e of r.errors) console.log(`        x ${e}`);
  for (const w of r.warnings.slice(0, 6)) console.log(`        ! ${w}`);
}
console.log(failed ? `\n${failed} asset(s) failed validation` : '\nall assets satisfy the contract');
process.exit(failed ? 1 : 0);

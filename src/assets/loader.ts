import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import contract from '../../tools/asset-contract.json';

/** Asset keys are the keys of tools/asset-contract.json (single source of truth shared with the Blender pipeline). */
export type AssetKey = keyof typeof contract.assets;
export const ASSET_KEYS = Object.keys(contract.assets) as AssetKey[];
export const assetFile = (key: AssetKey): string => (contract.assets[key] as { file: string }).file;

export interface LoadedAsset {
  scene: THREE.Group;
  animations: THREE.AnimationClip[];
}

const BASE = (import.meta as unknown as { env: { BASE_URL: string } }).env.BASE_URL ?? './';

export class Assets {
  private map = new Map<AssetKey, LoadedAsset>();

  async loadAll(onProgress?: (fraction: number, label: string) => void, only?: readonly AssetKey[]): Promise<void> {
    const loader = new GLTFLoader();
    const progress = new Map<AssetKey, number>();
    const keys = only ?? ASSET_KEYS;
    const report = (label: string) => {
      let sum = 0;
      for (const k of keys) sum += progress.get(k) ?? 0;
      onProgress?.(sum / keys.length, label);
    };
    await Promise.all(
      keys.map(async (key) => {
        const url = `${BASE}assets/${assetFile(key)}`;
        try {
          const gltf = await loader.loadAsync(url, (e) => {
            if (e.total > 0) {
              progress.set(key, Math.min(0.99, e.loaded / e.total));
              report(assetFile(key));
            }
          });
          this.map.set(key, { scene: gltf.scene, animations: gltf.animations });
          progress.set(key, 1);
          report(assetFile(key));
        } catch (err) {
          throw new Error(
            `Could not load asset "${assetFile(key)}" (${url}). Generate the assets with "npm run assets" (needs Blender).\n${String(err)}`,
          );
        }
      }),
    );
  }

  get(key: AssetKey): LoadedAsset {
    const a = this.map.get(key);
    if (!a) throw new Error(`asset ${key} not loaded`);
    return a;
  }

  /** Deep clone of the whole asset scene (materials/geometries are shared). */
  cloneScene(key: AssetKey): THREE.Group {
    return this.get(key).scene.clone(true);
  }

  /** Find a named node in the asset (not cloned). */
  node(key: AssetKey, name: string): THREE.Object3D {
    const n = this.get(key).scene.getObjectByName(name);
    if (!n) throw new Error(`asset ${key} has no node ${name}`);
    return n;
  }

  /** Clone one named subtree (e.g. "Drone" or "Column_Fractured"); world transform reset to identity. */
  cloneNode(key: AssetKey, name: string): THREE.Object3D {
    const c = this.node(key, name).clone(true);
    c.position.set(0, 0, 0);
    c.quaternion.identity();
    c.scale.set(1, 1, 1);
    c.updateMatrix();
    return c;
  }
}

/** Utility: apply shadow flags & env intensity to every mesh of a subtree. */
export function prepareMeshes(root: THREE.Object3D, opts: { cast?: boolean; receive?: boolean; envIntensity?: number } = {}) {
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    m.castShadow = opts.cast ?? true;
    m.receiveShadow = opts.receive ?? true;
    const mats = Array.isArray(m.material) ? m.material : [m.material];
    for (const mat of mats) {
      const s = mat as THREE.MeshStandardMaterial;
      if (opts.envIntensity !== undefined && s.isMeshStandardMaterial) s.envMapIntensity = opts.envIntensity;
    }
  });
}

/** Names of nodes inside a subtree keyed for quick lookup (first occurrence wins). */
export function indexNodes(root: THREE.Object3D): Record<string, THREE.Object3D> {
  const out: Record<string, THREE.Object3D> = {};
  root.traverse((o) => {
    if (o.name && !(o.name in out)) out[o.name] = o;
  });
  return out;
}

import * as THREE from 'three';

/** Procedural sunset sky dome, image-based-lighting environment and sun light rig. No textures needed. */

const SKY_VERT = /* glsl */ `
varying vec3 vDir;
void main() {
  vDir = normalize(position);
  vec4 p = projectionMatrix * mat4(mat3(viewMatrix)) * vec4(position, 1.0);
  gl_Position = p.xyww; // always at the far plane
}
`;

const SKY_FRAG = /* glsl */ `
varying vec3 vDir;
uniform vec3 uSunDir;
uniform float uTime;
uniform float uClouds;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
float fbm(vec2 p) {
  float a = 0.5;
  float s = 0.0;
  for (int i = 0; i < 5; i++) {
    s += a * noise(p);
    p = p * 2.03 + vec2(17.3, 9.1);
    a *= 0.5;
  }
  return s;
}

void main() {
  vec3 d = normalize(vDir);
  float h = d.y;
  float sunAmt = max(dot(d, uSunDir), 0.0);

  // vertical gradient: deep indigo zenith -> magenta/violet -> orange -> hot horizon
  vec3 zenith = vec3(0.045, 0.06, 0.24);
  vec3 upper = vec3(0.20, 0.13, 0.42);
  vec3 mid = vec3(0.78, 0.30, 0.36);
  vec3 low = vec3(1.15, 0.48, 0.22);
  vec3 hor = vec3(1.55, 0.70, 0.30);
  float t = clamp(h, 0.0, 1.0);
  vec3 col = mix(hor, low, smoothstep(0.0, 0.06, t));
  col = mix(col, mid, smoothstep(0.05, 0.22, t));
  col = mix(col, upper, smoothstep(0.18, 0.5, t));
  col = mix(col, zenith, smoothstep(0.45, 1.0, t));
  // warm the sky around the sun
  col += vec3(1.7, 0.8, 0.32) * pow(sunAmt, 6.0) * 0.55;
  col += vec3(2.6, 1.5, 0.75) * pow(sunAmt, 48.0) * 1.2;
  col += vec3(9.0, 6.2, 3.6) * pow(sunAmt, 900.0);

  // clouds: two drifting fbm layers projected on a plane, lit from the low sun
  if (uClouds > 0.5 && h > 0.0) {
    vec2 uv = d.xz / (h + 0.12) * 0.55 + vec2(uTime * 0.004, uTime * 0.0015);
    float c1 = fbm(uv * 1.3);
    float c2 = fbm(uv * 3.1 + 11.0);
    float cover = smoothstep(0.46, 0.78, c1 * 0.75 + c2 * 0.35);
    float horizonFade = smoothstep(0.02, 0.22, h);
    // cheap lighting: brighter where the cloud is thin toward the sun
    vec2 sunDir2 = normalize(uSunDir.xz + 1e-4);
    float lit = fbm(uv * 1.3 + sunDir2 * 0.06);
    float rim = clamp((c1 - lit) * 6.0 + 0.45, 0.0, 1.0);
    vec3 shade = vec3(0.30, 0.15, 0.32);
    vec3 lightC = vec3(2.4, 1.05, 0.5) * (0.6 + 0.9 * pow(sunAmt, 2.0));
    vec3 cloudCol = mix(shade, lightC, rim) + vec3(0.6, 0.25, 0.3) * (1.0 - h);
    col = mix(col, cloudCol, cover * horizonFade * 0.85);
  }

  // below the horizon: dusty haze so the far edge of the ground blends in
  if (h < 0.0) {
    vec3 haze = vec3(1.05, 0.5, 0.26) * 0.55;
    col = mix(hor, haze, smoothstep(0.0, 0.08, -h));
    col = mix(col, vec3(0.22, 0.15, 0.16), smoothstep(0.05, 0.5, -h));
  }
  gl_FragColor = vec4(col, 1.0);
}
`;

export class Sky {
  readonly dome: THREE.Mesh;
  readonly sunDir = new THREE.Vector3();
  readonly fogColor = new THREE.Color();
  readonly sun: THREE.DirectionalLight;
  readonly hemi: THREE.HemisphereLight;
  private mat: THREE.ShaderMaterial;
  private shadowSize = 150;
  private shadowRes = 2048;
  private time = 0;

  constructor(scene: THREE.Scene) {
    const elevation = 11 * (Math.PI / 180);
    const azimuth = 118 * (Math.PI / 180);
    this.sunDir.set(Math.sin(azimuth) * Math.cos(elevation), Math.sin(elevation), Math.cos(azimuth) * Math.cos(elevation)).normalize();

    this.mat = new THREE.ShaderMaterial({
      vertexShader: SKY_VERT,
      fragmentShader: SKY_FRAG,
      uniforms: { uSunDir: { value: this.sunDir.clone() }, uTime: { value: 0 }, uClouds: { value: 1 } },
      side: THREE.BackSide,
      depthWrite: false,
      depthTest: false,
      fog: false,
      toneMapped: false,
    });
    this.dome = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24), this.mat);
    this.dome.frustumCulled = false;
    this.dome.renderOrder = -100;
    scene.add(this.dome);

    // fog colour = sky colour at the horizon (matches the shader's `hor` value, slightly dimmed)
    this.fogColor.setRGB(1.05, 0.50, 0.28, THREE.LinearSRGBColorSpace);
    scene.fog = new THREE.FogExp2(this.fogColor, 0.00092);

    this.sun = new THREE.DirectionalLight(0xffb27a, 3.6);
    this.sun.castShadow = true;
    const cam = this.sun.shadow.camera;
    cam.left = -this.shadowSize;
    cam.right = this.shadowSize;
    cam.top = this.shadowSize;
    cam.bottom = -this.shadowSize;
    cam.near = 10;
    cam.far = 700;
    this.sun.shadow.mapSize.set(this.shadowRes, this.shadowRes);
    this.sun.shadow.bias = -0.0004;
    this.sun.shadow.normalBias = 0.35;
    scene.add(this.sun, this.sun.target);

    this.hemi = new THREE.HemisphereLight(0x8a7cc0, 0x4a3026, 0.55);
    scene.add(this.hemi);
  }

  /** Bake the sky into an environment map for metal reflections / ambient light. */
  buildEnvironment(renderer: THREE.WebGLRenderer): THREE.Texture {
    const envScene = new THREE.Scene();
    const mat = this.mat.clone();
    mat.uniforms = { uSunDir: { value: this.sunDir.clone() }, uTime: { value: 3.0 }, uClouds: { value: 1 } };
    const dome = new THREE.Mesh(new THREE.SphereGeometry(10, 32, 16), mat);
    envScene.add(dome);
    const pmrem = new THREE.PMREMGenerator(renderer);
    const rt = pmrem.fromScene(envScene, 0, 0.1, 100);
    pmrem.dispose();
    (dome.geometry as THREE.BufferGeometry).dispose();
    mat.dispose();
    return rt.texture;
  }

  setShadowQuality(res: number, size: number) {
    this.shadowRes = res;
    this.shadowSize = size;
    const cam = this.sun.shadow.camera;
    cam.left = -size;
    cam.right = size;
    cam.top = size;
    cam.bottom = -size;
    cam.updateProjectionMatrix();
    this.sun.shadow.mapSize.set(res, res);
    if (this.sun.shadow.map) {
      this.sun.shadow.map.dispose();
      this.sun.shadow.map = null;
    }
  }

  private _r = new THREE.Vector3();
  private _u = new THREE.Vector3();

  /** Call every frame: keep the dome on the camera and the shadow frustum centred on the player (texel snapped). */
  update(dt: number, camera: THREE.Camera, focus: THREE.Vector3) {
    this.time += dt;
    this.mat.uniforms.uTime.value = this.time;
    this.dome.position.copy(camera.position);
    const far = (camera as THREE.PerspectiveCamera).far ?? 3000;
    this.dome.scale.setScalar(far * 0.9);

    const texel = (this.shadowSize * 2) / this.shadowRes;
    // light-space basis
    const f = this.sunDir;
    this._r.set(0, 1, 0).cross(f).normalize();
    this._u.copy(f).cross(this._r).normalize();
    const r = Math.round(focus.dot(this._r) / texel) * texel;
    const u = Math.round(focus.dot(this._u) / texel) * texel;
    const fw = focus.dot(f);
    const p = this.sun.target.position;
    p.set(0, 0, 0).addScaledVector(this._r, r).addScaledVector(this._u, u).addScaledVector(f, fw);
    this.sun.position.copy(p).addScaledVector(f, 350);
    this.sun.target.updateMatrixWorld();
  }
}

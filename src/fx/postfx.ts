import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

/** Speed / damage / boost screen effects in a single cheap pass (radial blur, chromatic aberration, vignette). */
const SpeedShader = {
  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null },
    uSpeed: { value: 0 },
    uBoost: { value: 0 },
    uDamage: { value: 0 },
    uTime: { value: 0 },
    uAspect: { value: 1 },
    uCenter: { value: new THREE.Vector2(0.5, 0.5) },
    uLock: { value: 0 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float uSpeed;
    uniform float uBoost;
    uniform float uDamage;
    uniform float uTime;
    uniform float uAspect;
    uniform float uLock;
    uniform vec2 uCenter;
    varying vec2 vUv;

    float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

    void main() {
      vec2 dir = vUv - uCenter;
      float r = length(dir * vec2(uAspect, 1.0));
      float amt = uSpeed * 0.018 + uBoost * 0.03;
      // radial blur: 6 taps toward the centre, strength grows with radius
      vec3 col = vec3(0.0);
      float wsum = 0.0;
      for (int i = 0; i < 6; i++) {
        float k = float(i) / 5.0;
        float w = 1.0 - k * 0.5;
        vec2 uv = vUv - dir * amt * k * smoothstep(0.08, 0.7, r) * 2.0;
        // chromatic aberration grows toward the edges
        float ca = (uSpeed * 0.0025 + uBoost * 0.006 + uDamage * 0.004) * r;
        col += vec3(
          texture2D(tDiffuse, uv + dir * ca).r,
          texture2D(tDiffuse, uv).g,
          texture2D(tDiffuse, uv - dir * ca).b
        ) * w;
        wsum += w;
      }
      col /= wsum;
      // vignette
      float vig = smoothstep(0.35, 1.05, r);
      col *= 1.0 - vig * (0.42 + uSpeed * 0.18 + uBoost * 0.12);
      // boost: cool tint at the edges, damage: red pulse at the edges
      col += vec3(0.02, 0.10, 0.22) * vig * uBoost * 0.9;
      col = mix(col, col * vec3(1.6, 0.35, 0.3) + vec3(0.25, 0.0, 0.0) * vig, uDamage * (0.25 + vig * 0.75));
      col += vec3(0.0, 0.05, 0.08) * uLock * vig;
      // subtle film grain to hide banding in the sky gradient
      col += (hash(vUv * 1531.0 + uTime) - 0.5) * 0.012;
      gl_FragColor = vec4(col, 1.0);
    }
  `,
};

export type Quality = 'low' | 'medium' | 'high';

export class PostFX {
  readonly composer: EffectComposer;
  private bloom: UnrealBloomPass;
  private speedPass: ShaderPass;
  private renderPass: RenderPass;
  private outputPass: OutputPass;
  private target: THREE.WebGLRenderTarget;
  bloomEnabled = true;

  constructor(private renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera) {
    const size = renderer.getDrawingBufferSize(new THREE.Vector2());
    size.x = Math.max(2, size.x);
    size.y = Math.max(2, size.y);
    this.target = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(renderer, this.target);
    this.renderPass = new RenderPass(scene, camera);
    this.bloom = new UnrealBloomPass(new THREE.Vector2(size.x, size.y), 0.42, 0.42, 1.05);
    this.speedPass = new ShaderPass(SpeedShader);
    this.outputPass = new OutputPass();
    this.composer.addPass(this.renderPass);
    this.composer.addPass(this.bloom);
    this.composer.addPass(this.speedPass);
    this.composer.addPass(this.outputPass);
  }

  setSize(w: number, h: number, pixelRatio: number) {
    this.composer.setPixelRatio(pixelRatio);
    this.composer.setSize(w, h);
    this.speedPass.uniforms.uAspect.value = w / h;
  }

  setQuality(q: Quality) {
    this.bloomEnabled = q !== 'low';
    this.bloom.enabled = this.bloomEnabled;
    this.bloom.strength = q === 'high' ? 0.46 : 0.38;
    // MSAA on the main target: on for medium/high
    const samples = q === 'low' ? 0 : q === 'medium' ? 2 : 4;
    for (const rt of [this.composer.renderTarget1, this.composer.renderTarget2]) {
      if (rt.samples !== samples) {
        rt.samples = samples;
        rt.dispose();
      }
    }
  }

  update(time: number, speed01: number, boost01: number, damage01: number, lock01: number) {
    const u = this.speedPass.uniforms;
    u.uTime.value = time % 100;
    u.uSpeed.value = speed01;
    u.uBoost.value = boost01;
    u.uDamage.value = damage01;
    u.uLock.value = lock01;
  }

  render(dt: number) {
    this.composer.render(dt);
  }
}

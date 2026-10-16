import * as THREE from 'three';
import {
  createYNULibraryModel,
  createYNULibraryLookDevLights,
  createYNULibraryEnvironment,
} from '../src/createYNULibraryModel.ts';

const params = new URLSearchParams(location.search);
const viewName = params.get('view') || 'front-elevation';
const lightMode = params.get('light') || 'reference';
const azimuth = Number(params.get('az') ?? 'NaN');

const app = document.getElementById('app');
const hud = document.getElementById('hud');

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
app.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color('#bfd3e2');
scene.fog = new THREE.Fog('#c9d8e4', 420, 1200);

const camera = new THREE.PerspectiveCamera(30, window.innerWidth / window.innerHeight, 0.5, 3000);

// Track async texture loads (reference maps load through DefaultLoadingManager).
THREE.DefaultLoadingManager.onLoad = () => {
  window.__SCULPT_LOADED__ = true;
};
THREE.DefaultLoadingManager.onError = (url) => {
  console.warn('texture load error:', url);
};

const root = createYNULibraryModel({ castShadow: true, receiveShadow: true });
scene.add(root);

// ?stripped=1 — map-stripped evidence render for Tier-1 diagnostics: keep shape and
// light response, drop every albedo/roughness/normal map and fall back to flat albedo.
if (params.get('stripped') === '1') {
  const seen = new Set();
  root.traverse((obj) => {
    if (!obj.isMesh && !obj.isInstancedMesh) return;
    const materials = Array.isArray(obj.material) ? obj.material : [obj.material];
    for (const material of materials) {
      if (!material || seen.has(material)) continue;
      seen.add(material);
      const spec = material.userData && material.userData.sculptMaterial;
      const baseColor = spec && typeof spec.baseColor === 'string' ? spec.baseColor : '#8a8a8a';
      material.map = null;
      material.roughnessMap = null;
      material.normalMap = null;
      material.aoMap = null;
      material.bumpMap = null;
      material.color = new THREE.Color(baseColor);
      material.roughness = Math.max(0.6, material.roughness);
      material.needsUpdate = true;
    }
  });
}

const lights = createYNULibraryLookDevLights(lightMode);
for (const light of lights.children) {
  if (light.isDirectionalLight) {
    light.shadow.camera.left = -180;
    light.shadow.camera.right = 180;
    light.shadow.camera.top = 180;
    light.shadow.camera.bottom = -180;
    light.shadow.camera.far = 400;
    light.shadow.camera.updateProjectionMatrix();
    light.shadow.mapSize.set(2048, 2048);
    light.position.multiplyScalar(26);
    light.target.position.set(0, 10, -10);
    scene.add(light.target);
  }
}
scene.add(lights);

scene.environment = createYNULibraryEnvironment(renderer);
scene.environmentIntensity = 0.5;

const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(2400, 2400),
  new THREE.MeshStandardMaterial({ color: 0x6d7f63, roughness: 1.0 }),
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.35;
ground.receiveShadow = true;
scene.add(ground);

const VIEWS = {
  'front-elevation': { pos: [0, 16, 152], target: [0, 15, -14], fov: 30 },
  'front-aerial-3q': { pos: [4, 72, 138], target: [0, 10, -14], fov: 32 },
  'close-aerial': { pos: [78, 98, 52], target: [0, 16, -22], fov: 36 },
  'rear-quarter': { pos: [-84, 104, -128], target: [0, 12, -16], fov: 36 },
  'west-profile': { pos: [-158, 30, 28], target: [0, 13, -12], fov: 30 },
  'east-profile': { pos: [158, 30, 28], target: [0, 13, -12], fov: 30 },
};

function applyView() {
  let spec = VIEWS[viewName] || VIEWS['front-elevation'];
  if (Number.isFinite(azimuth)) {
    const radius = 150;
    const rad = (azimuth * Math.PI) / 180;
    spec = {
      pos: [Math.sin(rad) * radius, 46, Math.cos(rad) * radius],
      target: [0, 12, -8],
      fov: 34,
    };
  }
  camera.fov = spec.fov;
  camera.position.set(...spec.pos);
  camera.lookAt(new THREE.Vector3(...spec.target));
  camera.updateProjectionMatrix();
}
applyView();

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

let frames = 0;
function tick() {
  renderer.render(scene, camera);
  frames += 1;
  if (frames === 5) {
    window.__SCULPT_READY__ = true;
  }
  if (frames % 30 === 0) {
    const info = renderer.info.render;
    hud.textContent = `${viewName} 路 light=${lightMode} 路 tris=${info.triangles} 路 calls=${info.calls}`;
  }
  requestAnimationFrame(tick);
}
tick();

window.__SCULPT_VIEWER__ = { root, scene, camera, renderer, lights, THREE };
window.__SCULPT_STATS__ = () => ({
  triangles: renderer.info.render.triangles,
  calls: renderer.info.render.calls,
  ready: window.__SCULPT_READY__ === true,
});

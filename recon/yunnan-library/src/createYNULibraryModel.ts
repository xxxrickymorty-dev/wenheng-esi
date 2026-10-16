import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { BokehPass } from 'three/examples/jsm/postprocessing/BokehPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { refineYNULibraryModel } from './refineYNULibrary';

export type ProceduralModelOptions = {
  wireframe?: boolean;
  castShadow?: boolean;
  receiveShadow?: boolean;
  textureSize?: number;
  textureAnisotropy?: number;
  qualityPriority?: 'reference-fidelity' | 'balanced';
};

export type ProceduralModelRuntime = {
  nodes: Record<string, THREE.Object3D>;
  meshes: Record<string, THREE.Mesh>;
  sockets: Record<string, THREE.Object3D>;
  colliders: Record<string, unknown>;
  destructionGroups: Record<string, THREE.Object3D[]>;
};

type SculptMaterialSpec = Record<string, any>;

function buildLatheGeometry(profile: { points: [number, number][]; segments?: number }): THREE.LatheGeometry {
  const points = profile.points.map(([x, y]) => new THREE.Vector2(Math.max(0.0001, x), y));
  return new THREE.LatheGeometry(points, profile.segments ?? 24);
}

type TaperedStation = { position: [number, number, number]; rx: number; rz: number; twist?: number };

// Frames come from PARALLEL TRANSPORT, not from a Frenet frame. A Frenet frame is defined by
// the curve's normal, which flips sign wherever the path has an inflection or straightens out,
// and every flip twists the surface 180 degrees within one segment. Carrying the previous frame
// forward and removing only its along-path component keeps the twist continuous. THREE's own
// extrudePath and TubeGeometry do not expose this, which is why this is hand-built.
function buildTaperedSweepGeometry(
  sweep: { stations: TaperedStation[]; radialSegments?: number; capEnds?: boolean },
): THREE.BufferGeometry {
  const stations = sweep.stations;
  if (stations.length < 2) throw new Error('tapered-sweep needs at least two stations');
  const radial = Math.max(3, sweep.radialSegments ?? 10);
  const centres = stations.map((s) => new THREE.Vector3(...s.position));

  const tangents = centres.map((_, i) => {
    const prev = centres[Math.max(0, i - 1)];
    const next = centres[Math.min(centres.length - 1, i + 1)];
    const t = next.clone().sub(prev);
    // Coincident neighbours would normalise to NaN and poison every downstream vertex.
    return t.lengthSq() < 1e-12 ? new THREE.Vector3(0, 1, 0) : t.normalize();
  });

  // Seed a reference axis that is not parallel to the first tangent, or the first cross
  // product is degenerate and the whole sweep collapses to a line.
  let ref = new THREE.Vector3(0, 0, 1);
  if (Math.abs(tangents[0].dot(ref)) > 0.9) ref = new THREE.Vector3(1, 0, 0);

  const normals: THREE.Vector3[] = [];
  const binormals: THREE.Vector3[] = [];
  let carried = ref.clone().sub(tangents[0].clone().multiplyScalar(ref.dot(tangents[0]))).normalize();
  for (let i = 0; i < tangents.length; i += 1) {
    const t = tangents[i];
    // Project the carried frame back onto the plane perpendicular to this tangent.
    const n = carried.clone().sub(t.clone().multiplyScalar(carried.dot(t)));
    if (n.lengthSq() < 1e-12) {
      const fallback = Math.abs(t.y) > 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0);
      n.copy(fallback.sub(t.clone().multiplyScalar(fallback.dot(t))));
    }
    n.normalize();
    normals.push(n);
    binormals.push(new THREE.Vector3().crossVectors(t, n).normalize());
    carried = n;
  }

  const positions: number[] = [];
  const uvs: number[] = [];
  const indices: number[] = [];
  const ringStart: number[] = [];
  const isPoint: boolean[] = [];

  for (let i = 0; i < stations.length; i += 1) {
    const st = stations[i];
    const v = i / (stations.length - 1);
    ringStart.push(positions.length / 3);
    // A station whose section has collapsed emits ONE vertex, not a ring of radius zero.
    // A degenerate ring still carries `radial` coincident vertices and `radial` zero-area
    // triangles, so the lock ends in a blunt cap the width of the floating-point noise
    // rather than at a point -- and a hair lock, a horn or a blade tip has to reach a point.
    if (st.rx <= 1e-6 && st.rz <= 1e-6) {
      isPoint.push(true);
      positions.push(centres[i].x, centres[i].y, centres[i].z);
      uvs.push(0.5, v);
      continue;
    }
    isPoint.push(false);
    const twist = ((st.twist ?? 0) * Math.PI) / 180;
    for (let j = 0; j <= radial; j += 1) {
      const theta = (j / radial) * Math.PI * 2 + twist;
      const offset = normals[i].clone().multiplyScalar(Math.cos(theta) * st.rx)
        .add(binormals[i].clone().multiplyScalar(Math.sin(theta) * st.rz));
      const p = centres[i].clone().add(offset);
      positions.push(p.x, p.y, p.z);
      uvs.push(j / radial, v);
    }
  }

  for (let i = 0; i < stations.length - 1; i += 1) {
    const a0 = ringStart[i];
    const b0 = ringStart[i + 1];
    if (isPoint[i] && isPoint[i + 1]) continue;   // two collapsed stations bound nothing
    for (let j = 0; j < radial; j += 1) {
      // Wound so the face normal points radially OUTWARD.
      //
      // Ring vertices advance from `normal` toward `binormal`, and binormal is
      // tangent x normal, so increasing theta runs counter-clockwise seen from the
      // far end of the segment. Taking the ring-to-ring edge first therefore puts
      // the cross product on the inside. Measured as signed volume on the built
      // mesh: every tapered-sweep came out negative -- a torso at -0.0674 and a
      // tail at -0.0044 against a positive ellipsoid head -- so every sweep this
      // generator has ever emitted rendered its back faces, with normals pointing
      // into the solid and every lighting judgement made on the wrong surface.
      if (isPoint[i]) indices.push(a0, b0 + j + 1, b0 + j);
      else if (isPoint[i + 1]) indices.push(a0 + j, a0 + j + 1, b0);
      else indices.push(a0 + j, a0 + j + 1, b0 + j, a0 + j + 1, b0 + j + 1, b0 + j);
    }
  }

  if (sweep.capEnds ?? true) {
    for (const end of [0, stations.length - 1]) {
      if (isPoint[end]) continue;   // a point end is already closed
      const centreIndex = positions.length / 3;
      positions.push(centres[end].x, centres[end].y, centres[end].z);
      uvs.push(0.5, end === 0 ? 0 : 1);
      const base = ringStart[end];
      for (let j = 0; j < radial; j += 1) {
        if (end === 0) indices.push(centreIndex, base + j + 1, base + j);
        else indices.push(centreIndex, base + j, base + j + 1);
      }
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function readLayerNumber(value: unknown, keys: string[], fallback: number): number {
  if (typeof value === 'number') return value;
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    for (const key of keys) {
      if (typeof record[key] === 'number') return record[key] as number;
    }
  }
  return fallback;
}

function hexToRgb(hex: string): [number, number, number] {
  const normalized = /^#[0-9a-f]{3}$/i.test(hex)
    ? '#' + hex.slice(1).split('').map((part) => part + part).join('')
    : hex;
  const value = /^#[0-9a-f]{6}$/i.test(normalized) ? Number.parseInt(normalized.slice(1), 16) : 0x8a7a5f;
  return [clampAlbedoChannel((value >> 16) & 255), clampAlbedoChannel((value >> 8) & 255), clampAlbedoChannel(value & 255)];
}

function materialPalette(spec: SculptMaterialSpec): string[] {
  const palette = spec.colorVariation?.palette;
  if (Array.isArray(palette) && palette.length > 0) return palette.filter((value) => typeof value === 'string');
  const secondary = spec.albedo?.secondary;
  const colors = [spec.baseColor ?? spec.color ?? spec.albedo?.dominant, ...(Array.isArray(secondary) ? secondary : [])];
  return colors.filter((value): value is string => typeof value === 'string' && value.startsWith('#'));
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function clampAlbedoChannel(value: number): number {
  return Math.max(30, Math.min(240, Math.round(value)));
}

function clampPbrF0(value: number): number {
  return Math.max(0.02, Math.min(1, value));
}

function clampPbrIor(value: number): number {
  return Math.max(1, Math.min(2.5, value));
}

function clampPbrMetalness(value: number): number {
  return value >= 0.5 ? 1 : 0;
}

function clampedAlbedoColor(spec: SculptMaterialSpec): THREE.Color {
  const source = typeof spec.baseColor === 'string' ? spec.baseColor : '#8A7A5F';
  // setStyle with an explicit SRGBColorSpace, NOT the numeric constructor.
  //
  // `new THREE.Color(r, g, b)` treats its arguments as LINEAR working-space components,
  // while an authored `baseColor` hex is sRGB. Feeding one to the other skipped the
  // transfer function and lifted every dark albedo: #2e2a28, authored as a near-black
  // vinyl, rendered at roughly sRGB 0.46 — a mid grey. The error is largest exactly where
  // it matters most, because the transfer curve is steepest near black.
  return new THREE.Color().setStyle(source, THREE.SRGBColorSpace);
}

function smoothCurve(value: number): number {
  return value * value * (3 - 2 * value);
}

function periodicHash(x: number, y: number, seed: number, periodX: number, periodY: number): number {
  const wrappedX = ((x % periodX) + periodX) % periodX;
  const wrappedY = ((y % periodY) + periodY) % periodY;
  let value = Math.imul(wrappedX + seed * 17, 374761393) ^ Math.imul(wrappedY + seed * 31, 668265263);
  value = Math.imul(value ^ (value >>> 13), 1274126177);
  return ((value ^ (value >>> 16)) >>> 0) / 4294967295;
}

function periodicValueNoise(u: number, v: number, seed: number, periodX: number, periodY: number): number {
  const x = u * periodX;
  const y = v * periodY;
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const tx = smoothCurve(x - x0);
  const ty = smoothCurve(y - y0);
  const a = periodicHash(x0, y0, seed, periodX, periodY);
  const b = periodicHash(x0 + 1, y0, seed, periodX, periodY);
  const c = periodicHash(x0, y0 + 1, seed, periodX, periodY);
  const d = periodicHash(x0 + 1, y0 + 1, seed, periodX, periodY);
  return THREE.MathUtils.lerp(THREE.MathUtils.lerp(a, b, tx), THREE.MathUtils.lerp(c, d, tx), ty);
}

type SurfaceBand = {
  frequency: number;
  amplitude: number;
  stretchX: number;
  stretchY: number;
  ridge: boolean;
};

function surfaceBands(spec: SculptMaterialSpec): SurfaceBand[] {
  const source = Array.isArray(spec.surfaceFrequencyBands) ? spec.surfaceFrequencyBands : [];
  const parsed = source.flatMap((item: unknown) => {
    if (!item || typeof item !== 'object') return [];
    const band = item as Record<string, unknown>;
    const frequency = typeof band.frequency === 'number' ? band.frequency : 0;
    const amplitude = typeof band.amplitude === 'number' ? band.amplitude : 0;
    if (frequency <= 0 || amplitude <= 0) return [];
    const stretch = Array.isArray(band.stretch) ? band.stretch : [1, 1];
    const description = `${String(band.pattern ?? '')} ${String(band.role ?? '')}`.toLowerCase();
    return [{
      frequency,
      amplitude,
      stretchX: typeof stretch[0] === 'number' ? Math.max(0.1, stretch[0]) : 1,
      stretchY: typeof stretch[1] === 'number' ? Math.max(0.1, stretch[1]) : 1,
      ridge: /(ridge|groove|grain|fiber|striated|crack)/.test(description),
    }];
  });
  return parsed.length > 0 ? parsed : [
    { frequency: 2, amplitude: 0.42, stretchX: 1, stretchY: 1, ridge: false },
    { frequency: 12, amplitude: 0.22, stretchX: 1, stretchY: 1, ridge: false },
    { frequency: 56, amplitude: 0.08, stretchX: 1, stretchY: 1, ridge: false },
  ];
}

function sampleSurface(u: number, v: number, bands: SurfaceBand[], seed: number): number {
  let value = 0;
  let weight = 0;
  for (let index = 0; index < bands.length; index += 1) {
    const band = bands[index];
    const periodX = Math.max(1, Math.round(band.frequency * band.stretchX));
    const periodY = Math.max(1, Math.round(band.frequency * band.stretchY));
    let sample = periodicValueNoise(u, v, seed + index * 1013, periodX, periodY);
    if (band.ridge) sample = 1 - Math.abs(sample * 2 - 1);
    value += sample * band.amplitude;
    weight += band.amplitude;
  }
  return weight > 0 ? clamp01(value / weight) : 0.5;
}

function mixPalette(colors: [number, number, number][], value: number): [number, number, number] {
  if (colors.length === 1) return colors[0];
  const scaled = clamp01(value) * (colors.length - 1);
  const index = Math.min(colors.length - 2, Math.floor(scaled));
  const mix = scaled - index;
  const a = colors[index];
  const b = colors[index + 1];
  return [
    Math.round(THREE.MathUtils.lerp(a[0], b[0], mix)),
    Math.round(THREE.MathUtils.lerp(a[1], b[1], mix)),
    Math.round(THREE.MathUtils.lerp(a[2], b[2], mix)),
  ];
}

type ColorGradientStop = { offset: number; color: string };
type ColorGradientSpec = {
  type: 'linear' | 'radial';
  axis: [number, number];
  stops: ColorGradientStop[];
};

function parseRgba(value: string): [number, number, number] {
  const match = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(value);
  if (!match) return [138, 122, 95];
  return [clampAlbedoChannel(Number(match[1])), clampAlbedoChannel(Number(match[2])), clampAlbedoChannel(Number(match[3]))];
}

// Analytical per-pixel gradient sample. The extraction schema's colorGradient carries
// exact rgba(...) stop colors (see extract_part_color_recipe.py), so this samples the
// same trend directly in JS math rather than round-tripping through a Canvas 2D
// createLinearGradient/createRadialGradient object — same visual result, and it composes
// directly with the existing noise/height-correlated colorVariation blend below.
function sampleColorGradient(gradient: ColorGradientSpec, u: number, v: number): [number, number, number] {
  const stops = gradient.stops.length >= 2 ? gradient.stops : [{ offset: 0, color: 'rgba(138,122,95,1)' }, { offset: 1, color: 'rgba(138,122,95,1)' }];
  let t: number;
  if (gradient.type === 'radial') {
    const [cx, cy] = gradient.axis;
    const dx = u - cx;
    const dy = v - cy;
    const maxRadius = Math.max(0.001, Math.hypot(Math.max(cx, 1 - cx), Math.max(cy, 1 - cy)));
    t = clamp01(Math.hypot(dx, dy) / maxRadius);
  } else {
    const [ax, ay] = gradient.axis;
    const projection = (u - 0.5) * ax + (v - 0.5) * ay;
    const maxProjection = 0.5 * (Math.abs(ax) + Math.abs(ay)) || 0.5;
    t = clamp01(projection / maxProjection + 0.5);
  }
  const scaled = t * (stops.length - 1);
  const index = Math.min(stops.length - 2, Math.max(0, Math.floor(scaled)));
  const mix = scaled - index;
  const a = parseRgba(stops[index].color);
  const b = parseRgba(stops[index + 1].color);
  return [
    THREE.MathUtils.lerp(a[0], b[0], mix),
    THREE.MathUtils.lerp(a[1], b[1], mix),
    THREE.MathUtils.lerp(a[2], b[2], mix),
  ];
}

function writePixel(data: Uint8ClampedArray, offset: number, red: number, green: number, blue: number): void {
  data[offset] = Math.max(0, Math.min(255, Math.round(red)));
  data[offset + 1] = Math.max(0, Math.min(255, Math.round(green)));
  data[offset + 2] = Math.max(0, Math.min(255, Math.round(blue)));
  data[offset + 3] = 255;
}

function makeCanvas(size: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  return canvas;
}

function createMapTexture(
  canvas: HTMLCanvasElement,
  colorSpace: THREE.ColorSpace,
  spec: SculptMaterialSpec,
  options: ProceduralModelOptions,
): THREE.CanvasTexture {
  const texture = new THREE.CanvasTexture(canvas);
  const projection = spec.textureProjection && typeof spec.textureProjection === 'object' ? spec.textureProjection : {};
  const repeat = Array.isArray(projection.repeat) ? projection.repeat : [2, 2];
  texture.colorSpace = colorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(
    typeof repeat[0] === 'number' ? repeat[0] : 2,
    typeof repeat[1] === 'number' ? repeat[1] : 2,
  );
  texture.anisotropy = Math.max(1, Math.round(options.textureAnisotropy ?? projection.anisotropy ?? 8));
  texture.needsUpdate = true;
  return texture;
}

type ProceduralTextureSet = {
  albedo: THREE.Texture;
  roughness: THREE.Texture;
  height: THREE.Texture;
  normal: THREE.Texture;
  ao: THREE.Texture;
  source: 'reference-pixel-extraction' | 'procedural';
};

function referenceMapUrl(spec: SculptMaterialSpec, channel: string): string | null {
  const reference = spec.referencePbr;
  if (!reference || typeof reference !== 'object') return null;
  if (reference.usable === false) return null;
  const confidence = typeof reference.confidence === 'number'
    ? reference.confidence
    : (typeof reference.estimatedFidelity === 'number' ? reference.estimatedFidelity : 0);
  const threshold = typeof reference.targetThreshold === 'number' ? reference.targetThreshold : 0.7;
  if (confidence < threshold) return null;
  const maps = reference.maps;
  if (!maps || typeof maps !== 'object') return null;
  const map = (maps as Record<string, unknown>)[channel];
  if (!map || typeof map !== 'object') return null;
  const record = map as Record<string, unknown>;
  const url = typeof record.url === 'string' && record.url.trim() ? record.url : record.path;
  return typeof url === 'string' && url.trim() ? url : null;
}

function createLoadedMapTexture(
  url: string,
  colorSpace: THREE.ColorSpace,
  spec: SculptMaterialSpec,
  options: ProceduralModelOptions,
): THREE.Texture {
  const texture = new THREE.TextureLoader().load(url);
  const projection = spec.textureProjection && typeof spec.textureProjection === 'object' ? spec.textureProjection : {};
  const repeat = Array.isArray(projection.repeat) ? projection.repeat : [1, 1];
  texture.colorSpace = colorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(
    typeof repeat[0] === 'number' ? repeat[0] : 1,
    typeof repeat[1] === 'number' ? repeat[1] : 1,
  );
  texture.anisotropy = Math.max(1, Math.round(options.textureAnisotropy ?? projection.anisotropy ?? 8));
  texture.needsUpdate = true;
  return texture;
}

function makeReferenceTextureSet(spec: SculptMaterialSpec, options: ProceduralModelOptions): ProceduralTextureSet | null {
  const albedo = referenceMapUrl(spec, 'albedo');
  const roughness = referenceMapUrl(spec, 'roughness');
  const height = referenceMapUrl(spec, 'height');
  const normal = referenceMapUrl(spec, 'normal');
  const ao = referenceMapUrl(spec, 'ao');
  if (!albedo || !roughness || !height || !normal || !ao) return null;
  return {
    albedo: createLoadedMapTexture(albedo, THREE.SRGBColorSpace, spec, options),
    roughness: createLoadedMapTexture(roughness, THREE.NoColorSpace, spec, options),
    height: createLoadedMapTexture(height, THREE.NoColorSpace, spec, options),
    normal: createLoadedMapTexture(normal, THREE.NoColorSpace, spec, options),
    ao: createLoadedMapTexture(ao, THREE.NoColorSpace, spec, options),
    source: 'reference-pixel-extraction',
  };
}

function makeProceduralTextureSet(
  id: string,
  spec: SculptMaterialSpec,
  options: ProceduralModelOptions,
): ProceduralTextureSet | null {
  if (typeof document === 'undefined') return null;
  const qualityFirst = (options.qualityPriority ?? 'reference-fidelity') === 'reference-fidelity';
  const requested = options.textureSize ?? spec.textureResolution;
  const requestedSize = typeof requested === 'number' && Number.isFinite(requested)
    ? requested
    : (qualityFirst ? 1024 : 512);
  const size = Math.max(256, Math.min(2048, 2 ** Math.round(Math.log2(requestedSize))));
  const canvases = {
    albedo: makeCanvas(size),
    roughness: makeCanvas(size),
    height: makeCanvas(size),
    normal: makeCanvas(size),
    ao: makeCanvas(size),
  };
  const contexts = {
    albedo: canvases.albedo.getContext('2d'),
    roughness: canvases.roughness.getContext('2d'),
    height: canvases.height.getContext('2d'),
    normal: canvases.normal.getContext('2d'),
    ao: canvases.ao.getContext('2d'),
  };
  if (!contexts.albedo || !contexts.roughness || !contexts.height || !contexts.normal || !contexts.ao) return null;
  const images = {
    albedo: contexts.albedo.createImageData(size, size),
    roughness: contexts.roughness.createImageData(size, size),
    height: contexts.height.createImageData(size, size),
    normal: contexts.normal.createImageData(size, size),
    ao: contexts.ao.createImageData(size, size),
  };
  const seed = hashString(id);
  const bands = surfaceBands(spec);
  const heightField = new Float32Array(size * size);
  const roughnessField = new Float32Array(size * size);
  const palette = materialPalette(spec);
  const fallback = typeof spec.baseColor === 'string' ? spec.baseColor : '#8A7A5F';
  const colors = (palette.length >= 2 ? palette : [fallback, '#6E614B', '#A08F70']).map(hexToRgb);
  const baseRoughness = clamp01(readLayerNumber(spec.roughness, ['base'], 0.76));
  const roughnessVariation = clamp01(readLayerNumber(spec.roughness, ['variation'], 0.18));
  const colorAmplitude = clamp01(readLayerNumber(spec.colorVariation, ['amplitude', 'variation'], 0.18));
  const heightCorrelation = clamp01(readLayerNumber(spec.colorVariation, ['heightCorrelation'], 0.3));
  const colorGradient: ColorGradientSpec | undefined = spec.colorGradient;
  for (let y = 0; y < size; y += 1) {
    const v = y / size;
    for (let x = 0; x < size; x += 1) {
      const u = x / size;
      const index = y * size + x;
      const height = sampleSurface(u, v, bands, seed + 101);
      const roughNoise = sampleSurface(u, v, bands, seed + 7001);
      const colorNoise = sampleSurface(u, v, bands, seed + 15013);
      heightField[index] = height;
      roughnessField[index] = clamp01(baseRoughness + (roughNoise - 0.5) * roughnessVariation * 2);
      let color: [number, number, number];
      if (colorGradient) {
        // Evidence-derived spatial gradient (Plan 1.3 Workstream C) takes priority
        // over the noise-based palette blend below — it is a measured trend, not a guess.
        color = sampleColorGradient(colorGradient, u, v);
      } else {
        const paletteValue = clamp01(
          0.5 + (colorNoise - 0.5) * colorAmplitude * 2 + (height - 0.5) * heightCorrelation
        );
        color = mixPalette(colors, paletteValue);
      }
      writePixel(images.albedo.data, index * 4, color[0], color[1], color[2]);
    }
  }
  const normalStrength = Math.max(0.05, readLayerNumber(spec.normal, ['strength', 'amplitude'], 0.35));
  const aoStrength = clamp01(readLayerNumber(spec.ambientOcclusion, ['cavityStrength', 'strength'], 0.35));
  for (let y = 0; y < size; y += 1) {
    const up = ((y - 1 + size) % size) * size;
    const down = ((y + 1) % size) * size;
    for (let x = 0; x < size; x += 1) {
      const left = (x - 1 + size) % size;
      const right = (x + 1) % size;
      const index = y * size + x;
      const center = heightField[index];
      const dx = (heightField[y * size + right] - heightField[y * size + left]) * normalStrength * 6;
      const dy = (heightField[down + x] - heightField[up + x]) * normalStrength * 6;
      const inverseLength = 1 / Math.sqrt(dx * dx + dy * dy + 1);
      const normalX = -dx * inverseLength;
      const normalY = -dy * inverseLength;
      const normalZ = inverseLength;
      const neighborAverage = (
        heightField[y * size + left] + heightField[y * size + right]
        + heightField[up + x] + heightField[down + x]
      ) * 0.25;
      const cavity = Math.max(0, neighborAverage - center);
      const ao = clamp01(1 - aoStrength * (cavity * 12 + (1 - center) * 0.16));
      const offset = index * 4;
      const heightByte = center * 255;
      const roughnessByte = roughnessField[index] * 255;
      writePixel(images.height.data, offset, heightByte, heightByte, heightByte);
      writePixel(images.roughness.data, offset, roughnessByte, roughnessByte, roughnessByte);
      writePixel(
        images.normal.data, offset,
        (normalX * 0.5 + 0.5) * 255,
        (normalY * 0.5 + 0.5) * 255,
        (normalZ * 0.5 + 0.5) * 255,
      );
      writePixel(images.ao.data, offset, ao * 255, ao * 255, ao * 255);
    }
  }
  contexts.albedo.putImageData(images.albedo, 0, 0);
  contexts.roughness.putImageData(images.roughness, 0, 0);
  contexts.height.putImageData(images.height, 0, 0);
  contexts.normal.putImageData(images.normal, 0, 0);
  contexts.ao.putImageData(images.ao, 0, 0);
  return {
    albedo: createMapTexture(canvases.albedo, THREE.SRGBColorSpace, spec, options),
    roughness: createMapTexture(canvases.roughness, THREE.NoColorSpace, spec, options),
    height: createMapTexture(canvases.height, THREE.NoColorSpace, spec, options),
    normal: createMapTexture(canvases.normal, THREE.NoColorSpace, spec, options),
    ao: createMapTexture(canvases.ao, THREE.NoColorSpace, spec, options),
    source: 'procedural',
  };
}

function createSculptMaterial(id: string, spec: SculptMaterialSpec, options: ProceduralModelOptions, denseComponent = false): THREE.MeshPhysicalMaterial {
  // A material that declares -- with evidence -- that its subject carries no texture
  // detail gets NO texture set. Synthesising one anyway is not a harmless default: the
  // branch below then forces color to white and roughness to 1 and reads both from the
  // generated maps, so the authored albedo and the reference-derived roughness are both
  // discarded, and the model gains mottling the reference does not have. Measured on the
  // tuxedo cat, whose black fur rendered as speckled grey-and-white from a palette that
  // only ever described two flat regions.
  const textureless = (spec.textureless as { declared?: boolean } | undefined)?.declared === true;
  const textures = textureless
    ? null
    : makeReferenceTextureSet(spec, options) ?? makeProceduralTextureSet(id, spec, options);
  const material = new THREE.MeshPhysicalMaterial({
    color: textures ? 0xffffff : clampedAlbedoColor(spec),
    roughness: textures ? 1 : clamp01(readLayerNumber(spec.roughness, ['base'], 0.76)),
    metalness: clampPbrMetalness(readLayerNumber(spec.metalness, ['base'], 0.0)),
    clearcoat: clamp01(readLayerNumber(spec.clearcoat, ['base', 'amount'], 0)),
    clearcoatRoughness: clamp01(readLayerNumber(spec.clearcoatRoughness, ['base'], 0.25)),
    transmission: clamp01(readLayerNumber(spec.transmission, ['base', 'amount'], 0)),
    ior: clampPbrIor(readLayerNumber(spec.ior, ['base', 'value'], 1.5)),
    thickness: Math.max(0, readLayerNumber(spec.thickness, ['base', 'amount'], 0)),
    attenuationDistance: Math.max(0.001, readLayerNumber(spec.attenuationDistance, ['base', 'value'], Infinity)),
    attenuationColor: new THREE.Color(typeof spec.attenuationColor === 'string' ? spec.attenuationColor : '#ffffff'),
    sheen: clamp01(readLayerNumber(spec.sheen, ['base', 'amount'], 0)),
    sheenColor: new THREE.Color(typeof spec.sheenColor === 'string' ? spec.sheenColor : '#ffffff'),
    sheenRoughness: clamp01(readLayerNumber(spec.sheenRoughness, ['base'], 1.0)),
    iridescence: clamp01(readLayerNumber(spec.iridescence, ['base', 'amount'], 0)),
    iridescenceIOR: clampPbrIor(readLayerNumber(spec.iridescenceIOR, ['base', 'value'], 1.3)),
    anisotropy: clamp01(readLayerNumber(spec.anisotropy, ['base', 'amount'], 0)),
    anisotropyRotation: readLayerNumber(spec.anisotropy, ['rotation'], 0),
    specularIntensity: clampPbrF0(readLayerNumber(spec.specularF0 ?? spec.f0 ?? spec.specularIntensity, ['base', 'value'], 1.0)),
    specularColor: new THREE.Color(typeof spec.specularColor === 'string' ? spec.specularColor : '#ffffff'),
    emissive: new THREE.Color(typeof spec.emissive === 'string' ? spec.emissive : '#000000'),
    emissiveIntensity: Math.max(0, readLayerNumber(spec.emissiveIntensity, ['base'], 1.0)),
    opacity: clamp01(readLayerNumber(spec.opacity, ['base'], 1)),
    transparent: readLayerNumber(spec.transmission, ['base', 'amount'], 0) > 0 || readLayerNumber(spec.opacity, ['base'], 1) < 1,
    alphaTest: Math.max(0, readLayerNumber(spec.alpha, ['cutoff', 'alphaTest'], 0)),
    wireframe: options.wireframe ?? false,
    side: spec.doubleSided === true ? THREE.DoubleSide : THREE.FrontSide,
    flatShading: spec.flatShading === true,
  });
  if (textures) {
    material.map = textures.albedo;
    material.roughnessMap = textures.roughness;
    material.normalMap = textures.normal;
    material.normalScale.setScalar(Math.max(0.05, readLayerNumber(spec.normal, ['strength', 'amplitude'], 0.35)));
    material.aoMap = textures.ao;
    material.aoMap.channel = 0;
    material.aoMapIntensity = readLayerNumber(spec.ambientOcclusion, ['cavityStrength', 'strength'], 0.35);
    const denseMesh = denseComponent || spec.denseMesh === true || spec.geometryDensity === 'dense' || spec.topologyClass === 'dense';
    const bumpScale = Math.max(0, readLayerNumber(spec.bump, ['amplitude', 'strength'], 0));
    const effectiveBumpScale = denseMesh ? Math.max(0.05, bumpScale) : bumpScale;
    if (effectiveBumpScale > 0) {
      material.bumpMap = textures.height;
      material.bumpScale = effectiveBumpScale;
    }
    const displacementScale = Math.max(0, readLayerNumber(spec.displacement, ['amplitude', 'strength'], 0));
    const effectiveDisplacementScale = denseMesh ? Math.max(0.005, displacementScale) : displacementScale;
    if (effectiveDisplacementScale > 0) {
      material.displacementMap = textures.height;
      material.displacementScale = effectiveDisplacementScale;
      material.displacementBias = -effectiveDisplacementScale * 0.5;
    }
  }
  material.envMapIntensity = readLayerNumber(spec, ['envMapIntensity'], 0.8);
  material.userData.sculptMaterial = spec;
  material.userData.proceduralMapsIndependent = true;
  material.userData.pbrConstraints = { albedoRange: [30, 240], binaryMetalness: true, f0Range: [0.02, 1], iorRange: [1, 2.5] };
  material.userData.pbrTextureSource = textures?.source ?? 'flat-fallback';
  material.userData.referencePbr = spec.referencePbr ?? null;
  material.userData.referenceMaterialId = spec.referenceMaterialId ?? spec.materialReference?.profileId ?? null;
  material.userData.materialEvidence = spec.materialEvidence ?? null;
  material.userData.validationViews = spec.materialReference?.validationViews ?? [];
  material.needsUpdate = true;
  return material;
}

type AttachmentEndpoint = {
  start: THREE.Vector3;
  midpoint: THREE.Vector3;
  quaternion: THREE.Quaternion;
  length: number;
  baseRadius: number;
  endRadius: number;
};

function readVector3(value: unknown, fallback: [number, number, number]): THREE.Vector3 {
  if (Array.isArray(value) && value.length === 3 && value.every((item) => typeof item === 'number')) {
    return new THREE.Vector3(value[0], value[1], value[2]);
  }
  return new THREE.Vector3(fallback[0], fallback[1], fallback[2]);
}

function readNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function makeAttachmentEndpoint(attachment: unknown): AttachmentEndpoint | null {
  if (!attachment || typeof attachment !== 'object') return null;
  const record = attachment as Record<string, unknown>;
  const start = readVector3(record.localStart, [0, 0, 0]);
  const end = readVector3(record.localEnd, [0, 1, 0]);
  const delta = end.clone().sub(start);
  const length = delta.length();
  if (length <= 0.0001) return null;
  const direction = delta.clone().normalize();
  const quaternion = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  const baseRadius = Math.max(0.005, readNumber(record.baseRadius, 0.06));
  const endRadius = Math.max(0.003, readNumber(record.endRadius, baseRadius * 0.55));
  return {
    start,
    midpoint: delta.multiplyScalar(0.5),
    quaternion,
    length,
    baseRadius,
    endRadius,
  };
}

// Generated from ObjectSculptSpec target: YNU Library
// Sculpt build pass: optimization-pass
// This factory is intentionally pass-gated. Finish browser screenshot review before unlocking deeper passes.
export function createYNULibraryModel(options: ProceduralModelOptions = {}): THREE.Group {
  const root = new THREE.Group();
  root.name = "YNU Library";
  root.userData.reconstructionEvidence = {"itemFamily": null, "subtype": null, "componentAdapter": null, "route": null, "exactnessTier": null, "referenceCamera": {"solved": false, "fovDegrees": 40.0, "aspect": 1.0, "orientation": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}, "positionHint": [0.0, 0.0, 3.0], "note": "For likeness work, solve the reference camera (forge/stage1_intake/solve_camera_pose.py) so the review render aligns with the photo and the reference can be projected. Confirm by overlay review."}, "approximationNotes": []};
  root.userData.materialPipeline = {};
  root.userData.materialReferenceRegistry = null;

  const materialMap: Record<string, THREE.Material> = {};
  materialMap["brick-terracotta"] = createSculptMaterial(
    "brick-terracotta",
    {"id": "brick-terracotta", "name": "Terracotta brick", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#B2643C", "color": "#B2643C", "albedo": {"dominant": "#B2643C", "secondary": ["#9C5533", "#C0714A", "#8F4E30"], "samplingNotes": "Warm orange-terracotta brick with subtle tone variation between bays; mortar joints faint."}, "colorVariation": {"palette": ["#B2643C", "#9C5533", "#C0714A", "#8F4E30"], "pattern": "mottled", "amplitude": 0.14, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.88, "variation": 0.19, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [{"id": "ivy-stain", "region": "wing base in courtyard, soft patches up to 8m", "changes": {"dirtAmount": 0.5, "patinaColor": "#3F6B34", "roughnessDelta": 0.05}, "evidenceRef": "zones-ref04/zone-r1c1.png", "confidence": 0.8}], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Warm orange-terracotta brick with subtle tone variation between bays; mortar joints faint.", "referencePbr": {"usable": true, "confidence": 0.815, "estimatedFidelity": 0.815, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\brick-terracotta.png", "palette": ["#78471F", "#8D6824", "#182912", "#5D5530", "#AE7A4B"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\brick-terracotta\\brick-terracotta_albedo.png", "url": "/material-evidence/brick-terracotta/brick-terracotta_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\brick-terracotta\\brick-terracotta_roughness.png", "url": "/material-evidence/brick-terracotta/brick-terracotta_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\brick-terracotta\\brick-terracotta_height.png", "url": "/material-evidence/brick-terracotta/brick-terracotta_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\brick-terracotta\\brick-terracotta_normal.png", "url": "/material-evidence/brick-terracotta/brick-terracotta_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\brick-terracotta\\brick-terracotta_ao.png", "url": "/material-evidence/brick-terracotta/brick-terracotta_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.701, "roughnessVariation": 0.062, "normalStrength": 0.192}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["trim-limestone"] = createSculptMaterial(
    "trim-limestone",
    {"id": "trim-limestone", "name": "Cream limestone trim", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#E7DABC", "color": "#E7DABC", "albedo": {"dominant": "#E7DABC", "secondary": ["#D9CBA8", "#F0E6CC"], "samplingNotes": "Cream string courses, cornices, surrounds, tower panels; painted pale limestone."}, "colorVariation": {"palette": ["#E7DABC", "#D9CBA8", "#F0E6CC"], "pattern": "even", "amplitude": 0.06, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.8, "variation": 0.11, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Cream string courses, cornices, surrounds, tower panels; painted pale limestone.", "referencePbr": {"usable": true, "confidence": 0.769, "estimatedFidelity": 0.769, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\trim-limestone.png", "palette": ["#886635", "#2B4E53", "#A06F35", "#514B30", "#807763"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\trim-limestone\\trim-limestone_albedo.png", "url": "/material-evidence/trim-limestone/trim-limestone_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\trim-limestone\\trim-limestone_roughness.png", "url": "/material-evidence/trim-limestone/trim-limestone_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\trim-limestone\\trim-limestone_height.png", "url": "/material-evidence/trim-limestone/trim-limestone_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\trim-limestone\\trim-limestone_normal.png", "url": "/material-evidence/trim-limestone/trim-limestone_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\trim-limestone\\trim-limestone_ao.png", "url": "/material-evidence/trim-limestone/trim-limestone_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.737, "roughnessVariation": 0.17, "normalStrength": 0.262}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["stone-olive"] = createSculptMaterial(
    "stone-olive",
    {"id": "stone-olive", "name": "Olive stone pier and column", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#B3A67E", "color": "#B3A67E", "albedo": {"dominant": "#B3A67E", "secondary": ["#A49772", "#C2B58C"], "samplingNotes": "Olive-tan portico columns and loggia piers; slight sheen on the sunlit face."}, "colorVariation": {"palette": ["#B3A67E", "#A49772", "#C2B58C"], "pattern": "even", "amplitude": 0.08, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.72, "variation": 0.13, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Olive-tan portico columns and loggia piers; slight sheen on the sunlit face.", "referencePbr": {"usable": true, "confidence": 0.716, "estimatedFidelity": 0.716, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\stone-olive.png", "palette": ["#82787C", "#867B80", "#928686", "#7B7779", "#817474"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_albedo.png", "url": "/material-evidence/stone-olive/stone-olive_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_roughness.png", "url": "/material-evidence/stone-olive/stone-olive_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_height.png", "url": "/material-evidence/stone-olive/stone-olive_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_normal.png", "url": "/material-evidence/stone-olive/stone-olive_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_ao.png", "url": "/material-evidence/stone-olive/stone-olive_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.713, "roughnessVariation": 0.073, "normalStrength": 0.201}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["glass-dark"] = createSculptMaterial(
    "glass-dark",
    {"id": "glass-dark", "name": "Dark curtain glass", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#29424A", "color": "#29424A", "albedo": {"dominant": "#29424A", "secondary": ["#1E343B", "#3A565C"], "samplingNotes": "Deep green-blue glazing; broad low-roughness sky reflection band."}, "colorVariation": {"palette": ["#29424A", "#1E343B", "#3A565C"], "pattern": "even", "amplitude": 0.05, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.12, "variation": 0.1, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.3, "variation": 0.05}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [{"id": "sky-sheen", "region": "full facade glazing band", "changes": {"roughness": 0.08, "specularBoost": 0.35}, "evidenceRef": "refs/ref-03-elevation.png", "confidence": 0.8}], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Deep green-blue glazing; broad low-roughness sky reflection band.", "referencePbr": {"usable": true, "confidence": 0.819, "estimatedFidelity": 0.819, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\glass-dark.png", "palette": ["#2B5157", "#724123", "#CBA27B", "#527071", "#A1805E"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dark\\glass-dark_albedo.png", "url": "/material-evidence/glass-dark/glass-dark_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dark\\glass-dark_roughness.png", "url": "/material-evidence/glass-dark/glass-dark_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dark\\glass-dark_height.png", "url": "/material-evidence/glass-dark/glass-dark_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dark\\glass-dark_normal.png", "url": "/material-evidence/glass-dark/glass-dark_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dark\\glass-dark_ao.png", "url": "/material-evidence/glass-dark/glass-dark_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.698, "roughnessVariation": 0.069, "normalStrength": 0.195}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["glass-dome"] = createSculptMaterial(
    "glass-dome",
    {"id": "glass-dome", "name": "Dome glass", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#7FA0AC", "color": "#7FA0AC", "albedo": {"dominant": "#7FA0AC", "secondary": ["#69899A", "#A8C0C4"], "samplingNotes": "Blue-grey dome glazing in a square pane grid with darker seams."}, "colorVariation": {"palette": ["#7FA0AC", "#69899A", "#A8C0C4"], "pattern": "even", "amplitude": 0.05, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.12, "variation": 0.1, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.15, "variation": 0.05}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [{"id": "grid-seams", "region": "dome shell pane grid", "changes": {"panelLineDarken": 0.35, "roughness": 0.1}, "evidenceRef": "zones-ref04/zone-r0c1.png", "confidence": 0.8}], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Blue-grey dome glazing in a square pane grid with darker seams.", "transmission": {"base": 0.18}, "doubleSided": true, "referencePbr": {"usable": true, "confidence": 0.852, "estimatedFidelity": 0.852, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\glass-dome.png", "palette": ["#81A1B3", "#4E8095", "#5C7D46", "#2D6448", "#E9E8DB"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dome\\glass-dome_albedo.png", "url": "/material-evidence/glass-dome/glass-dome_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dome\\glass-dome_roughness.png", "url": "/material-evidence/glass-dome/glass-dome_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dome\\glass-dome_height.png", "url": "/material-evidence/glass-dome/glass-dome_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dome\\glass-dome_normal.png", "url": "/material-evidence/glass-dome/glass-dome_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-dome\\glass-dome_ao.png", "url": "/material-evidence/glass-dome/glass-dome_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.704, "roughnessVariation": 0.06, "normalStrength": 0.195}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["glass-sky"] = createSculptMaterial(
    "glass-sky",
    {"id": "glass-sky", "name": "Courtyard canopy glass", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#8FB4B4", "color": "#8FB4B4", "albedo": {"dominant": "#8FB4B4", "secondary": ["#7CA6A8", "#B0CCCB"], "samplingNotes": "Barrel-vault and canopy glazing; greenish sheen with frame grid."}, "colorVariation": {"palette": ["#8FB4B4", "#7CA6A8", "#B0CCCB"], "pattern": "even", "amplitude": 0.04, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.15, "variation": 0.09, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.1, "variation": 0.05}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Barrel-vault and canopy glazing; greenish sheen with frame grid.", "transmission": {"base": 0.22}, "doubleSided": true, "referencePbr": {"usable": true, "confidence": 0.86, "estimatedFidelity": 0.86, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\glass-sky.png", "palette": ["#879CAD", "#636D59", "#948969", "#394C3F", "#B5AEAC"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-sky\\glass-sky_albedo.png", "url": "/material-evidence/glass-sky/glass-sky_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-sky\\glass-sky_roughness.png", "url": "/material-evidence/glass-sky/glass-sky_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-sky\\glass-sky_height.png", "url": "/material-evidence/glass-sky/glass-sky_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-sky\\glass-sky_normal.png", "url": "/material-evidence/glass-sky/glass-sky_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\glass-sky\\glass-sky_ao.png", "url": "/material-evidence/glass-sky/glass-sky_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.708, "roughnessVariation": 0.102, "normalStrength": 0.22}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["roof-tile"] = createSculptMaterial(
    "roof-tile",
    {"id": "roof-tile", "name": "Barrel roof tile", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#B05A3A", "color": "#B05A3A", "albedo": {"dominant": "#B05A3A", "secondary": ["#9C4E31", "#C16A46"], "samplingNotes": "Terracotta barrel tiles; fine parallel ribs run down each slope."}, "colorVariation": {"palette": ["#B05A3A", "#9C4E31", "#C16A46"], "pattern": "striped", "amplitude": 0.12, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.2, "role": "roof slope tone shifts"}, {"id": "meso", "frequency": 30.0, "amplitude": 0.24, "role": "barrel-tile rib pattern down slope"}, {"id": "micro", "frequency": 90.0, "amplitude": 0.08, "role": "tile edge highlight breakup"}], "roughness": {"base": 0.86, "variation": 0.17, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [{"id": "barrel-ribs", "region": "every roof slope", "changes": {"roughnessDelta": 0.03, "ribPattern": "linear down-slope", "ribPitch": 0.25}, "evidenceRef": "zones-ref04/zone-r1c1.png", "confidence": 0.8}], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Terracotta barrel tiles; fine parallel ribs run down each slope.", "referencePbr": {"usable": true, "confidence": 0.816, "estimatedFidelity": 0.816, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\roof-tile.png", "palette": ["#6F4A23", "#0C2F0F", "#7C6E47", "#28523E", "#A88556"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-tile\\roof-tile_albedo.png", "url": "/material-evidence/roof-tile/roof-tile_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-tile\\roof-tile_roughness.png", "url": "/material-evidence/roof-tile/roof-tile_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-tile\\roof-tile_height.png", "url": "/material-evidence/roof-tile/roof-tile_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-tile\\roof-tile_normal.png", "url": "/material-evidence/roof-tile/roof-tile_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-tile\\roof-tile_ao.png", "url": "/material-evidence/roof-tile/roof-tile_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.732, "roughnessVariation": 0.131, "normalStrength": 0.237}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["roof-ridge"] = createSculptMaterial(
    "roof-ridge",
    {"id": "roof-ridge", "name": "Ridge and hip cap", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#C08A62", "color": "#C08A62", "albedo": {"dominant": "#C08A62", "secondary": ["#B27C55", "#D09C74"], "samplingNotes": "Pale tan capping along ridges and hips; brighter than the tile field."}, "colorVariation": {"palette": ["#C08A62", "#B27C55", "#D09C74"], "pattern": "even", "amplitude": 0.08, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.8, "variation": 0.13, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Pale tan capping along ridges and hips; brighter than the tile field.", "referencePbr": {"usable": true, "confidence": 0.829, "estimatedFidelity": 0.829, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\roof-ridge.png", "palette": ["#5B682A", "#355725", "#0C391B", "#7B7C43", "#E2A488"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-ridge\\roof-ridge_albedo.png", "url": "/material-evidence/roof-ridge/roof-ridge_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-ridge\\roof-ridge_roughness.png", "url": "/material-evidence/roof-ridge/roof-ridge_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-ridge\\roof-ridge_height.png", "url": "/material-evidence/roof-ridge/roof-ridge_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-ridge\\roof-ridge_normal.png", "url": "/material-evidence/roof-ridge/roof-ridge_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-ridge\\roof-ridge_ao.png", "url": "/material-evidence/roof-ridge/roof-ridge_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.717, "roughnessVariation": 0.08, "normalStrength": 0.203}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["paving-plaza"] = createSculptMaterial(
    "paving-plaza",
    {"id": "paving-plaza", "name": "Plaza paving", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#CDC5B0", "color": "#CDC5B0", "albedo": {"dominant": "#CDC5B0", "secondary": ["#BEB5A0", "#DCD4C0"], "samplingNotes": "Warm grey-beige granite tile field with visible joint grid."}, "colorVariation": {"palette": ["#CDC5B0", "#BEB5A0", "#DCD4C0"], "pattern": "grid", "amplitude": 0.1, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 3.0, "amplitude": 0.2, "role": "tile field tone variation"}, {"id": "meso", "frequency": 16.0, "amplitude": 0.16, "role": "paving joint grid"}, {"id": "micro", "frequency": 60.0, "amplitude": 0.05, "role": "surface speckle"}], "roughness": {"base": 0.95, "variation": 0.15, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Warm grey-beige granite tile field with visible joint grid.", "referencePbr": {"usable": true, "confidence": 0.751, "estimatedFidelity": 0.751, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\paving-plaza.png", "palette": ["#E6C2AA", "#E8C8B1", "#E2BDA5", "#E4C5B0", "#EACDB5"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\paving-plaza\\paving-plaza_albedo.png", "url": "/material-evidence/paving-plaza/paving-plaza_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\paving-plaza\\paving-plaza_roughness.png", "url": "/material-evidence/paving-plaza/paving-plaza_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\paving-plaza\\paving-plaza_height.png", "url": "/material-evidence/paving-plaza/paving-plaza_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\paving-plaza\\paving-plaza_normal.png", "url": "/material-evidence/paving-plaza/paving-plaza_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\paving-plaza\\paving-plaza_ao.png", "url": "/material-evidence/paving-plaza/paving-plaza_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.717, "roughnessVariation": 0.084, "normalStrength": 0.209}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["terrace-stone"] = createSculptMaterial(
    "terrace-stone",
    {"id": "terrace-stone", "name": "Terrace and step stone", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#B9B3A4", "color": "#B9B3A4", "albedo": {"dominant": "#B9B3A4", "secondary": ["#AAA495", "#C8C2B2"], "samplingNotes": "Grey granite for steps, balustrade and terrace edges; pale nosing strips."}, "colorVariation": {"palette": ["#B9B3A4", "#AAA495", "#C8C2B2"], "pattern": "even", "amplitude": 0.08, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.9, "variation": 0.13, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Grey granite for steps, balustrade and terrace edges; pale nosing strips.", "referencePbr": {"usable": true, "confidence": 0.86, "estimatedFidelity": 0.86, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\terrace-stone.png", "palette": ["#E1C0AB", "#927B66", "#A88E77", "#756857", "#DBBAA6"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\terrace-stone\\terrace-stone_albedo.png", "url": "/material-evidence/terrace-stone/terrace-stone_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\terrace-stone\\terrace-stone_roughness.png", "url": "/material-evidence/terrace-stone/terrace-stone_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\terrace-stone\\terrace-stone_height.png", "url": "/material-evidence/terrace-stone/terrace-stone_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\terrace-stone\\terrace-stone_normal.png", "url": "/material-evidence/terrace-stone/terrace-stone_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\terrace-stone\\terrace-stone_ao.png", "url": "/material-evidence/terrace-stone/terrace-stone_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.697, "roughnessVariation": 0.065, "normalStrength": 0.196}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["pool-water"] = createSculptMaterial(
    "pool-water",
    {"id": "pool-water", "name": "Pool water", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#4FB3B8", "color": "#4FB3B8", "albedo": {"dominant": "#4FB3B8", "secondary": ["#3E9EA6", "#6BC6C6"], "samplingNotes": "Turquoise sheet with glassy sky sheen and faint ripple; foam ring at fountain bases."}, "colorVariation": {"palette": ["#4FB3B8", "#3E9EA6", "#6BC6C6"], "pattern": "even", "amplitude": 0.05, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.08, "variation": 0.1, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.05, "variation": 0.05}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [{"id": "specular-sheet", "region": "entire water sheet", "changes": {"roughness": 0.06, "rippleNormal": 0.12, "foamRing": true}, "evidenceRef": "zones-ref03/zone-r2c1.png", "confidence": 0.8}], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Turquoise sheet with glassy sky sheen and faint ripple; foam ring at fountain bases.", "opacity": {"base": 0.93}, "referencePbr": {"usable": true, "confidence": 0.856, "estimatedFidelity": 0.856, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\pool-water.png", "palette": ["#76B8B5", "#76B3AC", "#E3C7B0", "#589494", "#296666"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-water\\pool-water_albedo.png", "url": "/material-evidence/pool-water/pool-water_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-water\\pool-water_roughness.png", "url": "/material-evidence/pool-water/pool-water_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-water\\pool-water_height.png", "url": "/material-evidence/pool-water/pool-water_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-water\\pool-water_normal.png", "url": "/material-evidence/pool-water/pool-water_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-water\\pool-water_ao.png", "url": "/material-evidence/pool-water/pool-water_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.691, "roughnessVariation": 0.05, "normalStrength": 0.181}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["pool-stone"] = createSculptMaterial(
    "pool-stone",
    {"id": "pool-stone", "name": "Pool coping and fountain stone", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#E0DCD0", "color": "#E0DCD0", "albedo": {"dominant": "#E0DCD0", "secondary": ["#D2CEC2", "#EFEBE0"], "samplingNotes": "Pale stone coping tracing the scalloped pool edge and the stepped fountain rings."}, "colorVariation": {"palette": ["#E0DCD0", "#D2CEC2", "#EFEBE0"], "pattern": "even", "amplitude": 0.06, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.85, "variation": 0.11, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Pale stone coping tracing the scalloped pool edge and the stepped fountain rings.", "referencePbr": {"usable": true, "confidence": 0.86, "estimatedFidelity": 0.86, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\pool-stone.png", "palette": ["#71B3AF", "#54838A", "#89B3B0", "#D4BAA5", "#21565B"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-stone\\pool-stone_albedo.png", "url": "/material-evidence/pool-stone/pool-stone_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-stone\\pool-stone_roughness.png", "url": "/material-evidence/pool-stone/pool-stone_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-stone\\pool-stone_height.png", "url": "/material-evidence/pool-stone/pool-stone_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-stone\\pool-stone_normal.png", "url": "/material-evidence/pool-stone/pool-stone_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\pool-stone\\pool-stone_ao.png", "url": "/material-evidence/pool-stone/pool-stone_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.687, "roughnessVariation": 0.05, "normalStrength": 0.182}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["lawn-turf"] = createSculptMaterial(
    "lawn-turf",
    {"id": "lawn-turf", "name": "Turf", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#5D7F3B", "color": "#5D7F3B", "albedo": {"dominant": "#5D7F3B", "secondary": ["#4F7134", "#6C9046"], "samplingNotes": "Mown turf strips on the parterre and lawn fields."}, "colorVariation": {"palette": ["#5D7F3B", "#4F7134", "#6C9046"], "pattern": "mottled", "amplitude": 0.18, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 3.0, "amplitude": 0.3, "role": "patch tone variation"}, {"id": "meso", "frequency": 24.0, "amplitude": 0.18, "role": "clump shading"}, {"id": "micro", "frequency": 80.0, "amplitude": 0.06, "role": "blade speckle"}], "roughness": {"base": 1.0, "variation": 0.23, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Mown turf strips on the parterre and lawn fields.", "referencePbr": {"usable": true, "confidence": 0.829, "estimatedFidelity": 0.829, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\lawn-turf.png", "palette": ["#BC8A08", "#1A2708", "#8C7015", "#4F4B24", "#D5AF89"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\lawn-turf\\lawn-turf_albedo.png", "url": "/material-evidence/lawn-turf/lawn-turf_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\lawn-turf\\lawn-turf_roughness.png", "url": "/material-evidence/lawn-turf/lawn-turf_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\lawn-turf\\lawn-turf_height.png", "url": "/material-evidence/lawn-turf/lawn-turf_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\lawn-turf\\lawn-turf_normal.png", "url": "/material-evidence/lawn-turf/lawn-turf_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\lawn-turf\\lawn-turf_ao.png", "url": "/material-evidence/lawn-turf/lawn-turf_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.707, "roughnessVariation": 0.07, "normalStrength": 0.199}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["hedge-purple"] = createSculptMaterial(
    "hedge-purple",
    {"id": "hedge-purple", "name": "Plum hedge blocks", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#4A2F3E", "color": "#4A2F3E", "albedo": {"dominant": "#4A2F3E", "secondary": ["#3C2532", "#5A3A4A"], "samplingNotes": "Dark plum clipped hedge blocks in rows on the parterre."}, "colorVariation": {"palette": ["#4A2F3E", "#3C2532", "#5A3A4A"], "pattern": "mottled", "amplitude": 0.12, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.95, "variation": 0.17, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Dark plum clipped hedge blocks in rows on the parterre.", "referencePbr": {"usable": true, "confidence": 0.829, "estimatedFidelity": 0.829, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\hedge-purple.png", "palette": ["#C39508", "#A8830E", "#44382C", "#7F6818", "#DCB999"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\hedge-purple\\hedge-purple_albedo.png", "url": "/material-evidence/hedge-purple/hedge-purple_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\hedge-purple\\hedge-purple_roughness.png", "url": "/material-evidence/hedge-purple/hedge-purple_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\hedge-purple\\hedge-purple_height.png", "url": "/material-evidence/hedge-purple/hedge-purple_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\hedge-purple\\hedge-purple_normal.png", "url": "/material-evidence/hedge-purple/hedge-purple_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\hedge-purple\\hedge-purple_ao.png", "url": "/material-evidence/hedge-purple/hedge-purple_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.708, "roughnessVariation": 0.101, "normalStrength": 0.223}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["foliage-green"] = createSculptMaterial(
    "foliage-green",
    {"id": "foliage-green", "name": "Tree foliage", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#4C6B3B", "color": "#4C6B3B", "albedo": {"dominant": "#4C6B3B", "secondary": ["#3C5A30", "#5E7F47", "#6E8F52"], "samplingNotes": "Plane-tree canopies: several green tones between crowns and within a crown."}, "colorVariation": {"palette": ["#4C6B3B", "#3C5A30", "#5E7F47", "#6E8F52"], "pattern": "mottled", "amplitude": 0.2, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.32, "role": "canopy mass variation"}, {"id": "meso", "frequency": 20.0, "amplitude": 0.2, "role": "leaf clump breakup"}, {"id": "micro", "frequency": 70.0, "amplitude": 0.08, "role": "leaf speckle"}], "roughness": {"base": 1.0, "variation": 0.25, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Plane-tree canopies: several green tones between crowns and within a crown.", "referencePbr": {"usable": true, "confidence": 0.86, "estimatedFidelity": 0.86, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\foliage-green.png", "palette": ["#203726", "#334F12", "#808379", "#53583B", "#516A0B"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\foliage-green\\foliage-green_albedo.png", "url": "/material-evidence/foliage-green/foliage-green_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\foliage-green\\foliage-green_roughness.png", "url": "/material-evidence/foliage-green/foliage-green_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\foliage-green\\foliage-green_height.png", "url": "/material-evidence/foliage-green/foliage-green_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\foliage-green\\foliage-green_normal.png", "url": "/material-evidence/foliage-green/foliage-green_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\foliage-green\\foliage-green_ao.png", "url": "/material-evidence/foliage-green/foliage-green_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.703, "roughnessVariation": 0.084, "normalStrength": 0.208}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["bark-brown"] = createSculptMaterial(
    "bark-brown",
    {"id": "bark-brown", "name": "Trunk bark", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#6E5C49", "color": "#6E5C49", "albedo": {"dominant": "#6E5C49", "secondary": ["#5C4C3B", "#7E6C56"], "samplingNotes": "Pale grey-brown plane-tree trunks."}, "colorVariation": {"palette": ["#6E5C49", "#5C4C3B", "#7E6C56"], "pattern": "striped", "amplitude": 0.12, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 1.0, "variation": 0.17, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Pale grey-brown plane-tree trunks.", "referencePbr": {"usable": true, "confidence": 0.85, "estimatedFidelity": 0.85, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\bark-brown.png", "palette": ["#5C7A84", "#4E636B", "#7F867C", "#384F1A", "#5E6349"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\bark-brown\\bark-brown_albedo.png", "url": "/material-evidence/bark-brown/bark-brown_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\bark-brown\\bark-brown_roughness.png", "url": "/material-evidence/bark-brown/bark-brown_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\bark-brown\\bark-brown_height.png", "url": "/material-evidence/bark-brown/bark-brown_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\bark-brown\\bark-brown_normal.png", "url": "/material-evidence/bark-brown/bark-brown_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\bark-brown\\bark-brown_ao.png", "url": "/material-evidence/bark-brown/bark-brown_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.685, "roughnessVariation": 0.062, "normalStrength": 0.197}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["steel-dark"] = createSculptMaterial(
    "steel-dark",
    {"id": "steel-dark", "name": "Dark steel frame", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#5F6B68", "color": "#5F6B68", "albedo": {"dominant": "#5F6B68", "secondary": ["#4F5B58", "#71807C"], "samplingNotes": "Vault ribs, canopy frames, window mullions where steel reads dark."}, "colorVariation": {"palette": ["#5F6B68", "#4F5B58", "#71807C"], "pattern": "even", "amplitude": 0.05, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.4, "variation": 0.1, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.7, "variation": 0.05}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Vault ribs, canopy frames, window mullions where steel reads dark.", "referencePbr": {"usable": true, "confidence": 0.86, "estimatedFidelity": 0.86, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\steel-dark.png", "palette": ["#879CAE", "#5D6A57", "#837E62", "#33493D", "#A1926F"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\steel-dark\\steel-dark_albedo.png", "url": "/material-evidence/steel-dark/steel-dark_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\steel-dark\\steel-dark_roughness.png", "url": "/material-evidence/steel-dark/steel-dark_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\steel-dark\\steel-dark_height.png", "url": "/material-evidence/steel-dark/steel-dark_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\steel-dark\\steel-dark_normal.png", "url": "/material-evidence/steel-dark/steel-dark_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\steel-dark\\steel-dark_ao.png", "url": "/material-evidence/steel-dark/steel-dark_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.709, "roughnessVariation": 0.103, "normalStrength": 0.217}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["dome-frame"] = createSculptMaterial(
    "dome-frame",
    {"id": "dome-frame", "name": "Dome frame", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#9FA8A2", "color": "#9FA8A2", "albedo": {"dominant": "#9FA8A2", "secondary": ["#8E9792", "#B2BAB4"], "samplingNotes": "Pale grey-green dome ribs, rings and drum mullions."}, "colorVariation": {"palette": ["#9FA8A2", "#8E9792", "#B2BAB4"], "pattern": "even", "amplitude": 0.04, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.5, "variation": 0.09, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.35, "variation": 0.05}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Pale grey-green dome ribs, rings and drum mullions.", "referencePbr": {"usable": true, "confidence": 0.86, "estimatedFidelity": 0.86, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\dome-frame.png", "palette": ["#84A3B5", "#56859A", "#5E7E48", "#2D6345", "#E4E3D6"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\dome-frame\\dome-frame_albedo.png", "url": "/material-evidence/dome-frame/dome-frame_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\dome-frame\\dome-frame_roughness.png", "url": "/material-evidence/dome-frame/dome-frame_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\dome-frame\\dome-frame_height.png", "url": "/material-evidence/dome-frame/dome-frame_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\dome-frame\\dome-frame_normal.png", "url": "/material-evidence/dome-frame/dome-frame_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\dome-frame\\dome-frame_ao.png", "url": "/material-evidence/dome-frame/dome-frame_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.698, "roughnessVariation": 0.05, "normalStrength": 0.184}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["equipment-white"] = createSculptMaterial(
    "equipment-white",
    {"id": "equipment-white", "name": "Roof equipment", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#E8E6E0", "color": "#E8E6E0", "albedo": {"dominant": "#E8E6E0", "secondary": ["#DAD8D2", "#F2F0EA"], "samplingNotes": "White AC boxes and pale equipment on the central deck."}, "colorVariation": {"palette": ["#E8E6E0", "#DAD8D2", "#F2F0EA"], "pattern": "even", "amplitude": 0.05, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.7, "variation": 0.1, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "White AC boxes and pale equipment on the central deck.", "referencePbr": {"usable": true, "confidence": 0.86, "estimatedFidelity": 0.86, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\equipment-white.png", "palette": ["#B4B6B8", "#985A31", "#B77349", "#92887D", "#E2D4C5"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\equipment-white\\equipment-white_albedo.png", "url": "/material-evidence/equipment-white/equipment-white_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\equipment-white\\equipment-white_roughness.png", "url": "/material-evidence/equipment-white/equipment-white_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\equipment-white\\equipment-white_height.png", "url": "/material-evidence/equipment-white/equipment-white_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\equipment-white\\equipment-white_normal.png", "url": "/material-evidence/equipment-white/equipment-white_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\equipment-white\\equipment-white_ao.png", "url": "/material-evidence/equipment-white/equipment-white_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.689, "roughnessVariation": 0.051, "normalStrength": 0.189}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["roof-deck"] = createSculptMaterial(
    "roof-deck",
    {"id": "roof-deck", "name": "Central roof deck", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#D8D2C2", "color": "#D8D2C2", "albedo": {"dominant": "#D8D2C2", "secondary": ["#C9C3B3", "#E4DFCF"], "samplingNotes": "Pale waterproofing deck with panel seams; solar heaters and skylight strips on top."}, "colorVariation": {"palette": ["#D8D2C2", "#C9C3B3", "#E4DFCF"], "pattern": "grid", "amplitude": 0.06, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.9, "variation": 0.11, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Pale waterproofing deck with panel seams; solar heaters and skylight strips on top.", "referencePbr": {"usable": true, "confidence": 0.82, "estimatedFidelity": 0.82, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\roof-deck.png", "palette": ["#EED7B0", "#866C43", "#A8865D", "#E3C6A8", "#CCAF99"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-deck\\roof-deck_albedo.png", "url": "/material-evidence/roof-deck/roof-deck_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-deck\\roof-deck_roughness.png", "url": "/material-evidence/roof-deck/roof-deck_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-deck\\roof-deck_height.png", "url": "/material-evidence/roof-deck/roof-deck_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-deck\\roof-deck_normal.png", "url": "/material-evidence/roof-deck/roof-deck_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\roof-deck\\roof-deck_ao.png", "url": "/material-evidence/roof-deck/roof-deck_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.69, "roughnessVariation": 0.05, "normalStrength": 0.18}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["banner-red"] = createSculptMaterial(
    "banner-red",
    {"id": "banner-red", "name": "Entrance banner", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#B23326", "color": "#B23326", "albedo": {"dominant": "#B23326", "secondary": ["#9E2B1F", "#C63D2E"], "samplingNotes": "Two saturated red vertical banners flanking the entrance doors."}, "colorVariation": {"palette": ["#B23326", "#9E2B1F", "#C63D2E"], "pattern": "even", "amplitude": 0.06, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.75, "variation": 0.11, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Two saturated red vertical banners flanking the entrance doors.", "referencePbr": {"usable": true, "confidence": 0.86, "estimatedFidelity": 0.86, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\banner-red.png", "palette": ["#061114", "#242F34", "#D1AE99", "#806D5D", "#863120"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\banner-red\\banner-red_albedo.png", "url": "/material-evidence/banner-red/banner-red_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\banner-red\\banner-red_roughness.png", "url": "/material-evidence/banner-red/banner-red_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\banner-red\\banner-red_height.png", "url": "/material-evidence/banner-red/banner-red_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\banner-red\\banner-red_normal.png", "url": "/material-evidence/banner-red/banner-red_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\banner-red\\banner-red_ao.png", "url": "/material-evidence/banner-red/banner-red_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.688, "roughnessVariation": 0.05, "normalStrength": 0.178}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
    options
  );
  materialMap["invisible-root"] = createSculptMaterial(
    "invisible-root",
    {"id": "invisible-root", "name": "Container (hidden)", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#6E6759", "color": "#6E6759", "albedo": {"dominant": "#6E6759", "secondary": ["#5F594C", "#7D7666"], "samplingNotes": "Container material for the root group: complete PBR so it passes the gate, but opacity 0 so the container box itself never renders (geometry_patterns.md rule)."}, "colorVariation": {"palette": ["#6E6759", "#5F594C", "#7D7666"], "pattern": "even", "amplitude": 0.05, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.9, "variation": 0.1, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Container material for the root group: complete PBR so it passes the gate, but opacity 0 so the container box itself never renders (geometry_patterns.md rule).", "opacity": {"base": 0.0}, "qualityTier": "utility"},
    options
  );

  const nodes: Record<string, THREE.Object3D> = { root };
  const meshes: Record<string, THREE.Mesh> = {};
  const sockets: Record<string, THREE.Object3D> = {};
  const colliders: Record<string, unknown> = {};
  const destructionGroups: Record<string, THREE.Object3D[]> = {};

  const endpoint_root_0 = makeAttachmentEndpoint(null);
  const node_root_0 = new THREE.Group();
  node_root_0.name = "YNU Library__pivot";
  node_root_0.scale.set(1, 1, 1);
  if (endpoint_root_0) {
    node_root_0.position.copy(endpoint_root_0.start);
    node_root_0.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_root_0.position.set(0.0, 0.0, 0.0);
    node_root_0.rotation.set(0.0, 0.0, 0.0);
  }
  node_root_0.userData.sculptComponent = {"id": "root", "name": "YNU Library", "level": "macro", "role": "body", "importance": 1.0, "confidence": 0.9, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Container root (geometry hidden by the invisible-root material). Identity: symmetric domed library on an axial plaza. Forward is +Z (plaza side).", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": null, "attachment": null, "dimensions": {"width": 1, "height": 1, "depth": 1, "units": "relative", "confidence": 0.9}, "transform": {"position": [0, 0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "root", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.9}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "root", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "invisible-root"}}, "material": "invisible-root", "materialLayers": ["invisible-root"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q", "view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(110, 103, 89, 1.0)", "secondaryAlbedo": "rgba(95, 89, 76, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_root_0.userData.actionProfile = {"animationRole": "root", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.9}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "root", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "invisible-root"}};
  (nodes["root"] ?? root).add(node_root_0);
  nodes["root"] = node_root_0;
  const mesh_root_0Geometry = endpoint_root_0
    ? new THREE.CylinderGeometry(endpoint_root_0.endRadius, endpoint_root_0.baseRadius, endpoint_root_0.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_root_0) {
    mesh_root_0Geometry.scale(1.0, 1.0, 1.0);
  }
  const mesh_root_0 = new THREE.Mesh(
    mesh_root_0Geometry,
    materialMap["invisible-root"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_root_0.name = "YNU Library";
  if (endpoint_root_0) {
    mesh_root_0.position.copy(endpoint_root_0.midpoint);
    mesh_root_0.quaternion.copy(endpoint_root_0.quaternion);
  }
  mesh_root_0.castShadow = options.castShadow ?? true;
  mesh_root_0.receiveShadow = options.receiveShadow ?? true;
  mesh_root_0.userData.sculptComponent = {"id": "root", "name": "YNU Library", "level": "macro", "role": "body", "importance": 1.0, "confidence": 0.9, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Container root (geometry hidden by the invisible-root material). Identity: symmetric domed library on an axial plaza. Forward is +Z (plaza side).", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": null, "attachment": null, "dimensions": {"width": 1, "height": 1, "depth": 1, "units": "relative", "confidence": 0.9}, "transform": {"position": [0, 0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "root", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.9}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "root", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "invisible-root"}}, "material": "invisible-root", "materialLayers": ["invisible-root"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q", "view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(110, 103, 89, 1.0)", "secondaryAlbedo": "rgba(95, 89, 76, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_root_0.add(mesh_root_0);
  meshes["root"] = mesh_root_0;
  colliders["root"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["root"] ??= [];
  destructionGroups["root"].push(node_root_0);

  const endpoint_terrace_podium_1 = makeAttachmentEndpoint(null);
  const node_terrace_podium_1 = new THREE.Group();
  node_terrace_podium_1.name = "Terrace podium__pivot";
  node_terrace_podium_1.scale.set(1, 1, 1);
  if (endpoint_terrace_podium_1) {
    node_terrace_podium_1.position.copy(endpoint_terrace_podium_1.start);
    node_terrace_podium_1.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_terrace_podium_1.position.set(0.0, 1.2, -24.0);
    node_terrace_podium_1.rotation.set(0.0, 0.0, 0.0);
  }
  node_terrace_podium_1.userData.sculptComponent = {"id": "terrace-podium", "name": "Terrace podium", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.75, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Stone base platform carrying the building; front edge meets the grand steps.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 152, "height": 2.4, "depth": 68, "units": "relative", "confidence": 0.75}, "transform": {"position": [0, 1.2, -24], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.75}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "terrace-podium", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_terrace_podium_1.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.75}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "terrace-podium", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}};
  (nodes["root"] ?? root).add(node_terrace_podium_1);
  nodes["terrace-podium"] = node_terrace_podium_1;
  const mesh_terrace_podium_1Geometry = endpoint_terrace_podium_1
    ? new THREE.CylinderGeometry(endpoint_terrace_podium_1.endRadius, endpoint_terrace_podium_1.baseRadius, endpoint_terrace_podium_1.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_terrace_podium_1) {
    mesh_terrace_podium_1Geometry.scale(152.0, 2.4, 68.0);
  }
  const mesh_terrace_podium_1 = new THREE.Mesh(
    mesh_terrace_podium_1Geometry,
    materialMap["terrace-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_terrace_podium_1.name = "Terrace podium";
  if (endpoint_terrace_podium_1) {
    mesh_terrace_podium_1.position.copy(endpoint_terrace_podium_1.midpoint);
    mesh_terrace_podium_1.quaternion.copy(endpoint_terrace_podium_1.quaternion);
  }
  mesh_terrace_podium_1.castShadow = options.castShadow ?? true;
  mesh_terrace_podium_1.receiveShadow = options.receiveShadow ?? true;
  mesh_terrace_podium_1.userData.sculptComponent = {"id": "terrace-podium", "name": "Terrace podium", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.75, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Stone base platform carrying the building; front edge meets the grand steps.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 152, "height": 2.4, "depth": 68, "units": "relative", "confidence": 0.75}, "transform": {"position": [0, 1.2, -24], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.75}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "terrace-podium", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_terrace_podium_1.add(mesh_terrace_podium_1);
  meshes["terrace-podium"] = mesh_terrace_podium_1;
  colliders["terrace-podium"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["terrace-podium"] ??= [];
  destructionGroups["terrace-podium"].push(node_terrace_podium_1);

  const endpoint_podium_slab_2 = makeAttachmentEndpoint(null);
  const node_podium_slab_2 = new THREE.Group();
  node_podium_slab_2.name = "Podium slab__pivot";
  node_podium_slab_2.scale.set(1, 1, 1);
  if (endpoint_podium_slab_2) {
    node_podium_slab_2.position.copy(endpoint_podium_slab_2.start);
    node_podium_slab_2.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_podium_slab_2.position.set(0.0, 0.0, 0.0);
    node_podium_slab_2.rotation.set(0.0, 0.0, 0.0);
  }
  node_podium_slab_2.userData.sculptComponent = {"id": "podium-slab", "name": "Podium slab", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Main slab of the podium, visible as the stone base line under the wings.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "terrace-podium", "attachment": null, "dimensions": {"width": 152, "height": 2.4, "depth": 68, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "podium-slab", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_podium_slab_2.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "podium-slab", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}};
  (nodes["terrace-podium"] ?? root).add(node_podium_slab_2);
  nodes["podium-slab"] = node_podium_slab_2;
  const mesh_podium_slab_2Geometry = endpoint_podium_slab_2
    ? new THREE.CylinderGeometry(endpoint_podium_slab_2.endRadius, endpoint_podium_slab_2.baseRadius, endpoint_podium_slab_2.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_podium_slab_2) {
    mesh_podium_slab_2Geometry.scale(152.0, 2.4, 68.0);
  }
  const mesh_podium_slab_2 = new THREE.Mesh(
    mesh_podium_slab_2Geometry,
    materialMap["terrace-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_podium_slab_2.name = "Podium slab";
  if (endpoint_podium_slab_2) {
    mesh_podium_slab_2.position.copy(endpoint_podium_slab_2.midpoint);
    mesh_podium_slab_2.quaternion.copy(endpoint_podium_slab_2.quaternion);
  }
  mesh_podium_slab_2.castShadow = options.castShadow ?? true;
  mesh_podium_slab_2.receiveShadow = options.receiveShadow ?? true;
  mesh_podium_slab_2.userData.sculptComponent = {"id": "podium-slab", "name": "Podium slab", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Main slab of the podium, visible as the stone base line under the wings.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "terrace-podium", "attachment": null, "dimensions": {"width": 152, "height": 2.4, "depth": 68, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "podium-slab", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_podium_slab_2.add(mesh_podium_slab_2);
  meshes["podium-slab"] = mesh_podium_slab_2;
  colliders["podium-slab"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["podium-slab"] ??= [];
  destructionGroups["podium-slab"].push(node_podium_slab_2);

  const endpoint_grand_steps_3 = makeAttachmentEndpoint(null);
  const node_grand_steps_3 = new THREE.Group();
  node_grand_steps_3.name = "Grand steps__pivot";
  node_grand_steps_3.scale.set(1, 1, 1);
  if (endpoint_grand_steps_3) {
    node_grand_steps_3.position.copy(endpoint_grand_steps_3.start);
    node_grand_steps_3.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_grand_steps_3.position.set(0.0, 0.0, 37.0);
    node_grand_steps_3.rotation.set(0.0, 0.0, 0.0);
  }
  node_grand_steps_3.userData.sculptComponent = {"id": "grand-steps", "name": "Grand steps", "level": "meso", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Three wide flights from the plaza up to the terrace, centered on the axis; real riser steps authored in the factory helper.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "terrace-podium", "attachment": null, "dimensions": {"width": 30, "height": 2.4, "depth": 10, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 37], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "grand-steps", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "nosing-bands", "description": "Pale stone nosing strip along every riser; three wide flights with landing bands."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png", "zones-ref04/zone-r2c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_grand_steps_3.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "grand-steps", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}};
  (nodes["terrace-podium"] ?? root).add(node_grand_steps_3);
  nodes["grand-steps"] = node_grand_steps_3;
  const mesh_grand_steps_3Geometry = endpoint_grand_steps_3
    ? new THREE.CylinderGeometry(endpoint_grand_steps_3.endRadius, endpoint_grand_steps_3.baseRadius, endpoint_grand_steps_3.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_grand_steps_3) {
    mesh_grand_steps_3Geometry.scale(30.0, 2.4, 10.0);
  }
  const mesh_grand_steps_3 = new THREE.Mesh(
    mesh_grand_steps_3Geometry,
    materialMap["terrace-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_grand_steps_3.name = "Grand steps";
  if (endpoint_grand_steps_3) {
    mesh_grand_steps_3.position.copy(endpoint_grand_steps_3.midpoint);
    mesh_grand_steps_3.quaternion.copy(endpoint_grand_steps_3.quaternion);
  }
  mesh_grand_steps_3.castShadow = options.castShadow ?? true;
  mesh_grand_steps_3.receiveShadow = options.receiveShadow ?? true;
  mesh_grand_steps_3.userData.sculptComponent = {"id": "grand-steps", "name": "Grand steps", "level": "meso", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Three wide flights from the plaza up to the terrace, centered on the axis; real riser steps authored in the factory helper.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "terrace-podium", "attachment": null, "dimensions": {"width": 30, "height": 2.4, "depth": 10, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 37], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "grand-steps", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "nosing-bands", "description": "Pale stone nosing strip along every riser; three wide flights with landing bands."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png", "zones-ref04/zone-r2c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_grand_steps_3.add(mesh_grand_steps_3);
  meshes["grand-steps"] = mesh_grand_steps_3;
  colliders["grand-steps"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["grand-steps"] ??= [];
  destructionGroups["grand-steps"].push(node_grand_steps_3);

  const endpoint_terrace_balustrade_west_4 = makeAttachmentEndpoint(null);
  const node_terrace_balustrade_west_4 = new THREE.Group();
  node_terrace_balustrade_west_4.name = "Terrace balustrade (west)__pivot";
  node_terrace_balustrade_west_4.scale.set(1, 1, 1);
  if (endpoint_terrace_balustrade_west_4) {
    node_terrace_balustrade_west_4.position.copy(endpoint_terrace_balustrade_west_4.start);
    node_terrace_balustrade_west_4.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_terrace_balustrade_west_4.position.set(-25.0, 1.8, 33.0);
    node_terrace_balustrade_west_4.rotation.set(0.0, 0.0, 0.0);
  }
  node_terrace_balustrade_west_4.userData.sculptComponent = {"id": "terrace-balustrade-west", "name": "Terrace balustrade (west)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low stone balustrade segment flanking the grand steps; baluster cadence authored in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "terrace-podium", "attachment": null, "dimensions": {"width": 20, "height": 1.2, "depth": 1.0, "units": "relative", "confidence": 0.6}, "transform": {"position": [-25, 1.8, 33], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "terrace-balustrade-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_terrace_balustrade_west_4.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "terrace-balustrade-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}};
  (nodes["terrace-podium"] ?? root).add(node_terrace_balustrade_west_4);
  nodes["terrace-balustrade-west"] = node_terrace_balustrade_west_4;
  const mesh_terrace_balustrade_west_4Geometry = endpoint_terrace_balustrade_west_4
    ? new THREE.CylinderGeometry(endpoint_terrace_balustrade_west_4.endRadius, endpoint_terrace_balustrade_west_4.baseRadius, endpoint_terrace_balustrade_west_4.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_terrace_balustrade_west_4) {
    mesh_terrace_balustrade_west_4Geometry.scale(20.0, 1.2, 1.0);
  }
  const mesh_terrace_balustrade_west_4 = new THREE.Mesh(
    mesh_terrace_balustrade_west_4Geometry,
    materialMap["terrace-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_terrace_balustrade_west_4.name = "Terrace balustrade (west)";
  if (endpoint_terrace_balustrade_west_4) {
    mesh_terrace_balustrade_west_4.position.copy(endpoint_terrace_balustrade_west_4.midpoint);
    mesh_terrace_balustrade_west_4.quaternion.copy(endpoint_terrace_balustrade_west_4.quaternion);
  }
  mesh_terrace_balustrade_west_4.castShadow = options.castShadow ?? true;
  mesh_terrace_balustrade_west_4.receiveShadow = options.receiveShadow ?? true;
  mesh_terrace_balustrade_west_4.userData.sculptComponent = {"id": "terrace-balustrade-west", "name": "Terrace balustrade (west)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low stone balustrade segment flanking the grand steps; baluster cadence authored in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "terrace-podium", "attachment": null, "dimensions": {"width": 20, "height": 1.2, "depth": 1.0, "units": "relative", "confidence": 0.6}, "transform": {"position": [-25, 1.8, 33], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "terrace-balustrade-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_terrace_balustrade_west_4.add(mesh_terrace_balustrade_west_4);
  meshes["terrace-balustrade-west"] = mesh_terrace_balustrade_west_4;
  colliders["terrace-balustrade-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["terrace-balustrade-west"] ??= [];
  destructionGroups["terrace-balustrade-west"].push(node_terrace_balustrade_west_4);

  const endpoint_terrace_balustrade_east_5 = makeAttachmentEndpoint(null);
  const node_terrace_balustrade_east_5 = new THREE.Group();
  node_terrace_balustrade_east_5.name = "Terrace balustrade (east)__pivot";
  node_terrace_balustrade_east_5.scale.set(1, 1, 1);
  if (endpoint_terrace_balustrade_east_5) {
    node_terrace_balustrade_east_5.position.copy(endpoint_terrace_balustrade_east_5.start);
    node_terrace_balustrade_east_5.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_terrace_balustrade_east_5.position.set(25.0, 1.8, 33.0);
    node_terrace_balustrade_east_5.rotation.set(0.0, 0.0, 0.0);
  }
  node_terrace_balustrade_east_5.userData.sculptComponent = {"id": "terrace-balustrade-east", "name": "Terrace balustrade (east)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low stone balustrade segment flanking the grand steps; baluster cadence authored in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "terrace-podium", "attachment": null, "dimensions": {"width": 20, "height": 1.2, "depth": 1.0, "units": "relative", "confidence": 0.6}, "transform": {"position": [25, 1.8, 33], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "terrace-balustrade-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_terrace_balustrade_east_5.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "terrace-balustrade-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}};
  (nodes["terrace-podium"] ?? root).add(node_terrace_balustrade_east_5);
  nodes["terrace-balustrade-east"] = node_terrace_balustrade_east_5;
  const mesh_terrace_balustrade_east_5Geometry = endpoint_terrace_balustrade_east_5
    ? new THREE.CylinderGeometry(endpoint_terrace_balustrade_east_5.endRadius, endpoint_terrace_balustrade_east_5.baseRadius, endpoint_terrace_balustrade_east_5.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_terrace_balustrade_east_5) {
    mesh_terrace_balustrade_east_5Geometry.scale(20.0, 1.2, 1.0);
  }
  const mesh_terrace_balustrade_east_5 = new THREE.Mesh(
    mesh_terrace_balustrade_east_5Geometry,
    materialMap["terrace-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_terrace_balustrade_east_5.name = "Terrace balustrade (east)";
  if (endpoint_terrace_balustrade_east_5) {
    mesh_terrace_balustrade_east_5.position.copy(endpoint_terrace_balustrade_east_5.midpoint);
    mesh_terrace_balustrade_east_5.quaternion.copy(endpoint_terrace_balustrade_east_5.quaternion);
  }
  mesh_terrace_balustrade_east_5.castShadow = options.castShadow ?? true;
  mesh_terrace_balustrade_east_5.receiveShadow = options.receiveShadow ?? true;
  mesh_terrace_balustrade_east_5.userData.sculptComponent = {"id": "terrace-balustrade-east", "name": "Terrace balustrade (east)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low stone balustrade segment flanking the grand steps; baluster cadence authored in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "terrace-podium", "attachment": null, "dimensions": {"width": 20, "height": 1.2, "depth": 1.0, "units": "relative", "confidence": 0.6}, "transform": {"position": [25, 1.8, 33], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "terrace-balustrade-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_terrace_balustrade_east_5.add(mesh_terrace_balustrade_east_5);
  meshes["terrace-balustrade-east"] = mesh_terrace_balustrade_east_5;
  colliders["terrace-balustrade-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["terrace-balustrade-east"] ??= [];
  destructionGroups["terrace-balustrade-east"].push(node_terrace_balustrade_east_5);

  const endpoint_central_block_6 = makeAttachmentEndpoint(null);
  const node_central_block_6 = new THREE.Group();
  node_central_block_6.name = "Central block__pivot";
  node_central_block_6.scale.set(1, 1, 1);
  if (endpoint_central_block_6) {
    node_central_block_6.position.copy(endpoint_central_block_6.start);
    node_central_block_6.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_central_block_6.position.set(0.0, 17.7, -17.0);
    node_central_block_6.rotation.set(0.0, 0.0, 0.0);
  }
  node_central_block_6.userData.sculptComponent = {"id": "central-block", "name": "Central block", "level": "macro", "role": "structure", "importance": 1.0, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Tall central mass carrying the glazed loggia, attic band and the dome; front face on the z=0 plane.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 42, "height": 30.6, "depth": 34, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 17.7, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-block", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:close-aerial"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_central_block_6.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-block", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_central_block_6);
  nodes["central-block"] = node_central_block_6;
  const mesh_central_block_6Geometry = endpoint_central_block_6
    ? new THREE.CylinderGeometry(endpoint_central_block_6.endRadius, endpoint_central_block_6.baseRadius, endpoint_central_block_6.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_central_block_6) {
    mesh_central_block_6Geometry.scale(42.0, 30.6, 34.0);
  }
  const mesh_central_block_6 = new THREE.Mesh(
    mesh_central_block_6Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_central_block_6.name = "Central block";
  if (endpoint_central_block_6) {
    mesh_central_block_6.position.copy(endpoint_central_block_6.midpoint);
    mesh_central_block_6.quaternion.copy(endpoint_central_block_6.quaternion);
  }
  mesh_central_block_6.castShadow = options.castShadow ?? true;
  mesh_central_block_6.receiveShadow = options.receiveShadow ?? true;
  mesh_central_block_6.userData.sculptComponent = {"id": "central-block", "name": "Central block", "level": "macro", "role": "structure", "importance": 1.0, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Tall central mass carrying the glazed loggia, attic band and the dome; front face on the z=0 plane.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 42, "height": 30.6, "depth": 34, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 17.7, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-block", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:close-aerial"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_central_block_6.add(mesh_central_block_6);
  meshes["central-block"] = mesh_central_block_6;
  colliders["central-block"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["central-block"] ??= [];
  destructionGroups["central-block"].push(node_central_block_6);

  const endpoint_central_body_7 = makeAttachmentEndpoint(null);
  const node_central_body_7 = new THREE.Group();
  node_central_body_7.name = "Central body__pivot";
  node_central_body_7.scale.set(1, 1, 1);
  if (endpoint_central_body_7) {
    node_central_body_7.position.copy(endpoint_central_body_7.start);
    node_central_body_7.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_central_body_7.position.set(0.0, 0.0, 0.0);
    node_central_body_7.rotation.set(0.0, 0.0, 0.0);
  }
  node_central_body_7.userData.sculptComponent = {"id": "central-body", "name": "Central body", "level": "meso", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Brick mass of the central block (floors below the loggia).", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 42, "height": 30.6, "depth": 34, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-body", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_central_body_7.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-body", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["central-block"] ?? root).add(node_central_body_7);
  nodes["central-body"] = node_central_body_7;
  const mesh_central_body_7Geometry = endpoint_central_body_7
    ? new THREE.CylinderGeometry(endpoint_central_body_7.endRadius, endpoint_central_body_7.baseRadius, endpoint_central_body_7.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_central_body_7) {
    mesh_central_body_7Geometry.scale(42.0, 30.6, 34.0);
  }
  const mesh_central_body_7 = new THREE.Mesh(
    mesh_central_body_7Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_central_body_7.name = "Central body";
  if (endpoint_central_body_7) {
    mesh_central_body_7.position.copy(endpoint_central_body_7.midpoint);
    mesh_central_body_7.quaternion.copy(endpoint_central_body_7.quaternion);
  }
  mesh_central_body_7.castShadow = options.castShadow ?? true;
  mesh_central_body_7.receiveShadow = options.receiveShadow ?? true;
  mesh_central_body_7.userData.sculptComponent = {"id": "central-body", "name": "Central body", "level": "meso", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Brick mass of the central block (floors below the loggia).", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 42, "height": 30.6, "depth": 34, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-body", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_central_body_7.add(mesh_central_body_7);
  meshes["central-body"] = mesh_central_body_7;
  colliders["central-body"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["central-body"] ??= [];
  destructionGroups["central-body"].push(node_central_body_7);

  const endpoint_glazed_loggia_8 = makeAttachmentEndpoint(null);
  const node_glazed_loggia_8 = new THREE.Group();
  node_glazed_loggia_8.name = "Glazed loggia__pivot";
  node_glazed_loggia_8.scale.set(1, 1, 1);
  if (endpoint_glazed_loggia_8) {
    node_glazed_loggia_8.position.copy(endpoint_glazed_loggia_8.start);
    node_glazed_loggia_8.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_glazed_loggia_8.position.set(0.0, 10.5, 16.6);
    node_glazed_loggia_8.rotation.set(0.0, 0.0, 0.0);
  }
  node_glazed_loggia_8.userData.sculptComponent = {"id": "glazed-loggia", "name": "Glazed loggia", "level": "meso", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Two-storey glazed attic band across the central block front, behind the portico entablature top.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 30, "height": 8.6, "depth": 0.8, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 10.5, 16.6], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "glazed-loggia", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "mullion-grid", "description": "Continuous curtain wall divided by olive piers into bays, thin transom lines per bay."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_glazed_loggia_8.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "glazed-loggia", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["central-block"] ?? root).add(node_glazed_loggia_8);
  nodes["glazed-loggia"] = node_glazed_loggia_8;
  const mesh_glazed_loggia_8Geometry = endpoint_glazed_loggia_8
    ? new THREE.CylinderGeometry(endpoint_glazed_loggia_8.endRadius, endpoint_glazed_loggia_8.baseRadius, endpoint_glazed_loggia_8.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_glazed_loggia_8) {
    mesh_glazed_loggia_8Geometry.scale(30.0, 8.6, 0.8);
  }
  const mesh_glazed_loggia_8 = new THREE.Mesh(
    mesh_glazed_loggia_8Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_glazed_loggia_8.name = "Glazed loggia";
  if (endpoint_glazed_loggia_8) {
    mesh_glazed_loggia_8.position.copy(endpoint_glazed_loggia_8.midpoint);
    mesh_glazed_loggia_8.quaternion.copy(endpoint_glazed_loggia_8.quaternion);
  }
  mesh_glazed_loggia_8.castShadow = options.castShadow ?? true;
  mesh_glazed_loggia_8.receiveShadow = options.receiveShadow ?? true;
  mesh_glazed_loggia_8.userData.sculptComponent = {"id": "glazed-loggia", "name": "Glazed loggia", "level": "meso", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Two-storey glazed attic band across the central block front, behind the portico entablature top.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 30, "height": 8.6, "depth": 0.8, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 10.5, 16.6], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "glazed-loggia", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "mullion-grid", "description": "Continuous curtain wall divided by olive piers into bays, thin transom lines per bay."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_glazed_loggia_8.add(mesh_glazed_loggia_8);
  meshes["glazed-loggia"] = mesh_glazed_loggia_8;
  colliders["glazed-loggia"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["glazed-loggia"] ??= [];
  destructionGroups["glazed-loggia"].push(node_glazed_loggia_8);

  const endpoint_attic_band_9 = makeAttachmentEndpoint(null);
  const node_attic_band_9 = new THREE.Group();
  node_attic_band_9.name = "Attic dentil band__pivot";
  node_attic_band_9.scale.set(1, 1, 1);
  if (endpoint_attic_band_9) {
    node_attic_band_9.position.copy(endpoint_attic_band_9.start);
    node_attic_band_9.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_attic_band_9.position.set(0.0, 15.45, 16.65);
    node_attic_band_9.rotation.set(0.0, 0.0, 0.0);
  }
  node_attic_band_9.userData.sculptComponent = {"id": "attic-band", "name": "Attic dentil band", "level": "meso", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Dentil course between loggia top and parapet; repeated bracket cadence authored in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 31.4, "height": 1.5, "depth": 1.1, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 15.45, 16.65], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "attic-band", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "dentil-brackets", "description": "Row of closely spaced pale dentil brackets under the central entablature."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_attic_band_9.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "attic-band", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["central-block"] ?? root).add(node_attic_band_9);
  nodes["attic-band"] = node_attic_band_9;
  const mesh_attic_band_9Geometry = endpoint_attic_band_9
    ? new THREE.CylinderGeometry(endpoint_attic_band_9.endRadius, endpoint_attic_band_9.baseRadius, endpoint_attic_band_9.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_attic_band_9) {
    mesh_attic_band_9Geometry.scale(31.4, 1.5, 1.1);
  }
  const mesh_attic_band_9 = new THREE.Mesh(
    mesh_attic_band_9Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_attic_band_9.name = "Attic dentil band";
  if (endpoint_attic_band_9) {
    mesh_attic_band_9.position.copy(endpoint_attic_band_9.midpoint);
    mesh_attic_band_9.quaternion.copy(endpoint_attic_band_9.quaternion);
  }
  mesh_attic_band_9.castShadow = options.castShadow ?? true;
  mesh_attic_band_9.receiveShadow = options.receiveShadow ?? true;
  mesh_attic_band_9.userData.sculptComponent = {"id": "attic-band", "name": "Attic dentil band", "level": "meso", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Dentil course between loggia top and parapet; repeated bracket cadence authored in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 31.4, "height": 1.5, "depth": 1.1, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 15.45, 16.65], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "attic-band", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "dentil-brackets", "description": "Row of closely spaced pale dentil brackets under the central entablature."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_attic_band_9.add(mesh_attic_band_9);
  meshes["attic-band"] = mesh_attic_band_9;
  colliders["attic-band"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["attic-band"] ??= [];
  destructionGroups["attic-band"].push(node_attic_band_9);

  const endpoint_central_parapet_10 = makeAttachmentEndpoint(null);
  const node_central_parapet_10 = new THREE.Group();
  node_central_parapet_10.name = "Central parapet__pivot";
  node_central_parapet_10.scale.set(1, 1, 1);
  if (endpoint_central_parapet_10) {
    node_central_parapet_10.position.copy(endpoint_central_parapet_10.start);
    node_central_parapet_10.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_central_parapet_10.position.set(0.0, 15.85, 0.0);
    node_central_parapet_10.rotation.set(0.0, 0.0, 0.0);
  }
  node_central_parapet_10.userData.sculptComponent = {"id": "central-parapet", "name": "Central parapet", "level": "meso", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Parapet ring around the central roof deck with a pale coping line.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 42.6, "height": 0.9, "depth": 34.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 15.85, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-parapet", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_central_parapet_10.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-parapet", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["central-block"] ?? root).add(node_central_parapet_10);
  nodes["central-parapet"] = node_central_parapet_10;
  const mesh_central_parapet_10Geometry = endpoint_central_parapet_10
    ? new THREE.CylinderGeometry(endpoint_central_parapet_10.endRadius, endpoint_central_parapet_10.baseRadius, endpoint_central_parapet_10.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_central_parapet_10) {
    mesh_central_parapet_10Geometry.scale(42.6, 0.9, 34.6);
  }
  const mesh_central_parapet_10 = new THREE.Mesh(
    mesh_central_parapet_10Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_central_parapet_10.name = "Central parapet";
  if (endpoint_central_parapet_10) {
    mesh_central_parapet_10.position.copy(endpoint_central_parapet_10.midpoint);
    mesh_central_parapet_10.quaternion.copy(endpoint_central_parapet_10.quaternion);
  }
  mesh_central_parapet_10.castShadow = options.castShadow ?? true;
  mesh_central_parapet_10.receiveShadow = options.receiveShadow ?? true;
  mesh_central_parapet_10.userData.sculptComponent = {"id": "central-parapet", "name": "Central parapet", "level": "meso", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Parapet ring around the central roof deck with a pale coping line.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 42.6, "height": 0.9, "depth": 34.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 15.85, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-parapet", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_central_parapet_10.add(mesh_central_parapet_10);
  meshes["central-parapet"] = mesh_central_parapet_10;
  colliders["central-parapet"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["central-parapet"] ??= [];
  destructionGroups["central-parapet"].push(node_central_parapet_10);

  const endpoint_roof_deck_11 = makeAttachmentEndpoint(null);
  const node_roof_deck_11 = new THREE.Group();
  node_roof_deck_11.name = "Central roof deck__pivot";
  node_roof_deck_11.scale.set(1, 1, 1);
  if (endpoint_roof_deck_11) {
    node_roof_deck_11.position.copy(endpoint_roof_deck_11.start);
    node_roof_deck_11.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_roof_deck_11.position.set(0.0, 15.8, 0.0);
    node_roof_deck_11.rotation.set(0.0, 0.0, 0.0);
  }
  node_roof_deck_11.userData.sculptComponent = {"id": "roof-deck", "name": "Central roof deck", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Flat deck around the drum; equipment and solar row authored as small repeated boxes in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 41, "height": 0.35, "depth": 33, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 15.8, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "roof-deck", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-deck"}}, "material": "roof-deck", "materialLayers": ["roof-deck"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "solar-row", "description": "Row of repeated dark slanted vacuum-tube solar panels beside the dome."}, {"id": "equipment-cluster", "description": "White AC boxes and low skylight strips scattered on the deck."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(216, 210, 194, 1.0)", "secondaryAlbedo": "rgba(201, 195, 179, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_roof_deck_11.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "roof-deck", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-deck"}};
  (nodes["central-block"] ?? root).add(node_roof_deck_11);
  nodes["roof-deck"] = node_roof_deck_11;
  const mesh_roof_deck_11Geometry = endpoint_roof_deck_11
    ? new THREE.CylinderGeometry(endpoint_roof_deck_11.endRadius, endpoint_roof_deck_11.baseRadius, endpoint_roof_deck_11.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_roof_deck_11) {
    mesh_roof_deck_11Geometry.scale(41.0, 0.35, 33.0);
  }
  const mesh_roof_deck_11 = new THREE.Mesh(
    mesh_roof_deck_11Geometry,
    materialMap["roof-deck"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_roof_deck_11.name = "Central roof deck";
  if (endpoint_roof_deck_11) {
    mesh_roof_deck_11.position.copy(endpoint_roof_deck_11.midpoint);
    mesh_roof_deck_11.quaternion.copy(endpoint_roof_deck_11.quaternion);
  }
  mesh_roof_deck_11.castShadow = options.castShadow ?? true;
  mesh_roof_deck_11.receiveShadow = options.receiveShadow ?? true;
  mesh_roof_deck_11.userData.sculptComponent = {"id": "roof-deck", "name": "Central roof deck", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Flat deck around the drum; equipment and solar row authored as small repeated boxes in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "central-block", "attachment": null, "dimensions": {"width": 41, "height": 0.35, "depth": 33, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 15.8, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "roof-deck", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-deck"}}, "material": "roof-deck", "materialLayers": ["roof-deck"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "solar-row", "description": "Row of repeated dark slanted vacuum-tube solar panels beside the dome."}, {"id": "equipment-cluster", "description": "White AC boxes and low skylight strips scattered on the deck."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(216, 210, 194, 1.0)", "secondaryAlbedo": "rgba(201, 195, 179, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_roof_deck_11.add(mesh_roof_deck_11);
  meshes["roof-deck"] = mesh_roof_deck_11;
  colliders["roof-deck"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["roof-deck"] ??= [];
  destructionGroups["roof-deck"].push(node_roof_deck_11);

  const endpoint_dome_assembly_12 = makeAttachmentEndpoint(null);
  const node_dome_assembly_12 = new THREE.Group();
  node_dome_assembly_12.name = "Dome assembly (container)__pivot";
  node_dome_assembly_12.scale.set(1, 1, 1);
  if (endpoint_dome_assembly_12) {
    node_dome_assembly_12.position.copy(endpoint_dome_assembly_12.start);
    node_dome_assembly_12.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_dome_assembly_12.position.set(0.0, 0.0, 0.0);
    node_dome_assembly_12.rotation.set(0.0, 0.0, 0.0);
  }
  node_dome_assembly_12.userData.sculptComponent = {"id": "dome-assembly", "name": "Dome assembly (container)", "level": "macro", "role": "structure", "importance": 1.0, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hidden container: drum, shell, rings, meridians and finial are the real geometry (children).", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 1, "height": 1, "depth": 1, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-assembly", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "invisible-root"}}, "material": "invisible-root", "materialLayers": ["invisible-root"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(110, 103, 89, 1.0)", "secondaryAlbedo": "rgba(95, 89, 76, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_dome_assembly_12.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-assembly", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "invisible-root"}};
  (nodes["root"] ?? root).add(node_dome_assembly_12);
  nodes["dome-assembly"] = node_dome_assembly_12;
  const mesh_dome_assembly_12Geometry = endpoint_dome_assembly_12
    ? new THREE.CylinderGeometry(endpoint_dome_assembly_12.endRadius, endpoint_dome_assembly_12.baseRadius, endpoint_dome_assembly_12.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_dome_assembly_12) {
    mesh_dome_assembly_12Geometry.scale(1.0, 1.0, 1.0);
  }
  const mesh_dome_assembly_12 = new THREE.Mesh(
    mesh_dome_assembly_12Geometry,
    materialMap["invisible-root"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_assembly_12.name = "Dome assembly (container)";
  if (endpoint_dome_assembly_12) {
    mesh_dome_assembly_12.position.copy(endpoint_dome_assembly_12.midpoint);
    mesh_dome_assembly_12.quaternion.copy(endpoint_dome_assembly_12.quaternion);
  }
  mesh_dome_assembly_12.castShadow = options.castShadow ?? true;
  mesh_dome_assembly_12.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_assembly_12.userData.sculptComponent = {"id": "dome-assembly", "name": "Dome assembly (container)", "level": "macro", "role": "structure", "importance": 1.0, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hidden container: drum, shell, rings, meridians and finial are the real geometry (children).", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 1, "height": 1, "depth": 1, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-assembly", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "invisible-root"}}, "material": "invisible-root", "materialLayers": ["invisible-root"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(110, 103, 89, 1.0)", "secondaryAlbedo": "rgba(95, 89, 76, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_dome_assembly_12.add(mesh_dome_assembly_12);
  meshes["dome-assembly"] = mesh_dome_assembly_12;
  colliders["dome-assembly"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-assembly"] ??= [];
  destructionGroups["dome-assembly"].push(node_dome_assembly_12);

  const endpoint_dome_drum_13 = makeAttachmentEndpoint(null);
  const node_dome_drum_13 = new THREE.Group();
  node_dome_drum_13.name = "Dome drum__pivot";
  node_dome_drum_13.scale.set(1, 1, 1);
  if (endpoint_dome_drum_13) {
    node_dome_drum_13.position.copy(endpoint_dome_drum_13.start);
    node_dome_drum_13.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_dome_drum_13.position.set(0.0, 34.7, -17.0);
    node_dome_drum_13.rotation.set(0.0, 0.0, 0.0);
  }
  node_dome_drum_13.userData.sculptComponent = {"id": "dome-drum", "name": "Dome drum", "level": "macro", "role": "structure", "importance": 0.85, "confidence": 0.85, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Cylindrical drum: rotationally symmetric revolved profile (lathe, straight profile).", "geometryDescriptor": {"topologyIntent": "Cream drum under the dome; window ribbon and mullions ring the upper part.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.5, 0.5]], "segments": 40}}, "parent": "dome-assembly", "attachment": null, "dimensions": {"width": 11.2, "height": 2.4, "depth": 11.2, "units": "relative", "confidence": 0.85}, "transform": {"position": [0, 34.7, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.85}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-drum", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "window-ribbon", "description": "Continuous ribbon of dark windows around the drum with slim pale mullions."}, {"id": "cornice-ring", "description": "Pale cornice ring with fine dentil course at the drum base."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_dome_drum_13.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.85}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-drum", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["dome-assembly"] ?? root).add(node_dome_drum_13);
  nodes["dome-drum"] = node_dome_drum_13;
  const mesh_dome_drum_13Geometry = endpoint_dome_drum_13
    ? new THREE.CylinderGeometry(endpoint_dome_drum_13.endRadius, endpoint_dome_drum_13.baseRadius, endpoint_dome_drum_13.length, 32, 12)
    : buildLatheGeometry({"points": [[0.5, -0.5], [0.5, 0.5]], "segments": 40});
  if (!endpoint_dome_drum_13) {
    mesh_dome_drum_13Geometry.scale(11.2, 2.4, 11.2);
  }
  const mesh_dome_drum_13 = new THREE.Mesh(
    mesh_dome_drum_13Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_drum_13.name = "Dome drum";
  if (endpoint_dome_drum_13) {
    mesh_dome_drum_13.position.copy(endpoint_dome_drum_13.midpoint);
    mesh_dome_drum_13.quaternion.copy(endpoint_dome_drum_13.quaternion);
  }
  mesh_dome_drum_13.castShadow = options.castShadow ?? true;
  mesh_dome_drum_13.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_drum_13.userData.sculptComponent = {"id": "dome-drum", "name": "Dome drum", "level": "macro", "role": "structure", "importance": 0.85, "confidence": 0.85, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Cylindrical drum: rotationally symmetric revolved profile (lathe, straight profile).", "geometryDescriptor": {"topologyIntent": "Cream drum under the dome; window ribbon and mullions ring the upper part.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.5, 0.5]], "segments": 40}}, "parent": "dome-assembly", "attachment": null, "dimensions": {"width": 11.2, "height": 2.4, "depth": 11.2, "units": "relative", "confidence": 0.85}, "transform": {"position": [0, 34.7, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.85}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-drum", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "window-ribbon", "description": "Continuous ribbon of dark windows around the drum with slim pale mullions."}, {"id": "cornice-ring", "description": "Pale cornice ring with fine dentil course at the drum base."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_dome_drum_13.add(mesh_dome_drum_13);
  meshes["dome-drum"] = mesh_dome_drum_13;
  colliders["dome-drum"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-drum"] ??= [];
  destructionGroups["dome-drum"].push(node_dome_drum_13);

  const endpoint_drum_window_ring_14 = makeAttachmentEndpoint(null);
  const node_drum_window_ring_14 = new THREE.Group();
  node_drum_window_ring_14.name = "Drum window ring__pivot";
  node_drum_window_ring_14.scale.set(1, 1, 1);
  if (endpoint_drum_window_ring_14) {
    node_drum_window_ring_14.position.copy(endpoint_drum_window_ring_14.start);
    node_drum_window_ring_14.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_drum_window_ring_14.position.set(0.0, 0.45, 0.0);
    node_drum_window_ring_14.rotation.set(0.0, 0.0, 0.0);
  }
  node_drum_window_ring_14.userData.sculptComponent = {"id": "drum-window-ring", "name": "Drum window ring", "level": "micro", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Thin cylindrical glazing band (lathe with straight profile).", "geometryDescriptor": {"topologyIntent": "Dark glazing ring of the drum; mullions come from the drum-mullions repetition system.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.5, 0.5]], "segments": 40}}, "parent": "dome-drum", "attachment": null, "dimensions": {"width": 11.0, "height": 1.1, "depth": 11.0, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.45, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "drum-window-ring", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_drum_window_ring_14.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "drum-window-ring", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["dome-drum"] ?? root).add(node_drum_window_ring_14);
  nodes["drum-window-ring"] = node_drum_window_ring_14;
  const mesh_drum_window_ring_14Geometry = endpoint_drum_window_ring_14
    ? new THREE.CylinderGeometry(endpoint_drum_window_ring_14.endRadius, endpoint_drum_window_ring_14.baseRadius, endpoint_drum_window_ring_14.length, 32, 12)
    : buildLatheGeometry({"points": [[0.5, -0.5], [0.5, 0.5]], "segments": 40});
  if (!endpoint_drum_window_ring_14) {
    mesh_drum_window_ring_14Geometry.scale(11.0, 1.1, 11.0);
  }
  const mesh_drum_window_ring_14 = new THREE.Mesh(
    mesh_drum_window_ring_14Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_drum_window_ring_14.name = "Drum window ring";
  if (endpoint_drum_window_ring_14) {
    mesh_drum_window_ring_14.position.copy(endpoint_drum_window_ring_14.midpoint);
    mesh_drum_window_ring_14.quaternion.copy(endpoint_drum_window_ring_14.quaternion);
  }
  mesh_drum_window_ring_14.castShadow = options.castShadow ?? true;
  mesh_drum_window_ring_14.receiveShadow = options.receiveShadow ?? true;
  mesh_drum_window_ring_14.userData.sculptComponent = {"id": "drum-window-ring", "name": "Drum window ring", "level": "micro", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Thin cylindrical glazing band (lathe with straight profile).", "geometryDescriptor": {"topologyIntent": "Dark glazing ring of the drum; mullions come from the drum-mullions repetition system.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.5, 0.5]], "segments": 40}}, "parent": "dome-drum", "attachment": null, "dimensions": {"width": 11.0, "height": 1.1, "depth": 11.0, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.45, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "drum-window-ring", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_drum_window_ring_14.add(mesh_drum_window_ring_14);
  meshes["drum-window-ring"] = mesh_drum_window_ring_14;
  colliders["drum-window-ring"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["drum-window-ring"] ??= [];
  destructionGroups["drum-window-ring"].push(node_drum_window_ring_14);

  const endpoint_dome_shell_15 = makeAttachmentEndpoint(null);
  const node_dome_shell_15 = new THREE.Group();
  node_dome_shell_15.name = "Dome shell__pivot";
  node_dome_shell_15.scale.set(1, 1, 1);
  if (endpoint_dome_shell_15) {
    node_dome_shell_15.position.copy(endpoint_dome_shell_15.start);
    node_dome_shell_15.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_dome_shell_15.position.set(0.0, 35.9, -17.0);
    node_dome_shell_15.rotation.set(0.0, 0.0, 0.0);
  }
  node_dome_shell_15.userData.sculptComponent = {"id": "dome-shell", "name": "Dome shell", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "sphere", "topologyClass": "continuous-sculpt", "topologyRationale": "Rotational half-dome: a smooth revolved shell, sphere primitive scaled.", "geometryDescriptor": {"topologyIntent": "Hemisphere above the drum; pane grid via material override plus real rib and ring geometry.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "dome-assembly", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 35.9, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-shell", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dome"}}, "material": "glass-dome", "materialLayers": ["glass-dome"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "dome-grid-pattern", "description": "Regular grid of near-square glass panes with steel meridian ribs and two ring ribs; darker seams."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png", "view:front-elevation"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(127, 160, 172, 1.0)", "secondaryAlbedo": "rgba(105, 137, 154, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_dome_shell_15.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-shell", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dome"}};
  (nodes["dome-assembly"] ?? root).add(node_dome_shell_15);
  nodes["dome-shell"] = node_dome_shell_15;
  const mesh_dome_shell_15Geometry = endpoint_dome_shell_15
    ? new THREE.CylinderGeometry(endpoint_dome_shell_15.endRadius, endpoint_dome_shell_15.baseRadius, endpoint_dome_shell_15.length, 32, 12)
    : new THREE.SphereGeometry(0.5, 64, 40);
  if (!endpoint_dome_shell_15) {
    mesh_dome_shell_15Geometry.scale(9.6, 9.6, 9.6);
  }
  const mesh_dome_shell_15 = new THREE.Mesh(
    mesh_dome_shell_15Geometry,
    materialMap["glass-dome"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_shell_15.name = "Dome shell";
  if (endpoint_dome_shell_15) {
    mesh_dome_shell_15.position.copy(endpoint_dome_shell_15.midpoint);
    mesh_dome_shell_15.quaternion.copy(endpoint_dome_shell_15.quaternion);
  }
  mesh_dome_shell_15.castShadow = options.castShadow ?? true;
  mesh_dome_shell_15.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_shell_15.userData.sculptComponent = {"id": "dome-shell", "name": "Dome shell", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "sphere", "topologyClass": "continuous-sculpt", "topologyRationale": "Rotational half-dome: a smooth revolved shell, sphere primitive scaled.", "geometryDescriptor": {"topologyIntent": "Hemisphere above the drum; pane grid via material override plus real rib and ring geometry.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "dome-assembly", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 35.9, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-shell", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dome"}}, "material": "glass-dome", "materialLayers": ["glass-dome"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "dome-grid-pattern", "description": "Regular grid of near-square glass panes with steel meridian ribs and two ring ribs; darker seams."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png", "view:front-elevation"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(127, 160, 172, 1.0)", "secondaryAlbedo": "rgba(105, 137, 154, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_dome_shell_15.add(mesh_dome_shell_15);
  meshes["dome-shell"] = mesh_dome_shell_15;
  colliders["dome-shell"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-shell"] ??= [];
  destructionGroups["dome-shell"].push(node_dome_shell_15);

  const endpoint_dome_ring_low_16 = makeAttachmentEndpoint(null);
  const node_dome_ring_low_16 = new THREE.Group();
  node_dome_ring_low_16.name = "Dome ring (low)__pivot";
  node_dome_ring_low_16.scale.set(1, 1, 1);
  if (endpoint_dome_ring_low_16) {
    node_dome_ring_low_16.position.copy(endpoint_dome_ring_low_16.start);
    node_dome_ring_low_16.rotation.set(1.5707963267948966, 0.0, 0.0);
  } else {
    node_dome_ring_low_16.position.set(0.0, 0.7, 0.0);
    node_dome_ring_low_16.rotation.set(1.5707963267948966, 0.0, 0.0);
  }
  node_dome_ring_low_16.userData.sculptComponent = {"id": "dome-ring-low", "name": "Dome ring (low)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "torus", "topologyClass": "assembled-solid", "topologyRationale": "Flat structural ring on the dome shell.", "geometryDescriptor": {"topologyIntent": "Concentric ring rib of the dome frame.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.666666666666666, "height": 9.666666666666666, "depth": 0.18, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.7, 0], "rotation": [1.5707963267948966, 0, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-ring-low", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_ring_low_16.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-ring-low", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_ring_low_16);
  nodes["dome-ring-low"] = node_dome_ring_low_16;
  const mesh_dome_ring_low_16Geometry = endpoint_dome_ring_low_16
    ? new THREE.CylinderGeometry(endpoint_dome_ring_low_16.endRadius, endpoint_dome_ring_low_16.baseRadius, endpoint_dome_ring_low_16.length, 32, 12)
    : new THREE.TorusGeometry(0.45, 0.08, 24, 96);
  if (!endpoint_dome_ring_low_16) {
    mesh_dome_ring_low_16Geometry.scale(9.666666666666666, 9.666666666666666, 0.18);
  }
  const mesh_dome_ring_low_16 = new THREE.Mesh(
    mesh_dome_ring_low_16Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_ring_low_16.name = "Dome ring (low)";
  if (endpoint_dome_ring_low_16) {
    mesh_dome_ring_low_16.position.copy(endpoint_dome_ring_low_16.midpoint);
    mesh_dome_ring_low_16.quaternion.copy(endpoint_dome_ring_low_16.quaternion);
  }
  mesh_dome_ring_low_16.castShadow = options.castShadow ?? true;
  mesh_dome_ring_low_16.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_ring_low_16.userData.sculptComponent = {"id": "dome-ring-low", "name": "Dome ring (low)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "torus", "topologyClass": "assembled-solid", "topologyRationale": "Flat structural ring on the dome shell.", "geometryDescriptor": {"topologyIntent": "Concentric ring rib of the dome frame.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.666666666666666, "height": 9.666666666666666, "depth": 0.18, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.7, 0], "rotation": [1.5707963267948966, 0, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-ring-low", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_ring_low_16.add(mesh_dome_ring_low_16);
  meshes["dome-ring-low"] = mesh_dome_ring_low_16;
  colliders["dome-ring-low"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-ring-low"] ??= [];
  destructionGroups["dome-ring-low"].push(node_dome_ring_low_16);

  const endpoint_dome_ring_high_17 = makeAttachmentEndpoint(null);
  const node_dome_ring_high_17 = new THREE.Group();
  node_dome_ring_high_17.name = "Dome ring (high)__pivot";
  node_dome_ring_high_17.scale.set(1, 1, 1);
  if (endpoint_dome_ring_high_17) {
    node_dome_ring_high_17.position.copy(endpoint_dome_ring_high_17.start);
    node_dome_ring_high_17.rotation.set(1.5707963267948966, 0.0, 0.0);
  } else {
    node_dome_ring_high_17.position.set(0.0, 1.8, 0.0);
    node_dome_ring_high_17.rotation.set(1.5707963267948966, 0.0, 0.0);
  }
  node_dome_ring_high_17.userData.sculptComponent = {"id": "dome-ring-high", "name": "Dome ring (high)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "torus", "topologyClass": "assembled-solid", "topologyRationale": "Flat structural ring on the dome shell.", "geometryDescriptor": {"topologyIntent": "Concentric ring rib of the dome frame.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 7.111111111111112, "height": 7.111111111111112, "depth": 0.18, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 1.8, 0], "rotation": [1.5707963267948966, 0, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-ring-high", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_ring_high_17.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-ring-high", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_ring_high_17);
  nodes["dome-ring-high"] = node_dome_ring_high_17;
  const mesh_dome_ring_high_17Geometry = endpoint_dome_ring_high_17
    ? new THREE.CylinderGeometry(endpoint_dome_ring_high_17.endRadius, endpoint_dome_ring_high_17.baseRadius, endpoint_dome_ring_high_17.length, 32, 12)
    : new THREE.TorusGeometry(0.45, 0.08, 24, 96);
  if (!endpoint_dome_ring_high_17) {
    mesh_dome_ring_high_17Geometry.scale(7.111111111111112, 7.111111111111112, 0.18);
  }
  const mesh_dome_ring_high_17 = new THREE.Mesh(
    mesh_dome_ring_high_17Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_ring_high_17.name = "Dome ring (high)";
  if (endpoint_dome_ring_high_17) {
    mesh_dome_ring_high_17.position.copy(endpoint_dome_ring_high_17.midpoint);
    mesh_dome_ring_high_17.quaternion.copy(endpoint_dome_ring_high_17.quaternion);
  }
  mesh_dome_ring_high_17.castShadow = options.castShadow ?? true;
  mesh_dome_ring_high_17.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_ring_high_17.userData.sculptComponent = {"id": "dome-ring-high", "name": "Dome ring (high)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "torus", "topologyClass": "assembled-solid", "topologyRationale": "Flat structural ring on the dome shell.", "geometryDescriptor": {"topologyIntent": "Concentric ring rib of the dome frame.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 7.111111111111112, "height": 7.111111111111112, "depth": 0.18, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 1.8, 0], "rotation": [1.5707963267948966, 0, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-ring-high", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_ring_high_17.add(mesh_dome_ring_high_17);
  meshes["dome-ring-high"] = mesh_dome_ring_high_17;
  colliders["dome-ring-high"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-ring-high"] ??= [];
  destructionGroups["dome-ring-high"].push(node_dome_ring_high_17);

  const endpoint_dome_meridian_a_18 = makeAttachmentEndpoint(null);
  const node_dome_meridian_a_18 = new THREE.Group();
  node_dome_meridian_a_18.name = "Dome meridian 0deg__pivot";
  node_dome_meridian_a_18.scale.set(1, 1, 1);
  if (endpoint_dome_meridian_a_18) {
    node_dome_meridian_a_18.position.copy(endpoint_dome_meridian_a_18.start);
    node_dome_meridian_a_18.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_dome_meridian_a_18.position.set(0.0, 0.0, 0.0);
    node_dome_meridian_a_18.rotation.set(0.0, 0.0, 0.0);
  }
  node_dome_meridian_a_18.userData.sculptComponent = {"id": "dome-meridian-a", "name": "Dome meridian 0deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 0.0, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-a", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_a_18.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-a", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_meridian_a_18);
  nodes["dome-meridian-a"] = node_dome_meridian_a_18;
  const mesh_dome_meridian_a_18Geometry = endpoint_dome_meridian_a_18
    ? new THREE.CylinderGeometry(endpoint_dome_meridian_a_18.endRadius, endpoint_dome_meridian_a_18.baseRadius, endpoint_dome_meridian_a_18.length, 32, 12)
    : buildTaperedSweepGeometry({"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false});
  if (!endpoint_dome_meridian_a_18) {
    mesh_dome_meridian_a_18Geometry.scale(9.6, 9.6, 9.6);
  }
  const mesh_dome_meridian_a_18 = new THREE.Mesh(
    mesh_dome_meridian_a_18Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_meridian_a_18.name = "Dome meridian 0deg";
  if (endpoint_dome_meridian_a_18) {
    mesh_dome_meridian_a_18.position.copy(endpoint_dome_meridian_a_18.midpoint);
    mesh_dome_meridian_a_18.quaternion.copy(endpoint_dome_meridian_a_18.quaternion);
  }
  mesh_dome_meridian_a_18.castShadow = options.castShadow ?? true;
  mesh_dome_meridian_a_18.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_meridian_a_18.userData.sculptComponent = {"id": "dome-meridian-a", "name": "Dome meridian 0deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 0.0, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-a", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_a_18.add(mesh_dome_meridian_a_18);
  meshes["dome-meridian-a"] = mesh_dome_meridian_a_18;
  colliders["dome-meridian-a"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-meridian-a"] ??= [];
  destructionGroups["dome-meridian-a"].push(node_dome_meridian_a_18);

  const endpoint_dome_meridian_b_19 = makeAttachmentEndpoint(null);
  const node_dome_meridian_b_19 = new THREE.Group();
  node_dome_meridian_b_19.name = "Dome meridian 45deg__pivot";
  node_dome_meridian_b_19.scale.set(1, 1, 1);
  if (endpoint_dome_meridian_b_19) {
    node_dome_meridian_b_19.position.copy(endpoint_dome_meridian_b_19.start);
    node_dome_meridian_b_19.rotation.set(0.0, 0.785398, 0.0);
  } else {
    node_dome_meridian_b_19.position.set(0.0, 0.0, 0.0);
    node_dome_meridian_b_19.rotation.set(0.0, 0.785398, 0.0);
  }
  node_dome_meridian_b_19.userData.sculptComponent = {"id": "dome-meridian-b", "name": "Dome meridian 45deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 0.785398, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-b", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_b_19.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-b", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_meridian_b_19);
  nodes["dome-meridian-b"] = node_dome_meridian_b_19;
  const mesh_dome_meridian_b_19Geometry = endpoint_dome_meridian_b_19
    ? new THREE.CylinderGeometry(endpoint_dome_meridian_b_19.endRadius, endpoint_dome_meridian_b_19.baseRadius, endpoint_dome_meridian_b_19.length, 32, 12)
    : buildTaperedSweepGeometry({"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false});
  if (!endpoint_dome_meridian_b_19) {
    mesh_dome_meridian_b_19Geometry.scale(9.6, 9.6, 9.6);
  }
  const mesh_dome_meridian_b_19 = new THREE.Mesh(
    mesh_dome_meridian_b_19Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_meridian_b_19.name = "Dome meridian 45deg";
  if (endpoint_dome_meridian_b_19) {
    mesh_dome_meridian_b_19.position.copy(endpoint_dome_meridian_b_19.midpoint);
    mesh_dome_meridian_b_19.quaternion.copy(endpoint_dome_meridian_b_19.quaternion);
  }
  mesh_dome_meridian_b_19.castShadow = options.castShadow ?? true;
  mesh_dome_meridian_b_19.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_meridian_b_19.userData.sculptComponent = {"id": "dome-meridian-b", "name": "Dome meridian 45deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 0.785398, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-b", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_b_19.add(mesh_dome_meridian_b_19);
  meshes["dome-meridian-b"] = mesh_dome_meridian_b_19;
  colliders["dome-meridian-b"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-meridian-b"] ??= [];
  destructionGroups["dome-meridian-b"].push(node_dome_meridian_b_19);

  const endpoint_dome_meridian_c_20 = makeAttachmentEndpoint(null);
  const node_dome_meridian_c_20 = new THREE.Group();
  node_dome_meridian_c_20.name = "Dome meridian 90deg__pivot";
  node_dome_meridian_c_20.scale.set(1, 1, 1);
  if (endpoint_dome_meridian_c_20) {
    node_dome_meridian_c_20.position.copy(endpoint_dome_meridian_c_20.start);
    node_dome_meridian_c_20.rotation.set(0.0, 1.570796, 0.0);
  } else {
    node_dome_meridian_c_20.position.set(0.0, 0.0, 0.0);
    node_dome_meridian_c_20.rotation.set(0.0, 1.570796, 0.0);
  }
  node_dome_meridian_c_20.userData.sculptComponent = {"id": "dome-meridian-c", "name": "Dome meridian 90deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 1.570796, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-c", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_c_20.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-c", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_meridian_c_20);
  nodes["dome-meridian-c"] = node_dome_meridian_c_20;
  const mesh_dome_meridian_c_20Geometry = endpoint_dome_meridian_c_20
    ? new THREE.CylinderGeometry(endpoint_dome_meridian_c_20.endRadius, endpoint_dome_meridian_c_20.baseRadius, endpoint_dome_meridian_c_20.length, 32, 12)
    : buildTaperedSweepGeometry({"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false});
  if (!endpoint_dome_meridian_c_20) {
    mesh_dome_meridian_c_20Geometry.scale(9.6, 9.6, 9.6);
  }
  const mesh_dome_meridian_c_20 = new THREE.Mesh(
    mesh_dome_meridian_c_20Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_meridian_c_20.name = "Dome meridian 90deg";
  if (endpoint_dome_meridian_c_20) {
    mesh_dome_meridian_c_20.position.copy(endpoint_dome_meridian_c_20.midpoint);
    mesh_dome_meridian_c_20.quaternion.copy(endpoint_dome_meridian_c_20.quaternion);
  }
  mesh_dome_meridian_c_20.castShadow = options.castShadow ?? true;
  mesh_dome_meridian_c_20.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_meridian_c_20.userData.sculptComponent = {"id": "dome-meridian-c", "name": "Dome meridian 90deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 1.570796, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-c", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_c_20.add(mesh_dome_meridian_c_20);
  meshes["dome-meridian-c"] = mesh_dome_meridian_c_20;
  colliders["dome-meridian-c"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-meridian-c"] ??= [];
  destructionGroups["dome-meridian-c"].push(node_dome_meridian_c_20);

  const endpoint_dome_meridian_d_21 = makeAttachmentEndpoint(null);
  const node_dome_meridian_d_21 = new THREE.Group();
  node_dome_meridian_d_21.name = "Dome meridian 135deg__pivot";
  node_dome_meridian_d_21.scale.set(1, 1, 1);
  if (endpoint_dome_meridian_d_21) {
    node_dome_meridian_d_21.position.copy(endpoint_dome_meridian_d_21.start);
    node_dome_meridian_d_21.rotation.set(0.0, 2.356194, 0.0);
  } else {
    node_dome_meridian_d_21.position.set(0.0, 0.0, 0.0);
    node_dome_meridian_d_21.rotation.set(0.0, 2.356194, 0.0);
  }
  node_dome_meridian_d_21.userData.sculptComponent = {"id": "dome-meridian-d", "name": "Dome meridian 135deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 2.356194, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-d", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_d_21.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-d", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_meridian_d_21);
  nodes["dome-meridian-d"] = node_dome_meridian_d_21;
  const mesh_dome_meridian_d_21Geometry = endpoint_dome_meridian_d_21
    ? new THREE.CylinderGeometry(endpoint_dome_meridian_d_21.endRadius, endpoint_dome_meridian_d_21.baseRadius, endpoint_dome_meridian_d_21.length, 32, 12)
    : buildTaperedSweepGeometry({"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false});
  if (!endpoint_dome_meridian_d_21) {
    mesh_dome_meridian_d_21Geometry.scale(9.6, 9.6, 9.6);
  }
  const mesh_dome_meridian_d_21 = new THREE.Mesh(
    mesh_dome_meridian_d_21Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_meridian_d_21.name = "Dome meridian 135deg";
  if (endpoint_dome_meridian_d_21) {
    mesh_dome_meridian_d_21.position.copy(endpoint_dome_meridian_d_21.midpoint);
    mesh_dome_meridian_d_21.quaternion.copy(endpoint_dome_meridian_d_21.quaternion);
  }
  mesh_dome_meridian_d_21.castShadow = options.castShadow ?? true;
  mesh_dome_meridian_d_21.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_meridian_d_21.userData.sculptComponent = {"id": "dome-meridian-d", "name": "Dome meridian 135deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 2.356194, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-d", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_d_21.add(mesh_dome_meridian_d_21);
  meshes["dome-meridian-d"] = mesh_dome_meridian_d_21;
  colliders["dome-meridian-d"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-meridian-d"] ??= [];
  destructionGroups["dome-meridian-d"].push(node_dome_meridian_d_21);

  const endpoint_dome_meridian_e_22 = makeAttachmentEndpoint(null);
  const node_dome_meridian_e_22 = new THREE.Group();
  node_dome_meridian_e_22.name = "Dome meridian 180deg__pivot";
  node_dome_meridian_e_22.scale.set(1, 1, 1);
  if (endpoint_dome_meridian_e_22) {
    node_dome_meridian_e_22.position.copy(endpoint_dome_meridian_e_22.start);
    node_dome_meridian_e_22.rotation.set(0.0, 3.141593, 0.0);
  } else {
    node_dome_meridian_e_22.position.set(0.0, 0.0, 0.0);
    node_dome_meridian_e_22.rotation.set(0.0, 3.141593, 0.0);
  }
  node_dome_meridian_e_22.userData.sculptComponent = {"id": "dome-meridian-e", "name": "Dome meridian 180deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 3.141593, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-e", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_e_22.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-e", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_meridian_e_22);
  nodes["dome-meridian-e"] = node_dome_meridian_e_22;
  const mesh_dome_meridian_e_22Geometry = endpoint_dome_meridian_e_22
    ? new THREE.CylinderGeometry(endpoint_dome_meridian_e_22.endRadius, endpoint_dome_meridian_e_22.baseRadius, endpoint_dome_meridian_e_22.length, 32, 12)
    : buildTaperedSweepGeometry({"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false});
  if (!endpoint_dome_meridian_e_22) {
    mesh_dome_meridian_e_22Geometry.scale(9.6, 9.6, 9.6);
  }
  const mesh_dome_meridian_e_22 = new THREE.Mesh(
    mesh_dome_meridian_e_22Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_meridian_e_22.name = "Dome meridian 180deg";
  if (endpoint_dome_meridian_e_22) {
    mesh_dome_meridian_e_22.position.copy(endpoint_dome_meridian_e_22.midpoint);
    mesh_dome_meridian_e_22.quaternion.copy(endpoint_dome_meridian_e_22.quaternion);
  }
  mesh_dome_meridian_e_22.castShadow = options.castShadow ?? true;
  mesh_dome_meridian_e_22.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_meridian_e_22.userData.sculptComponent = {"id": "dome-meridian-e", "name": "Dome meridian 180deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 3.141593, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-e", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_e_22.add(mesh_dome_meridian_e_22);
  meshes["dome-meridian-e"] = mesh_dome_meridian_e_22;
  colliders["dome-meridian-e"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-meridian-e"] ??= [];
  destructionGroups["dome-meridian-e"].push(node_dome_meridian_e_22);

  const endpoint_dome_meridian_f_23 = makeAttachmentEndpoint(null);
  const node_dome_meridian_f_23 = new THREE.Group();
  node_dome_meridian_f_23.name = "Dome meridian 225deg__pivot";
  node_dome_meridian_f_23.scale.set(1, 1, 1);
  if (endpoint_dome_meridian_f_23) {
    node_dome_meridian_f_23.position.copy(endpoint_dome_meridian_f_23.start);
    node_dome_meridian_f_23.rotation.set(0.0, 3.926991, 0.0);
  } else {
    node_dome_meridian_f_23.position.set(0.0, 0.0, 0.0);
    node_dome_meridian_f_23.rotation.set(0.0, 3.926991, 0.0);
  }
  node_dome_meridian_f_23.userData.sculptComponent = {"id": "dome-meridian-f", "name": "Dome meridian 225deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 3.926991, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-f", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_f_23.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-f", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_meridian_f_23);
  nodes["dome-meridian-f"] = node_dome_meridian_f_23;
  const mesh_dome_meridian_f_23Geometry = endpoint_dome_meridian_f_23
    ? new THREE.CylinderGeometry(endpoint_dome_meridian_f_23.endRadius, endpoint_dome_meridian_f_23.baseRadius, endpoint_dome_meridian_f_23.length, 32, 12)
    : buildTaperedSweepGeometry({"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false});
  if (!endpoint_dome_meridian_f_23) {
    mesh_dome_meridian_f_23Geometry.scale(9.6, 9.6, 9.6);
  }
  const mesh_dome_meridian_f_23 = new THREE.Mesh(
    mesh_dome_meridian_f_23Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_meridian_f_23.name = "Dome meridian 225deg";
  if (endpoint_dome_meridian_f_23) {
    mesh_dome_meridian_f_23.position.copy(endpoint_dome_meridian_f_23.midpoint);
    mesh_dome_meridian_f_23.quaternion.copy(endpoint_dome_meridian_f_23.quaternion);
  }
  mesh_dome_meridian_f_23.castShadow = options.castShadow ?? true;
  mesh_dome_meridian_f_23.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_meridian_f_23.userData.sculptComponent = {"id": "dome-meridian-f", "name": "Dome meridian 225deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 3.926991, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-f", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_f_23.add(mesh_dome_meridian_f_23);
  meshes["dome-meridian-f"] = mesh_dome_meridian_f_23;
  colliders["dome-meridian-f"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-meridian-f"] ??= [];
  destructionGroups["dome-meridian-f"].push(node_dome_meridian_f_23);

  const endpoint_dome_meridian_g_24 = makeAttachmentEndpoint(null);
  const node_dome_meridian_g_24 = new THREE.Group();
  node_dome_meridian_g_24.name = "Dome meridian 270deg__pivot";
  node_dome_meridian_g_24.scale.set(1, 1, 1);
  if (endpoint_dome_meridian_g_24) {
    node_dome_meridian_g_24.position.copy(endpoint_dome_meridian_g_24.start);
    node_dome_meridian_g_24.rotation.set(0.0, 4.712389, 0.0);
  } else {
    node_dome_meridian_g_24.position.set(0.0, 0.0, 0.0);
    node_dome_meridian_g_24.rotation.set(0.0, 4.712389, 0.0);
  }
  node_dome_meridian_g_24.userData.sculptComponent = {"id": "dome-meridian-g", "name": "Dome meridian 270deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 4.712389, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-g", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_g_24.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-g", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_meridian_g_24);
  nodes["dome-meridian-g"] = node_dome_meridian_g_24;
  const mesh_dome_meridian_g_24Geometry = endpoint_dome_meridian_g_24
    ? new THREE.CylinderGeometry(endpoint_dome_meridian_g_24.endRadius, endpoint_dome_meridian_g_24.baseRadius, endpoint_dome_meridian_g_24.length, 32, 12)
    : buildTaperedSweepGeometry({"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false});
  if (!endpoint_dome_meridian_g_24) {
    mesh_dome_meridian_g_24Geometry.scale(9.6, 9.6, 9.6);
  }
  const mesh_dome_meridian_g_24 = new THREE.Mesh(
    mesh_dome_meridian_g_24Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_meridian_g_24.name = "Dome meridian 270deg";
  if (endpoint_dome_meridian_g_24) {
    mesh_dome_meridian_g_24.position.copy(endpoint_dome_meridian_g_24.midpoint);
    mesh_dome_meridian_g_24.quaternion.copy(endpoint_dome_meridian_g_24.quaternion);
  }
  mesh_dome_meridian_g_24.castShadow = options.castShadow ?? true;
  mesh_dome_meridian_g_24.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_meridian_g_24.userData.sculptComponent = {"id": "dome-meridian-g", "name": "Dome meridian 270deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 4.712389, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-g", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_g_24.add(mesh_dome_meridian_g_24);
  meshes["dome-meridian-g"] = mesh_dome_meridian_g_24;
  colliders["dome-meridian-g"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-meridian-g"] ??= [];
  destructionGroups["dome-meridian-g"].push(node_dome_meridian_g_24);

  const endpoint_dome_meridian_h_25 = makeAttachmentEndpoint(null);
  const node_dome_meridian_h_25 = new THREE.Group();
  node_dome_meridian_h_25.name = "Dome meridian 315deg__pivot";
  node_dome_meridian_h_25.scale.set(1, 1, 1);
  if (endpoint_dome_meridian_h_25) {
    node_dome_meridian_h_25.position.copy(endpoint_dome_meridian_h_25.start);
    node_dome_meridian_h_25.rotation.set(0.0, 5.497787, 0.0);
  } else {
    node_dome_meridian_h_25.position.set(0.0, 0.0, 0.0);
    node_dome_meridian_h_25.rotation.set(0.0, 5.497787, 0.0);
  }
  node_dome_meridian_h_25.userData.sculptComponent = {"id": "dome-meridian-h", "name": "Dome meridian 315deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 5.497787, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-h", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_h_25.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-h", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}};
  (nodes["dome-shell"] ?? root).add(node_dome_meridian_h_25);
  nodes["dome-meridian-h"] = node_dome_meridian_h_25;
  const mesh_dome_meridian_h_25Geometry = endpoint_dome_meridian_h_25
    ? new THREE.CylinderGeometry(endpoint_dome_meridian_h_25.endRadius, endpoint_dome_meridian_h_25.baseRadius, endpoint_dome_meridian_h_25.length, 32, 12)
    : buildTaperedSweepGeometry({"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false});
  if (!endpoint_dome_meridian_h_25) {
    mesh_dome_meridian_h_25Geometry.scale(9.6, 9.6, 9.6);
  }
  const mesh_dome_meridian_h_25 = new THREE.Mesh(
    mesh_dome_meridian_h_25Geometry,
    materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_meridian_h_25.name = "Dome meridian 315deg";
  if (endpoint_dome_meridian_h_25) {
    mesh_dome_meridian_h_25.position.copy(endpoint_dome_meridian_h_25.midpoint);
    mesh_dome_meridian_h_25.quaternion.copy(endpoint_dome_meridian_h_25.quaternion);
  }
  mesh_dome_meridian_h_25.castShadow = options.castShadow ?? true;
  mesh_dome_meridian_h_25.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_meridian_h_25.userData.sculptComponent = {"id": "dome-meridian-h", "name": "Dome meridian 315deg", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "tapered-sweep", "topologyClass": "fiber-strand", "topologyRationale": "Thin structural arc following the dome surface: a swept strand with stations along the arc.", "geometryDescriptor": {"topologyIntent": "One of eight meridian ribs on the dome; quarter-arc stations in the descriptor.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "taperedSweep": {"stations": [{"position": [0.5, 0.0, 0.0], "rx": 0.016, "rz": 0.013, "twist": 0}, {"position": [0.475, 0.155, 0.0], "rx": 0.015, "rz": 0.012, "twist": 0}, {"position": [0.4, 0.3, 0.0], "rx": 0.014, "rz": 0.011, "twist": 0}, {"position": [0.28, 0.415, 0.0], "rx": 0.013, "rz": 0.01, "twist": 0}, {"position": [0.13, 0.48, 0.0], "rx": 0.011, "rz": 0.008, "twist": 0}, {"position": [0.0, 0.5, 0.0], "rx": 0.008, "rz": 0.006, "twist": 0}], "closed": false}}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 9.6, "height": 9.6, "depth": 9.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0, 5.497787, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-meridian-h", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "dome-frame"}}, "material": "dome-frame", "materialLayers": ["dome-frame"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(159, 168, 162, 1.0)", "secondaryAlbedo": "rgba(142, 151, 146, 1.0)", "materialClass": "metal", "materialClassConfidence": 0.8}};
  node_dome_meridian_h_25.add(mesh_dome_meridian_h_25);
  meshes["dome-meridian-h"] = mesh_dome_meridian_h_25;
  colliders["dome-meridian-h"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-meridian-h"] ??= [];
  destructionGroups["dome-meridian-h"].push(node_dome_meridian_h_25);

  const endpoint_dome_finial_26 = makeAttachmentEndpoint(null);
  const node_dome_finial_26 = new THREE.Group();
  node_dome_finial_26.name = "Dome finial__pivot";
  node_dome_finial_26.scale.set(1, 1, 1);
  if (endpoint_dome_finial_26) {
    node_dome_finial_26.position.copy(endpoint_dome_finial_26.start);
    node_dome_finial_26.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_dome_finial_26.position.set(0.0, 5.1, 0.0);
    node_dome_finial_26.rotation.set(0.0, 0.0, 0.0);
  }
  node_dome_finial_26.userData.sculptComponent = {"id": "dome-finial", "name": "Dome finial", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Small pale cap at the dome apex.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 0.9, "height": 1.2, "depth": 0.9, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 5.1, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-finial", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "apex-cap", "description": "Pale cap/vent on a short stem at the dome apex."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["refs/ref-03-elevation.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_dome_finial_26.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-finial", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["dome-shell"] ?? root).add(node_dome_finial_26);
  nodes["dome-finial"] = node_dome_finial_26;
  const mesh_dome_finial_26Geometry = endpoint_dome_finial_26
    ? new THREE.CylinderGeometry(endpoint_dome_finial_26.endRadius, endpoint_dome_finial_26.baseRadius, endpoint_dome_finial_26.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_dome_finial_26) {
    mesh_dome_finial_26Geometry.scale(0.9, 1.2, 0.9);
  }
  const mesh_dome_finial_26 = new THREE.Mesh(
    mesh_dome_finial_26Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_finial_26.name = "Dome finial";
  if (endpoint_dome_finial_26) {
    mesh_dome_finial_26.position.copy(endpoint_dome_finial_26.midpoint);
    mesh_dome_finial_26.quaternion.copy(endpoint_dome_finial_26.quaternion);
  }
  mesh_dome_finial_26.castShadow = options.castShadow ?? true;
  mesh_dome_finial_26.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_finial_26.userData.sculptComponent = {"id": "dome-finial", "name": "Dome finial", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Small pale cap at the dome apex.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "dome-shell", "attachment": null, "dimensions": {"width": 0.9, "height": 1.2, "depth": 0.9, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 5.1, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-finial", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "apex-cap", "description": "Pale cap/vent on a short stem at the dome apex."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["refs/ref-03-elevation.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_dome_finial_26.add(mesh_dome_finial_26);
  meshes["dome-finial"] = mesh_dome_finial_26;
  colliders["dome-finial"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-finial"] ??= [];
  destructionGroups["dome-finial"].push(node_dome_finial_26);

  const endpoint_entrance_portico_27 = makeAttachmentEndpoint(null);
  const node_entrance_portico_27 = new THREE.Group();
  node_entrance_portico_27.name = "Entrance portico__pivot";
  node_entrance_portico_27.scale.set(1, 1, 1);
  if (endpoint_entrance_portico_27) {
    node_entrance_portico_27.position.copy(endpoint_entrance_portico_27.start);
    node_entrance_portico_27.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_entrance_portico_27.position.set(0.0, 7.0, 4.6);
    node_entrance_portico_27.rotation.set(0.0, 0.0, 0.0);
  }
  node_entrance_portico_27.userData.sculptComponent = {"id": "entrance-portico", "name": "Entrance portico", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Columned entrance on the axis: podium, columns, entablature, recessed glass wall, banners.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 28, "height": 9.2, "depth": 12.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 7.0, 4.6], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-portico", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}}, "material": "stone-olive", "materialLayers": ["stone-olive"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(179, 166, 126, 1.0)", "secondaryAlbedo": "rgba(164, 151, 114, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_entrance_portico_27.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-portico", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}};
  (nodes["root"] ?? root).add(node_entrance_portico_27);
  nodes["entrance-portico"] = node_entrance_portico_27;
  const mesh_entrance_portico_27Geometry = endpoint_entrance_portico_27
    ? new THREE.CylinderGeometry(endpoint_entrance_portico_27.endRadius, endpoint_entrance_portico_27.baseRadius, endpoint_entrance_portico_27.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_entrance_portico_27) {
    mesh_entrance_portico_27Geometry.scale(28.0, 9.2, 12.6);
  }
  const mesh_entrance_portico_27 = new THREE.Mesh(
    mesh_entrance_portico_27Geometry,
    materialMap["stone-olive"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_entrance_portico_27.name = "Entrance portico";
  if (endpoint_entrance_portico_27) {
    mesh_entrance_portico_27.position.copy(endpoint_entrance_portico_27.midpoint);
    mesh_entrance_portico_27.quaternion.copy(endpoint_entrance_portico_27.quaternion);
  }
  mesh_entrance_portico_27.castShadow = options.castShadow ?? true;
  mesh_entrance_portico_27.receiveShadow = options.receiveShadow ?? true;
  mesh_entrance_portico_27.userData.sculptComponent = {"id": "entrance-portico", "name": "Entrance portico", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Columned entrance on the axis: podium, columns, entablature, recessed glass wall, banners.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 28, "height": 9.2, "depth": 12.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 7.0, 4.6], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-portico", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}}, "material": "stone-olive", "materialLayers": ["stone-olive"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(179, 166, 126, 1.0)", "secondaryAlbedo": "rgba(164, 151, 114, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_entrance_portico_27.add(mesh_entrance_portico_27);
  meshes["entrance-portico"] = mesh_entrance_portico_27;
  colliders["entrance-portico"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["entrance-portico"] ??= [];
  destructionGroups["entrance-portico"].push(node_entrance_portico_27);

  const endpoint_portico_podium_28 = makeAttachmentEndpoint(null);
  const node_portico_podium_28 = new THREE.Group();
  node_portico_podium_28.name = "Portico podium__pivot";
  node_portico_podium_28.scale.set(1, 1, 1);
  if (endpoint_portico_podium_28) {
    node_portico_podium_28.position.copy(endpoint_portico_podium_28.start);
    node_portico_podium_28.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_portico_podium_28.position.set(0.0, -4.05, 0.0);
    node_portico_podium_28.rotation.set(0.0, 0.0, 0.0);
  }
  node_portico_podium_28.userData.sculptComponent = {"id": "portico-podium", "name": "Portico podium", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Raised entrance stoop in front of the recessed doors.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 28, "height": 1.1, "depth": 12, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -4.05, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-podium", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_portico_podium_28.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-podium", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}};
  (nodes["entrance-portico"] ?? root).add(node_portico_podium_28);
  nodes["portico-podium"] = node_portico_podium_28;
  const mesh_portico_podium_28Geometry = endpoint_portico_podium_28
    ? new THREE.CylinderGeometry(endpoint_portico_podium_28.endRadius, endpoint_portico_podium_28.baseRadius, endpoint_portico_podium_28.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_portico_podium_28) {
    mesh_portico_podium_28Geometry.scale(28.0, 1.1, 12.0);
  }
  const mesh_portico_podium_28 = new THREE.Mesh(
    mesh_portico_podium_28Geometry,
    materialMap["terrace-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_portico_podium_28.name = "Portico podium";
  if (endpoint_portico_podium_28) {
    mesh_portico_podium_28.position.copy(endpoint_portico_podium_28.midpoint);
    mesh_portico_podium_28.quaternion.copy(endpoint_portico_podium_28.quaternion);
  }
  mesh_portico_podium_28.castShadow = options.castShadow ?? true;
  mesh_portico_podium_28.receiveShadow = options.receiveShadow ?? true;
  mesh_portico_podium_28.userData.sculptComponent = {"id": "portico-podium", "name": "Portico podium", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Raised entrance stoop in front of the recessed doors.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 28, "height": 1.1, "depth": 12, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -4.05, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-podium", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_portico_podium_28.add(mesh_portico_podium_28);
  meshes["portico-podium"] = mesh_portico_podium_28;
  colliders["portico-podium"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["portico-podium"] ??= [];
  destructionGroups["portico-podium"].push(node_portico_podium_28);

  const endpoint_portico_columns_29 = makeAttachmentEndpoint(null);
  const node_portico_columns_29 = new THREE.Group();
  node_portico_columns_29.name = "Portico columns__pivot";
  node_portico_columns_29.scale.set(1, 1, 1);
  if (endpoint_portico_columns_29) {
    node_portico_columns_29.position.copy(endpoint_portico_columns_29.start);
    node_portico_columns_29.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_portico_columns_29.position.set(0.0, 0.8, 4.0);
    node_portico_columns_29.rotation.set(0.0, 0.0, 0.0);
  }
  node_portico_columns_29.userData.sculptComponent = {"id": "portico-columns", "name": "Portico columns", "level": "meso", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Eight square columns in one line; the array is looped in code from this single authored member.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 1.05, "height": 8.6, "depth": 1.05, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.8, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-columns", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}}, "material": "stone-olive", "materialLayers": ["stone-olive"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "column-capitals", "description": "Square olive columns with simple flared capitals; bright bevel under the entablature."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(179, 166, 126, 1.0)", "secondaryAlbedo": "rgba(164, 151, 114, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_portico_columns_29.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-columns", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}};
  (nodes["entrance-portico"] ?? root).add(node_portico_columns_29);
  nodes["portico-columns"] = node_portico_columns_29;
  const mesh_portico_columns_29Geometry = endpoint_portico_columns_29
    ? new THREE.CylinderGeometry(endpoint_portico_columns_29.endRadius, endpoint_portico_columns_29.baseRadius, endpoint_portico_columns_29.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_portico_columns_29) {
    mesh_portico_columns_29Geometry.scale(1.05, 8.6, 1.05);
  }
  const mesh_portico_columns_29 = new THREE.Mesh(
    mesh_portico_columns_29Geometry,
    materialMap["stone-olive"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_portico_columns_29.name = "Portico columns";
  if (endpoint_portico_columns_29) {
    mesh_portico_columns_29.position.copy(endpoint_portico_columns_29.midpoint);
    mesh_portico_columns_29.quaternion.copy(endpoint_portico_columns_29.quaternion);
  }
  mesh_portico_columns_29.castShadow = options.castShadow ?? true;
  mesh_portico_columns_29.receiveShadow = options.receiveShadow ?? true;
  mesh_portico_columns_29.userData.sculptComponent = {"id": "portico-columns", "name": "Portico columns", "level": "meso", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Eight square columns in one line; the array is looped in code from this single authored member.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 1.05, "height": 8.6, "depth": 1.05, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.8, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-columns", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}}, "material": "stone-olive", "materialLayers": ["stone-olive"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "column-capitals", "description": "Square olive columns with simple flared capitals; bright bevel under the entablature."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(179, 166, 126, 1.0)", "secondaryAlbedo": "rgba(164, 151, 114, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_portico_columns_29.add(mesh_portico_columns_29);
  meshes["portico-columns"] = mesh_portico_columns_29;
  colliders["portico-columns"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["portico-columns"] ??= [];
  destructionGroups["portico-columns"].push(node_portico_columns_29);

  const endpoint_portico_entablature_30 = makeAttachmentEndpoint(null);
  const node_portico_entablature_30 = new THREE.Group();
  node_portico_entablature_30.name = "Portico entablature__pivot";
  node_portico_entablature_30.scale.set(1, 1, 1);
  if (endpoint_portico_entablature_30) {
    node_portico_entablature_30.position.copy(endpoint_portico_entablature_30.start);
    node_portico_entablature_30.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_portico_entablature_30.position.set(0.0, 5.85, 0.0);
    node_portico_entablature_30.rotation.set(0.0, 0.0, 0.0);
  }
  node_portico_entablature_30.userData.sculptComponent = {"id": "portico-entablature", "name": "Portico entablature", "level": "meso", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Deep entablature slab bridging the columns.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 27, "height": 1.5, "depth": 12.4, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 5.85, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-entablature", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}}, "material": "stone-olive", "materialLayers": ["stone-olive"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(179, 166, 126, 1.0)", "secondaryAlbedo": "rgba(164, 151, 114, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_portico_entablature_30.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-entablature", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}};
  (nodes["entrance-portico"] ?? root).add(node_portico_entablature_30);
  nodes["portico-entablature"] = node_portico_entablature_30;
  const mesh_portico_entablature_30Geometry = endpoint_portico_entablature_30
    ? new THREE.CylinderGeometry(endpoint_portico_entablature_30.endRadius, endpoint_portico_entablature_30.baseRadius, endpoint_portico_entablature_30.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_portico_entablature_30) {
    mesh_portico_entablature_30Geometry.scale(27.0, 1.5, 12.4);
  }
  const mesh_portico_entablature_30 = new THREE.Mesh(
    mesh_portico_entablature_30Geometry,
    materialMap["stone-olive"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_portico_entablature_30.name = "Portico entablature";
  if (endpoint_portico_entablature_30) {
    mesh_portico_entablature_30.position.copy(endpoint_portico_entablature_30.midpoint);
    mesh_portico_entablature_30.quaternion.copy(endpoint_portico_entablature_30.quaternion);
  }
  mesh_portico_entablature_30.castShadow = options.castShadow ?? true;
  mesh_portico_entablature_30.receiveShadow = options.receiveShadow ?? true;
  mesh_portico_entablature_30.userData.sculptComponent = {"id": "portico-entablature", "name": "Portico entablature", "level": "meso", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Deep entablature slab bridging the columns.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 27, "height": 1.5, "depth": 12.4, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 5.85, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-entablature", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}}, "material": "stone-olive", "materialLayers": ["stone-olive"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(179, 166, 126, 1.0)", "secondaryAlbedo": "rgba(164, 151, 114, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_portico_entablature_30.add(mesh_portico_entablature_30);
  meshes["portico-entablature"] = mesh_portico_entablature_30;
  colliders["portico-entablature"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["portico-entablature"] ??= [];
  destructionGroups["portico-entablature"].push(node_portico_entablature_30);

  const endpoint_portico_curtainwall_31 = makeAttachmentEndpoint(null);
  const node_portico_curtainwall_31 = new THREE.Group();
  node_portico_curtainwall_31.name = "Portico curtain wall__pivot";
  node_portico_curtainwall_31.scale.set(1, 1, 1);
  if (endpoint_portico_curtainwall_31) {
    node_portico_curtainwall_31.position.copy(endpoint_portico_curtainwall_31.start);
    node_portico_curtainwall_31.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_portico_curtainwall_31.position.set(0.0, 0.8, -4.8);
    node_portico_curtainwall_31.rotation.set(0.0, 0.0, 0.0);
  }
  node_portico_curtainwall_31.userData.sculptComponent = {"id": "portico-curtainwall", "name": "Portico curtain wall", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Recessed glazed wall behind the columns; door zone sits at its center.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 26, "height": 8.6, "depth": 0.5, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.8, -4.8], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-curtainwall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_portico_curtainwall_31.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-curtainwall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["entrance-portico"] ?? root).add(node_portico_curtainwall_31);
  nodes["portico-curtainwall"] = node_portico_curtainwall_31;
  const mesh_portico_curtainwall_31Geometry = endpoint_portico_curtainwall_31
    ? new THREE.CylinderGeometry(endpoint_portico_curtainwall_31.endRadius, endpoint_portico_curtainwall_31.baseRadius, endpoint_portico_curtainwall_31.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_portico_curtainwall_31) {
    mesh_portico_curtainwall_31Geometry.scale(26.0, 8.6, 0.5);
  }
  const mesh_portico_curtainwall_31 = new THREE.Mesh(
    mesh_portico_curtainwall_31Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_portico_curtainwall_31.name = "Portico curtain wall";
  if (endpoint_portico_curtainwall_31) {
    mesh_portico_curtainwall_31.position.copy(endpoint_portico_curtainwall_31.midpoint);
    mesh_portico_curtainwall_31.quaternion.copy(endpoint_portico_curtainwall_31.quaternion);
  }
  mesh_portico_curtainwall_31.castShadow = options.castShadow ?? true;
  mesh_portico_curtainwall_31.receiveShadow = options.receiveShadow ?? true;
  mesh_portico_curtainwall_31.userData.sculptComponent = {"id": "portico-curtainwall", "name": "Portico curtain wall", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Recessed glazed wall behind the columns; door zone sits at its center.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 26, "height": 8.6, "depth": 0.5, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.8, -4.8], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "portico-curtainwall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_portico_curtainwall_31.add(mesh_portico_curtainwall_31);
  meshes["portico-curtainwall"] = mesh_portico_curtainwall_31;
  colliders["portico-curtainwall"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["portico-curtainwall"] ??= [];
  destructionGroups["portico-curtainwall"].push(node_portico_curtainwall_31);

  const endpoint_entrance_banners_32 = makeAttachmentEndpoint(null);
  const node_entrance_banners_32 = new THREE.Group();
  node_entrance_banners_32.name = "Entrance banners__pivot";
  node_entrance_banners_32.scale.set(1, 1, 1);
  if (endpoint_entrance_banners_32) {
    node_entrance_banners_32.position.copy(endpoint_entrance_banners_32.start);
    node_entrance_banners_32.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_entrance_banners_32.position.set(0.0, -0.2, -4.25);
    node_entrance_banners_32.rotation.set(0.0, 0.0, 0.0);
  }
  node_entrance_banners_32.userData.sculptComponent = {"id": "entrance-banners", "name": "Entrance banners", "level": "micro", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Authoring box spans both banner positions; code places the two panels.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 12.4, "height": 4.0, "depth": 0.3, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -0.2, -4.25], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-banners", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "banner-red"}}, "material": "banner-red", "materialLayers": ["banner-red"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "banner-panels", "description": "Two red vertical banner panels flanking the entrance doors."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 51, 38, 1.0)", "secondaryAlbedo": "rgba(158, 43, 31, 1.0)", "materialClass": "fabric", "materialClassConfidence": 0.8}};
  node_entrance_banners_32.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-banners", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "banner-red"}};
  (nodes["entrance-portico"] ?? root).add(node_entrance_banners_32);
  nodes["entrance-banners"] = node_entrance_banners_32;
  const mesh_entrance_banners_32Geometry = endpoint_entrance_banners_32
    ? new THREE.CylinderGeometry(endpoint_entrance_banners_32.endRadius, endpoint_entrance_banners_32.baseRadius, endpoint_entrance_banners_32.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_entrance_banners_32) {
    mesh_entrance_banners_32Geometry.scale(12.4, 4.0, 0.3);
  }
  const mesh_entrance_banners_32 = new THREE.Mesh(
    mesh_entrance_banners_32Geometry,
    materialMap["banner-red"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_entrance_banners_32.name = "Entrance banners";
  if (endpoint_entrance_banners_32) {
    mesh_entrance_banners_32.position.copy(endpoint_entrance_banners_32.midpoint);
    mesh_entrance_banners_32.quaternion.copy(endpoint_entrance_banners_32.quaternion);
  }
  mesh_entrance_banners_32.castShadow = options.castShadow ?? true;
  mesh_entrance_banners_32.receiveShadow = options.receiveShadow ?? true;
  mesh_entrance_banners_32.userData.sculptComponent = {"id": "entrance-banners", "name": "Entrance banners", "level": "micro", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Authoring box spans both banner positions; code places the two panels.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 12.4, "height": 4.0, "depth": 0.3, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -0.2, -4.25], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-banners", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "banner-red"}}, "material": "banner-red", "materialLayers": ["banner-red"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "banner-panels", "description": "Two red vertical banner panels flanking the entrance doors."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 51, 38, 1.0)", "secondaryAlbedo": "rgba(158, 43, 31, 1.0)", "materialClass": "fabric", "materialClassConfidence": 0.8}};
  node_entrance_banners_32.add(mesh_entrance_banners_32);
  meshes["entrance-banners"] = mesh_entrance_banners_32;
  colliders["entrance-banners"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["entrance-banners"] ??= [];
  destructionGroups["entrance-banners"].push(node_entrance_banners_32);

  const endpoint_entrance_doors_33 = makeAttachmentEndpoint(null);
  const node_entrance_doors_33 = new THREE.Group();
  node_entrance_doors_33.name = "Entrance doors__pivot";
  node_entrance_doors_33.scale.set(1, 1, 1);
  if (endpoint_entrance_doors_33) {
    node_entrance_doors_33.position.copy(endpoint_entrance_doors_33.start);
    node_entrance_doors_33.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_entrance_doors_33.position.set(0.0, -1.65, -4.4);
    node_entrance_doors_33.rotation.set(0.0, 0.0, 0.0);
  }
  node_entrance_doors_33.userData.sculptComponent = {"id": "entrance-doors", "name": "Entrance doors", "level": "micro", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Central door leaf behind the banner pair.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 5.4, "height": 3.6, "depth": 0.4, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -1.65, -4.4], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-doors", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_entrance_doors_33.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-doors", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["entrance-portico"] ?? root).add(node_entrance_doors_33);
  nodes["entrance-doors"] = node_entrance_doors_33;
  const mesh_entrance_doors_33Geometry = endpoint_entrance_doors_33
    ? new THREE.CylinderGeometry(endpoint_entrance_doors_33.endRadius, endpoint_entrance_doors_33.baseRadius, endpoint_entrance_doors_33.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_entrance_doors_33) {
    mesh_entrance_doors_33Geometry.scale(5.4, 3.6, 0.4);
  }
  const mesh_entrance_doors_33 = new THREE.Mesh(
    mesh_entrance_doors_33Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_entrance_doors_33.name = "Entrance doors";
  if (endpoint_entrance_doors_33) {
    mesh_entrance_doors_33.position.copy(endpoint_entrance_doors_33.midpoint);
    mesh_entrance_doors_33.quaternion.copy(endpoint_entrance_doors_33.quaternion);
  }
  mesh_entrance_doors_33.castShadow = options.castShadow ?? true;
  mesh_entrance_doors_33.receiveShadow = options.receiveShadow ?? true;
  mesh_entrance_doors_33.userData.sculptComponent = {"id": "entrance-doors", "name": "Entrance doors", "level": "micro", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Central door leaf behind the banner pair.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "entrance-portico", "attachment": null, "dimensions": {"width": 5.4, "height": 3.6, "depth": 0.4, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -1.65, -4.4], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-doors", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_entrance_doors_33.add(mesh_entrance_doors_33);
  meshes["entrance-doors"] = mesh_entrance_doors_33;
  colliders["entrance-doors"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["entrance-doors"] ??= [];
  destructionGroups["entrance-doors"].push(node_entrance_doors_33);

  const endpoint_west_hall_34 = makeAttachmentEndpoint(null);
  const node_west_hall_34 = new THREE.Group();
  node_west_hall_34.name = "West hall__pivot";
  node_west_hall_34.scale.set(1, 1, 1);
  if (endpoint_west_hall_34) {
    node_west_hall_34.position.copy(endpoint_west_hall_34.start);
    node_west_hall_34.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_west_hall_34.position.set(-40.0, 12.1, -10.0);
    node_west_hall_34.rotation.set(0.0, 0.0, 0.0);
  }
  node_west_hall_34.userData.sculptComponent = {"id": "west-hall", "name": "West hall", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Five-storey side hall with regular window grid, string courses and a hip roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [-40, 12.1, -10], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_west_hall_34.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_west_hall_34);
  nodes["west-hall"] = node_west_hall_34;
  const mesh_west_hall_34Geometry = endpoint_west_hall_34
    ? new THREE.CylinderGeometry(endpoint_west_hall_34.endRadius, endpoint_west_hall_34.baseRadius, endpoint_west_hall_34.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_west_hall_34) {
    mesh_west_hall_34Geometry.scale(38.0, 19.4, 20.0);
  }
  const mesh_west_hall_34 = new THREE.Mesh(
    mesh_west_hall_34Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_west_hall_34.name = "West hall";
  if (endpoint_west_hall_34) {
    mesh_west_hall_34.position.copy(endpoint_west_hall_34.midpoint);
    mesh_west_hall_34.quaternion.copy(endpoint_west_hall_34.quaternion);
  }
  mesh_west_hall_34.castShadow = options.castShadow ?? true;
  mesh_west_hall_34.receiveShadow = options.receiveShadow ?? true;
  mesh_west_hall_34.userData.sculptComponent = {"id": "west-hall", "name": "West hall", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Five-storey side hall with regular window grid, string courses and a hip roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [-40, 12.1, -10], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_west_hall_34.add(mesh_west_hall_34);
  meshes["west-hall"] = mesh_west_hall_34;
  colliders["west-hall"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["west-hall"] ??= [];
  destructionGroups["west-hall"].push(node_west_hall_34);

  const endpoint_west_body_35 = makeAttachmentEndpoint(null);
  const node_west_body_35 = new THREE.Group();
  node_west_body_35.name = "West hall body__pivot";
  node_west_body_35.scale.set(1, 1, 1);
  if (endpoint_west_body_35) {
    node_west_body_35.position.copy(endpoint_west_body_35.start);
    node_west_body_35.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_west_body_35.position.set(0.0, 0.0, 0.0);
    node_west_body_35.rotation.set(0.0, 0.0, 0.0);
  }
  node_west_body_35.userData.sculptComponent = {"id": "west-body", "name": "West hall body", "level": "meso", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Main brick mass; pilasters and string courses are looped in code from these features.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "west-hall", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-body", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "pilaster-strips", "description": "Vertical brick pilaster strips between window bays, slightly proud of the wall."}, {"id": "string-courses", "description": "Thin cream band at each floor line, continuous past the pilasters."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c0.png", "zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_west_body_35.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-body", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["west-hall"] ?? root).add(node_west_body_35);
  nodes["west-body"] = node_west_body_35;
  const mesh_west_body_35Geometry = endpoint_west_body_35
    ? new THREE.CylinderGeometry(endpoint_west_body_35.endRadius, endpoint_west_body_35.baseRadius, endpoint_west_body_35.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_west_body_35) {
    mesh_west_body_35Geometry.scale(38.0, 19.4, 20.0);
  }
  const mesh_west_body_35 = new THREE.Mesh(
    mesh_west_body_35Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_west_body_35.name = "West hall body";
  if (endpoint_west_body_35) {
    mesh_west_body_35.position.copy(endpoint_west_body_35.midpoint);
    mesh_west_body_35.quaternion.copy(endpoint_west_body_35.quaternion);
  }
  mesh_west_body_35.castShadow = options.castShadow ?? true;
  mesh_west_body_35.receiveShadow = options.receiveShadow ?? true;
  mesh_west_body_35.userData.sculptComponent = {"id": "west-body", "name": "West hall body", "level": "meso", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Main brick mass; pilasters and string courses are looped in code from these features.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "west-hall", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-body", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "pilaster-strips", "description": "Vertical brick pilaster strips between window bays, slightly proud of the wall."}, {"id": "string-courses", "description": "Thin cream band at each floor line, continuous past the pilasters."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c0.png", "zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_west_body_35.add(mesh_west_body_35);
  meshes["west-body"] = mesh_west_body_35;
  colliders["west-body"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["west-body"] ??= [];
  destructionGroups["west-body"].push(node_west_body_35);

  const endpoint_wing_windows_west_36 = makeAttachmentEndpoint(null);
  const node_wing_windows_west_36 = new THREE.Group();
  node_wing_windows_west_36.name = "West hall windows__pivot";
  node_wing_windows_west_36.scale.set(1, 1, 1);
  if (endpoint_wing_windows_west_36) {
    node_wing_windows_west_36.position.copy(endpoint_wing_windows_west_36.start);
    node_wing_windows_west_36.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_wing_windows_west_36.position.set(-17.0, 4.0, 10.2);
    node_wing_windows_west_36.rotation.set(0.0, 0.0, 0.0);
  }
  node_wing_windows_west_36.userData.sculptComponent = {"id": "wing-windows-west", "name": "West hall windows", "level": "micro", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored window; the factory loops the full grid (bays x floors) with frames and sills.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "west-hall", "attachment": null, "dimensions": {"width": 1.7, "height": 2.3, "depth": 0.35, "units": "relative", "confidence": 0.8}, "transform": {"position": [-17.0, 4.0, 10.2], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "wing-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "recessed-reveal", "description": "Cream frame surround, glass set back with a projecting sill ledge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_wing_windows_west_36.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "wing-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["west-hall"] ?? root).add(node_wing_windows_west_36);
  nodes["wing-windows-west"] = node_wing_windows_west_36;
  const mesh_wing_windows_west_36Geometry = endpoint_wing_windows_west_36
    ? new THREE.CylinderGeometry(endpoint_wing_windows_west_36.endRadius, endpoint_wing_windows_west_36.baseRadius, endpoint_wing_windows_west_36.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_wing_windows_west_36) {
    mesh_wing_windows_west_36Geometry.scale(1.7, 2.3, 0.35);
  }
  const mesh_wing_windows_west_36 = new THREE.Mesh(
    mesh_wing_windows_west_36Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_wing_windows_west_36.name = "West hall windows";
  if (endpoint_wing_windows_west_36) {
    mesh_wing_windows_west_36.position.copy(endpoint_wing_windows_west_36.midpoint);
    mesh_wing_windows_west_36.quaternion.copy(endpoint_wing_windows_west_36.quaternion);
  }
  mesh_wing_windows_west_36.castShadow = options.castShadow ?? true;
  mesh_wing_windows_west_36.receiveShadow = options.receiveShadow ?? true;
  mesh_wing_windows_west_36.userData.sculptComponent = {"id": "wing-windows-west", "name": "West hall windows", "level": "micro", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored window; the factory loops the full grid (bays x floors) with frames and sills.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "west-hall", "attachment": null, "dimensions": {"width": 1.7, "height": 2.3, "depth": 0.35, "units": "relative", "confidence": 0.8}, "transform": {"position": [-17.0, 4.0, 10.2], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "wing-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "recessed-reveal", "description": "Cream frame surround, glass set back with a projecting sill ledge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_wing_windows_west_36.add(mesh_wing_windows_west_36);
  meshes["wing-windows-west"] = mesh_wing_windows_west_36;
  colliders["wing-windows-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["wing-windows-west"] ??= [];
  destructionGroups["wing-windows-west"].push(node_wing_windows_west_36);

  const endpoint_west_cornice_37 = makeAttachmentEndpoint(null);
  const node_west_cornice_37 = new THREE.Group();
  node_west_cornice_37.name = "West hall eave cornice__pivot";
  node_west_cornice_37.scale.set(1, 1, 1);
  if (endpoint_west_cornice_37) {
    node_west_cornice_37.position.copy(endpoint_west_cornice_37.start);
    node_west_cornice_37.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_west_cornice_37.position.set(0.0, 10.15, 0.0);
    node_west_cornice_37.rotation.set(0.0, 0.0, 0.0);
  }
  node_west_cornice_37.userData.sculptComponent = {"id": "west-cornice", "name": "West hall eave cornice", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Eave cornice band running the full hall front and sides.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "west-hall", "attachment": null, "dimensions": {"width": 38.6, "height": 0.9, "depth": 20.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 10.15, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-cornice", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "eave-cornice", "description": "Pale projecting cornice with dentil shadow line under the eaves."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_west_cornice_37.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-cornice", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["west-hall"] ?? root).add(node_west_cornice_37);
  nodes["west-cornice"] = node_west_cornice_37;
  const mesh_west_cornice_37Geometry = endpoint_west_cornice_37
    ? new THREE.CylinderGeometry(endpoint_west_cornice_37.endRadius, endpoint_west_cornice_37.baseRadius, endpoint_west_cornice_37.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_west_cornice_37) {
    mesh_west_cornice_37Geometry.scale(38.6, 0.9, 20.6);
  }
  const mesh_west_cornice_37 = new THREE.Mesh(
    mesh_west_cornice_37Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_west_cornice_37.name = "West hall eave cornice";
  if (endpoint_west_cornice_37) {
    mesh_west_cornice_37.position.copy(endpoint_west_cornice_37.midpoint);
    mesh_west_cornice_37.quaternion.copy(endpoint_west_cornice_37.quaternion);
  }
  mesh_west_cornice_37.castShadow = options.castShadow ?? true;
  mesh_west_cornice_37.receiveShadow = options.receiveShadow ?? true;
  mesh_west_cornice_37.userData.sculptComponent = {"id": "west-cornice", "name": "West hall eave cornice", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Eave cornice band running the full hall front and sides.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "west-hall", "attachment": null, "dimensions": {"width": 38.6, "height": 0.9, "depth": 20.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 10.15, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-cornice", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "eave-cornice", "description": "Pale projecting cornice with dentil shadow line under the eaves."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_west_cornice_37.add(mesh_west_cornice_37);
  meshes["west-cornice"] = mesh_west_cornice_37;
  colliders["west-cornice"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["west-cornice"] ??= [];
  destructionGroups["west-cornice"].push(node_west_cornice_37);

  const endpoint_west_roof_38 = makeAttachmentEndpoint(null);
  const node_west_roof_38 = new THREE.Group();
  node_west_roof_38.name = "West hall roof__pivot";
  node_west_roof_38.scale.set(1, 1, 1);
  if (endpoint_west_roof_38) {
    node_west_roof_38.position.copy(endpoint_west_roof_38.start);
    node_west_roof_38.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_west_roof_38.position.set(0.0, 12.3, 0.0);
    node_west_roof_38.rotation.set(0.0, 0.0, 0.0);
  }
  node_west_roof_38.userData.sculptComponent = {"id": "west-roof", "name": "West hall roof", "level": "macro", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof: four slopes with ridge and hip caps; hip geometry authored in a factory helper.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "west-hall", "attachment": null, "dimensions": {"width": 39.4, "height": 4.4, "depth": 21.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 12.3, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-roof", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Lighter tan capping runs along every hip and ridge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_west_roof_38.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-roof", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}};
  (nodes["west-hall"] ?? root).add(node_west_roof_38);
  nodes["west-roof"] = node_west_roof_38;
  const mesh_west_roof_38Geometry = endpoint_west_roof_38
    ? new THREE.CylinderGeometry(endpoint_west_roof_38.endRadius, endpoint_west_roof_38.baseRadius, endpoint_west_roof_38.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_west_roof_38) {
    mesh_west_roof_38Geometry.scale(39.4, 4.4, 21.2);
  }
  const mesh_west_roof_38 = new THREE.Mesh(
    mesh_west_roof_38Geometry,
    materialMap["roof-tile"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_west_roof_38.name = "West hall roof";
  if (endpoint_west_roof_38) {
    mesh_west_roof_38.position.copy(endpoint_west_roof_38.midpoint);
    mesh_west_roof_38.quaternion.copy(endpoint_west_roof_38.quaternion);
  }
  mesh_west_roof_38.castShadow = options.castShadow ?? true;
  mesh_west_roof_38.receiveShadow = options.receiveShadow ?? true;
  mesh_west_roof_38.userData.sculptComponent = {"id": "west-roof", "name": "West hall roof", "level": "macro", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof: four slopes with ridge and hip caps; hip geometry authored in a factory helper.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "west-hall", "attachment": null, "dimensions": {"width": 39.4, "height": 4.4, "depth": 21.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 12.3, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-roof", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Lighter tan capping runs along every hip and ridge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_west_roof_38.add(mesh_west_roof_38);
  meshes["west-roof"] = mesh_west_roof_38;
  colliders["west-roof"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["west-roof"] ??= [];
  destructionGroups["west-roof"].push(node_west_roof_38);

  const endpoint_tower_west_39 = makeAttachmentEndpoint(null);
  const node_tower_west_39 = new THREE.Group();
  node_tower_west_39.name = "Tower (west)__pivot";
  node_tower_west_39.scale.set(1, 1, 1);
  if (endpoint_tower_west_39) {
    node_tower_west_39.position.copy(endpoint_tower_west_39.start);
    node_tower_west_39.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_west_39.position.set(-60.2, 17.0, -0.5);
    node_tower_west_39.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_west_39.userData.sculptComponent = {"id": "tower-west", "name": "Tower (west)", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Square terminal tower: brick shaft, cream front panel with paired slots, belfry stage with arches, balustrade, pyramid cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 7.0, "height": 29.2, "depth": 7.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [-60.2, 17.0, -0.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png", "zones-ref04/zone-r0c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_west_39.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_tower_west_39);
  nodes["tower-west"] = node_tower_west_39;
  const mesh_tower_west_39Geometry = endpoint_tower_west_39
    ? new THREE.CylinderGeometry(endpoint_tower_west_39.endRadius, endpoint_tower_west_39.baseRadius, endpoint_tower_west_39.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_west_39) {
    mesh_tower_west_39Geometry.scale(7.0, 29.2, 7.2);
  }
  const mesh_tower_west_39 = new THREE.Mesh(
    mesh_tower_west_39Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_west_39.name = "Tower (west)";
  if (endpoint_tower_west_39) {
    mesh_tower_west_39.position.copy(endpoint_tower_west_39.midpoint);
    mesh_tower_west_39.quaternion.copy(endpoint_tower_west_39.quaternion);
  }
  mesh_tower_west_39.castShadow = options.castShadow ?? true;
  mesh_tower_west_39.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_west_39.userData.sculptComponent = {"id": "tower-west", "name": "Tower (west)", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Square terminal tower: brick shaft, cream front panel with paired slots, belfry stage with arches, balustrade, pyramid cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 7.0, "height": 29.2, "depth": 7.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [-60.2, 17.0, -0.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png", "zones-ref04/zone-r0c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_west_39.add(mesh_tower_west_39);
  meshes["tower-west"] = mesh_tower_west_39;
  colliders["tower-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-west"] ??= [];
  destructionGroups["tower-west"].push(node_tower_west_39);

  const endpoint_tower_shaft_west_40 = makeAttachmentEndpoint(null);
  const node_tower_shaft_west_40 = new THREE.Group();
  node_tower_shaft_west_40.name = "Tower shaft (west)__pivot";
  node_tower_shaft_west_40.scale.set(1, 1, 1);
  if (endpoint_tower_shaft_west_40) {
    node_tower_shaft_west_40.position.copy(endpoint_tower_shaft_west_40.start);
    node_tower_shaft_west_40.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_shaft_west_40.position.set(0.0, -1.6, 0.0);
    node_tower_shaft_west_40.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_shaft_west_40.userData.sculptComponent = {"id": "tower-shaft-west", "name": "Tower shaft (west)", "level": "meso", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Brick shaft; corner quoins looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 6.8, "height": 26.0, "depth": 7.0, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-shaft-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "corner-quoins", "description": "Pale vertical quoin strips on the tower corners."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_shaft_west_40.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-shaft-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["tower-west"] ?? root).add(node_tower_shaft_west_40);
  nodes["tower-shaft-west"] = node_tower_shaft_west_40;
  const mesh_tower_shaft_west_40Geometry = endpoint_tower_shaft_west_40
    ? new THREE.CylinderGeometry(endpoint_tower_shaft_west_40.endRadius, endpoint_tower_shaft_west_40.baseRadius, endpoint_tower_shaft_west_40.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_shaft_west_40) {
    mesh_tower_shaft_west_40Geometry.scale(6.8, 26.0, 7.0);
  }
  const mesh_tower_shaft_west_40 = new THREE.Mesh(
    mesh_tower_shaft_west_40Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_shaft_west_40.name = "Tower shaft (west)";
  if (endpoint_tower_shaft_west_40) {
    mesh_tower_shaft_west_40.position.copy(endpoint_tower_shaft_west_40.midpoint);
    mesh_tower_shaft_west_40.quaternion.copy(endpoint_tower_shaft_west_40.quaternion);
  }
  mesh_tower_shaft_west_40.castShadow = options.castShadow ?? true;
  mesh_tower_shaft_west_40.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_shaft_west_40.userData.sculptComponent = {"id": "tower-shaft-west", "name": "Tower shaft (west)", "level": "meso", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Brick shaft; corner quoins looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 6.8, "height": 26.0, "depth": 7.0, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-shaft-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "corner-quoins", "description": "Pale vertical quoin strips on the tower corners."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_shaft_west_40.add(mesh_tower_shaft_west_40);
  meshes["tower-shaft-west"] = mesh_tower_shaft_west_40;
  colliders["tower-shaft-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-shaft-west"] ??= [];
  destructionGroups["tower-shaft-west"].push(node_tower_shaft_west_40);

  const endpoint_tower_frontpanel_west_41 = makeAttachmentEndpoint(null);
  const node_tower_frontpanel_west_41 = new THREE.Group();
  node_tower_frontpanel_west_41.name = "Tower front panel (west)__pivot";
  node_tower_frontpanel_west_41.scale.set(1, 1, 1);
  if (endpoint_tower_frontpanel_west_41) {
    node_tower_frontpanel_west_41.position.copy(endpoint_tower_frontpanel_west_41.start);
    node_tower_frontpanel_west_41.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_frontpanel_west_41.position.set(0.0, -1.6, 3.22);
    node_tower_frontpanel_west_41.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_frontpanel_west_41.userData.sculptComponent = {"id": "tower-frontpanel-west", "name": "Tower front panel (west)", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream vertical panel carrying the paired slot windows; slots looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 4.4, "height": 24.0, "depth": 0.5, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 3.22], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-frontpanel-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "paired-slots", "description": "Stacked narrow paired windows, one pair per floor, cream frames."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_frontpanel_west_41.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-frontpanel-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["tower-west"] ?? root).add(node_tower_frontpanel_west_41);
  nodes["tower-frontpanel-west"] = node_tower_frontpanel_west_41;
  const mesh_tower_frontpanel_west_41Geometry = endpoint_tower_frontpanel_west_41
    ? new THREE.CylinderGeometry(endpoint_tower_frontpanel_west_41.endRadius, endpoint_tower_frontpanel_west_41.baseRadius, endpoint_tower_frontpanel_west_41.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_frontpanel_west_41) {
    mesh_tower_frontpanel_west_41Geometry.scale(4.4, 24.0, 0.5);
  }
  const mesh_tower_frontpanel_west_41 = new THREE.Mesh(
    mesh_tower_frontpanel_west_41Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_frontpanel_west_41.name = "Tower front panel (west)";
  if (endpoint_tower_frontpanel_west_41) {
    mesh_tower_frontpanel_west_41.position.copy(endpoint_tower_frontpanel_west_41.midpoint);
    mesh_tower_frontpanel_west_41.quaternion.copy(endpoint_tower_frontpanel_west_41.quaternion);
  }
  mesh_tower_frontpanel_west_41.castShadow = options.castShadow ?? true;
  mesh_tower_frontpanel_west_41.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_frontpanel_west_41.userData.sculptComponent = {"id": "tower-frontpanel-west", "name": "Tower front panel (west)", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream vertical panel carrying the paired slot windows; slots looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 4.4, "height": 24.0, "depth": 0.5, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 3.22], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-frontpanel-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "paired-slots", "description": "Stacked narrow paired windows, one pair per floor, cream frames."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_frontpanel_west_41.add(mesh_tower_frontpanel_west_41);
  meshes["tower-frontpanel-west"] = mesh_tower_frontpanel_west_41;
  colliders["tower-frontpanel-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-frontpanel-west"] ??= [];
  destructionGroups["tower-frontpanel-west"].push(node_tower_frontpanel_west_41);

  const endpoint_tower_windows_west_42 = makeAttachmentEndpoint(null);
  const node_tower_windows_west_42 = new THREE.Group();
  node_tower_windows_west_42.name = "Tower slot windows (west)__pivot";
  node_tower_windows_west_42.scale.set(1, 1, 1);
  if (endpoint_tower_windows_west_42) {
    node_tower_windows_west_42.position.copy(endpoint_tower_windows_west_42.start);
    node_tower_windows_west_42.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_windows_west_42.position.set(0.0, -1.6, 3.45);
    node_tower_windows_west_42.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_windows_west_42.userData.sculptComponent = {"id": "tower-windows-west", "name": "Tower slot windows (west)", "level": "micro", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored slot; looped as stacked pairs in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 0.55, "height": 1.5, "depth": 0.3, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 3.45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_tower_windows_west_42.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["tower-west"] ?? root).add(node_tower_windows_west_42);
  nodes["tower-windows-west"] = node_tower_windows_west_42;
  const mesh_tower_windows_west_42Geometry = endpoint_tower_windows_west_42
    ? new THREE.CylinderGeometry(endpoint_tower_windows_west_42.endRadius, endpoint_tower_windows_west_42.baseRadius, endpoint_tower_windows_west_42.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_windows_west_42) {
    mesh_tower_windows_west_42Geometry.scale(0.55, 1.5, 0.3);
  }
  const mesh_tower_windows_west_42 = new THREE.Mesh(
    mesh_tower_windows_west_42Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_windows_west_42.name = "Tower slot windows (west)";
  if (endpoint_tower_windows_west_42) {
    mesh_tower_windows_west_42.position.copy(endpoint_tower_windows_west_42.midpoint);
    mesh_tower_windows_west_42.quaternion.copy(endpoint_tower_windows_west_42.quaternion);
  }
  mesh_tower_windows_west_42.castShadow = options.castShadow ?? true;
  mesh_tower_windows_west_42.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_windows_west_42.userData.sculptComponent = {"id": "tower-windows-west", "name": "Tower slot windows (west)", "level": "micro", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored slot; looped as stacked pairs in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 0.55, "height": 1.5, "depth": 0.3, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 3.45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_tower_windows_west_42.add(mesh_tower_windows_west_42);
  meshes["tower-windows-west"] = mesh_tower_windows_west_42;
  colliders["tower-windows-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-windows-west"] ??= [];
  destructionGroups["tower-windows-west"].push(node_tower_windows_west_42);

  const endpoint_tower_bands_west_43 = makeAttachmentEndpoint(null);
  const node_tower_bands_west_43 = new THREE.Group();
  node_tower_bands_west_43.name = "Tower bands (west)__pivot";
  node_tower_bands_west_43.scale.set(1, 1, 1);
  if (endpoint_tower_bands_west_43) {
    node_tower_bands_west_43.position.copy(endpoint_tower_bands_west_43.start);
    node_tower_bands_west_43.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_bands_west_43.position.set(0.0, 11.4, 0.0);
    node_tower_bands_west_43.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_bands_west_43.userData.sculptComponent = {"id": "tower-bands-west", "name": "Tower bands (west)", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream band at each tower stage line; three bands looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 7.2, "height": 0.6, "depth": 7.4, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 11.4, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-bands-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_bands_west_43.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-bands-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["tower-west"] ?? root).add(node_tower_bands_west_43);
  nodes["tower-bands-west"] = node_tower_bands_west_43;
  const mesh_tower_bands_west_43Geometry = endpoint_tower_bands_west_43
    ? new THREE.CylinderGeometry(endpoint_tower_bands_west_43.endRadius, endpoint_tower_bands_west_43.baseRadius, endpoint_tower_bands_west_43.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_bands_west_43) {
    mesh_tower_bands_west_43Geometry.scale(7.2, 0.6, 7.4);
  }
  const mesh_tower_bands_west_43 = new THREE.Mesh(
    mesh_tower_bands_west_43Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_bands_west_43.name = "Tower bands (west)";
  if (endpoint_tower_bands_west_43) {
    mesh_tower_bands_west_43.position.copy(endpoint_tower_bands_west_43.midpoint);
    mesh_tower_bands_west_43.quaternion.copy(endpoint_tower_bands_west_43.quaternion);
  }
  mesh_tower_bands_west_43.castShadow = options.castShadow ?? true;
  mesh_tower_bands_west_43.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_bands_west_43.userData.sculptComponent = {"id": "tower-bands-west", "name": "Tower bands (west)", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream band at each tower stage line; three bands looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 7.2, "height": 0.6, "depth": 7.4, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 11.4, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-bands-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_bands_west_43.add(mesh_tower_bands_west_43);
  meshes["tower-bands-west"] = mesh_tower_bands_west_43;
  colliders["tower-bands-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-bands-west"] ??= [];
  destructionGroups["tower-bands-west"].push(node_tower_bands_west_43);

  const endpoint_tower_belfry_west_44 = makeAttachmentEndpoint(null);
  const node_tower_belfry_west_44 = new THREE.Group();
  node_tower_belfry_west_44.name = "Tower belfry (west)__pivot";
  node_tower_belfry_west_44.scale.set(1, 1, 1);
  if (endpoint_tower_belfry_west_44) {
    node_tower_belfry_west_44.position.copy(endpoint_tower_belfry_west_44.start);
    node_tower_belfry_west_44.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_belfry_west_44.position.set(0.0, 14.6, 0.0);
    node_tower_belfry_west_44.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_belfry_west_44.userData.sculptComponent = {"id": "tower-belfry-west", "name": "Tower belfry (west)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Open belfry stage: arch cutouts authored with arch-shaped plates in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 6.4, "height": 5.8, "depth": 6.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 14.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-belfry-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "arch-openings", "description": "Two arched openings with cream surrounds at the belfry stage; dark shadow inside."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_belfry_west_44.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-belfry-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["tower-west"] ?? root).add(node_tower_belfry_west_44);
  nodes["tower-belfry-west"] = node_tower_belfry_west_44;
  const mesh_tower_belfry_west_44Geometry = endpoint_tower_belfry_west_44
    ? new THREE.CylinderGeometry(endpoint_tower_belfry_west_44.endRadius, endpoint_tower_belfry_west_44.baseRadius, endpoint_tower_belfry_west_44.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_belfry_west_44) {
    mesh_tower_belfry_west_44Geometry.scale(6.4, 5.8, 6.6);
  }
  const mesh_tower_belfry_west_44 = new THREE.Mesh(
    mesh_tower_belfry_west_44Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_belfry_west_44.name = "Tower belfry (west)";
  if (endpoint_tower_belfry_west_44) {
    mesh_tower_belfry_west_44.position.copy(endpoint_tower_belfry_west_44.midpoint);
    mesh_tower_belfry_west_44.quaternion.copy(endpoint_tower_belfry_west_44.quaternion);
  }
  mesh_tower_belfry_west_44.castShadow = options.castShadow ?? true;
  mesh_tower_belfry_west_44.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_belfry_west_44.userData.sculptComponent = {"id": "tower-belfry-west", "name": "Tower belfry (west)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Open belfry stage: arch cutouts authored with arch-shaped plates in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 6.4, "height": 5.8, "depth": 6.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 14.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-belfry-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "arch-openings", "description": "Two arched openings with cream surrounds at the belfry stage; dark shadow inside."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_belfry_west_44.add(mesh_tower_belfry_west_44);
  meshes["tower-belfry-west"] = mesh_tower_belfry_west_44;
  colliders["tower-belfry-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-belfry-west"] ??= [];
  destructionGroups["tower-belfry-west"].push(node_tower_belfry_west_44);

  const endpoint_tower_balustrade_west_45 = makeAttachmentEndpoint(null);
  const node_tower_balustrade_west_45 = new THREE.Group();
  node_tower_balustrade_west_45.name = "Tower balustrade (west)__pivot";
  node_tower_balustrade_west_45.scale.set(1, 1, 1);
  if (endpoint_tower_balustrade_west_45) {
    node_tower_balustrade_west_45.position.copy(endpoint_tower_balustrade_west_45.start);
    node_tower_balustrade_west_45.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_balustrade_west_45.position.set(0.0, 17.75, 0.0);
    node_tower_balustrade_west_45.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_balustrade_west_45.userData.sculptComponent = {"id": "tower-balustrade-west", "name": "Tower balustrade (west)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Fine baluster cadence looped in code under the pyramid roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 6.4, "height": 0.7, "depth": 6.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 17.75, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-balustrade-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "baluster-row", "description": "Row of small repeated baluster posts between rail and cornice at the tower top."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["refs/ref-03-elevation.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_balustrade_west_45.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-balustrade-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}};
  (nodes["tower-west"] ?? root).add(node_tower_balustrade_west_45);
  nodes["tower-balustrade-west"] = node_tower_balustrade_west_45;
  const mesh_tower_balustrade_west_45Geometry = endpoint_tower_balustrade_west_45
    ? new THREE.CylinderGeometry(endpoint_tower_balustrade_west_45.endRadius, endpoint_tower_balustrade_west_45.baseRadius, endpoint_tower_balustrade_west_45.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_balustrade_west_45) {
    mesh_tower_balustrade_west_45Geometry.scale(6.4, 0.7, 6.6);
  }
  const mesh_tower_balustrade_west_45 = new THREE.Mesh(
    mesh_tower_balustrade_west_45Geometry,
    materialMap["terrace-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_balustrade_west_45.name = "Tower balustrade (west)";
  if (endpoint_tower_balustrade_west_45) {
    mesh_tower_balustrade_west_45.position.copy(endpoint_tower_balustrade_west_45.midpoint);
    mesh_tower_balustrade_west_45.quaternion.copy(endpoint_tower_balustrade_west_45.quaternion);
  }
  mesh_tower_balustrade_west_45.castShadow = options.castShadow ?? true;
  mesh_tower_balustrade_west_45.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_balustrade_west_45.userData.sculptComponent = {"id": "tower-balustrade-west", "name": "Tower balustrade (west)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Fine baluster cadence looped in code under the pyramid roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 6.4, "height": 0.7, "depth": 6.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 17.75, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-balustrade-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "baluster-row", "description": "Row of small repeated baluster posts between rail and cornice at the tower top."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["refs/ref-03-elevation.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_balustrade_west_45.add(mesh_tower_balustrade_west_45);
  meshes["tower-balustrade-west"] = mesh_tower_balustrade_west_45;
  colliders["tower-balustrade-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-balustrade-west"] ??= [];
  destructionGroups["tower-balustrade-west"].push(node_tower_balustrade_west_45);

  const endpoint_tower_roof_west_46 = makeAttachmentEndpoint(null);
  const node_tower_roof_west_46 = new THREE.Group();
  node_tower_roof_west_46.name = "Tower cap (west)__pivot";
  node_tower_roof_west_46.scale.set(1, 1, 1);
  if (endpoint_tower_roof_west_46) {
    node_tower_roof_west_46.position.copy(endpoint_tower_roof_west_46.start);
    node_tower_roof_west_46.rotation.set(0.0, 0.7853981633974483, 0.0);
  } else {
    node_tower_roof_west_46.position.set(0.0, 20.3, 0.0);
    node_tower_roof_west_46.rotation.set(0.0, 0.7853981633974483, 0.0);
  }
  node_tower_roof_west_46.userData.sculptComponent = {"id": "tower-roof-west", "name": "Tower cap (west)", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Four-sided pyramid: a 4-segment lathe with a square base.", "geometryDescriptor": {"topologyIntent": "Shallow pyramid cap; emitted as a 4-segment lathe.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 4}}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 10.47, "height": 4.2, "depth": 10.47, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 20.3, 0.0], "rotation": [0, 0.7853981633974483, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-roof-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_roof_west_46.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-roof-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}};
  (nodes["tower-west"] ?? root).add(node_tower_roof_west_46);
  nodes["tower-roof-west"] = node_tower_roof_west_46;
  const mesh_tower_roof_west_46Geometry = endpoint_tower_roof_west_46
    ? new THREE.CylinderGeometry(endpoint_tower_roof_west_46.endRadius, endpoint_tower_roof_west_46.baseRadius, endpoint_tower_roof_west_46.length, 32, 12)
    : buildLatheGeometry({"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 4});
  if (!endpoint_tower_roof_west_46) {
    mesh_tower_roof_west_46Geometry.scale(10.47, 4.2, 10.47);
  }
  const mesh_tower_roof_west_46 = new THREE.Mesh(
    mesh_tower_roof_west_46Geometry,
    materialMap["roof-tile"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_roof_west_46.name = "Tower cap (west)";
  if (endpoint_tower_roof_west_46) {
    mesh_tower_roof_west_46.position.copy(endpoint_tower_roof_west_46.midpoint);
    mesh_tower_roof_west_46.quaternion.copy(endpoint_tower_roof_west_46.quaternion);
  }
  mesh_tower_roof_west_46.castShadow = options.castShadow ?? true;
  mesh_tower_roof_west_46.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_roof_west_46.userData.sculptComponent = {"id": "tower-roof-west", "name": "Tower cap (west)", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Four-sided pyramid: a 4-segment lathe with a square base.", "geometryDescriptor": {"topologyIntent": "Shallow pyramid cap; emitted as a 4-segment lathe.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 4}}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 10.47, "height": 4.2, "depth": 10.47, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 20.3, 0.0], "rotation": [0, 0.7853981633974483, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-roof-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_roof_west_46.add(mesh_tower_roof_west_46);
  meshes["tower-roof-west"] = mesh_tower_roof_west_46;
  colliders["tower-roof-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-roof-west"] ??= [];
  destructionGroups["tower-roof-west"].push(node_tower_roof_west_46);

  const endpoint_tower_finial_west_47 = makeAttachmentEndpoint(null);
  const node_tower_finial_west_47 = new THREE.Group();
  node_tower_finial_west_47.name = "Tower finial (west)__pivot";
  node_tower_finial_west_47.scale.set(1, 1, 1);
  if (endpoint_tower_finial_west_47) {
    node_tower_finial_west_47.position.copy(endpoint_tower_finial_west_47.start);
    node_tower_finial_west_47.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_finial_west_47.position.set(0.0, 22.6, 0.0);
    node_tower_finial_west_47.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_finial_west_47.userData.sculptComponent = {"id": "tower-finial-west", "name": "Tower finial (west)", "level": "micro", "role": "structure", "importance": 0.35, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Small finial on the tower apex.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 0.6, "height": 1.2, "depth": 0.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 22.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-finial-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-ridge"}}, "material": "roof-ridge", "materialLayers": ["roof-ridge"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(192, 138, 98, 1.0)", "secondaryAlbedo": "rgba(178, 124, 85, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_finial_west_47.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-finial-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-ridge"}};
  (nodes["tower-west"] ?? root).add(node_tower_finial_west_47);
  nodes["tower-finial-west"] = node_tower_finial_west_47;
  const mesh_tower_finial_west_47Geometry = endpoint_tower_finial_west_47
    ? new THREE.CylinderGeometry(endpoint_tower_finial_west_47.endRadius, endpoint_tower_finial_west_47.baseRadius, endpoint_tower_finial_west_47.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_finial_west_47) {
    mesh_tower_finial_west_47Geometry.scale(0.6, 1.2, 0.6);
  }
  const mesh_tower_finial_west_47 = new THREE.Mesh(
    mesh_tower_finial_west_47Geometry,
    materialMap["roof-ridge"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_finial_west_47.name = "Tower finial (west)";
  if (endpoint_tower_finial_west_47) {
    mesh_tower_finial_west_47.position.copy(endpoint_tower_finial_west_47.midpoint);
    mesh_tower_finial_west_47.quaternion.copy(endpoint_tower_finial_west_47.quaternion);
  }
  mesh_tower_finial_west_47.castShadow = options.castShadow ?? true;
  mesh_tower_finial_west_47.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_finial_west_47.userData.sculptComponent = {"id": "tower-finial-west", "name": "Tower finial (west)", "level": "micro", "role": "structure", "importance": 0.35, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Small finial on the tower apex.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-west", "attachment": null, "dimensions": {"width": 0.6, "height": 1.2, "depth": 0.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 22.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-finial-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-ridge"}}, "material": "roof-ridge", "materialLayers": ["roof-ridge"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(192, 138, 98, 1.0)", "secondaryAlbedo": "rgba(178, 124, 85, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_finial_west_47.add(mesh_tower_finial_west_47);
  meshes["tower-finial-west"] = mesh_tower_finial_west_47;
  colliders["tower-finial-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-finial-west"] ??= [];
  destructionGroups["tower-finial-west"].push(node_tower_finial_west_47);

  const endpoint_pavilion_west_48 = makeAttachmentEndpoint(null);
  const node_pavilion_west_48 = new THREE.Group();
  node_pavilion_west_48.name = "Front pavilion (west)__pivot";
  node_pavilion_west_48.scale.set(1, 1, 1);
  if (endpoint_pavilion_west_48) {
    node_pavilion_west_48.position.copy(endpoint_pavilion_west_48.start);
    node_pavilion_west_48.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pavilion_west_48.position.set(-22.0, 8.7, 4.0);
    node_pavilion_west_48.rotation.set(0.0, 0.0, 0.0);
  }
  node_pavilion_west_48.userData.sculptComponent = {"id": "pavilion-west", "name": "Front pavilion (west)", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low two-storey mass with a hip roof flanking the portico in front of the hall junction.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 13, "height": 12.6, "depth": 13, "units": "relative", "confidence": 0.8}, "transform": {"position": [-22.0, 8.7, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_west_48.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_pavilion_west_48);
  nodes["pavilion-west"] = node_pavilion_west_48;
  const mesh_pavilion_west_48Geometry = endpoint_pavilion_west_48
    ? new THREE.CylinderGeometry(endpoint_pavilion_west_48.endRadius, endpoint_pavilion_west_48.baseRadius, endpoint_pavilion_west_48.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pavilion_west_48) {
    mesh_pavilion_west_48Geometry.scale(13.0, 12.6, 13.0);
  }
  const mesh_pavilion_west_48 = new THREE.Mesh(
    mesh_pavilion_west_48Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pavilion_west_48.name = "Front pavilion (west)";
  if (endpoint_pavilion_west_48) {
    mesh_pavilion_west_48.position.copy(endpoint_pavilion_west_48.midpoint);
    mesh_pavilion_west_48.quaternion.copy(endpoint_pavilion_west_48.quaternion);
  }
  mesh_pavilion_west_48.castShadow = options.castShadow ?? true;
  mesh_pavilion_west_48.receiveShadow = options.receiveShadow ?? true;
  mesh_pavilion_west_48.userData.sculptComponent = {"id": "pavilion-west", "name": "Front pavilion (west)", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low two-storey mass with a hip roof flanking the portico in front of the hall junction.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 13, "height": 12.6, "depth": 13, "units": "relative", "confidence": 0.8}, "transform": {"position": [-22.0, 8.7, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_west_48.add(mesh_pavilion_west_48);
  meshes["pavilion-west"] = mesh_pavilion_west_48;
  colliders["pavilion-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pavilion-west"] ??= [];
  destructionGroups["pavilion-west"].push(node_pavilion_west_48);

  const endpoint_pavilion_windows_west_49 = makeAttachmentEndpoint(null);
  const node_pavilion_windows_west_49 = new THREE.Group();
  node_pavilion_windows_west_49.name = "Pavilion windows (west)__pivot";
  node_pavilion_windows_west_49.scale.set(1, 1, 1);
  if (endpoint_pavilion_windows_west_49) {
    node_pavilion_windows_west_49.position.copy(endpoint_pavilion_windows_west_49.start);
    node_pavilion_windows_west_49.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pavilion_windows_west_49.position.set(0.0, 0.7, 6.4);
    node_pavilion_windows_west_49.rotation.set(0.0, 0.0, 0.0);
  }
  node_pavilion_windows_west_49.userData.sculptComponent = {"id": "pavilion-windows-west", "name": "Pavilion windows (west)", "level": "micro", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored window; a 2-row bay grid is looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "pavilion-west", "attachment": null, "dimensions": {"width": 1.5, "height": 2.0, "depth": 0.35, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 0.7, 6.4], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_pavilion_windows_west_49.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["pavilion-west"] ?? root).add(node_pavilion_windows_west_49);
  nodes["pavilion-windows-west"] = node_pavilion_windows_west_49;
  const mesh_pavilion_windows_west_49Geometry = endpoint_pavilion_windows_west_49
    ? new THREE.CylinderGeometry(endpoint_pavilion_windows_west_49.endRadius, endpoint_pavilion_windows_west_49.baseRadius, endpoint_pavilion_windows_west_49.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pavilion_windows_west_49) {
    mesh_pavilion_windows_west_49Geometry.scale(1.5, 2.0, 0.35);
  }
  const mesh_pavilion_windows_west_49 = new THREE.Mesh(
    mesh_pavilion_windows_west_49Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pavilion_windows_west_49.name = "Pavilion windows (west)";
  if (endpoint_pavilion_windows_west_49) {
    mesh_pavilion_windows_west_49.position.copy(endpoint_pavilion_windows_west_49.midpoint);
    mesh_pavilion_windows_west_49.quaternion.copy(endpoint_pavilion_windows_west_49.quaternion);
  }
  mesh_pavilion_windows_west_49.castShadow = options.castShadow ?? true;
  mesh_pavilion_windows_west_49.receiveShadow = options.receiveShadow ?? true;
  mesh_pavilion_windows_west_49.userData.sculptComponent = {"id": "pavilion-windows-west", "name": "Pavilion windows (west)", "level": "micro", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored window; a 2-row bay grid is looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "pavilion-west", "attachment": null, "dimensions": {"width": 1.5, "height": 2.0, "depth": 0.35, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 0.7, 6.4], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_pavilion_windows_west_49.add(mesh_pavilion_windows_west_49);
  meshes["pavilion-windows-west"] = mesh_pavilion_windows_west_49;
  colliders["pavilion-windows-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pavilion-windows-west"] ??= [];
  destructionGroups["pavilion-windows-west"].push(node_pavilion_windows_west_49);

  const endpoint_pavilion_roof_west_50 = makeAttachmentEndpoint(null);
  const node_pavilion_roof_west_50 = new THREE.Group();
  node_pavilion_roof_west_50.name = "Pavilion roof (west)__pivot";
  node_pavilion_roof_west_50.scale.set(1, 1, 1);
  if (endpoint_pavilion_roof_west_50) {
    node_pavilion_roof_west_50.position.copy(endpoint_pavilion_roof_west_50.start);
    node_pavilion_roof_west_50.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pavilion_roof_west_50.position.set(0.0, 7.9, 0.0);
    node_pavilion_roof_west_50.rotation.set(0.0, 0.0, 0.0);
  }
  node_pavilion_roof_west_50.userData.sculptComponent = {"id": "pavilion-roof-west", "name": "Pavilion roof (west)", "level": "macro", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof of the pavilion; apex ridge cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "pavilion-west", "attachment": null, "dimensions": {"width": 14.2, "height": 3.6, "depth": 14.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 7.9, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-roof-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Pale ridge capping along hips and apex."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_roof_west_50.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-roof-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}};
  (nodes["pavilion-west"] ?? root).add(node_pavilion_roof_west_50);
  nodes["pavilion-roof-west"] = node_pavilion_roof_west_50;
  const mesh_pavilion_roof_west_50Geometry = endpoint_pavilion_roof_west_50
    ? new THREE.CylinderGeometry(endpoint_pavilion_roof_west_50.endRadius, endpoint_pavilion_roof_west_50.baseRadius, endpoint_pavilion_roof_west_50.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pavilion_roof_west_50) {
    mesh_pavilion_roof_west_50Geometry.scale(14.2, 3.6, 14.2);
  }
  const mesh_pavilion_roof_west_50 = new THREE.Mesh(
    mesh_pavilion_roof_west_50Geometry,
    materialMap["roof-tile"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pavilion_roof_west_50.name = "Pavilion roof (west)";
  if (endpoint_pavilion_roof_west_50) {
    mesh_pavilion_roof_west_50.position.copy(endpoint_pavilion_roof_west_50.midpoint);
    mesh_pavilion_roof_west_50.quaternion.copy(endpoint_pavilion_roof_west_50.quaternion);
  }
  mesh_pavilion_roof_west_50.castShadow = options.castShadow ?? true;
  mesh_pavilion_roof_west_50.receiveShadow = options.receiveShadow ?? true;
  mesh_pavilion_roof_west_50.userData.sculptComponent = {"id": "pavilion-roof-west", "name": "Pavilion roof (west)", "level": "macro", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof of the pavilion; apex ridge cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "pavilion-west", "attachment": null, "dimensions": {"width": 14.2, "height": 3.6, "depth": 14.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 7.9, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-roof-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Pale ridge capping along hips and apex."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_roof_west_50.add(mesh_pavilion_roof_west_50);
  meshes["pavilion-roof-west"] = mesh_pavilion_roof_west_50;
  colliders["pavilion-roof-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pavilion-roof-west"] ??= [];
  destructionGroups["pavilion-roof-west"].push(node_pavilion_roof_west_50);

  const endpoint_rear_block_west_51 = makeAttachmentEndpoint(null);
  const node_rear_block_west_51 = new THREE.Group();
  node_rear_block_west_51.name = "Rear block (west)__pivot";
  node_rear_block_west_51.scale.set(1, 1, 1);
  if (endpoint_rear_block_west_51) {
    node_rear_block_west_51.position.copy(endpoint_rear_block_west_51.start);
    node_rear_block_west_51.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_rear_block_west_51.position.set(-46.0, 12.1, -45.0);
    node_rear_block_west_51.rotation.set(0.0, 0.0, 0.0);
  }
  node_rear_block_west_51.userData.sculptComponent = {"id": "rear-block-west", "name": "Rear block (west)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Rear hall closing the courtyard; inferred from aerials, front rhythm assumed continued.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 19.4, "depth": 22, "units": "relative", "confidence": 0.6}, "transform": {"position": [-46.0, 12.1, -45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_block_west_51.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_rear_block_west_51);
  nodes["rear-block-west"] = node_rear_block_west_51;
  const mesh_rear_block_west_51Geometry = endpoint_rear_block_west_51
    ? new THREE.CylinderGeometry(endpoint_rear_block_west_51.endRadius, endpoint_rear_block_west_51.baseRadius, endpoint_rear_block_west_51.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_rear_block_west_51) {
    mesh_rear_block_west_51Geometry.scale(17.0, 19.4, 22.0);
  }
  const mesh_rear_block_west_51 = new THREE.Mesh(
    mesh_rear_block_west_51Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_rear_block_west_51.name = "Rear block (west)";
  if (endpoint_rear_block_west_51) {
    mesh_rear_block_west_51.position.copy(endpoint_rear_block_west_51.midpoint);
    mesh_rear_block_west_51.quaternion.copy(endpoint_rear_block_west_51.quaternion);
  }
  mesh_rear_block_west_51.castShadow = options.castShadow ?? true;
  mesh_rear_block_west_51.receiveShadow = options.receiveShadow ?? true;
  mesh_rear_block_west_51.userData.sculptComponent = {"id": "rear-block-west", "name": "Rear block (west)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Rear hall closing the courtyard; inferred from aerials, front rhythm assumed continued.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 19.4, "depth": 22, "units": "relative", "confidence": 0.6}, "transform": {"position": [-46.0, 12.1, -45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_block_west_51.add(mesh_rear_block_west_51);
  meshes["rear-block-west"] = mesh_rear_block_west_51;
  colliders["rear-block-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["rear-block-west"] ??= [];
  destructionGroups["rear-block-west"].push(node_rear_block_west_51);

  const endpoint_rear_windows_west_52 = makeAttachmentEndpoint(null);
  const node_rear_windows_west_52 = new THREE.Group();
  node_rear_windows_west_52.name = "Rear block windows (west)__pivot";
  node_rear_windows_west_52.scale.set(1, 1, 1);
  if (endpoint_rear_windows_west_52) {
    node_rear_windows_west_52.position.copy(endpoint_rear_windows_west_52.start);
    node_rear_windows_west_52.rotation.set(0.0, 1.570796, 0.0);
  } else {
    node_rear_windows_west_52.position.set(8.5, 1.9, 0.0);
    node_rear_windows_west_52.rotation.set(0.0, 1.570796, 0.0);
  }
  node_rear_windows_west_52.userData.sculptComponent = {"id": "rear-windows-west", "name": "Rear block windows (west)", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.5, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Courtyard-facing windows; grid looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "rear-block-west", "attachment": null, "dimensions": {"width": 0.35, "height": 2.2, "depth": 1.6, "units": "relative", "confidence": 0.5}, "transform": {"position": [8.5, 1.9, 0], "rotation": [0, 1.570796, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.5}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_rear_windows_west_52.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.5}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["rear-block-west"] ?? root).add(node_rear_windows_west_52);
  nodes["rear-windows-west"] = node_rear_windows_west_52;
  const mesh_rear_windows_west_52Geometry = endpoint_rear_windows_west_52
    ? new THREE.CylinderGeometry(endpoint_rear_windows_west_52.endRadius, endpoint_rear_windows_west_52.baseRadius, endpoint_rear_windows_west_52.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_rear_windows_west_52) {
    mesh_rear_windows_west_52Geometry.scale(0.35, 2.2, 1.6);
  }
  const mesh_rear_windows_west_52 = new THREE.Mesh(
    mesh_rear_windows_west_52Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_rear_windows_west_52.name = "Rear block windows (west)";
  if (endpoint_rear_windows_west_52) {
    mesh_rear_windows_west_52.position.copy(endpoint_rear_windows_west_52.midpoint);
    mesh_rear_windows_west_52.quaternion.copy(endpoint_rear_windows_west_52.quaternion);
  }
  mesh_rear_windows_west_52.castShadow = options.castShadow ?? true;
  mesh_rear_windows_west_52.receiveShadow = options.receiveShadow ?? true;
  mesh_rear_windows_west_52.userData.sculptComponent = {"id": "rear-windows-west", "name": "Rear block windows (west)", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.5, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Courtyard-facing windows; grid looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "rear-block-west", "attachment": null, "dimensions": {"width": 0.35, "height": 2.2, "depth": 1.6, "units": "relative", "confidence": 0.5}, "transform": {"position": [8.5, 1.9, 0], "rotation": [0, 1.570796, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.5}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-windows-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_rear_windows_west_52.add(mesh_rear_windows_west_52);
  meshes["rear-windows-west"] = mesh_rear_windows_west_52;
  colliders["rear-windows-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["rear-windows-west"] ??= [];
  destructionGroups["rear-windows-west"].push(node_rear_windows_west_52);

  const endpoint_rear_roof_west_53 = makeAttachmentEndpoint(null);
  const node_rear_roof_west_53 = new THREE.Group();
  node_rear_roof_west_53.name = "Rear block roof (west)__pivot";
  node_rear_roof_west_53.scale.set(1, 1, 1);
  if (endpoint_rear_roof_west_53) {
    node_rear_roof_west_53.position.copy(endpoint_rear_roof_west_53.start);
    node_rear_roof_west_53.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_rear_roof_west_53.position.set(0.0, 12.3, 0.0);
    node_rear_roof_west_53.rotation.set(0.0, 0.0, 0.0);
  }
  node_rear_roof_west_53.userData.sculptComponent = {"id": "rear-roof-west", "name": "Rear block roof (west)", "level": "macro", "role": "structure", "importance": 0.55, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof matching the front halls, inferred.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "rear-block-west", "attachment": null, "dimensions": {"width": 18, "height": 4.4, "depth": 23, "units": "relative", "confidence": 0.6}, "transform": {"position": [0.0, 12.3, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-roof-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Pale ridge capping along hips and ridge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_roof_west_53.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-roof-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}};
  (nodes["rear-block-west"] ?? root).add(node_rear_roof_west_53);
  nodes["rear-roof-west"] = node_rear_roof_west_53;
  const mesh_rear_roof_west_53Geometry = endpoint_rear_roof_west_53
    ? new THREE.CylinderGeometry(endpoint_rear_roof_west_53.endRadius, endpoint_rear_roof_west_53.baseRadius, endpoint_rear_roof_west_53.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_rear_roof_west_53) {
    mesh_rear_roof_west_53Geometry.scale(18.0, 4.4, 23.0);
  }
  const mesh_rear_roof_west_53 = new THREE.Mesh(
    mesh_rear_roof_west_53Geometry,
    materialMap["roof-tile"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_rear_roof_west_53.name = "Rear block roof (west)";
  if (endpoint_rear_roof_west_53) {
    mesh_rear_roof_west_53.position.copy(endpoint_rear_roof_west_53.midpoint);
    mesh_rear_roof_west_53.quaternion.copy(endpoint_rear_roof_west_53.quaternion);
  }
  mesh_rear_roof_west_53.castShadow = options.castShadow ?? true;
  mesh_rear_roof_west_53.receiveShadow = options.receiveShadow ?? true;
  mesh_rear_roof_west_53.userData.sculptComponent = {"id": "rear-roof-west", "name": "Rear block roof (west)", "level": "macro", "role": "structure", "importance": 0.55, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof matching the front halls, inferred.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "rear-block-west", "attachment": null, "dimensions": {"width": 18, "height": 4.4, "depth": 23, "units": "relative", "confidence": 0.6}, "transform": {"position": [0.0, 12.3, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-roof-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Pale ridge capping along hips and ridge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_roof_west_53.add(mesh_rear_roof_west_53);
  meshes["rear-roof-west"] = mesh_rear_roof_west_53;
  colliders["rear-roof-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["rear-roof-west"] ??= [];
  destructionGroups["rear-roof-west"].push(node_rear_roof_west_53);

  const endpoint_courtyard_conifers_west_54 = makeAttachmentEndpoint(null);
  const node_courtyard_conifers_west_54 = new THREE.Group();
  node_courtyard_conifers_west_54.name = "Courtyard conifers (west)__pivot";
  node_courtyard_conifers_west_54.scale.set(1, 1, 1);
  if (endpoint_courtyard_conifers_west_54) {
    node_courtyard_conifers_west_54.position.copy(endpoint_courtyard_conifers_west_54.start);
    node_courtyard_conifers_west_54.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_courtyard_conifers_west_54.position.set(-33.0, 6.0, -25.0);
    node_courtyard_conifers_west_54.rotation.set(0.0, 0.0, 0.0);
  }
  node_courtyard_conifers_west_54.userData.sculptComponent = {"id": "courtyard-conifers-west", "name": "Courtyard conifers (west)", "level": "micro", "role": "structure", "importance": 0.35, "confidence": 0.6, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Conical trees: revolved cone profile (lathe).", "geometryDescriptor": {"topologyIntent": "Row of dark conifers along the courtyard wall; looped in code with slight scale variance.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 10}}, "parent": "root", "attachment": null, "dimensions": {"width": 2.4, "height": 12, "depth": 2.4, "units": "relative", "confidence": 0.6}, "transform": {"position": [-33, 6.0, -25], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-conifers-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_courtyard_conifers_west_54.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-conifers-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}};
  (nodes["root"] ?? root).add(node_courtyard_conifers_west_54);
  nodes["courtyard-conifers-west"] = node_courtyard_conifers_west_54;
  const mesh_courtyard_conifers_west_54Geometry = endpoint_courtyard_conifers_west_54
    ? new THREE.CylinderGeometry(endpoint_courtyard_conifers_west_54.endRadius, endpoint_courtyard_conifers_west_54.baseRadius, endpoint_courtyard_conifers_west_54.length, 32, 12)
    : buildLatheGeometry({"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 10});
  if (!endpoint_courtyard_conifers_west_54) {
    mesh_courtyard_conifers_west_54Geometry.scale(2.4, 12.0, 2.4);
  }
  const mesh_courtyard_conifers_west_54 = new THREE.Mesh(
    mesh_courtyard_conifers_west_54Geometry,
    materialMap["foliage-green"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_courtyard_conifers_west_54.name = "Courtyard conifers (west)";
  if (endpoint_courtyard_conifers_west_54) {
    mesh_courtyard_conifers_west_54.position.copy(endpoint_courtyard_conifers_west_54.midpoint);
    mesh_courtyard_conifers_west_54.quaternion.copy(endpoint_courtyard_conifers_west_54.quaternion);
  }
  mesh_courtyard_conifers_west_54.castShadow = options.castShadow ?? true;
  mesh_courtyard_conifers_west_54.receiveShadow = options.receiveShadow ?? true;
  mesh_courtyard_conifers_west_54.userData.sculptComponent = {"id": "courtyard-conifers-west", "name": "Courtyard conifers (west)", "level": "micro", "role": "structure", "importance": 0.35, "confidence": 0.6, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Conical trees: revolved cone profile (lathe).", "geometryDescriptor": {"topologyIntent": "Row of dark conifers along the courtyard wall; looped in code with slight scale variance.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 10}}, "parent": "root", "attachment": null, "dimensions": {"width": 2.4, "height": 12, "depth": 2.4, "units": "relative", "confidence": 0.6}, "transform": {"position": [-33, 6.0, -25], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-conifers-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_courtyard_conifers_west_54.add(mesh_courtyard_conifers_west_54);
  meshes["courtyard-conifers-west"] = mesh_courtyard_conifers_west_54;
  colliders["courtyard-conifers-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["courtyard-conifers-west"] ??= [];
  destructionGroups["courtyard-conifers-west"].push(node_courtyard_conifers_west_54);

  const endpoint_east_hall_55 = makeAttachmentEndpoint(null);
  const node_east_hall_55 = new THREE.Group();
  node_east_hall_55.name = "East hall__pivot";
  node_east_hall_55.scale.set(1, 1, 1);
  if (endpoint_east_hall_55) {
    node_east_hall_55.position.copy(endpoint_east_hall_55.start);
    node_east_hall_55.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_east_hall_55.position.set(40.0, 12.1, -10.0);
    node_east_hall_55.rotation.set(0.0, 0.0, 0.0);
  }
  node_east_hall_55.userData.sculptComponent = {"id": "east-hall", "name": "East hall", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Five-storey side hall with regular window grid, string courses and a hip roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [40, 12.1, -10], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_east_hall_55.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_east_hall_55);
  nodes["east-hall"] = node_east_hall_55;
  const mesh_east_hall_55Geometry = endpoint_east_hall_55
    ? new THREE.CylinderGeometry(endpoint_east_hall_55.endRadius, endpoint_east_hall_55.baseRadius, endpoint_east_hall_55.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_east_hall_55) {
    mesh_east_hall_55Geometry.scale(38.0, 19.4, 20.0);
  }
  const mesh_east_hall_55 = new THREE.Mesh(
    mesh_east_hall_55Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_east_hall_55.name = "East hall";
  if (endpoint_east_hall_55) {
    mesh_east_hall_55.position.copy(endpoint_east_hall_55.midpoint);
    mesh_east_hall_55.quaternion.copy(endpoint_east_hall_55.quaternion);
  }
  mesh_east_hall_55.castShadow = options.castShadow ?? true;
  mesh_east_hall_55.receiveShadow = options.receiveShadow ?? true;
  mesh_east_hall_55.userData.sculptComponent = {"id": "east-hall", "name": "East hall", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Five-storey side hall with regular window grid, string courses and a hip roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [40, 12.1, -10], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_east_hall_55.add(mesh_east_hall_55);
  meshes["east-hall"] = mesh_east_hall_55;
  colliders["east-hall"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["east-hall"] ??= [];
  destructionGroups["east-hall"].push(node_east_hall_55);

  const endpoint_east_body_56 = makeAttachmentEndpoint(null);
  const node_east_body_56 = new THREE.Group();
  node_east_body_56.name = "East hall body__pivot";
  node_east_body_56.scale.set(1, 1, 1);
  if (endpoint_east_body_56) {
    node_east_body_56.position.copy(endpoint_east_body_56.start);
    node_east_body_56.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_east_body_56.position.set(0.0, 0.0, 0.0);
    node_east_body_56.rotation.set(0.0, 0.0, 0.0);
  }
  node_east_body_56.userData.sculptComponent = {"id": "east-body", "name": "East hall body", "level": "meso", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Main brick mass; pilasters and string courses are looped in code from these features.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "east-hall", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-body", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "pilaster-strips", "description": "Vertical brick pilaster strips between window bays, slightly proud of the wall."}, {"id": "string-courses", "description": "Thin cream band at each floor line, continuous past the pilasters."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c0.png", "zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_east_body_56.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-body", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["east-hall"] ?? root).add(node_east_body_56);
  nodes["east-body"] = node_east_body_56;
  const mesh_east_body_56Geometry = endpoint_east_body_56
    ? new THREE.CylinderGeometry(endpoint_east_body_56.endRadius, endpoint_east_body_56.baseRadius, endpoint_east_body_56.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_east_body_56) {
    mesh_east_body_56Geometry.scale(38.0, 19.4, 20.0);
  }
  const mesh_east_body_56 = new THREE.Mesh(
    mesh_east_body_56Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_east_body_56.name = "East hall body";
  if (endpoint_east_body_56) {
    mesh_east_body_56.position.copy(endpoint_east_body_56.midpoint);
    mesh_east_body_56.quaternion.copy(endpoint_east_body_56.quaternion);
  }
  mesh_east_body_56.castShadow = options.castShadow ?? true;
  mesh_east_body_56.receiveShadow = options.receiveShadow ?? true;
  mesh_east_body_56.userData.sculptComponent = {"id": "east-body", "name": "East hall body", "level": "meso", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Main brick mass; pilasters and string courses are looped in code from these features.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "east-hall", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-body", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "pilaster-strips", "description": "Vertical brick pilaster strips between window bays, slightly proud of the wall."}, {"id": "string-courses", "description": "Thin cream band at each floor line, continuous past the pilasters."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c0.png", "zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_east_body_56.add(mesh_east_body_56);
  meshes["east-body"] = mesh_east_body_56;
  colliders["east-body"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["east-body"] ??= [];
  destructionGroups["east-body"].push(node_east_body_56);

  const endpoint_wing_windows_east_57 = makeAttachmentEndpoint(null);
  const node_wing_windows_east_57 = new THREE.Group();
  node_wing_windows_east_57.name = "East hall windows__pivot";
  node_wing_windows_east_57.scale.set(1, 1, 1);
  if (endpoint_wing_windows_east_57) {
    node_wing_windows_east_57.position.copy(endpoint_wing_windows_east_57.start);
    node_wing_windows_east_57.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_wing_windows_east_57.position.set(17.0, 4.0, 10.2);
    node_wing_windows_east_57.rotation.set(0.0, 0.0, 0.0);
  }
  node_wing_windows_east_57.userData.sculptComponent = {"id": "wing-windows-east", "name": "East hall windows", "level": "micro", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored window; the factory loops the full grid (bays x floors) with frames and sills.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "east-hall", "attachment": null, "dimensions": {"width": 1.7, "height": 2.3, "depth": 0.35, "units": "relative", "confidence": 0.8}, "transform": {"position": [17.0, 4.0, 10.2], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "wing-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "recessed-reveal", "description": "Cream frame surround, glass set back with a projecting sill ledge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_wing_windows_east_57.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "wing-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["east-hall"] ?? root).add(node_wing_windows_east_57);
  nodes["wing-windows-east"] = node_wing_windows_east_57;
  const mesh_wing_windows_east_57Geometry = endpoint_wing_windows_east_57
    ? new THREE.CylinderGeometry(endpoint_wing_windows_east_57.endRadius, endpoint_wing_windows_east_57.baseRadius, endpoint_wing_windows_east_57.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_wing_windows_east_57) {
    mesh_wing_windows_east_57Geometry.scale(1.7, 2.3, 0.35);
  }
  const mesh_wing_windows_east_57 = new THREE.Mesh(
    mesh_wing_windows_east_57Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_wing_windows_east_57.name = "East hall windows";
  if (endpoint_wing_windows_east_57) {
    mesh_wing_windows_east_57.position.copy(endpoint_wing_windows_east_57.midpoint);
    mesh_wing_windows_east_57.quaternion.copy(endpoint_wing_windows_east_57.quaternion);
  }
  mesh_wing_windows_east_57.castShadow = options.castShadow ?? true;
  mesh_wing_windows_east_57.receiveShadow = options.receiveShadow ?? true;
  mesh_wing_windows_east_57.userData.sculptComponent = {"id": "wing-windows-east", "name": "East hall windows", "level": "micro", "role": "structure", "importance": 0.9, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored window; the factory loops the full grid (bays x floors) with frames and sills.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "east-hall", "attachment": null, "dimensions": {"width": 1.7, "height": 2.3, "depth": 0.35, "units": "relative", "confidence": 0.8}, "transform": {"position": [17.0, 4.0, 10.2], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "wing-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "recessed-reveal", "description": "Cream frame surround, glass set back with a projecting sill ledge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_wing_windows_east_57.add(mesh_wing_windows_east_57);
  meshes["wing-windows-east"] = mesh_wing_windows_east_57;
  colliders["wing-windows-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["wing-windows-east"] ??= [];
  destructionGroups["wing-windows-east"].push(node_wing_windows_east_57);

  const endpoint_east_cornice_58 = makeAttachmentEndpoint(null);
  const node_east_cornice_58 = new THREE.Group();
  node_east_cornice_58.name = "East hall eave cornice__pivot";
  node_east_cornice_58.scale.set(1, 1, 1);
  if (endpoint_east_cornice_58) {
    node_east_cornice_58.position.copy(endpoint_east_cornice_58.start);
    node_east_cornice_58.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_east_cornice_58.position.set(0.0, 10.15, 0.0);
    node_east_cornice_58.rotation.set(0.0, 0.0, 0.0);
  }
  node_east_cornice_58.userData.sculptComponent = {"id": "east-cornice", "name": "East hall eave cornice", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Eave cornice band running the full hall front and sides.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "east-hall", "attachment": null, "dimensions": {"width": 38.6, "height": 0.9, "depth": 20.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 10.15, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-cornice", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "eave-cornice", "description": "Pale projecting cornice with dentil shadow line under the eaves."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_east_cornice_58.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-cornice", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["east-hall"] ?? root).add(node_east_cornice_58);
  nodes["east-cornice"] = node_east_cornice_58;
  const mesh_east_cornice_58Geometry = endpoint_east_cornice_58
    ? new THREE.CylinderGeometry(endpoint_east_cornice_58.endRadius, endpoint_east_cornice_58.baseRadius, endpoint_east_cornice_58.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_east_cornice_58) {
    mesh_east_cornice_58Geometry.scale(38.6, 0.9, 20.6);
  }
  const mesh_east_cornice_58 = new THREE.Mesh(
    mesh_east_cornice_58Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_east_cornice_58.name = "East hall eave cornice";
  if (endpoint_east_cornice_58) {
    mesh_east_cornice_58.position.copy(endpoint_east_cornice_58.midpoint);
    mesh_east_cornice_58.quaternion.copy(endpoint_east_cornice_58.quaternion);
  }
  mesh_east_cornice_58.castShadow = options.castShadow ?? true;
  mesh_east_cornice_58.receiveShadow = options.receiveShadow ?? true;
  mesh_east_cornice_58.userData.sculptComponent = {"id": "east-cornice", "name": "East hall eave cornice", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Eave cornice band running the full hall front and sides.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "east-hall", "attachment": null, "dimensions": {"width": 38.6, "height": 0.9, "depth": 20.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 10.15, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-cornice", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "eave-cornice", "description": "Pale projecting cornice with dentil shadow line under the eaves."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_east_cornice_58.add(mesh_east_cornice_58);
  meshes["east-cornice"] = mesh_east_cornice_58;
  colliders["east-cornice"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["east-cornice"] ??= [];
  destructionGroups["east-cornice"].push(node_east_cornice_58);

  const endpoint_east_roof_59 = makeAttachmentEndpoint(null);
  const node_east_roof_59 = new THREE.Group();
  node_east_roof_59.name = "East hall roof__pivot";
  node_east_roof_59.scale.set(1, 1, 1);
  if (endpoint_east_roof_59) {
    node_east_roof_59.position.copy(endpoint_east_roof_59.start);
    node_east_roof_59.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_east_roof_59.position.set(0.0, 12.3, 0.0);
    node_east_roof_59.rotation.set(0.0, 0.0, 0.0);
  }
  node_east_roof_59.userData.sculptComponent = {"id": "east-roof", "name": "East hall roof", "level": "macro", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof: four slopes with ridge and hip caps; hip geometry authored in a factory helper.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "east-hall", "attachment": null, "dimensions": {"width": 39.4, "height": 4.4, "depth": 21.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 12.3, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-roof", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Lighter tan capping runs along every hip and ridge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_east_roof_59.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-roof", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}};
  (nodes["east-hall"] ?? root).add(node_east_roof_59);
  nodes["east-roof"] = node_east_roof_59;
  const mesh_east_roof_59Geometry = endpoint_east_roof_59
    ? new THREE.CylinderGeometry(endpoint_east_roof_59.endRadius, endpoint_east_roof_59.baseRadius, endpoint_east_roof_59.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_east_roof_59) {
    mesh_east_roof_59Geometry.scale(39.4, 4.4, 21.2);
  }
  const mesh_east_roof_59 = new THREE.Mesh(
    mesh_east_roof_59Geometry,
    materialMap["roof-tile"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_east_roof_59.name = "East hall roof";
  if (endpoint_east_roof_59) {
    mesh_east_roof_59.position.copy(endpoint_east_roof_59.midpoint);
    mesh_east_roof_59.quaternion.copy(endpoint_east_roof_59.quaternion);
  }
  mesh_east_roof_59.castShadow = options.castShadow ?? true;
  mesh_east_roof_59.receiveShadow = options.receiveShadow ?? true;
  mesh_east_roof_59.userData.sculptComponent = {"id": "east-roof", "name": "East hall roof", "level": "macro", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof: four slopes with ridge and hip caps; hip geometry authored in a factory helper.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "east-hall", "attachment": null, "dimensions": {"width": 39.4, "height": 4.4, "depth": 21.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 12.3, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-roof", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Lighter tan capping runs along every hip and ridge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_east_roof_59.add(mesh_east_roof_59);
  meshes["east-roof"] = mesh_east_roof_59;
  colliders["east-roof"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["east-roof"] ??= [];
  destructionGroups["east-roof"].push(node_east_roof_59);

  const endpoint_tower_east_60 = makeAttachmentEndpoint(null);
  const node_tower_east_60 = new THREE.Group();
  node_tower_east_60.name = "Tower (east)__pivot";
  node_tower_east_60.scale.set(1, 1, 1);
  if (endpoint_tower_east_60) {
    node_tower_east_60.position.copy(endpoint_tower_east_60.start);
    node_tower_east_60.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_east_60.position.set(60.2, 17.0, -0.5);
    node_tower_east_60.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_east_60.userData.sculptComponent = {"id": "tower-east", "name": "Tower (east)", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Square terminal tower: brick shaft, cream front panel with paired slots, belfry stage with arches, balustrade, pyramid cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 7.0, "height": 29.2, "depth": 7.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [60.2, 17.0, -0.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png", "zones-ref04/zone-r0c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_east_60.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_tower_east_60);
  nodes["tower-east"] = node_tower_east_60;
  const mesh_tower_east_60Geometry = endpoint_tower_east_60
    ? new THREE.CylinderGeometry(endpoint_tower_east_60.endRadius, endpoint_tower_east_60.baseRadius, endpoint_tower_east_60.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_east_60) {
    mesh_tower_east_60Geometry.scale(7.0, 29.2, 7.2);
  }
  const mesh_tower_east_60 = new THREE.Mesh(
    mesh_tower_east_60Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_east_60.name = "Tower (east)";
  if (endpoint_tower_east_60) {
    mesh_tower_east_60.position.copy(endpoint_tower_east_60.midpoint);
    mesh_tower_east_60.quaternion.copy(endpoint_tower_east_60.quaternion);
  }
  mesh_tower_east_60.castShadow = options.castShadow ?? true;
  mesh_tower_east_60.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_east_60.userData.sculptComponent = {"id": "tower-east", "name": "Tower (east)", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Square terminal tower: brick shaft, cream front panel with paired slots, belfry stage with arches, balustrade, pyramid cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 7.0, "height": 29.2, "depth": 7.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [60.2, 17.0, -0.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png", "zones-ref04/zone-r0c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_east_60.add(mesh_tower_east_60);
  meshes["tower-east"] = mesh_tower_east_60;
  colliders["tower-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-east"] ??= [];
  destructionGroups["tower-east"].push(node_tower_east_60);

  const endpoint_tower_shaft_east_61 = makeAttachmentEndpoint(null);
  const node_tower_shaft_east_61 = new THREE.Group();
  node_tower_shaft_east_61.name = "Tower shaft (east)__pivot";
  node_tower_shaft_east_61.scale.set(1, 1, 1);
  if (endpoint_tower_shaft_east_61) {
    node_tower_shaft_east_61.position.copy(endpoint_tower_shaft_east_61.start);
    node_tower_shaft_east_61.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_shaft_east_61.position.set(0.0, -1.6, 0.0);
    node_tower_shaft_east_61.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_shaft_east_61.userData.sculptComponent = {"id": "tower-shaft-east", "name": "Tower shaft (east)", "level": "meso", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Brick shaft; corner quoins looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 6.8, "height": 26.0, "depth": 7.0, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-shaft-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "corner-quoins", "description": "Pale vertical quoin strips on the tower corners."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_shaft_east_61.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-shaft-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["tower-east"] ?? root).add(node_tower_shaft_east_61);
  nodes["tower-shaft-east"] = node_tower_shaft_east_61;
  const mesh_tower_shaft_east_61Geometry = endpoint_tower_shaft_east_61
    ? new THREE.CylinderGeometry(endpoint_tower_shaft_east_61.endRadius, endpoint_tower_shaft_east_61.baseRadius, endpoint_tower_shaft_east_61.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_shaft_east_61) {
    mesh_tower_shaft_east_61Geometry.scale(6.8, 26.0, 7.0);
  }
  const mesh_tower_shaft_east_61 = new THREE.Mesh(
    mesh_tower_shaft_east_61Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_shaft_east_61.name = "Tower shaft (east)";
  if (endpoint_tower_shaft_east_61) {
    mesh_tower_shaft_east_61.position.copy(endpoint_tower_shaft_east_61.midpoint);
    mesh_tower_shaft_east_61.quaternion.copy(endpoint_tower_shaft_east_61.quaternion);
  }
  mesh_tower_shaft_east_61.castShadow = options.castShadow ?? true;
  mesh_tower_shaft_east_61.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_shaft_east_61.userData.sculptComponent = {"id": "tower-shaft-east", "name": "Tower shaft (east)", "level": "meso", "role": "structure", "importance": 0.85, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Brick shaft; corner quoins looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 6.8, "height": 26.0, "depth": 7.0, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-shaft-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "corner-quoins", "description": "Pale vertical quoin strips on the tower corners."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_shaft_east_61.add(mesh_tower_shaft_east_61);
  meshes["tower-shaft-east"] = mesh_tower_shaft_east_61;
  colliders["tower-shaft-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-shaft-east"] ??= [];
  destructionGroups["tower-shaft-east"].push(node_tower_shaft_east_61);

  const endpoint_tower_frontpanel_east_62 = makeAttachmentEndpoint(null);
  const node_tower_frontpanel_east_62 = new THREE.Group();
  node_tower_frontpanel_east_62.name = "Tower front panel (east)__pivot";
  node_tower_frontpanel_east_62.scale.set(1, 1, 1);
  if (endpoint_tower_frontpanel_east_62) {
    node_tower_frontpanel_east_62.position.copy(endpoint_tower_frontpanel_east_62.start);
    node_tower_frontpanel_east_62.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_frontpanel_east_62.position.set(0.0, -1.6, 3.22);
    node_tower_frontpanel_east_62.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_frontpanel_east_62.userData.sculptComponent = {"id": "tower-frontpanel-east", "name": "Tower front panel (east)", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream vertical panel carrying the paired slot windows; slots looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 4.4, "height": 24.0, "depth": 0.5, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 3.22], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-frontpanel-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "paired-slots", "description": "Stacked narrow paired windows, one pair per floor, cream frames."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_frontpanel_east_62.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-frontpanel-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["tower-east"] ?? root).add(node_tower_frontpanel_east_62);
  nodes["tower-frontpanel-east"] = node_tower_frontpanel_east_62;
  const mesh_tower_frontpanel_east_62Geometry = endpoint_tower_frontpanel_east_62
    ? new THREE.CylinderGeometry(endpoint_tower_frontpanel_east_62.endRadius, endpoint_tower_frontpanel_east_62.baseRadius, endpoint_tower_frontpanel_east_62.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_frontpanel_east_62) {
    mesh_tower_frontpanel_east_62Geometry.scale(4.4, 24.0, 0.5);
  }
  const mesh_tower_frontpanel_east_62 = new THREE.Mesh(
    mesh_tower_frontpanel_east_62Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_frontpanel_east_62.name = "Tower front panel (east)";
  if (endpoint_tower_frontpanel_east_62) {
    mesh_tower_frontpanel_east_62.position.copy(endpoint_tower_frontpanel_east_62.midpoint);
    mesh_tower_frontpanel_east_62.quaternion.copy(endpoint_tower_frontpanel_east_62.quaternion);
  }
  mesh_tower_frontpanel_east_62.castShadow = options.castShadow ?? true;
  mesh_tower_frontpanel_east_62.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_frontpanel_east_62.userData.sculptComponent = {"id": "tower-frontpanel-east", "name": "Tower front panel (east)", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream vertical panel carrying the paired slot windows; slots looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 4.4, "height": 24.0, "depth": 0.5, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 3.22], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-frontpanel-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "paired-slots", "description": "Stacked narrow paired windows, one pair per floor, cream frames."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_frontpanel_east_62.add(mesh_tower_frontpanel_east_62);
  meshes["tower-frontpanel-east"] = mesh_tower_frontpanel_east_62;
  colliders["tower-frontpanel-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-frontpanel-east"] ??= [];
  destructionGroups["tower-frontpanel-east"].push(node_tower_frontpanel_east_62);

  const endpoint_tower_windows_east_63 = makeAttachmentEndpoint(null);
  const node_tower_windows_east_63 = new THREE.Group();
  node_tower_windows_east_63.name = "Tower slot windows (east)__pivot";
  node_tower_windows_east_63.scale.set(1, 1, 1);
  if (endpoint_tower_windows_east_63) {
    node_tower_windows_east_63.position.copy(endpoint_tower_windows_east_63.start);
    node_tower_windows_east_63.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_windows_east_63.position.set(0.0, -1.6, 3.45);
    node_tower_windows_east_63.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_windows_east_63.userData.sculptComponent = {"id": "tower-windows-east", "name": "Tower slot windows (east)", "level": "micro", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored slot; looped as stacked pairs in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 0.55, "height": 1.5, "depth": 0.3, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 3.45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_tower_windows_east_63.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["tower-east"] ?? root).add(node_tower_windows_east_63);
  nodes["tower-windows-east"] = node_tower_windows_east_63;
  const mesh_tower_windows_east_63Geometry = endpoint_tower_windows_east_63
    ? new THREE.CylinderGeometry(endpoint_tower_windows_east_63.endRadius, endpoint_tower_windows_east_63.baseRadius, endpoint_tower_windows_east_63.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_windows_east_63) {
    mesh_tower_windows_east_63Geometry.scale(0.55, 1.5, 0.3);
  }
  const mesh_tower_windows_east_63 = new THREE.Mesh(
    mesh_tower_windows_east_63Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_windows_east_63.name = "Tower slot windows (east)";
  if (endpoint_tower_windows_east_63) {
    mesh_tower_windows_east_63.position.copy(endpoint_tower_windows_east_63.midpoint);
    mesh_tower_windows_east_63.quaternion.copy(endpoint_tower_windows_east_63.quaternion);
  }
  mesh_tower_windows_east_63.castShadow = options.castShadow ?? true;
  mesh_tower_windows_east_63.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_windows_east_63.userData.sculptComponent = {"id": "tower-windows-east", "name": "Tower slot windows (east)", "level": "micro", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored slot; looped as stacked pairs in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 0.55, "height": 1.5, "depth": 0.3, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, -1.6, 3.45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_tower_windows_east_63.add(mesh_tower_windows_east_63);
  meshes["tower-windows-east"] = mesh_tower_windows_east_63;
  colliders["tower-windows-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-windows-east"] ??= [];
  destructionGroups["tower-windows-east"].push(node_tower_windows_east_63);

  const endpoint_tower_bands_east_64 = makeAttachmentEndpoint(null);
  const node_tower_bands_east_64 = new THREE.Group();
  node_tower_bands_east_64.name = "Tower bands (east)__pivot";
  node_tower_bands_east_64.scale.set(1, 1, 1);
  if (endpoint_tower_bands_east_64) {
    node_tower_bands_east_64.position.copy(endpoint_tower_bands_east_64.start);
    node_tower_bands_east_64.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_bands_east_64.position.set(0.0, 11.4, 0.0);
    node_tower_bands_east_64.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_bands_east_64.userData.sculptComponent = {"id": "tower-bands-east", "name": "Tower bands (east)", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream band at each tower stage line; three bands looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 7.2, "height": 0.6, "depth": 7.4, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 11.4, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-bands-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_bands_east_64.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-bands-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["tower-east"] ?? root).add(node_tower_bands_east_64);
  nodes["tower-bands-east"] = node_tower_bands_east_64;
  const mesh_tower_bands_east_64Geometry = endpoint_tower_bands_east_64
    ? new THREE.CylinderGeometry(endpoint_tower_bands_east_64.endRadius, endpoint_tower_bands_east_64.baseRadius, endpoint_tower_bands_east_64.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_bands_east_64) {
    mesh_tower_bands_east_64Geometry.scale(7.2, 0.6, 7.4);
  }
  const mesh_tower_bands_east_64 = new THREE.Mesh(
    mesh_tower_bands_east_64Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_bands_east_64.name = "Tower bands (east)";
  if (endpoint_tower_bands_east_64) {
    mesh_tower_bands_east_64.position.copy(endpoint_tower_bands_east_64.midpoint);
    mesh_tower_bands_east_64.quaternion.copy(endpoint_tower_bands_east_64.quaternion);
  }
  mesh_tower_bands_east_64.castShadow = options.castShadow ?? true;
  mesh_tower_bands_east_64.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_bands_east_64.userData.sculptComponent = {"id": "tower-bands-east", "name": "Tower bands (east)", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream band at each tower stage line; three bands looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 7.2, "height": 0.6, "depth": 7.4, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 11.4, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-bands-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_bands_east_64.add(mesh_tower_bands_east_64);
  meshes["tower-bands-east"] = mesh_tower_bands_east_64;
  colliders["tower-bands-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-bands-east"] ??= [];
  destructionGroups["tower-bands-east"].push(node_tower_bands_east_64);

  const endpoint_tower_belfry_east_65 = makeAttachmentEndpoint(null);
  const node_tower_belfry_east_65 = new THREE.Group();
  node_tower_belfry_east_65.name = "Tower belfry (east)__pivot";
  node_tower_belfry_east_65.scale.set(1, 1, 1);
  if (endpoint_tower_belfry_east_65) {
    node_tower_belfry_east_65.position.copy(endpoint_tower_belfry_east_65.start);
    node_tower_belfry_east_65.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_belfry_east_65.position.set(0.0, 14.6, 0.0);
    node_tower_belfry_east_65.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_belfry_east_65.userData.sculptComponent = {"id": "tower-belfry-east", "name": "Tower belfry (east)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Open belfry stage: arch cutouts authored with arch-shaped plates in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 6.4, "height": 5.8, "depth": 6.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 14.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-belfry-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "arch-openings", "description": "Two arched openings with cream surrounds at the belfry stage; dark shadow inside."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_belfry_east_65.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-belfry-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}};
  (nodes["tower-east"] ?? root).add(node_tower_belfry_east_65);
  nodes["tower-belfry-east"] = node_tower_belfry_east_65;
  const mesh_tower_belfry_east_65Geometry = endpoint_tower_belfry_east_65
    ? new THREE.CylinderGeometry(endpoint_tower_belfry_east_65.endRadius, endpoint_tower_belfry_east_65.baseRadius, endpoint_tower_belfry_east_65.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_belfry_east_65) {
    mesh_tower_belfry_east_65Geometry.scale(6.4, 5.8, 6.6);
  }
  const mesh_tower_belfry_east_65 = new THREE.Mesh(
    mesh_tower_belfry_east_65Geometry,
    materialMap["trim-limestone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_belfry_east_65.name = "Tower belfry (east)";
  if (endpoint_tower_belfry_east_65) {
    mesh_tower_belfry_east_65.position.copy(endpoint_tower_belfry_east_65.midpoint);
    mesh_tower_belfry_east_65.quaternion.copy(endpoint_tower_belfry_east_65.quaternion);
  }
  mesh_tower_belfry_east_65.castShadow = options.castShadow ?? true;
  mesh_tower_belfry_east_65.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_belfry_east_65.userData.sculptComponent = {"id": "tower-belfry-east", "name": "Tower belfry (east)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Open belfry stage: arch cutouts authored with arch-shaped plates in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 6.4, "height": 5.8, "depth": 6.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 14.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-belfry-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "trim-limestone"}}, "material": "trim-limestone", "materialLayers": ["trim-limestone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "arch-openings", "description": "Two arched openings with cream surrounds at the belfry stage; dark shadow inside."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(231, 218, 188, 1.0)", "secondaryAlbedo": "rgba(217, 203, 168, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_belfry_east_65.add(mesh_tower_belfry_east_65);
  meshes["tower-belfry-east"] = mesh_tower_belfry_east_65;
  colliders["tower-belfry-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-belfry-east"] ??= [];
  destructionGroups["tower-belfry-east"].push(node_tower_belfry_east_65);

  const endpoint_tower_balustrade_east_66 = makeAttachmentEndpoint(null);
  const node_tower_balustrade_east_66 = new THREE.Group();
  node_tower_balustrade_east_66.name = "Tower balustrade (east)__pivot";
  node_tower_balustrade_east_66.scale.set(1, 1, 1);
  if (endpoint_tower_balustrade_east_66) {
    node_tower_balustrade_east_66.position.copy(endpoint_tower_balustrade_east_66.start);
    node_tower_balustrade_east_66.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_balustrade_east_66.position.set(0.0, 17.75, 0.0);
    node_tower_balustrade_east_66.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_balustrade_east_66.userData.sculptComponent = {"id": "tower-balustrade-east", "name": "Tower balustrade (east)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Fine baluster cadence looped in code under the pyramid roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 6.4, "height": 0.7, "depth": 6.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 17.75, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-balustrade-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "baluster-row", "description": "Row of small repeated baluster posts between rail and cornice at the tower top."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["refs/ref-03-elevation.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_balustrade_east_66.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-balustrade-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}};
  (nodes["tower-east"] ?? root).add(node_tower_balustrade_east_66);
  nodes["tower-balustrade-east"] = node_tower_balustrade_east_66;
  const mesh_tower_balustrade_east_66Geometry = endpoint_tower_balustrade_east_66
    ? new THREE.CylinderGeometry(endpoint_tower_balustrade_east_66.endRadius, endpoint_tower_balustrade_east_66.baseRadius, endpoint_tower_balustrade_east_66.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_balustrade_east_66) {
    mesh_tower_balustrade_east_66Geometry.scale(6.4, 0.7, 6.6);
  }
  const mesh_tower_balustrade_east_66 = new THREE.Mesh(
    mesh_tower_balustrade_east_66Geometry,
    materialMap["terrace-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_balustrade_east_66.name = "Tower balustrade (east)";
  if (endpoint_tower_balustrade_east_66) {
    mesh_tower_balustrade_east_66.position.copy(endpoint_tower_balustrade_east_66.midpoint);
    mesh_tower_balustrade_east_66.quaternion.copy(endpoint_tower_balustrade_east_66.quaternion);
  }
  mesh_tower_balustrade_east_66.castShadow = options.castShadow ?? true;
  mesh_tower_balustrade_east_66.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_balustrade_east_66.userData.sculptComponent = {"id": "tower-balustrade-east", "name": "Tower balustrade (east)", "level": "micro", "role": "structure", "importance": 0.4, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Fine baluster cadence looped in code under the pyramid roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 6.4, "height": 0.7, "depth": 6.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 17.75, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-balustrade-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "terrace-stone"}}, "material": "terrace-stone", "materialLayers": ["terrace-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "baluster-row", "description": "Row of small repeated baluster posts between rail and cornice at the tower top."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["refs/ref-03-elevation.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(185, 179, 164, 1.0)", "secondaryAlbedo": "rgba(170, 164, 149, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_tower_balustrade_east_66.add(mesh_tower_balustrade_east_66);
  meshes["tower-balustrade-east"] = mesh_tower_balustrade_east_66;
  colliders["tower-balustrade-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-balustrade-east"] ??= [];
  destructionGroups["tower-balustrade-east"].push(node_tower_balustrade_east_66);

  const endpoint_tower_roof_east_67 = makeAttachmentEndpoint(null);
  const node_tower_roof_east_67 = new THREE.Group();
  node_tower_roof_east_67.name = "Tower cap (east)__pivot";
  node_tower_roof_east_67.scale.set(1, 1, 1);
  if (endpoint_tower_roof_east_67) {
    node_tower_roof_east_67.position.copy(endpoint_tower_roof_east_67.start);
    node_tower_roof_east_67.rotation.set(0.0, 0.7853981633974483, 0.0);
  } else {
    node_tower_roof_east_67.position.set(0.0, 20.3, 0.0);
    node_tower_roof_east_67.rotation.set(0.0, 0.7853981633974483, 0.0);
  }
  node_tower_roof_east_67.userData.sculptComponent = {"id": "tower-roof-east", "name": "Tower cap (east)", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Four-sided pyramid: a 4-segment lathe with a square base.", "geometryDescriptor": {"topologyIntent": "Shallow pyramid cap; emitted as a 4-segment lathe.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 4}}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 10.47, "height": 4.2, "depth": 10.47, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 20.3, 0.0], "rotation": [0, 0.7853981633974483, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-roof-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_roof_east_67.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-roof-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}};
  (nodes["tower-east"] ?? root).add(node_tower_roof_east_67);
  nodes["tower-roof-east"] = node_tower_roof_east_67;
  const mesh_tower_roof_east_67Geometry = endpoint_tower_roof_east_67
    ? new THREE.CylinderGeometry(endpoint_tower_roof_east_67.endRadius, endpoint_tower_roof_east_67.baseRadius, endpoint_tower_roof_east_67.length, 32, 12)
    : buildLatheGeometry({"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 4});
  if (!endpoint_tower_roof_east_67) {
    mesh_tower_roof_east_67Geometry.scale(10.47, 4.2, 10.47);
  }
  const mesh_tower_roof_east_67 = new THREE.Mesh(
    mesh_tower_roof_east_67Geometry,
    materialMap["roof-tile"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_roof_east_67.name = "Tower cap (east)";
  if (endpoint_tower_roof_east_67) {
    mesh_tower_roof_east_67.position.copy(endpoint_tower_roof_east_67.midpoint);
    mesh_tower_roof_east_67.quaternion.copy(endpoint_tower_roof_east_67.quaternion);
  }
  mesh_tower_roof_east_67.castShadow = options.castShadow ?? true;
  mesh_tower_roof_east_67.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_roof_east_67.userData.sculptComponent = {"id": "tower-roof-east", "name": "Tower cap (east)", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Four-sided pyramid: a 4-segment lathe with a square base.", "geometryDescriptor": {"topologyIntent": "Shallow pyramid cap; emitted as a 4-segment lathe.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 4}}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 10.47, "height": 4.2, "depth": 10.47, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 20.3, 0.0], "rotation": [0, 0.7853981633974483, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-roof-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_roof_east_67.add(mesh_tower_roof_east_67);
  meshes["tower-roof-east"] = mesh_tower_roof_east_67;
  colliders["tower-roof-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-roof-east"] ??= [];
  destructionGroups["tower-roof-east"].push(node_tower_roof_east_67);

  const endpoint_tower_finial_east_68 = makeAttachmentEndpoint(null);
  const node_tower_finial_east_68 = new THREE.Group();
  node_tower_finial_east_68.name = "Tower finial (east)__pivot";
  node_tower_finial_east_68.scale.set(1, 1, 1);
  if (endpoint_tower_finial_east_68) {
    node_tower_finial_east_68.position.copy(endpoint_tower_finial_east_68.start);
    node_tower_finial_east_68.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_finial_east_68.position.set(0.0, 22.6, 0.0);
    node_tower_finial_east_68.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_finial_east_68.userData.sculptComponent = {"id": "tower-finial-east", "name": "Tower finial (east)", "level": "micro", "role": "structure", "importance": 0.35, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Small finial on the tower apex.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 0.6, "height": 1.2, "depth": 0.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 22.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-finial-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-ridge"}}, "material": "roof-ridge", "materialLayers": ["roof-ridge"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(192, 138, 98, 1.0)", "secondaryAlbedo": "rgba(178, 124, 85, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_finial_east_68.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-finial-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-ridge"}};
  (nodes["tower-east"] ?? root).add(node_tower_finial_east_68);
  nodes["tower-finial-east"] = node_tower_finial_east_68;
  const mesh_tower_finial_east_68Geometry = endpoint_tower_finial_east_68
    ? new THREE.CylinderGeometry(endpoint_tower_finial_east_68.endRadius, endpoint_tower_finial_east_68.baseRadius, endpoint_tower_finial_east_68.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_finial_east_68) {
    mesh_tower_finial_east_68Geometry.scale(0.6, 1.2, 0.6);
  }
  const mesh_tower_finial_east_68 = new THREE.Mesh(
    mesh_tower_finial_east_68Geometry,
    materialMap["roof-ridge"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_finial_east_68.name = "Tower finial (east)";
  if (endpoint_tower_finial_east_68) {
    mesh_tower_finial_east_68.position.copy(endpoint_tower_finial_east_68.midpoint);
    mesh_tower_finial_east_68.quaternion.copy(endpoint_tower_finial_east_68.quaternion);
  }
  mesh_tower_finial_east_68.castShadow = options.castShadow ?? true;
  mesh_tower_finial_east_68.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_finial_east_68.userData.sculptComponent = {"id": "tower-finial-east", "name": "Tower finial (east)", "level": "micro", "role": "structure", "importance": 0.35, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Small finial on the tower apex.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tower-east", "attachment": null, "dimensions": {"width": 0.6, "height": 1.2, "depth": 0.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 22.6, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-finial-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-ridge"}}, "material": "roof-ridge", "materialLayers": ["roof-ridge"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(192, 138, 98, 1.0)", "secondaryAlbedo": "rgba(178, 124, 85, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_finial_east_68.add(mesh_tower_finial_east_68);
  meshes["tower-finial-east"] = mesh_tower_finial_east_68;
  colliders["tower-finial-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-finial-east"] ??= [];
  destructionGroups["tower-finial-east"].push(node_tower_finial_east_68);

  const endpoint_pavilion_east_69 = makeAttachmentEndpoint(null);
  const node_pavilion_east_69 = new THREE.Group();
  node_pavilion_east_69.name = "Front pavilion (east)__pivot";
  node_pavilion_east_69.scale.set(1, 1, 1);
  if (endpoint_pavilion_east_69) {
    node_pavilion_east_69.position.copy(endpoint_pavilion_east_69.start);
    node_pavilion_east_69.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pavilion_east_69.position.set(22.0, 8.7, 4.0);
    node_pavilion_east_69.rotation.set(0.0, 0.0, 0.0);
  }
  node_pavilion_east_69.userData.sculptComponent = {"id": "pavilion-east", "name": "Front pavilion (east)", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low two-storey mass with a hip roof flanking the portico in front of the hall junction.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 13, "height": 12.6, "depth": 13, "units": "relative", "confidence": 0.8}, "transform": {"position": [22.0, 8.7, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_east_69.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_pavilion_east_69);
  nodes["pavilion-east"] = node_pavilion_east_69;
  const mesh_pavilion_east_69Geometry = endpoint_pavilion_east_69
    ? new THREE.CylinderGeometry(endpoint_pavilion_east_69.endRadius, endpoint_pavilion_east_69.baseRadius, endpoint_pavilion_east_69.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pavilion_east_69) {
    mesh_pavilion_east_69Geometry.scale(13.0, 12.6, 13.0);
  }
  const mesh_pavilion_east_69 = new THREE.Mesh(
    mesh_pavilion_east_69Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pavilion_east_69.name = "Front pavilion (east)";
  if (endpoint_pavilion_east_69) {
    mesh_pavilion_east_69.position.copy(endpoint_pavilion_east_69.midpoint);
    mesh_pavilion_east_69.quaternion.copy(endpoint_pavilion_east_69.quaternion);
  }
  mesh_pavilion_east_69.castShadow = options.castShadow ?? true;
  mesh_pavilion_east_69.receiveShadow = options.receiveShadow ?? true;
  mesh_pavilion_east_69.userData.sculptComponent = {"id": "pavilion-east", "name": "Front pavilion (east)", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low two-storey mass with a hip roof flanking the portico in front of the hall junction.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 13, "height": 12.6, "depth": 13, "units": "relative", "confidence": 0.8}, "transform": {"position": [22.0, 8.7, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_east_69.add(mesh_pavilion_east_69);
  meshes["pavilion-east"] = mesh_pavilion_east_69;
  colliders["pavilion-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pavilion-east"] ??= [];
  destructionGroups["pavilion-east"].push(node_pavilion_east_69);

  const endpoint_pavilion_windows_east_70 = makeAttachmentEndpoint(null);
  const node_pavilion_windows_east_70 = new THREE.Group();
  node_pavilion_windows_east_70.name = "Pavilion windows (east)__pivot";
  node_pavilion_windows_east_70.scale.set(1, 1, 1);
  if (endpoint_pavilion_windows_east_70) {
    node_pavilion_windows_east_70.position.copy(endpoint_pavilion_windows_east_70.start);
    node_pavilion_windows_east_70.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pavilion_windows_east_70.position.set(0.0, 0.7, 6.4);
    node_pavilion_windows_east_70.rotation.set(0.0, 0.0, 0.0);
  }
  node_pavilion_windows_east_70.userData.sculptComponent = {"id": "pavilion-windows-east", "name": "Pavilion windows (east)", "level": "micro", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored window; a 2-row bay grid is looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "pavilion-east", "attachment": null, "dimensions": {"width": 1.5, "height": 2.0, "depth": 0.35, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 0.7, 6.4], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_pavilion_windows_east_70.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["pavilion-east"] ?? root).add(node_pavilion_windows_east_70);
  nodes["pavilion-windows-east"] = node_pavilion_windows_east_70;
  const mesh_pavilion_windows_east_70Geometry = endpoint_pavilion_windows_east_70
    ? new THREE.CylinderGeometry(endpoint_pavilion_windows_east_70.endRadius, endpoint_pavilion_windows_east_70.baseRadius, endpoint_pavilion_windows_east_70.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pavilion_windows_east_70) {
    mesh_pavilion_windows_east_70Geometry.scale(1.5, 2.0, 0.35);
  }
  const mesh_pavilion_windows_east_70 = new THREE.Mesh(
    mesh_pavilion_windows_east_70Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pavilion_windows_east_70.name = "Pavilion windows (east)";
  if (endpoint_pavilion_windows_east_70) {
    mesh_pavilion_windows_east_70.position.copy(endpoint_pavilion_windows_east_70.midpoint);
    mesh_pavilion_windows_east_70.quaternion.copy(endpoint_pavilion_windows_east_70.quaternion);
  }
  mesh_pavilion_windows_east_70.castShadow = options.castShadow ?? true;
  mesh_pavilion_windows_east_70.receiveShadow = options.receiveShadow ?? true;
  mesh_pavilion_windows_east_70.userData.sculptComponent = {"id": "pavilion-windows-east", "name": "Pavilion windows (east)", "level": "micro", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored window; a 2-row bay grid is looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "pavilion-east", "attachment": null, "dimensions": {"width": 1.5, "height": 2.0, "depth": 0.35, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 0.7, 6.4], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_pavilion_windows_east_70.add(mesh_pavilion_windows_east_70);
  meshes["pavilion-windows-east"] = mesh_pavilion_windows_east_70;
  colliders["pavilion-windows-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pavilion-windows-east"] ??= [];
  destructionGroups["pavilion-windows-east"].push(node_pavilion_windows_east_70);

  const endpoint_pavilion_roof_east_71 = makeAttachmentEndpoint(null);
  const node_pavilion_roof_east_71 = new THREE.Group();
  node_pavilion_roof_east_71.name = "Pavilion roof (east)__pivot";
  node_pavilion_roof_east_71.scale.set(1, 1, 1);
  if (endpoint_pavilion_roof_east_71) {
    node_pavilion_roof_east_71.position.copy(endpoint_pavilion_roof_east_71.start);
    node_pavilion_roof_east_71.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pavilion_roof_east_71.position.set(0.0, 7.9, 0.0);
    node_pavilion_roof_east_71.rotation.set(0.0, 0.0, 0.0);
  }
  node_pavilion_roof_east_71.userData.sculptComponent = {"id": "pavilion-roof-east", "name": "Pavilion roof (east)", "level": "macro", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof of the pavilion; apex ridge cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "pavilion-east", "attachment": null, "dimensions": {"width": 14.2, "height": 3.6, "depth": 14.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 7.9, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-roof-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Pale ridge capping along hips and apex."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_roof_east_71.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-roof-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}};
  (nodes["pavilion-east"] ?? root).add(node_pavilion_roof_east_71);
  nodes["pavilion-roof-east"] = node_pavilion_roof_east_71;
  const mesh_pavilion_roof_east_71Geometry = endpoint_pavilion_roof_east_71
    ? new THREE.CylinderGeometry(endpoint_pavilion_roof_east_71.endRadius, endpoint_pavilion_roof_east_71.baseRadius, endpoint_pavilion_roof_east_71.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pavilion_roof_east_71) {
    mesh_pavilion_roof_east_71Geometry.scale(14.2, 3.6, 14.2);
  }
  const mesh_pavilion_roof_east_71 = new THREE.Mesh(
    mesh_pavilion_roof_east_71Geometry,
    materialMap["roof-tile"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pavilion_roof_east_71.name = "Pavilion roof (east)";
  if (endpoint_pavilion_roof_east_71) {
    mesh_pavilion_roof_east_71.position.copy(endpoint_pavilion_roof_east_71.midpoint);
    mesh_pavilion_roof_east_71.quaternion.copy(endpoint_pavilion_roof_east_71.quaternion);
  }
  mesh_pavilion_roof_east_71.castShadow = options.castShadow ?? true;
  mesh_pavilion_roof_east_71.receiveShadow = options.receiveShadow ?? true;
  mesh_pavilion_roof_east_71.userData.sculptComponent = {"id": "pavilion-roof-east", "name": "Pavilion roof (east)", "level": "macro", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof of the pavilion; apex ridge cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "pavilion-east", "attachment": null, "dimensions": {"width": 14.2, "height": 3.6, "depth": 14.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0.0, 7.9, 0.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-roof-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Pale ridge capping along hips and apex."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_roof_east_71.add(mesh_pavilion_roof_east_71);
  meshes["pavilion-roof-east"] = mesh_pavilion_roof_east_71;
  colliders["pavilion-roof-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pavilion-roof-east"] ??= [];
  destructionGroups["pavilion-roof-east"].push(node_pavilion_roof_east_71);

  const endpoint_rear_block_east_72 = makeAttachmentEndpoint(null);
  const node_rear_block_east_72 = new THREE.Group();
  node_rear_block_east_72.name = "Rear block (east)__pivot";
  node_rear_block_east_72.scale.set(1, 1, 1);
  if (endpoint_rear_block_east_72) {
    node_rear_block_east_72.position.copy(endpoint_rear_block_east_72.start);
    node_rear_block_east_72.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_rear_block_east_72.position.set(46.0, 12.1, -45.0);
    node_rear_block_east_72.rotation.set(0.0, 0.0, 0.0);
  }
  node_rear_block_east_72.userData.sculptComponent = {"id": "rear-block-east", "name": "Rear block (east)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Rear hall closing the courtyard; inferred from aerials, front rhythm assumed continued.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 19.4, "depth": 22, "units": "relative", "confidence": 0.6}, "transform": {"position": [46.0, 12.1, -45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_block_east_72.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_rear_block_east_72);
  nodes["rear-block-east"] = node_rear_block_east_72;
  const mesh_rear_block_east_72Geometry = endpoint_rear_block_east_72
    ? new THREE.CylinderGeometry(endpoint_rear_block_east_72.endRadius, endpoint_rear_block_east_72.baseRadius, endpoint_rear_block_east_72.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_rear_block_east_72) {
    mesh_rear_block_east_72Geometry.scale(17.0, 19.4, 22.0);
  }
  const mesh_rear_block_east_72 = new THREE.Mesh(
    mesh_rear_block_east_72Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_rear_block_east_72.name = "Rear block (east)";
  if (endpoint_rear_block_east_72) {
    mesh_rear_block_east_72.position.copy(endpoint_rear_block_east_72.midpoint);
    mesh_rear_block_east_72.quaternion.copy(endpoint_rear_block_east_72.quaternion);
  }
  mesh_rear_block_east_72.castShadow = options.castShadow ?? true;
  mesh_rear_block_east_72.receiveShadow = options.receiveShadow ?? true;
  mesh_rear_block_east_72.userData.sculptComponent = {"id": "rear-block-east", "name": "Rear block (east)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Rear hall closing the courtyard; inferred from aerials, front rhythm assumed continued.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 19.4, "depth": 22, "units": "relative", "confidence": 0.6}, "transform": {"position": [46.0, 12.1, -45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_block_east_72.add(mesh_rear_block_east_72);
  meshes["rear-block-east"] = mesh_rear_block_east_72;
  colliders["rear-block-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["rear-block-east"] ??= [];
  destructionGroups["rear-block-east"].push(node_rear_block_east_72);

  const endpoint_rear_windows_east_73 = makeAttachmentEndpoint(null);
  const node_rear_windows_east_73 = new THREE.Group();
  node_rear_windows_east_73.name = "Rear block windows (east)__pivot";
  node_rear_windows_east_73.scale.set(1, 1, 1);
  if (endpoint_rear_windows_east_73) {
    node_rear_windows_east_73.position.copy(endpoint_rear_windows_east_73.start);
    node_rear_windows_east_73.rotation.set(0.0, 1.570796, 0.0);
  } else {
    node_rear_windows_east_73.position.set(-8.5, 1.9, 0.0);
    node_rear_windows_east_73.rotation.set(0.0, 1.570796, 0.0);
  }
  node_rear_windows_east_73.userData.sculptComponent = {"id": "rear-windows-east", "name": "Rear block windows (east)", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.5, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Courtyard-facing windows; grid looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "rear-block-east", "attachment": null, "dimensions": {"width": 0.35, "height": 2.2, "depth": 1.6, "units": "relative", "confidence": 0.5}, "transform": {"position": [-8.5, 1.9, 0], "rotation": [0, 1.570796, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.5}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_rear_windows_east_73.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.5}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["rear-block-east"] ?? root).add(node_rear_windows_east_73);
  nodes["rear-windows-east"] = node_rear_windows_east_73;
  const mesh_rear_windows_east_73Geometry = endpoint_rear_windows_east_73
    ? new THREE.CylinderGeometry(endpoint_rear_windows_east_73.endRadius, endpoint_rear_windows_east_73.baseRadius, endpoint_rear_windows_east_73.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_rear_windows_east_73) {
    mesh_rear_windows_east_73Geometry.scale(0.35, 2.2, 1.6);
  }
  const mesh_rear_windows_east_73 = new THREE.Mesh(
    mesh_rear_windows_east_73Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_rear_windows_east_73.name = "Rear block windows (east)";
  if (endpoint_rear_windows_east_73) {
    mesh_rear_windows_east_73.position.copy(endpoint_rear_windows_east_73.midpoint);
    mesh_rear_windows_east_73.quaternion.copy(endpoint_rear_windows_east_73.quaternion);
  }
  mesh_rear_windows_east_73.castShadow = options.castShadow ?? true;
  mesh_rear_windows_east_73.receiveShadow = options.receiveShadow ?? true;
  mesh_rear_windows_east_73.userData.sculptComponent = {"id": "rear-windows-east", "name": "Rear block windows (east)", "level": "micro", "role": "structure", "importance": 0.45, "confidence": 0.5, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Courtyard-facing windows; grid looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "rear-block-east", "attachment": null, "dimensions": {"width": 0.35, "height": 2.2, "depth": 1.6, "units": "relative", "confidence": 0.5}, "transform": {"position": [-8.5, 1.9, 0], "rotation": [0, 1.570796, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.5}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-windows-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_rear_windows_east_73.add(mesh_rear_windows_east_73);
  meshes["rear-windows-east"] = mesh_rear_windows_east_73;
  colliders["rear-windows-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["rear-windows-east"] ??= [];
  destructionGroups["rear-windows-east"].push(node_rear_windows_east_73);

  const endpoint_rear_roof_east_74 = makeAttachmentEndpoint(null);
  const node_rear_roof_east_74 = new THREE.Group();
  node_rear_roof_east_74.name = "Rear block roof (east)__pivot";
  node_rear_roof_east_74.scale.set(1, 1, 1);
  if (endpoint_rear_roof_east_74) {
    node_rear_roof_east_74.position.copy(endpoint_rear_roof_east_74.start);
    node_rear_roof_east_74.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_rear_roof_east_74.position.set(0.0, 12.3, 0.0);
    node_rear_roof_east_74.rotation.set(0.0, 0.0, 0.0);
  }
  node_rear_roof_east_74.userData.sculptComponent = {"id": "rear-roof-east", "name": "Rear block roof (east)", "level": "macro", "role": "structure", "importance": 0.55, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof matching the front halls, inferred.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "rear-block-east", "attachment": null, "dimensions": {"width": 18, "height": 4.4, "depth": 23, "units": "relative", "confidence": 0.6}, "transform": {"position": [0.0, 12.3, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-roof-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Pale ridge capping along hips and ridge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_roof_east_74.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-roof-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}};
  (nodes["rear-block-east"] ?? root).add(node_rear_roof_east_74);
  nodes["rear-roof-east"] = node_rear_roof_east_74;
  const mesh_rear_roof_east_74Geometry = endpoint_rear_roof_east_74
    ? new THREE.CylinderGeometry(endpoint_rear_roof_east_74.endRadius, endpoint_rear_roof_east_74.baseRadius, endpoint_rear_roof_east_74.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_rear_roof_east_74) {
    mesh_rear_roof_east_74Geometry.scale(18.0, 4.4, 23.0);
  }
  const mesh_rear_roof_east_74 = new THREE.Mesh(
    mesh_rear_roof_east_74Geometry,
    materialMap["roof-tile"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_rear_roof_east_74.name = "Rear block roof (east)";
  if (endpoint_rear_roof_east_74) {
    mesh_rear_roof_east_74.position.copy(endpoint_rear_roof_east_74.midpoint);
    mesh_rear_roof_east_74.quaternion.copy(endpoint_rear_roof_east_74.quaternion);
  }
  mesh_rear_roof_east_74.castShadow = options.castShadow ?? true;
  mesh_rear_roof_east_74.receiveShadow = options.receiveShadow ?? true;
  mesh_rear_roof_east_74.userData.sculptComponent = {"id": "rear-roof-east", "name": "Rear block roof (east)", "level": "macro", "role": "structure", "importance": 0.55, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hip roof matching the front halls, inferred.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "rear-block-east", "attachment": null, "dimensions": {"width": 18, "height": 4.4, "depth": 23, "units": "relative", "confidence": 0.6}, "transform": {"position": [0.0, 12.3, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-roof-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "roof-tile"}}, "material": "roof-tile", "materialLayers": ["roof-tile"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "ridge-caps", "description": "Pale ridge capping along hips and ridge."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(176, 90, 58, 1.0)", "secondaryAlbedo": "rgba(156, 78, 49, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_roof_east_74.add(mesh_rear_roof_east_74);
  meshes["rear-roof-east"] = mesh_rear_roof_east_74;
  colliders["rear-roof-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["rear-roof-east"] ??= [];
  destructionGroups["rear-roof-east"].push(node_rear_roof_east_74);

  const endpoint_courtyard_conifers_east_75 = makeAttachmentEndpoint(null);
  const node_courtyard_conifers_east_75 = new THREE.Group();
  node_courtyard_conifers_east_75.name = "Courtyard conifers (east)__pivot";
  node_courtyard_conifers_east_75.scale.set(1, 1, 1);
  if (endpoint_courtyard_conifers_east_75) {
    node_courtyard_conifers_east_75.position.copy(endpoint_courtyard_conifers_east_75.start);
    node_courtyard_conifers_east_75.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_courtyard_conifers_east_75.position.set(33.0, 6.0, -25.0);
    node_courtyard_conifers_east_75.rotation.set(0.0, 0.0, 0.0);
  }
  node_courtyard_conifers_east_75.userData.sculptComponent = {"id": "courtyard-conifers-east", "name": "Courtyard conifers (east)", "level": "micro", "role": "structure", "importance": 0.35, "confidence": 0.6, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Conical trees: revolved cone profile (lathe).", "geometryDescriptor": {"topologyIntent": "Row of dark conifers along the courtyard wall; looped in code with slight scale variance.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 10}}, "parent": "root", "attachment": null, "dimensions": {"width": 2.4, "height": 12, "depth": 2.4, "units": "relative", "confidence": 0.6}, "transform": {"position": [33, 6.0, -25], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-conifers-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_courtyard_conifers_east_75.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-conifers-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}};
  (nodes["root"] ?? root).add(node_courtyard_conifers_east_75);
  nodes["courtyard-conifers-east"] = node_courtyard_conifers_east_75;
  const mesh_courtyard_conifers_east_75Geometry = endpoint_courtyard_conifers_east_75
    ? new THREE.CylinderGeometry(endpoint_courtyard_conifers_east_75.endRadius, endpoint_courtyard_conifers_east_75.baseRadius, endpoint_courtyard_conifers_east_75.length, 32, 12)
    : buildLatheGeometry({"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 10});
  if (!endpoint_courtyard_conifers_east_75) {
    mesh_courtyard_conifers_east_75Geometry.scale(2.4, 12.0, 2.4);
  }
  const mesh_courtyard_conifers_east_75 = new THREE.Mesh(
    mesh_courtyard_conifers_east_75Geometry,
    materialMap["foliage-green"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_courtyard_conifers_east_75.name = "Courtyard conifers (east)";
  if (endpoint_courtyard_conifers_east_75) {
    mesh_courtyard_conifers_east_75.position.copy(endpoint_courtyard_conifers_east_75.midpoint);
    mesh_courtyard_conifers_east_75.quaternion.copy(endpoint_courtyard_conifers_east_75.quaternion);
  }
  mesh_courtyard_conifers_east_75.castShadow = options.castShadow ?? true;
  mesh_courtyard_conifers_east_75.receiveShadow = options.receiveShadow ?? true;
  mesh_courtyard_conifers_east_75.userData.sculptComponent = {"id": "courtyard-conifers-east", "name": "Courtyard conifers (east)", "level": "micro", "role": "structure", "importance": 0.35, "confidence": 0.6, "primitive": "lathe", "topologyClass": "assembled-solid", "topologyRationale": "Conical trees: revolved cone profile (lathe).", "geometryDescriptor": {"topologyIntent": "Row of dark conifers along the courtyard wall; looped in code with slight scale variance.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.5, -0.5], [0.0, 0.5]], "segments": 10}}, "parent": "root", "attachment": null, "dimensions": {"width": 2.4, "height": 12, "depth": 2.4, "units": "relative", "confidence": 0.6}, "transform": {"position": [33, 6.0, -25], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-conifers-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_courtyard_conifers_east_75.add(mesh_courtyard_conifers_east_75);
  meshes["courtyard-conifers-east"] = mesh_courtyard_conifers_east_75;
  colliders["courtyard-conifers-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["courtyard-conifers-east"] ??= [];
  destructionGroups["courtyard-conifers-east"].push(node_courtyard_conifers_east_75);

  const endpoint_courtyard_hall_76 = makeAttachmentEndpoint(null);
  const node_courtyard_hall_76 = new THREE.Group();
  node_courtyard_hall_76.name = "Courtyard glass hall__pivot";
  node_courtyard_hall_76.scale.set(1, 1, 1);
  if (endpoint_courtyard_hall_76) {
    node_courtyard_hall_76.position.copy(endpoint_courtyard_hall_76.start);
    node_courtyard_hall_76.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_courtyard_hall_76.position.set(-30.0, 5.4, -24.0);
    node_courtyard_hall_76.rotation.set(0.0, 0.0, 0.0);
  }
  node_courtyard_hall_76.userData.sculptComponent = {"id": "courtyard-hall", "name": "Courtyard glass hall", "level": "meso", "role": "structure", "importance": 0.55, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Glazed volume in the west courtyard nook under the sloped canopy.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 15, "height": 6.0, "depth": 13, "units": "relative", "confidence": 0.6}, "transform": {"position": [-30, 5.4, -24], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_courtyard_hall_76.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}};
  (nodes["root"] ?? root).add(node_courtyard_hall_76);
  nodes["courtyard-hall"] = node_courtyard_hall_76;
  const mesh_courtyard_hall_76Geometry = endpoint_courtyard_hall_76
    ? new THREE.CylinderGeometry(endpoint_courtyard_hall_76.endRadius, endpoint_courtyard_hall_76.baseRadius, endpoint_courtyard_hall_76.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_courtyard_hall_76) {
    mesh_courtyard_hall_76Geometry.scale(15.0, 6.0, 13.0);
  }
  const mesh_courtyard_hall_76 = new THREE.Mesh(
    mesh_courtyard_hall_76Geometry,
    materialMap["glass-dark"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_courtyard_hall_76.name = "Courtyard glass hall";
  if (endpoint_courtyard_hall_76) {
    mesh_courtyard_hall_76.position.copy(endpoint_courtyard_hall_76.midpoint);
    mesh_courtyard_hall_76.quaternion.copy(endpoint_courtyard_hall_76.quaternion);
  }
  mesh_courtyard_hall_76.castShadow = options.castShadow ?? true;
  mesh_courtyard_hall_76.receiveShadow = options.receiveShadow ?? true;
  mesh_courtyard_hall_76.userData.sculptComponent = {"id": "courtyard-hall", "name": "Courtyard glass hall", "level": "meso", "role": "structure", "importance": 0.55, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Glazed volume in the west courtyard nook under the sloped canopy.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 15, "height": 6.0, "depth": 13, "units": "relative", "confidence": 0.6}, "transform": {"position": [-30, 5.4, -24], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dark"}}, "material": "glass-dark", "materialLayers": ["glass-dark"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(41, 66, 74, 1.0)", "secondaryAlbedo": "rgba(30, 52, 59, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_courtyard_hall_76.add(mesh_courtyard_hall_76);
  meshes["courtyard-hall"] = mesh_courtyard_hall_76;
  colliders["courtyard-hall"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["courtyard-hall"] ??= [];
  destructionGroups["courtyard-hall"].push(node_courtyard_hall_76);

  const endpoint_courtyard_canopy_77 = makeAttachmentEndpoint(null);
  const node_courtyard_canopy_77 = new THREE.Group();
  node_courtyard_canopy_77.name = "Courtyard sloped canopy__pivot";
  node_courtyard_canopy_77.scale.set(1, 1, 1);
  if (endpoint_courtyard_canopy_77) {
    node_courtyard_canopy_77.position.copy(endpoint_courtyard_canopy_77.start);
    node_courtyard_canopy_77.rotation.set(-0.191986, 0.0, 0.0);
  } else {
    node_courtyard_canopy_77.position.set(-30.0, 9.0, -24.0);
    node_courtyard_canopy_77.rotation.set(-0.191986, 0.0, 0.0);
  }
  node_courtyard_canopy_77.userData.sculptComponent = {"id": "courtyard-canopy", "name": "Courtyard sloped canopy", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.65, "primitive": "box", "topologyClass": "conforming-shell", "topologyRationale": "Thin framed glazing plane riding over the glass hall; a shallow tilted shell.", "geometryDescriptor": {"topologyIntent": "Single-pitch framed glass canopy over the courtyard hall.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 15.4, "height": 1.0, "depth": 13.4, "units": "relative", "confidence": 0.65}, "transform": {"position": [-30, 9.0, -24], "rotation": [-0.191986, 0, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.65}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-canopy", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-sky"}}, "material": "glass-sky", "materialLayers": ["glass-sky"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "pane-grid", "description": "Square glass panes in a steel grid; frame lines bright against the dark interior."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(143, 180, 180, 1.0)", "secondaryAlbedo": "rgba(124, 166, 168, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_courtyard_canopy_77.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.65}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-canopy", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-sky"}};
  (nodes["root"] ?? root).add(node_courtyard_canopy_77);
  nodes["courtyard-canopy"] = node_courtyard_canopy_77;
  const mesh_courtyard_canopy_77Geometry = endpoint_courtyard_canopy_77
    ? new THREE.CylinderGeometry(endpoint_courtyard_canopy_77.endRadius, endpoint_courtyard_canopy_77.baseRadius, endpoint_courtyard_canopy_77.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_courtyard_canopy_77) {
    mesh_courtyard_canopy_77Geometry.scale(15.4, 1.0, 13.4);
  }
  const mesh_courtyard_canopy_77 = new THREE.Mesh(
    mesh_courtyard_canopy_77Geometry,
    materialMap["glass-sky"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_courtyard_canopy_77.name = "Courtyard sloped canopy";
  if (endpoint_courtyard_canopy_77) {
    mesh_courtyard_canopy_77.position.copy(endpoint_courtyard_canopy_77.midpoint);
    mesh_courtyard_canopy_77.quaternion.copy(endpoint_courtyard_canopy_77.quaternion);
  }
  mesh_courtyard_canopy_77.castShadow = options.castShadow ?? true;
  mesh_courtyard_canopy_77.receiveShadow = options.receiveShadow ?? true;
  mesh_courtyard_canopy_77.userData.sculptComponent = {"id": "courtyard-canopy", "name": "Courtyard sloped canopy", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.65, "primitive": "box", "topologyClass": "conforming-shell", "topologyRationale": "Thin framed glazing plane riding over the glass hall; a shallow tilted shell.", "geometryDescriptor": {"topologyIntent": "Single-pitch framed glass canopy over the courtyard hall.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 15.4, "height": 1.0, "depth": 13.4, "units": "relative", "confidence": 0.65}, "transform": {"position": [-30, 9.0, -24], "rotation": [-0.191986, 0, 0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.65}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "courtyard-canopy", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-sky"}}, "material": "glass-sky", "materialLayers": ["glass-sky"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "pane-grid", "description": "Square glass panes in a steel grid; frame lines bright against the dark interior."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r1c0.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(143, 180, 180, 1.0)", "secondaryAlbedo": "rgba(124, 166, 168, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_courtyard_canopy_77.add(mesh_courtyard_canopy_77);
  meshes["courtyard-canopy"] = mesh_courtyard_canopy_77;
  colliders["courtyard-canopy"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["courtyard-canopy"] ??= [];
  destructionGroups["courtyard-canopy"].push(node_courtyard_canopy_77);

  const endpoint_vault_shell_78 = makeAttachmentEndpoint(null);
  const node_vault_shell_78 = new THREE.Group();
  node_vault_shell_78.name = "Courtyard vault shell__pivot";
  node_vault_shell_78.scale.set(1, 1, 1);
  if (endpoint_vault_shell_78) {
    node_vault_shell_78.position.copy(endpoint_vault_shell_78.start);
    node_vault_shell_78.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_vault_shell_78.position.set(29.5, 6.4, -36.0);
    node_vault_shell_78.rotation.set(0.0, 0.0, 0.0);
  }
  node_vault_shell_78.userData.sculptComponent = {"id": "vault-shell", "name": "Courtyard vault shell", "level": "meso", "role": "structure", "importance": 0.55, "confidence": 0.6, "primitive": "box", "topologyClass": "conforming-shell", "topologyRationale": "Barrel vault placeholder mass; the curved half-pipe shell is authored in the factory refine step.", "geometryDescriptor": {"topologyIntent": "Glazed barrel vault bridging the central block and the east rear block; box placeholder, half-pipe + ribs in refine-code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 6.0, "depth": 6.4, "units": "relative", "confidence": 0.6}, "transform": {"position": [29.5, 6.4, -36], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "vault-shell", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-sky"}}, "material": "glass-sky", "materialLayers": ["glass-sky"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "rib-row", "description": "Repeated parallel steel ribs over the curved glass."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(143, 180, 180, 1.0)", "secondaryAlbedo": "rgba(124, 166, 168, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_vault_shell_78.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "vault-shell", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-sky"}};
  (nodes["root"] ?? root).add(node_vault_shell_78);
  nodes["vault-shell"] = node_vault_shell_78;
  const mesh_vault_shell_78Geometry = endpoint_vault_shell_78
    ? new THREE.CylinderGeometry(endpoint_vault_shell_78.endRadius, endpoint_vault_shell_78.baseRadius, endpoint_vault_shell_78.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_vault_shell_78) {
    mesh_vault_shell_78Geometry.scale(17.0, 6.0, 6.4);
  }
  const mesh_vault_shell_78 = new THREE.Mesh(
    mesh_vault_shell_78Geometry,
    materialMap["glass-sky"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_vault_shell_78.name = "Courtyard vault shell";
  if (endpoint_vault_shell_78) {
    mesh_vault_shell_78.position.copy(endpoint_vault_shell_78.midpoint);
    mesh_vault_shell_78.quaternion.copy(endpoint_vault_shell_78.quaternion);
  }
  mesh_vault_shell_78.castShadow = options.castShadow ?? true;
  mesh_vault_shell_78.receiveShadow = options.receiveShadow ?? true;
  mesh_vault_shell_78.userData.sculptComponent = {"id": "vault-shell", "name": "Courtyard vault shell", "level": "meso", "role": "structure", "importance": 0.55, "confidence": 0.6, "primitive": "box", "topologyClass": "conforming-shell", "topologyRationale": "Barrel vault placeholder mass; the curved half-pipe shell is authored in the factory refine step.", "geometryDescriptor": {"topologyIntent": "Glazed barrel vault bridging the central block and the east rear block; box placeholder, half-pipe + ribs in refine-code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 6.0, "depth": 6.4, "units": "relative", "confidence": 0.6}, "transform": {"position": [29.5, 6.4, -36], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "vault-shell", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-sky"}}, "material": "glass-sky", "materialLayers": ["glass-sky"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "rib-row", "description": "Repeated parallel steel ribs over the curved glass."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(143, 180, 180, 1.0)", "secondaryAlbedo": "rgba(124, 166, 168, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_vault_shell_78.add(mesh_vault_shell_78);
  meshes["vault-shell"] = mesh_vault_shell_78;
  colliders["vault-shell"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["vault-shell"] ??= [];
  destructionGroups["vault-shell"].push(node_vault_shell_78);

  const endpoint_vault_base_79 = makeAttachmentEndpoint(null);
  const node_vault_base_79 = new THREE.Group();
  node_vault_base_79.name = "Vault base wall__pivot";
  node_vault_base_79.scale.set(1, 1, 1);
  if (endpoint_vault_base_79) {
    node_vault_base_79.position.copy(endpoint_vault_base_79.start);
    node_vault_base_79.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_vault_base_79.position.set(29.5, 4.0, -36.0);
    node_vault_base_79.rotation.set(0.0, 0.0, 0.0);
  }
  node_vault_base_79.userData.sculptComponent = {"id": "vault-base", "name": "Vault base wall", "level": "meso", "role": "structure", "importance": 0.4, "confidence": 0.55, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low wall under the vault edges.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 3.2, "depth": 6.8, "units": "relative", "confidence": 0.55}, "transform": {"position": [29.5, 4.0, -36], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.55}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "vault-base", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_vault_base_79.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.55}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "vault-base", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_vault_base_79);
  nodes["vault-base"] = node_vault_base_79;
  const mesh_vault_base_79Geometry = endpoint_vault_base_79
    ? new THREE.CylinderGeometry(endpoint_vault_base_79.endRadius, endpoint_vault_base_79.baseRadius, endpoint_vault_base_79.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_vault_base_79) {
    mesh_vault_base_79Geometry.scale(17.0, 3.2, 6.8);
  }
  const mesh_vault_base_79 = new THREE.Mesh(
    mesh_vault_base_79Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_vault_base_79.name = "Vault base wall";
  if (endpoint_vault_base_79) {
    mesh_vault_base_79.position.copy(endpoint_vault_base_79.midpoint);
    mesh_vault_base_79.quaternion.copy(endpoint_vault_base_79.quaternion);
  }
  mesh_vault_base_79.castShadow = options.castShadow ?? true;
  mesh_vault_base_79.receiveShadow = options.receiveShadow ?? true;
  mesh_vault_base_79.userData.sculptComponent = {"id": "vault-base", "name": "Vault base wall", "level": "meso", "role": "structure", "importance": 0.4, "confidence": 0.55, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low wall under the vault edges.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 3.2, "depth": 6.8, "units": "relative", "confidence": 0.55}, "transform": {"position": [29.5, 4.0, -36], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.55}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "vault-base", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref04/zone-r0c2.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_vault_base_79.add(mesh_vault_base_79);
  meshes["vault-base"] = mesh_vault_base_79;
  colliders["vault-base"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["vault-base"] ??= [];
  destructionGroups["vault-base"].push(node_vault_base_79);

  const endpoint_plaza_grounds_80 = makeAttachmentEndpoint(null);
  const node_plaza_grounds_80 = new THREE.Group();
  node_plaza_grounds_80.name = "Plaza grounds__pivot";
  node_plaza_grounds_80.scale.set(1, 1, 1);
  if (endpoint_plaza_grounds_80) {
    node_plaza_grounds_80.position.copy(endpoint_plaza_grounds_80.start);
    node_plaza_grounds_80.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_plaza_grounds_80.position.set(0.0, 0.0, 45.0);
    node_plaza_grounds_80.rotation.set(0.0, 0.0, 0.0);
  }
  node_plaza_grounds_80.userData.sculptComponent = {"id": "plaza-grounds", "name": "Plaza grounds", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Axial plaza field: paving, lawn edges, parterre and tree rows.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 220, "height": 1.2, "depth": 120, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0, 45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-grounds", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "paving-plaza"}}, "material": "paving-plaza", "materialLayers": ["paving-plaza"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(205, 197, 176, 1.0)", "secondaryAlbedo": "rgba(190, 181, 160, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_grounds_80.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-grounds", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "paving-plaza"}};
  (nodes["root"] ?? root).add(node_plaza_grounds_80);
  nodes["plaza-grounds"] = node_plaza_grounds_80;
  const mesh_plaza_grounds_80Geometry = endpoint_plaza_grounds_80
    ? new THREE.CylinderGeometry(endpoint_plaza_grounds_80.endRadius, endpoint_plaza_grounds_80.baseRadius, endpoint_plaza_grounds_80.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_plaza_grounds_80) {
    mesh_plaza_grounds_80Geometry.scale(220.0, 1.2, 120.0);
  }
  const mesh_plaza_grounds_80 = new THREE.Mesh(
    mesh_plaza_grounds_80Geometry,
    materialMap["paving-plaza"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_plaza_grounds_80.name = "Plaza grounds";
  if (endpoint_plaza_grounds_80) {
    mesh_plaza_grounds_80.position.copy(endpoint_plaza_grounds_80.midpoint);
    mesh_plaza_grounds_80.quaternion.copy(endpoint_plaza_grounds_80.quaternion);
  }
  mesh_plaza_grounds_80.castShadow = options.castShadow ?? true;
  mesh_plaza_grounds_80.receiveShadow = options.receiveShadow ?? true;
  mesh_plaza_grounds_80.userData.sculptComponent = {"id": "plaza-grounds", "name": "Plaza grounds", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Axial plaza field: paving, lawn edges, parterre and tree rows.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 220, "height": 1.2, "depth": 120, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0, 45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-grounds", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "paving-plaza"}}, "material": "paving-plaza", "materialLayers": ["paving-plaza"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(205, 197, 176, 1.0)", "secondaryAlbedo": "rgba(190, 181, 160, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_grounds_80.add(mesh_plaza_grounds_80);
  meshes["plaza-grounds"] = mesh_plaza_grounds_80;
  colliders["plaza-grounds"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["plaza-grounds"] ??= [];
  destructionGroups["plaza-grounds"].push(node_plaza_grounds_80);

  const endpoint_plaza_paving_81 = makeAttachmentEndpoint(null);
  const node_plaza_paving_81 = new THREE.Group();
  node_plaza_paving_81.name = "Plaza paving field__pivot";
  node_plaza_paving_81.scale.set(1, 1, 1);
  if (endpoint_plaza_paving_81) {
    node_plaza_paving_81.position.copy(endpoint_plaza_paving_81.start);
    node_plaza_paving_81.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_plaza_paving_81.position.set(0.0, -0.03, -1.0);
    node_plaza_paving_81.rotation.set(0.0, 0.0, 0.0);
  }
  node_plaza_paving_81.userData.sculptComponent = {"id": "plaza-paving", "name": "Plaza paving field", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Light granite tile field on the central axis; joints visible up close.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 150, "height": 0.12, "depth": 95, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -0.03, -1], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-paving", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "paving-plaza"}}, "material": "paving-plaza", "materialLayers": ["paving-plaza"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(205, 197, 176, 1.0)", "secondaryAlbedo": "rgba(190, 181, 160, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_paving_81.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-paving", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "paving-plaza"}};
  (nodes["plaza-grounds"] ?? root).add(node_plaza_paving_81);
  nodes["plaza-paving"] = node_plaza_paving_81;
  const mesh_plaza_paving_81Geometry = endpoint_plaza_paving_81
    ? new THREE.CylinderGeometry(endpoint_plaza_paving_81.endRadius, endpoint_plaza_paving_81.baseRadius, endpoint_plaza_paving_81.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_plaza_paving_81) {
    mesh_plaza_paving_81Geometry.scale(150.0, 0.12, 95.0);
  }
  const mesh_plaza_paving_81 = new THREE.Mesh(
    mesh_plaza_paving_81Geometry,
    materialMap["paving-plaza"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_plaza_paving_81.name = "Plaza paving field";
  if (endpoint_plaza_paving_81) {
    mesh_plaza_paving_81.position.copy(endpoint_plaza_paving_81.midpoint);
    mesh_plaza_paving_81.quaternion.copy(endpoint_plaza_paving_81.quaternion);
  }
  mesh_plaza_paving_81.castShadow = options.castShadow ?? true;
  mesh_plaza_paving_81.receiveShadow = options.receiveShadow ?? true;
  mesh_plaza_paving_81.userData.sculptComponent = {"id": "plaza-paving", "name": "Plaza paving field", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Light granite tile field on the central axis; joints visible up close.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 150, "height": 0.12, "depth": 95, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -0.03, -1], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-paving", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "paving-plaza"}}, "material": "paving-plaza", "materialLayers": ["paving-plaza"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(205, 197, 176, 1.0)", "secondaryAlbedo": "rgba(190, 181, 160, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_paving_81.add(mesh_plaza_paving_81);
  meshes["plaza-paving"] = mesh_plaza_paving_81;
  colliders["plaza-paving"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["plaza-paving"] ??= [];
  destructionGroups["plaza-paving"].push(node_plaza_paving_81);

  const endpoint_plaza_lawn_field_82 = makeAttachmentEndpoint(null);
  const node_plaza_lawn_field_82 = new THREE.Group();
  node_plaza_lawn_field_82.name = "Lawn fields__pivot";
  node_plaza_lawn_field_82.scale.set(1, 1, 1);
  if (endpoint_plaza_lawn_field_82) {
    node_plaza_lawn_field_82.position.copy(endpoint_plaza_lawn_field_82.start);
    node_plaza_lawn_field_82.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_plaza_lawn_field_82.position.set(0.0, -0.1, -5.0);
    node_plaza_lawn_field_82.rotation.set(0.0, 0.0, 0.0);
  }
  node_plaza_lawn_field_82.userData.sculptComponent = {"id": "plaza-lawn-field", "name": "Lawn fields", "level": "meso", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Lawn surround under and around the paving field.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 230, "height": 0.16, "depth": 120, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -0.1, -5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-lawn-field", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "lawn-turf"}}, "material": "lawn-turf", "materialLayers": ["lawn-turf"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(93, 127, 59, 1.0)", "secondaryAlbedo": "rgba(79, 113, 52, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_plaza_lawn_field_82.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-lawn-field", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "lawn-turf"}};
  (nodes["plaza-grounds"] ?? root).add(node_plaza_lawn_field_82);
  nodes["plaza-lawn-field"] = node_plaza_lawn_field_82;
  const mesh_plaza_lawn_field_82Geometry = endpoint_plaza_lawn_field_82
    ? new THREE.CylinderGeometry(endpoint_plaza_lawn_field_82.endRadius, endpoint_plaza_lawn_field_82.baseRadius, endpoint_plaza_lawn_field_82.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_plaza_lawn_field_82) {
    mesh_plaza_lawn_field_82Geometry.scale(230.0, 0.16, 120.0);
  }
  const mesh_plaza_lawn_field_82 = new THREE.Mesh(
    mesh_plaza_lawn_field_82Geometry,
    materialMap["lawn-turf"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_plaza_lawn_field_82.name = "Lawn fields";
  if (endpoint_plaza_lawn_field_82) {
    mesh_plaza_lawn_field_82.position.copy(endpoint_plaza_lawn_field_82.midpoint);
    mesh_plaza_lawn_field_82.quaternion.copy(endpoint_plaza_lawn_field_82.quaternion);
  }
  mesh_plaza_lawn_field_82.castShadow = options.castShadow ?? true;
  mesh_plaza_lawn_field_82.receiveShadow = options.receiveShadow ?? true;
  mesh_plaza_lawn_field_82.userData.sculptComponent = {"id": "plaza-lawn-field", "name": "Lawn fields", "level": "meso", "role": "structure", "importance": 0.5, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Lawn surround under and around the paving field.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 230, "height": 0.16, "depth": 120, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -0.1, -5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-lawn-field", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "lawn-turf"}}, "material": "lawn-turf", "materialLayers": ["lawn-turf"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(93, 127, 59, 1.0)", "secondaryAlbedo": "rgba(79, 113, 52, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_plaza_lawn_field_82.add(mesh_plaza_lawn_field_82);
  meshes["plaza-lawn-field"] = mesh_plaza_lawn_field_82;
  colliders["plaza-lawn-field"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["plaza-lawn-field"] ??= [];
  destructionGroups["plaza-lawn-field"].push(node_plaza_lawn_field_82);

  const endpoint_parterre_turf_83 = makeAttachmentEndpoint(null);
  const node_parterre_turf_83 = new THREE.Group();
  node_parterre_turf_83.name = "Parterre turf strips__pivot";
  node_parterre_turf_83.scale.set(1, 1, 1);
  if (endpoint_parterre_turf_83) {
    node_parterre_turf_83.position.copy(endpoint_parterre_turf_83.start);
    node_parterre_turf_83.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_parterre_turf_83.position.set(0.0, 0.18, -19.0);
    node_parterre_turf_83.rotation.set(0.0, 0.0, 0.0);
  }
  node_parterre_turf_83.userData.sculptComponent = {"id": "parterre-turf", "name": "Parterre turf strips", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Mown turf strip on the axis between the steps and the pool.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 18, "height": 0.35, "depth": 15, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.18, -19], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "parterre-turf", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "lawn-turf"}}, "material": "lawn-turf", "materialLayers": ["lawn-turf"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(93, 127, 59, 1.0)", "secondaryAlbedo": "rgba(79, 113, 52, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_parterre_turf_83.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "parterre-turf", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "lawn-turf"}};
  (nodes["plaza-grounds"] ?? root).add(node_parterre_turf_83);
  nodes["parterre-turf"] = node_parterre_turf_83;
  const mesh_parterre_turf_83Geometry = endpoint_parterre_turf_83
    ? new THREE.CylinderGeometry(endpoint_parterre_turf_83.endRadius, endpoint_parterre_turf_83.baseRadius, endpoint_parterre_turf_83.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_parterre_turf_83) {
    mesh_parterre_turf_83Geometry.scale(18.0, 0.35, 15.0);
  }
  const mesh_parterre_turf_83 = new THREE.Mesh(
    mesh_parterre_turf_83Geometry,
    materialMap["lawn-turf"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_parterre_turf_83.name = "Parterre turf strips";
  if (endpoint_parterre_turf_83) {
    mesh_parterre_turf_83.position.copy(endpoint_parterre_turf_83.midpoint);
    mesh_parterre_turf_83.quaternion.copy(endpoint_parterre_turf_83.quaternion);
  }
  mesh_parterre_turf_83.castShadow = options.castShadow ?? true;
  mesh_parterre_turf_83.receiveShadow = options.receiveShadow ?? true;
  mesh_parterre_turf_83.userData.sculptComponent = {"id": "parterre-turf", "name": "Parterre turf strips", "level": "meso", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Mown turf strip on the axis between the steps and the pool.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 18, "height": 0.35, "depth": 15, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.18, -19], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "parterre-turf", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "lawn-turf"}}, "material": "lawn-turf", "materialLayers": ["lawn-turf"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(93, 127, 59, 1.0)", "secondaryAlbedo": "rgba(79, 113, 52, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_parterre_turf_83.add(mesh_parterre_turf_83);
  meshes["parterre-turf"] = mesh_parterre_turf_83;
  colliders["parterre-turf"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["parterre-turf"] ??= [];
  destructionGroups["parterre-turf"].push(node_parterre_turf_83);

  const endpoint_parterre_blocks_84 = makeAttachmentEndpoint(null);
  const node_parterre_blocks_84 = new THREE.Group();
  node_parterre_blocks_84.name = "Parterre hedge blocks__pivot";
  node_parterre_blocks_84.scale.set(1, 1, 1);
  if (endpoint_parterre_blocks_84) {
    node_parterre_blocks_84.position.copy(endpoint_parterre_blocks_84.start);
    node_parterre_blocks_84.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_parterre_blocks_84.position.set(-6.3, 0.78, -22.5);
    node_parterre_blocks_84.rotation.set(0.0, 0.0, 0.0);
  }
  node_parterre_blocks_84.userData.sculptComponent = {"id": "parterre-blocks", "name": "Parterre hedge blocks", "level": "micro", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored block; the 2x4 arrangement is looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 1.7, "height": 0.85, "depth": 1.5, "units": "relative", "confidence": 0.8}, "transform": {"position": [-6.3, 0.78, -22.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "parterre-blocks", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "hedge-purple"}}, "material": "hedge-purple", "materialLayers": ["hedge-purple"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "hedge-rows", "description": "Rows of dark plum clipped hedge blocks laid across the turf strip."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(74, 47, 62, 1.0)", "secondaryAlbedo": "rgba(60, 37, 50, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_parterre_blocks_84.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "parterre-blocks", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "hedge-purple"}};
  (nodes["plaza-grounds"] ?? root).add(node_parterre_blocks_84);
  nodes["parterre-blocks"] = node_parterre_blocks_84;
  const mesh_parterre_blocks_84Geometry = endpoint_parterre_blocks_84
    ? new THREE.CylinderGeometry(endpoint_parterre_blocks_84.endRadius, endpoint_parterre_blocks_84.baseRadius, endpoint_parterre_blocks_84.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_parterre_blocks_84) {
    mesh_parterre_blocks_84Geometry.scale(1.7, 0.85, 1.5);
  }
  const mesh_parterre_blocks_84 = new THREE.Mesh(
    mesh_parterre_blocks_84Geometry,
    materialMap["hedge-purple"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_parterre_blocks_84.name = "Parterre hedge blocks";
  if (endpoint_parterre_blocks_84) {
    mesh_parterre_blocks_84.position.copy(endpoint_parterre_blocks_84.midpoint);
    mesh_parterre_blocks_84.quaternion.copy(endpoint_parterre_blocks_84.quaternion);
  }
  mesh_parterre_blocks_84.castShadow = options.castShadow ?? true;
  mesh_parterre_blocks_84.receiveShadow = options.receiveShadow ?? true;
  mesh_parterre_blocks_84.userData.sculptComponent = {"id": "parterre-blocks", "name": "Parterre hedge blocks", "level": "micro", "role": "structure", "importance": 0.6, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Single authored block; the 2x4 arrangement is looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 1.7, "height": 0.85, "depth": 1.5, "units": "relative", "confidence": 0.8}, "transform": {"position": [-6.3, 0.78, -22.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "parterre-blocks", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "hedge-purple"}}, "material": "hedge-purple", "materialLayers": ["hedge-purple"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "hedge-rows", "description": "Rows of dark plum clipped hedge blocks laid across the turf strip."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(74, 47, 62, 1.0)", "secondaryAlbedo": "rgba(60, 37, 50, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_parterre_blocks_84.add(mesh_parterre_blocks_84);
  meshes["parterre-blocks"] = mesh_parterre_blocks_84;
  colliders["parterre-blocks"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["parterre-blocks"] ??= [];
  destructionGroups["parterre-blocks"].push(node_parterre_blocks_84);

  const endpoint_topiary_balls_85 = makeAttachmentEndpoint(null);
  const node_topiary_balls_85 = new THREE.Group();
  node_topiary_balls_85.name = "Topiary balls__pivot";
  node_topiary_balls_85.scale.set(1, 1, 1);
  if (endpoint_topiary_balls_85) {
    node_topiary_balls_85.position.copy(endpoint_topiary_balls_85.start);
    node_topiary_balls_85.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_topiary_balls_85.position.set(8.5, 0.6, -6.5);
    node_topiary_balls_85.rotation.set(0.0, 0.0, 0.0);
  }
  node_topiary_balls_85.userData.sculptComponent = {"id": "topiary-balls", "name": "Topiary balls", "level": "micro", "role": "structure", "importance": 0.3, "confidence": 0.55, "primitive": "sphere", "topologyClass": "assembled-solid", "topologyRationale": "Rounded clipped shrub: a sphere.", "geometryDescriptor": {"topologyIntent": "Round clipped bushes at the pool corners; looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 1.4, "height": 1.4, "depth": 1.4, "units": "relative", "confidence": 0.55}, "transform": {"position": [8.5, 0.6, -6.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.55}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "topiary-balls", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "hedge-purple"}}, "material": "hedge-purple", "materialLayers": ["hedge-purple"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(74, 47, 62, 1.0)", "secondaryAlbedo": "rgba(60, 37, 50, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_topiary_balls_85.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.55}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "topiary-balls", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "hedge-purple"}};
  (nodes["plaza-grounds"] ?? root).add(node_topiary_balls_85);
  nodes["topiary-balls"] = node_topiary_balls_85;
  const mesh_topiary_balls_85Geometry = endpoint_topiary_balls_85
    ? new THREE.CylinderGeometry(endpoint_topiary_balls_85.endRadius, endpoint_topiary_balls_85.baseRadius, endpoint_topiary_balls_85.length, 32, 12)
    : new THREE.SphereGeometry(0.5, 64, 40);
  if (!endpoint_topiary_balls_85) {
    mesh_topiary_balls_85Geometry.scale(1.4, 1.4, 1.4);
  }
  const mesh_topiary_balls_85 = new THREE.Mesh(
    mesh_topiary_balls_85Geometry,
    materialMap["hedge-purple"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_topiary_balls_85.name = "Topiary balls";
  if (endpoint_topiary_balls_85) {
    mesh_topiary_balls_85.position.copy(endpoint_topiary_balls_85.midpoint);
    mesh_topiary_balls_85.quaternion.copy(endpoint_topiary_balls_85.quaternion);
  }
  mesh_topiary_balls_85.castShadow = options.castShadow ?? true;
  mesh_topiary_balls_85.receiveShadow = options.receiveShadow ?? true;
  mesh_topiary_balls_85.userData.sculptComponent = {"id": "topiary-balls", "name": "Topiary balls", "level": "micro", "role": "structure", "importance": 0.3, "confidence": 0.55, "primitive": "sphere", "topologyClass": "assembled-solid", "topologyRationale": "Rounded clipped shrub: a sphere.", "geometryDescriptor": {"topologyIntent": "Round clipped bushes at the pool corners; looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-grounds", "attachment": null, "dimensions": {"width": 1.4, "height": 1.4, "depth": 1.4, "units": "relative", "confidence": 0.55}, "transform": {"position": [8.5, 0.6, -6.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.55}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "topiary-balls", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "hedge-purple"}}, "material": "hedge-purple", "materialLayers": ["hedge-purple"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(74, 47, 62, 1.0)", "secondaryAlbedo": "rgba(60, 37, 50, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_topiary_balls_85.add(mesh_topiary_balls_85);
  meshes["topiary-balls"] = mesh_topiary_balls_85;
  colliders["topiary-balls"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["topiary-balls"] ??= [];
  destructionGroups["topiary-balls"].push(node_topiary_balls_85);

  const endpoint_plaza_pool_86 = makeAttachmentEndpoint(null);
  const node_plaza_pool_86 = new THREE.Group();
  node_plaza_pool_86.name = "Plaza pool__pivot";
  node_plaza_pool_86.scale.set(1, 1, 1);
  if (endpoint_plaza_pool_86) {
    node_plaza_pool_86.position.copy(endpoint_plaza_pool_86.start);
    node_plaza_pool_86.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_plaza_pool_86.position.set(0.0, 0.25, 47.0);
    node_plaza_pool_86.rotation.set(0.0, 0.0, 0.0);
  }
  node_plaza_pool_86.userData.sculptComponent = {"id": "plaza-pool", "name": "Plaza pool", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Big water basin on the axis with scalloped coping and two stepped circular fountains.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 46, "height": 1.0, "depth": 26, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.25, 47], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-pool", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_pool_86.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-pool", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}};
  (nodes["root"] ?? root).add(node_plaza_pool_86);
  nodes["plaza-pool"] = node_plaza_pool_86;
  const mesh_plaza_pool_86Geometry = endpoint_plaza_pool_86
    ? new THREE.CylinderGeometry(endpoint_plaza_pool_86.endRadius, endpoint_plaza_pool_86.baseRadius, endpoint_plaza_pool_86.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_plaza_pool_86) {
    mesh_plaza_pool_86Geometry.scale(46.0, 1.0, 26.0);
  }
  const mesh_plaza_pool_86 = new THREE.Mesh(
    mesh_plaza_pool_86Geometry,
    materialMap["pool-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_plaza_pool_86.name = "Plaza pool";
  if (endpoint_plaza_pool_86) {
    mesh_plaza_pool_86.position.copy(endpoint_plaza_pool_86.midpoint);
    mesh_plaza_pool_86.quaternion.copy(endpoint_plaza_pool_86.quaternion);
  }
  mesh_plaza_pool_86.castShadow = options.castShadow ?? true;
  mesh_plaza_pool_86.receiveShadow = options.receiveShadow ?? true;
  mesh_plaza_pool_86.userData.sculptComponent = {"id": "plaza-pool", "name": "Plaza pool", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Big water basin on the axis with scalloped coping and two stepped circular fountains.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 46, "height": 1.0, "depth": 26, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.25, 47], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-pool", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_pool_86.add(mesh_plaza_pool_86);
  meshes["plaza-pool"] = mesh_plaza_pool_86;
  colliders["plaza-pool"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["plaza-pool"] ??= [];
  destructionGroups["plaza-pool"].push(node_plaza_pool_86);

  const endpoint_pool_basin_87 = makeAttachmentEndpoint(null);
  const node_pool_basin_87 = new THREE.Group();
  node_pool_basin_87.name = "Pool basin__pivot";
  node_pool_basin_87.scale.set(1, 1, 1);
  if (endpoint_pool_basin_87) {
    node_pool_basin_87.position.copy(endpoint_pool_basin_87.start);
    node_pool_basin_87.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pool_basin_87.position.set(0.0, -0.2, 0.0);
    node_pool_basin_87.rotation.set(0.0, 0.0, 0.0);
  }
  node_pool_basin_87.userData.sculptComponent = {"id": "pool-basin", "name": "Pool basin", "level": "meso", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Basin walls and coping; scallop lobes looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-pool", "attachment": null, "dimensions": {"width": 46, "height": 0.9, "depth": 26, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -0.2, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pool-basin", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "scalloped-coping", "description": "Pale coping tracing a scalloped/lobed pool edge with shallow shelf."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_pool_basin_87.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pool-basin", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}};
  (nodes["plaza-pool"] ?? root).add(node_pool_basin_87);
  nodes["pool-basin"] = node_pool_basin_87;
  const mesh_pool_basin_87Geometry = endpoint_pool_basin_87
    ? new THREE.CylinderGeometry(endpoint_pool_basin_87.endRadius, endpoint_pool_basin_87.baseRadius, endpoint_pool_basin_87.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pool_basin_87) {
    mesh_pool_basin_87Geometry.scale(46.0, 0.9, 26.0);
  }
  const mesh_pool_basin_87 = new THREE.Mesh(
    mesh_pool_basin_87Geometry,
    materialMap["pool-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pool_basin_87.name = "Pool basin";
  if (endpoint_pool_basin_87) {
    mesh_pool_basin_87.position.copy(endpoint_pool_basin_87.midpoint);
    mesh_pool_basin_87.quaternion.copy(endpoint_pool_basin_87.quaternion);
  }
  mesh_pool_basin_87.castShadow = options.castShadow ?? true;
  mesh_pool_basin_87.receiveShadow = options.receiveShadow ?? true;
  mesh_pool_basin_87.userData.sculptComponent = {"id": "pool-basin", "name": "Pool basin", "level": "meso", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Basin walls and coping; scallop lobes looped in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-pool", "attachment": null, "dimensions": {"width": 46, "height": 0.9, "depth": 26, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, -0.2, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pool-basin", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "scalloped-coping", "description": "Pale coping tracing a scalloped/lobed pool edge with shallow shelf."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_pool_basin_87.add(mesh_pool_basin_87);
  meshes["pool-basin"] = mesh_pool_basin_87;
  colliders["pool-basin"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pool-basin"] ??= [];
  destructionGroups["pool-basin"].push(node_pool_basin_87);

  const endpoint_pool_water_88 = makeAttachmentEndpoint(null);
  const node_pool_water_88 = new THREE.Group();
  node_pool_water_88.name = "Pool water sheet__pivot";
  node_pool_water_88.scale.set(1, 1, 1);
  if (endpoint_pool_water_88) {
    node_pool_water_88.position.copy(endpoint_pool_water_88.start);
    node_pool_water_88.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pool_water_88.position.set(0.0, 0.17, 0.0);
    node_pool_water_88.rotation.set(0.0, 0.0, 0.0);
  }
  node_pool_water_88.userData.sculptComponent = {"id": "pool-water", "name": "Pool water sheet", "level": "meso", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Water sheet plane inside the basin.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-pool", "attachment": null, "dimensions": {"width": 43.6, "height": 0.12, "depth": 23.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.17, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pool-water", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-water"}}, "material": "pool-water", "materialLayers": ["pool-water"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "specular-sheet", "description": "Glassy turquoise sheet with soft sky sheen, faint ripple and foam rings."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(79, 179, 184, 1.0)", "secondaryAlbedo": "rgba(62, 158, 166, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_pool_water_88.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pool-water", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-water"}};
  (nodes["plaza-pool"] ?? root).add(node_pool_water_88);
  nodes["pool-water"] = node_pool_water_88;
  const mesh_pool_water_88Geometry = endpoint_pool_water_88
    ? new THREE.CylinderGeometry(endpoint_pool_water_88.endRadius, endpoint_pool_water_88.baseRadius, endpoint_pool_water_88.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pool_water_88) {
    mesh_pool_water_88Geometry.scale(43.6, 0.12, 23.6);
  }
  const mesh_pool_water_88 = new THREE.Mesh(
    mesh_pool_water_88Geometry,
    materialMap["pool-water"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pool_water_88.name = "Pool water sheet";
  if (endpoint_pool_water_88) {
    mesh_pool_water_88.position.copy(endpoint_pool_water_88.midpoint);
    mesh_pool_water_88.quaternion.copy(endpoint_pool_water_88.quaternion);
  }
  mesh_pool_water_88.castShadow = options.castShadow ?? true;
  mesh_pool_water_88.receiveShadow = options.receiveShadow ?? true;
  mesh_pool_water_88.userData.sculptComponent = {"id": "pool-water", "name": "Pool water sheet", "level": "meso", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Water sheet plane inside the basin.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "plaza-pool", "attachment": null, "dimensions": {"width": 43.6, "height": 0.12, "depth": 23.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.17, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pool-water", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-water"}}, "material": "pool-water", "materialLayers": ["pool-water"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "specular-sheet", "description": "Glassy turquoise sheet with soft sky sheen, faint ripple and foam rings."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(79, 179, 184, 1.0)", "secondaryAlbedo": "rgba(62, 158, 166, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_pool_water_88.add(mesh_pool_water_88);
  meshes["pool-water"] = mesh_pool_water_88;
  colliders["pool-water"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pool-water"] ??= [];
  destructionGroups["pool-water"].push(node_pool_water_88);

  const endpoint_fountain_a_89 = makeAttachmentEndpoint(null);
  const node_fountain_a_89 = new THREE.Group();
  node_fountain_a_89.name = "Fountain (a)__pivot";
  node_fountain_a_89.scale.set(1, 1, 1);
  if (endpoint_fountain_a_89) {
    node_fountain_a_89.position.copy(endpoint_fountain_a_89.start);
    node_fountain_a_89.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_fountain_a_89.position.set(0.0, 0.25, -5.5);
    node_fountain_a_89.rotation.set(0.0, 0.0, 0.0);
  }
  node_fountain_a_89.userData.sculptComponent = {"id": "fountain-a", "name": "Fountain (a)", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "lathe", "topologyClass": "continuous-sculpt", "topologyRationale": "Stepped circular pedestal: revolved profile, lathe.", "geometryDescriptor": {"topologyIntent": "Stepped fountain pedestal; polished ring edges catch light against the water.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.0, 0.0], [0.46, 0.0], [0.46, 0.16], [0.38, 0.16], [0.38, 0.38], [0.3, 0.38], [0.3, 0.6], [0.22, 0.6], [0.22, 0.84], [0.12, 0.84], [0.12, 1.0], [0.0, 1.0]], "segments": 40}}, "parent": "plaza-pool", "attachment": null, "dimensions": {"width": 9.2, "height": 1.5, "depth": 9.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.25, -5.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "fountain-a", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "step-rings", "description": "Stacked pale stone rings (three steps) around a low centre."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_fountain_a_89.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "fountain-a", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}};
  (nodes["plaza-pool"] ?? root).add(node_fountain_a_89);
  nodes["fountain-a"] = node_fountain_a_89;
  const mesh_fountain_a_89Geometry = endpoint_fountain_a_89
    ? new THREE.CylinderGeometry(endpoint_fountain_a_89.endRadius, endpoint_fountain_a_89.baseRadius, endpoint_fountain_a_89.length, 32, 12)
    : buildLatheGeometry({"points": [[0.0, 0.0], [0.46, 0.0], [0.46, 0.16], [0.38, 0.16], [0.38, 0.38], [0.3, 0.38], [0.3, 0.6], [0.22, 0.6], [0.22, 0.84], [0.12, 0.84], [0.12, 1.0], [0.0, 1.0]], "segments": 40});
  if (!endpoint_fountain_a_89) {
    mesh_fountain_a_89Geometry.scale(9.2, 1.5, 9.2);
  }
  const mesh_fountain_a_89 = new THREE.Mesh(
    mesh_fountain_a_89Geometry,
    materialMap["pool-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_fountain_a_89.name = "Fountain (a)";
  if (endpoint_fountain_a_89) {
    mesh_fountain_a_89.position.copy(endpoint_fountain_a_89.midpoint);
    mesh_fountain_a_89.quaternion.copy(endpoint_fountain_a_89.quaternion);
  }
  mesh_fountain_a_89.castShadow = options.castShadow ?? true;
  mesh_fountain_a_89.receiveShadow = options.receiveShadow ?? true;
  mesh_fountain_a_89.userData.sculptComponent = {"id": "fountain-a", "name": "Fountain (a)", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "lathe", "topologyClass": "continuous-sculpt", "topologyRationale": "Stepped circular pedestal: revolved profile, lathe.", "geometryDescriptor": {"topologyIntent": "Stepped fountain pedestal; polished ring edges catch light against the water.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.0, 0.0], [0.46, 0.0], [0.46, 0.16], [0.38, 0.16], [0.38, 0.38], [0.3, 0.38], [0.3, 0.6], [0.22, 0.6], [0.22, 0.84], [0.12, 0.84], [0.12, 1.0], [0.0, 1.0]], "segments": 40}}, "parent": "plaza-pool", "attachment": null, "dimensions": {"width": 9.2, "height": 1.5, "depth": 9.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.25, -5.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "fountain-a", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "step-rings", "description": "Stacked pale stone rings (three steps) around a low centre."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_fountain_a_89.add(mesh_fountain_a_89);
  meshes["fountain-a"] = mesh_fountain_a_89;
  colliders["fountain-a"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["fountain-a"] ??= [];
  destructionGroups["fountain-a"].push(node_fountain_a_89);

  const endpoint_fountain_b_90 = makeAttachmentEndpoint(null);
  const node_fountain_b_90 = new THREE.Group();
  node_fountain_b_90.name = "Fountain (b)__pivot";
  node_fountain_b_90.scale.set(1, 1, 1);
  if (endpoint_fountain_b_90) {
    node_fountain_b_90.position.copy(endpoint_fountain_b_90.start);
    node_fountain_b_90.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_fountain_b_90.position.set(0.0, 0.25, 5.5);
    node_fountain_b_90.rotation.set(0.0, 0.0, 0.0);
  }
  node_fountain_b_90.userData.sculptComponent = {"id": "fountain-b", "name": "Fountain (b)", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "lathe", "topologyClass": "continuous-sculpt", "topologyRationale": "Stepped circular pedestal: revolved profile, lathe.", "geometryDescriptor": {"topologyIntent": "Stepped fountain pedestal; polished ring edges catch light against the water.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.0, 0.0], [0.46, 0.0], [0.46, 0.16], [0.38, 0.16], [0.38, 0.38], [0.3, 0.38], [0.3, 0.6], [0.22, 0.6], [0.22, 0.84], [0.12, 0.84], [0.12, 1.0], [0.0, 1.0]], "segments": 40}}, "parent": "plaza-pool", "attachment": null, "dimensions": {"width": 9.2, "height": 1.5, "depth": 9.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.25, 5.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "fountain-b", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "step-rings", "description": "Stacked pale stone rings (three steps) around a low centre."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_fountain_b_90.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "fountain-b", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}};
  (nodes["plaza-pool"] ?? root).add(node_fountain_b_90);
  nodes["fountain-b"] = node_fountain_b_90;
  const mesh_fountain_b_90Geometry = endpoint_fountain_b_90
    ? new THREE.CylinderGeometry(endpoint_fountain_b_90.endRadius, endpoint_fountain_b_90.baseRadius, endpoint_fountain_b_90.length, 32, 12)
    : buildLatheGeometry({"points": [[0.0, 0.0], [0.46, 0.0], [0.46, 0.16], [0.38, 0.16], [0.38, 0.38], [0.3, 0.38], [0.3, 0.6], [0.22, 0.6], [0.22, 0.84], [0.12, 0.84], [0.12, 1.0], [0.0, 1.0]], "segments": 40});
  if (!endpoint_fountain_b_90) {
    mesh_fountain_b_90Geometry.scale(9.2, 1.5, 9.2);
  }
  const mesh_fountain_b_90 = new THREE.Mesh(
    mesh_fountain_b_90Geometry,
    materialMap["pool-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_fountain_b_90.name = "Fountain (b)";
  if (endpoint_fountain_b_90) {
    mesh_fountain_b_90.position.copy(endpoint_fountain_b_90.midpoint);
    mesh_fountain_b_90.quaternion.copy(endpoint_fountain_b_90.quaternion);
  }
  mesh_fountain_b_90.castShadow = options.castShadow ?? true;
  mesh_fountain_b_90.receiveShadow = options.receiveShadow ?? true;
  mesh_fountain_b_90.userData.sculptComponent = {"id": "fountain-b", "name": "Fountain (b)", "level": "meso", "role": "structure", "importance": 0.7, "confidence": 0.8, "primitive": "lathe", "topologyClass": "continuous-sculpt", "topologyRationale": "Stepped circular pedestal: revolved profile, lathe.", "geometryDescriptor": {"topologyIntent": "Stepped fountain pedestal; polished ring edges catch light against the water.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry", "latheProfile": {"points": [[0.0, 0.0], [0.46, 0.0], [0.46, 0.16], [0.38, 0.16], [0.38, 0.38], [0.3, 0.38], [0.3, 0.6], [0.22, 0.6], [0.22, 0.84], [0.12, 0.84], [0.12, 1.0], [0.0, 1.0]], "segments": 40}}, "parent": "plaza-pool", "attachment": null, "dimensions": {"width": 9.2, "height": 1.5, "depth": 9.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.25, 5.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "fountain-b", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [{"id": "step-rings", "description": "Stacked pale stone rings (three steps) around a low centre."}], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_fountain_b_90.add(mesh_fountain_b_90);
  meshes["fountain-b"] = mesh_fountain_b_90;
  colliders["fountain-b"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["fountain-b"] ??= [];
  destructionGroups["fountain-b"].push(node_fountain_b_90);

  const endpoint_tree_rows_91 = makeAttachmentEndpoint(null);
  const node_tree_rows_91 = new THREE.Group();
  node_tree_rows_91.name = "Plaza tree rows (container)__pivot";
  node_tree_rows_91.scale.set(1, 1, 1);
  if (endpoint_tree_rows_91) {
    node_tree_rows_91.position.copy(endpoint_tree_rows_91.start);
    node_tree_rows_91.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tree_rows_91.position.set(0.0, 0.0, 0.0);
    node_tree_rows_91.rotation.set(0.0, 0.0, 0.0);
  }
  node_tree_rows_91.userData.sculptComponent = {"id": "tree-rows", "name": "Plaza tree rows (container)", "level": "macro", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hidden container for the two tree rows (real trees are the meso children, looped in code).", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 1, "height": 1, "depth": 1, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-rows", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "invisible-root"}}, "material": "invisible-root", "materialLayers": ["invisible-root"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q", "zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(110, 103, 89, 1.0)", "secondaryAlbedo": "rgba(95, 89, 76, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_tree_rows_91.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-rows", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "invisible-root"}};
  (nodes["root"] ?? root).add(node_tree_rows_91);
  nodes["tree-rows"] = node_tree_rows_91;
  const mesh_tree_rows_91Geometry = endpoint_tree_rows_91
    ? new THREE.CylinderGeometry(endpoint_tree_rows_91.endRadius, endpoint_tree_rows_91.baseRadius, endpoint_tree_rows_91.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tree_rows_91) {
    mesh_tree_rows_91Geometry.scale(1.0, 1.0, 1.0);
  }
  const mesh_tree_rows_91 = new THREE.Mesh(
    mesh_tree_rows_91Geometry,
    materialMap["invisible-root"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tree_rows_91.name = "Plaza tree rows (container)";
  if (endpoint_tree_rows_91) {
    mesh_tree_rows_91.position.copy(endpoint_tree_rows_91.midpoint);
    mesh_tree_rows_91.quaternion.copy(endpoint_tree_rows_91.quaternion);
  }
  mesh_tree_rows_91.castShadow = options.castShadow ?? true;
  mesh_tree_rows_91.receiveShadow = options.receiveShadow ?? true;
  mesh_tree_rows_91.userData.sculptComponent = {"id": "tree-rows", "name": "Plaza tree rows (container)", "level": "macro", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Hidden container for the two tree rows (real trees are the meso children, looped in code).", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 1, "height": 1, "depth": 1, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0, 0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-rows", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "invisible-root"}}, "material": "invisible-root", "materialLayers": ["invisible-root"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q", "zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(110, 103, 89, 1.0)", "secondaryAlbedo": "rgba(95, 89, 76, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_tree_rows_91.add(mesh_tree_rows_91);
  meshes["tree-rows"] = mesh_tree_rows_91;
  colliders["tree-rows"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tree-rows"] ??= [];
  destructionGroups["tree-rows"].push(node_tree_rows_91);

  const endpoint_tree_row_west_92 = makeAttachmentEndpoint(null);
  const node_tree_row_west_92 = new THREE.Group();
  node_tree_row_west_92.name = "Tree row (west)__pivot";
  node_tree_row_west_92.scale.set(1, 1, 1);
  if (endpoint_tree_row_west_92) {
    node_tree_row_west_92.position.copy(endpoint_tree_row_west_92.start);
    node_tree_row_west_92.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tree_row_west_92.position.set(-15.5, 7.0, 35.0);
    node_tree_row_west_92.rotation.set(0.0, 0.0, 0.0);
  }
  node_tree_row_west_92.userData.sculptComponent = {"id": "tree-row-west", "name": "Tree row (west)", "level": "meso", "role": "structure", "importance": 0.55, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "One row of plane trees with pale trunks and round crowns; instanced loop in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tree-rows", "attachment": null, "dimensions": {"width": 6, "height": 14, "depth": 46, "units": "relative", "confidence": 0.8}, "transform": {"position": [-15.5, 7.0, 35], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-row-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_tree_row_west_92.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-row-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}};
  (nodes["tree-rows"] ?? root).add(node_tree_row_west_92);
  nodes["tree-row-west"] = node_tree_row_west_92;
  const mesh_tree_row_west_92Geometry = endpoint_tree_row_west_92
    ? new THREE.CylinderGeometry(endpoint_tree_row_west_92.endRadius, endpoint_tree_row_west_92.baseRadius, endpoint_tree_row_west_92.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tree_row_west_92) {
    mesh_tree_row_west_92Geometry.scale(6.0, 14.0, 46.0);
  }
  const mesh_tree_row_west_92 = new THREE.Mesh(
    mesh_tree_row_west_92Geometry,
    materialMap["foliage-green"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tree_row_west_92.name = "Tree row (west)";
  if (endpoint_tree_row_west_92) {
    mesh_tree_row_west_92.position.copy(endpoint_tree_row_west_92.midpoint);
    mesh_tree_row_west_92.quaternion.copy(endpoint_tree_row_west_92.quaternion);
  }
  mesh_tree_row_west_92.castShadow = options.castShadow ?? true;
  mesh_tree_row_west_92.receiveShadow = options.receiveShadow ?? true;
  mesh_tree_row_west_92.userData.sculptComponent = {"id": "tree-row-west", "name": "Tree row (west)", "level": "meso", "role": "structure", "importance": 0.55, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "One row of plane trees with pale trunks and round crowns; instanced loop in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tree-rows", "attachment": null, "dimensions": {"width": 6, "height": 14, "depth": 46, "units": "relative", "confidence": 0.8}, "transform": {"position": [-15.5, 7.0, 35], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-row-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_tree_row_west_92.add(mesh_tree_row_west_92);
  meshes["tree-row-west"] = mesh_tree_row_west_92;
  colliders["tree-row-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tree-row-west"] ??= [];
  destructionGroups["tree-row-west"].push(node_tree_row_west_92);

  const endpoint_tree_row_east_93 = makeAttachmentEndpoint(null);
  const node_tree_row_east_93 = new THREE.Group();
  node_tree_row_east_93.name = "Tree row (east)__pivot";
  node_tree_row_east_93.scale.set(1, 1, 1);
  if (endpoint_tree_row_east_93) {
    node_tree_row_east_93.position.copy(endpoint_tree_row_east_93.start);
    node_tree_row_east_93.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tree_row_east_93.position.set(15.5, 7.0, 35.0);
    node_tree_row_east_93.rotation.set(0.0, 0.0, 0.0);
  }
  node_tree_row_east_93.userData.sculptComponent = {"id": "tree-row-east", "name": "Tree row (east)", "level": "meso", "role": "structure", "importance": 0.55, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "One row of plane trees with pale trunks and round crowns; instanced loop in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tree-rows", "attachment": null, "dimensions": {"width": 6, "height": 14, "depth": 46, "units": "relative", "confidence": 0.8}, "transform": {"position": [15.5, 7.0, 35], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-row-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_tree_row_east_93.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-row-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}};
  (nodes["tree-rows"] ?? root).add(node_tree_row_east_93);
  nodes["tree-row-east"] = node_tree_row_east_93;
  const mesh_tree_row_east_93Geometry = endpoint_tree_row_east_93
    ? new THREE.CylinderGeometry(endpoint_tree_row_east_93.endRadius, endpoint_tree_row_east_93.baseRadius, endpoint_tree_row_east_93.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tree_row_east_93) {
    mesh_tree_row_east_93Geometry.scale(6.0, 14.0, 46.0);
  }
  const mesh_tree_row_east_93 = new THREE.Mesh(
    mesh_tree_row_east_93Geometry,
    materialMap["foliage-green"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tree_row_east_93.name = "Tree row (east)";
  if (endpoint_tree_row_east_93) {
    mesh_tree_row_east_93.position.copy(endpoint_tree_row_east_93.midpoint);
    mesh_tree_row_east_93.quaternion.copy(endpoint_tree_row_east_93.quaternion);
  }
  mesh_tree_row_east_93.castShadow = options.castShadow ?? true;
  mesh_tree_row_east_93.receiveShadow = options.receiveShadow ?? true;
  mesh_tree_row_east_93.userData.sculptComponent = {"id": "tree-row-east", "name": "Tree row (east)", "level": "meso", "role": "structure", "importance": 0.55, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "One row of plane trees with pale trunks and round crowns; instanced loop in code.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "tree-rows", "attachment": null, "dimensions": {"width": 6, "height": 14, "depth": 46, "units": "relative", "confidence": 0.8}, "transform": {"position": [15.5, 7.0, 35], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-row-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q"], "details": [], "fidelityTier": "structure", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_tree_row_east_93.add(mesh_tree_row_east_93);
  meshes["tree-row-east"] = mesh_tree_row_east_93;
  colliders["tree-row-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tree-row-east"] ??= [];
  destructionGroups["tree-row-east"].push(node_tree_row_east_93);

  // repetition system: drum-mullions (InstancedMesh, radial, count=28, level=micro)
  {
    const parent = nodes["dome-drum"] ?? root;
    const geo = new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
    const mat = materialMap["dome-frame"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 });
    // Contract (PLAN_1.5 WS-E): instanceScale is ABSOLUTE, in the parent pivot's
    // local units -- it is never multiplied by the parent component's own declared
    // dimensional scale. This falls out of the same fix as componentTree: the pivot
    // Group this cluster is parented to always carries identity scale (dimensions are
    // baked into that component's OWN geometry, not exposed on the Group), so an
    // instanced fastener/tooth/spoke sized [0.05, 0.05, 0.05] renders at exactly that
    // size regardless of how non-uniformly its host component is shaped, and a
    // `radial` ring's placement stays circular instead of being squashed into an
    // ellipse by a non-uniform host.
    const scl = [0.16, 1.15, 0.1];
    const axis = new THREE.Vector3(0.0, 1.0, 0.0).normalize();
    const radius = 11.25;
    const seed = Math.abs(axis.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0);
    const perp = new THREE.Vector3().crossVectors(axis, seed).normalize();
    // One InstancedMesh = one draw call for all repeated parts (teeth/fasteners/spokes),
    // replacing the former per-instance Mesh clone loop (real-time perf principle).
    const cluster = new THREE.InstancedMesh(geo, mat, 28);
    const _m = new THREE.Matrix4();
    const _p = new THREE.Vector3();
    const _q = new THREE.Quaternion();
    const _s = new THREE.Vector3(scl[0], scl[1], scl[2]);
    for (let i = 0; i < 28; i++) {
      const ang = ((0.0) + (i * 360) / 28) * Math.PI / 180;
      const dir = perp.clone().applyQuaternion(new THREE.Quaternion().setFromAxisAngle(axis, ang));
      _p.copy(radius > 0 ? dir.clone().multiplyScalar(radius * 0.5) : new THREE.Vector3());
      _q.setFromUnitVectors(new THREE.Vector3(1, 0, 0), dir);
      _m.compose(_p, _q, _s);
      cluster.setMatrixAt(i, _m);
    }
    cluster.instanceMatrix.needsUpdate = true;
    cluster.castShadow = options.castShadow ?? true;
    cluster.receiveShadow = options.receiveShadow ?? true;
    cluster.name = "drum-mullions";
    parent.add(cluster);
  }
  // repetition system "west-window-grid" describes 1 parts that are already built individually; not instanced.
  // repetition system "east-window-grid" describes 1 parts that are already built individually; not instanced.
  // repetition system "colonnade-columns" describes 1 parts that are already built individually; not instanced.
  // repetition system "parterre-hedges" describes 1 parts that are already built individually; not instanced.
  // repetition system "tree-rows-system" describes 2 parts that are already built individually; not instanced.
  // repetition system "tower-baluster-rows" describes 2 parts that are already built individually; not instanced.

  root.userData.sculptRuntime = { nodes, meshes, sockets, colliders, destructionGroups } satisfies ProceduralModelRuntime;
  root.userData.lookDevTargets = {"qualityPriority": "reference-fidelity", "materialPass": {"albedoPaletteRequired": true, "roughnessVariationRequired": true, "normalOrBumpRequired": true, "localOverridesRequired": true, "minimumTextureResolution": 1024, "preferredTextureResolution": 2048, "independentMapChannels": ["albedo", "roughness", "height", "normal", "ambient-occlusion"], "requiredSurfaceFrequencyBands": ["macro", "meso", "micro"], "geometryReliefRequiredWhenSilhouetteAffected": true, "referencePbrExtraction": {"requiredWhenSourceImagePresent": true, "targetThreshold": 0.7, "stopOnLowConfidence": true, "script": "forge/stage1_intake/extract_pbr_evidence.py", "acceptedLimitation": "single-image extraction is reference-derived inference, not exact photogrammetry"}, "mustAvoid": ["single flat albedo per material", "uniform roughness", "albedo texture reused as roughness/height/normal/AO", "single-frequency random noise", "plastic-looking smooth bark, stone, cloth, foliage, or aged material", "local color/detail described only in prose without material masks", "claiming exact PBR recovery when confidence is below the target threshold"]}, "lightingPass": {"requiredTerms": ["key light", "fill light", "rim or environment light", "exposure", "tone mapping", "background", "contact shadow"], "mustAvoid": ["ambient-only lighting", "flat value range", "missing contact shadow", "reference lighting copied without separating material readability"]}, "screenshotReview": ["Compare albedo palette and local color zones.", "Compare roughness/normal/bump response under light.", "Compare cavity dirt, edge wear, stains, moss, scratches, or other local masks.", "Compare key/fill/rim structure, exposure, tone mapping, background, and contact shadows.", "Capture a neutral-light render to verify material readability without reference lighting.", "Capture a grazing-light close-up to expose flat normals, uniform roughness, tiling, and plastic highlights.", "Capture a reference-matched render from the same camera framing as the source."]};
  root.userData.actionReadiness = {
    note: 'Use root.userData.sculptRuntime.nodes for transforms, sockets for attachments, colliders for physics proxies, and destructionGroups for breakable sets.',
  };
// [apply_refine] refinement layer applied
  refineYNULibraryModel(root, root.userData.sculptRuntime as ProceduralModelRuntime);

  return root;
}

export function createYNULibraryLookDevLights(
  mode: 'neutral' | 'grazing' | 'reference' = 'neutral',
): THREE.Group {
  const lights = new THREE.Group();
  lights.name = "YNU Library look-dev lights";
  const hemi = new THREE.HemisphereLight(
    mode === 'reference' ? 0xfff0d6 : 0xf2f4ff,
    0x363b42,
    mode === 'grazing' ? 0.28 : mode === 'reference' ? 0.72 : 0.85,
  );
  lights.add(hemi);
  const key = new THREE.DirectionalLight(
    mode === 'reference' ? 0xffcf8a : 0xfff4e8,
    mode === 'grazing' ? 4.2 : mode === 'reference' ? 2.6 : 2.15,
  );
  if (mode === 'grazing') key.position.set(7.5, 1.1, 4.0);
  else if (mode === 'reference') key.position.set(-4.5, 7.5, 5.0);
  else key.position.set(-4.0, 6.0, 5.5);
  key.castShadow = true;
  key.shadow.mapSize.set(4096, 4096);
  key.shadow.bias = -0.00025;
  key.shadow.normalBias = 0.018;
  key.shadow.radius = 7;
  key.shadow.blurSamples = 24;
  key.shadow.camera.near = 0.5;
  key.shadow.camera.far = 30;
  key.shadow.camera.left = -2.6;
  key.shadow.camera.right = 2.6;
  key.shadow.camera.top = 2.6;
  key.shadow.camera.bottom = -2.6;
  key.shadow.camera.updateProjectionMatrix();
  lights.add(key);
  const fill = new THREE.DirectionalLight(0xa8c4ff, mode === 'grazing' ? 0.12 : 0.42);
  fill.position.set(4.0, 3.0, 3.5);
  lights.add(fill);
  const rim = new THREE.DirectionalLight(0xfff1c4, mode === 'grazing' ? 0.28 : 0.85);
  rim.position.set(0.5, 4.5, -6.0);
  lights.add(rim);
  lights.userData.reviewMode = mode;
  lights.userData.lightingFromPhoto = ["key light: warm low sun from the front-west quarter (ref-01 golden hour); color #FFD9A0, relative intensity 2.6; in the neutral preview a high sun at (-70, 80, 60) aims at the plaza axis", "fill light: cool sky dome fill (hemisphere), color #BFD4E8 over ground #3A3A3A, relative intensity 0.55", "rim or environment light: soft sky environment reflection for the glazing and dome (RoomEnvironment via PMREM), envMapIntensity 0.8; weak warm back rim at (10, 45, -90)", "exposure and tone mapping: ACESFilmic tone mapping, exposure 1.0, background gradient from pale blue zenith to warm horizon haze", "contact shadow: PCFSoft directional shadow at ~35 deg sun elevation, 4096 map; ground contact shadows under trees, halls, towers and pool coping; per-material AO darkens seams and recesses", "reference note: ref-03 is high noon (hard cold key, deep blue sky) while ref-01/ref-04 are golden hour; previews standardize on a late-afternoon warm key for comparison against ref-01/ref-03"];
  lights.userData.lookDevTargets = {"qualityPriority": "reference-fidelity", "materialPass": {"albedoPaletteRequired": true, "roughnessVariationRequired": true, "normalOrBumpRequired": true, "localOverridesRequired": true, "minimumTextureResolution": 1024, "preferredTextureResolution": 2048, "independentMapChannels": ["albedo", "roughness", "height", "normal", "ambient-occlusion"], "requiredSurfaceFrequencyBands": ["macro", "meso", "micro"], "geometryReliefRequiredWhenSilhouetteAffected": true, "referencePbrExtraction": {"requiredWhenSourceImagePresent": true, "targetThreshold": 0.7, "stopOnLowConfidence": true, "script": "forge/stage1_intake/extract_pbr_evidence.py", "acceptedLimitation": "single-image extraction is reference-derived inference, not exact photogrammetry"}, "mustAvoid": ["single flat albedo per material", "uniform roughness", "albedo texture reused as roughness/height/normal/AO", "single-frequency random noise", "plastic-looking smooth bark, stone, cloth, foliage, or aged material", "local color/detail described only in prose without material masks", "claiming exact PBR recovery when confidence is below the target threshold"]}, "lightingPass": {"requiredTerms": ["key light", "fill light", "rim or environment light", "exposure", "tone mapping", "background", "contact shadow"], "mustAvoid": ["ambient-only lighting", "flat value range", "missing contact shadow", "reference lighting copied without separating material readability"]}, "screenshotReview": ["Compare albedo palette and local color zones.", "Compare roughness/normal/bump response under light.", "Compare cavity dirt, edge wear, stains, moss, scratches, or other local masks.", "Compare key/fill/rim structure, exposure, tone mapping, background, and contact shadows.", "Capture a neutral-light render to verify material readability without reference lighting.", "Capture a grazing-light close-up to expose flat normals, uniform roughness, tiling, and plastic highlights.", "Capture a reference-matched render from the same camera framing as the source."]};
  return lights;
}

// PBR materials (clearcoat/iridescence/transmission/anisotropy) need an environment
// map to visually behave as intended — call this once per renderer and assign the
// result to scene.environment before rendering. No external HDR asset required.
export function createYNULibraryEnvironment(renderer: THREE.WebGLRenderer): THREE.Texture {
  const pmrem = new THREE.PMREMGenerator(renderer);
  const texture = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  return texture;
}

// Plan 1.3 §3.2 — auto-framing by bounding box. The Divine Eye can only compare a
// render to the reference if the object is FRAMED consistently (an object framed
// differently scores as wrong even when its shape is right). This positions the camera
// deterministically from the object's bounding box so it fills the frame at a stable
// margin, and sets near/far to the object scale. Call after adding the model to the
// scene, and again on resize (after updating camera.aspect).
export function frameYNULibraryCamera(
  camera: THREE.PerspectiveCamera,
  object: THREE.Object3D,
  options: { margin?: number; azimuthDeg?: number; elevationDeg?: number } = {},
): void {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const margin = options.margin ?? 1.15;
  const maxDim = Math.max(size.x, size.y, size.z) * margin;
  const fov = (camera.fov * Math.PI) / 180;
  // distance so the largest object dimension fits vertically in the frame
  const distance = (maxDim / 2) / Math.tan(fov / 2);
  const az = ((options.azimuthDeg ?? 0) * Math.PI) / 180;
  const el = ((options.elevationDeg ?? 0) * Math.PI) / 180;
  const dir = new THREE.Vector3(
    Math.sin(az) * Math.cos(el),
    Math.sin(el),
    Math.cos(az) * Math.cos(el),
  );
  camera.position.copy(center).addScaledVector(dir, distance);
  camera.near = Math.max(0.01, distance - maxDim);
  camera.far = distance + maxDim * 2;
  camera.lookAt(center);
  camera.updateProjectionMatrix();
}

// Plan 1.3 §3.2c — PRESENTATION composer (DOF + bloom). CRITICAL (R-POSTFX): this is
// for the showcase/hero render ONLY. The Divine Eye's EVALUATION render MUST use a
// plain renderer with NO composer — bloom blows highlights and DOF blurs edges, which
// would corrupt the deterministic IoU/DCD/edge/blowout signals. Enable dof/bloom ONLY
// when the reference photo actually exhibits them (detect_reference_effects.py authorizes).
export function createYNULibraryPresentationComposer(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  camera: THREE.Camera,
  options: { dof?: boolean; bloom?: boolean; bloomStrength?: number; dofFocus?: number; dofAperture?: number } = {},
): EffectComposer {
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  if (options.dof) {
    composer.addPass(new BokehPass(scene, camera, {
      focus: options.dofFocus ?? 10.0,
      aperture: options.dofAperture ?? 0.0002,
      maxblur: 0.01,
    }));
  }
  if (options.bloom) {
    const size = new THREE.Vector2();
    renderer.getSize(size);
    composer.addPass(new UnrealBloomPass(size, options.bloomStrength ?? 0.4, 0.4, 0.85));
  }
  return composer;
}

export function configureYNULibraryRenderer(renderer: THREE.WebGLRenderer): void {
  // Load-bearing for view-dependent finishes (anodized / Doppler): without ACES + sRGB
  // the environment reflection reads flat/washed instead of a believable metal response.
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
}

export function createYNULibraryInspectControls(
  camera: THREE.Camera,
  domElement: HTMLElement,
): OrbitControls {
  // View-dependent finishes only read correctly once the user orbits — their color
  // comes from the environment reflection, not albedo, so free rotation matters here.
  const controls = new OrbitControls(camera, domElement);
  controls.enableDamping = true;
  controls.minDistance = 1.0;
  controls.maxDistance = 8.0;
  controls.autoRotate = false;
  return controls;
}

import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { BokehPass } from 'three/examples/jsm/postprocessing/BokehPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

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
// Sculpt build pass: blockout
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
    {"id": "stone-olive", "name": "Olive stone pier and column", "type": "standard", "shaderModel": "MeshPhysicalMaterial / PBR approximation", "baseColor": "#B3A67E", "color": "#B3A67E", "albedo": {"dominant": "#B3A67E", "secondary": ["#A49772", "#C2B58C"], "samplingNotes": "Olive-tan portico columns and loggia piers; slight sheen on the sunlit face."}, "colorVariation": {"palette": ["#B3A67E", "#A49772", "#C2B58C"], "pattern": "even", "amplitude": 0.08, "heightCorrelation": 0.2}, "textureResolution": 1024, "textureProjection": {"mode": "uv", "repeat": [3.0, 3.0], "anisotropy": 8, "texelDensityIntent": "stable world-scale detail; no stretching with component scale"}, "surfaceFrequencyBands": [{"id": "macro", "frequency": 2.0, "amplitude": 0.3, "role": "broad tone breakup"}, {"id": "meso", "frequency": 12.0, "amplitude": 0.16, "role": "visible relief: courses, grain, ribs"}, {"id": "micro", "frequency": 56.0, "amplitude": 0.06, "role": "highlight breakup at grazing light"}], "roughness": {"base": 0.72, "variation": 0.13, "map": "independent-procedural-field", "localResponse": "slightly higher roughness in cavities; lower on worn/polished edges"}, "metalness": {"base": 0.0, "variation": 0.0}, "normal": {"pattern": "derived-from-independent-height-field", "strength": 0.3, "scale": 20.0, "space": "tangent"}, "bump": {"pattern": "procedural-noise", "amplitude": 0.04, "scale": 1.0}, "displacement": {"pattern": "none", "amplitude": 0.0, "scale": 1.0, "silhouetteAffects": false}, "ambientOcclusion": {"cavityStrength": 0.28, "contactShadowBias": 0.4, "notes": "darken seams and recesses"}, "wear": {"edgeWear": 0.05, "scratches": [], "chips": []}, "dirt": {"amount": 0.05, "cavityBias": 0.6, "color": "#3A322A"}, "localOverrides": [], "shaderNotes": ["Generate albedo, roughness, height/normal, and AO independently; never alias albedo into roughness.", "Reference-derived scalars carried from the four supplied views; runtime maps are procedural canvases."], "notes": "Olive-tan portico columns and loggia piers; slight sheen on the sunlit face.", "referencePbr": {"usable": true, "confidence": 0.86, "estimatedFidelity": 0.86, "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py", "sourceCrop": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\crops\\stone-olive.png", "palette": ["#06181C", "#02090B", "#202F30", "#706152", "#D0AC96"], "maps": {"albedo": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_albedo.png", "url": "/material-evidence/stone-olive/stone-olive_albedo.png", "channel": "albedo", "source": "reference-pixel-extraction"}, "roughness": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_roughness.png", "url": "/material-evidence/stone-olive/stone-olive_roughness.png", "channel": "roughness", "source": "reference-pixel-extraction"}, "height": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_height.png", "url": "/material-evidence/stone-olive/stone-olive_height.png", "channel": "height", "source": "reference-pixel-extraction"}, "normal": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_normal.png", "url": "/material-evidence/stone-olive/stone-olive_normal.png", "channel": "normal", "source": "reference-pixel-extraction"}, "ao": {"path": "C:\\Users\\damn\\Desktop\\首届高校图书馆\\wenheng\\recon\\yunnan-library\\material-evidence\\stone-olive\\stone-olive_ao.png", "url": "/material-evidence/stone-olive/stone-olive_ao.png", "channel": "ao", "source": "reference-pixel-extraction"}}, "diagnostics": {"roughnessBase": 0.686, "roughnessVariation": 0.05, "normalStrength": 0.178}, "limitation": "single-image PBR extraction is an estimate; 70%+ extraction confidence still needs render screenshot review"}},
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

  const endpoint_central_block_2 = makeAttachmentEndpoint(null);
  const node_central_block_2 = new THREE.Group();
  node_central_block_2.name = "Central block__pivot";
  node_central_block_2.scale.set(1, 1, 1);
  if (endpoint_central_block_2) {
    node_central_block_2.position.copy(endpoint_central_block_2.start);
    node_central_block_2.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_central_block_2.position.set(0.0, 17.7, -17.0);
    node_central_block_2.rotation.set(0.0, 0.0, 0.0);
  }
  node_central_block_2.userData.sculptComponent = {"id": "central-block", "name": "Central block", "level": "macro", "role": "structure", "importance": 1.0, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Tall central mass carrying the glazed loggia, attic band and the dome; front face on the z=0 plane.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 42, "height": 30.6, "depth": 34, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 17.7, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-block", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:close-aerial"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_central_block_2.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-block", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_central_block_2);
  nodes["central-block"] = node_central_block_2;
  const mesh_central_block_2Geometry = endpoint_central_block_2
    ? new THREE.CylinderGeometry(endpoint_central_block_2.endRadius, endpoint_central_block_2.baseRadius, endpoint_central_block_2.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_central_block_2) {
    mesh_central_block_2Geometry.scale(42.0, 30.6, 34.0);
  }
  const mesh_central_block_2 = new THREE.Mesh(
    mesh_central_block_2Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_central_block_2.name = "Central block";
  if (endpoint_central_block_2) {
    mesh_central_block_2.position.copy(endpoint_central_block_2.midpoint);
    mesh_central_block_2.quaternion.copy(endpoint_central_block_2.quaternion);
  }
  mesh_central_block_2.castShadow = options.castShadow ?? true;
  mesh_central_block_2.receiveShadow = options.receiveShadow ?? true;
  mesh_central_block_2.userData.sculptComponent = {"id": "central-block", "name": "Central block", "level": "macro", "role": "structure", "importance": 1.0, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Tall central mass carrying the glazed loggia, attic band and the dome; front face on the z=0 plane.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 42, "height": 30.6, "depth": 34, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 17.7, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "central-block", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:close-aerial"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_central_block_2.add(mesh_central_block_2);
  meshes["central-block"] = mesh_central_block_2;
  colliders["central-block"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["central-block"] ??= [];
  destructionGroups["central-block"].push(node_central_block_2);

  const endpoint_dome_assembly_3 = makeAttachmentEndpoint(null);
  const node_dome_assembly_3 = new THREE.Group();
  node_dome_assembly_3.name = "Dome assembly__pivot";
  node_dome_assembly_3.scale.set(1, 1, 1);
  if (endpoint_dome_assembly_3) {
    node_dome_assembly_3.position.copy(endpoint_dome_assembly_3.start);
    node_dome_assembly_3.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_dome_assembly_3.position.set(0.0, 36.0, -17.0);
    node_dome_assembly_3.rotation.set(0.0, 0.0, 0.0);
  }
  node_dome_assembly_3.userData.sculptComponent = {"id": "dome-assembly", "name": "Dome assembly", "level": "macro", "role": "structure", "importance": 1.0, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream drum with a window ribbon and the glass dome above; the building's strongest landmark.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 11.2, "height": 10.6, "depth": 11.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 36.0, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-assembly", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dome"}}, "material": "glass-dome", "materialLayers": ["glass-dome"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(127, 160, 172, 1.0)", "secondaryAlbedo": "rgba(105, 137, 154, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_dome_assembly_3.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-assembly", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dome"}};
  (nodes["root"] ?? root).add(node_dome_assembly_3);
  nodes["dome-assembly"] = node_dome_assembly_3;
  const mesh_dome_assembly_3Geometry = endpoint_dome_assembly_3
    ? new THREE.CylinderGeometry(endpoint_dome_assembly_3.endRadius, endpoint_dome_assembly_3.baseRadius, endpoint_dome_assembly_3.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_dome_assembly_3) {
    mesh_dome_assembly_3Geometry.scale(11.2, 10.6, 11.2);
  }
  const mesh_dome_assembly_3 = new THREE.Mesh(
    mesh_dome_assembly_3Geometry,
    materialMap["glass-dome"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_dome_assembly_3.name = "Dome assembly";
  if (endpoint_dome_assembly_3) {
    mesh_dome_assembly_3.position.copy(endpoint_dome_assembly_3.midpoint);
    mesh_dome_assembly_3.quaternion.copy(endpoint_dome_assembly_3.quaternion);
  }
  mesh_dome_assembly_3.castShadow = options.castShadow ?? true;
  mesh_dome_assembly_3.receiveShadow = options.receiveShadow ?? true;
  mesh_dome_assembly_3.userData.sculptComponent = {"id": "dome-assembly", "name": "Dome assembly", "level": "macro", "role": "structure", "importance": 1.0, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Cream drum with a window ribbon and the glass dome above; the building's strongest landmark.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 11.2, "height": 10.6, "depth": 11.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 36.0, -17], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "dome-assembly", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "glass-dome"}}, "material": "glass-dome", "materialLayers": ["glass-dome"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref04/zone-r0c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(127, 160, 172, 1.0)", "secondaryAlbedo": "rgba(105, 137, 154, 1.0)", "materialClass": "glass", "materialClassConfidence": 0.8}};
  node_dome_assembly_3.add(mesh_dome_assembly_3);
  meshes["dome-assembly"] = mesh_dome_assembly_3;
  colliders["dome-assembly"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["dome-assembly"] ??= [];
  destructionGroups["dome-assembly"].push(node_dome_assembly_3);

  const endpoint_entrance_portico_4 = makeAttachmentEndpoint(null);
  const node_entrance_portico_4 = new THREE.Group();
  node_entrance_portico_4.name = "Entrance portico__pivot";
  node_entrance_portico_4.scale.set(1, 1, 1);
  if (endpoint_entrance_portico_4) {
    node_entrance_portico_4.position.copy(endpoint_entrance_portico_4.start);
    node_entrance_portico_4.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_entrance_portico_4.position.set(0.0, 7.0, 4.6);
    node_entrance_portico_4.rotation.set(0.0, 0.0, 0.0);
  }
  node_entrance_portico_4.userData.sculptComponent = {"id": "entrance-portico", "name": "Entrance portico", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Columned entrance on the axis: podium, columns, entablature, recessed glass wall, banners.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 28, "height": 9.2, "depth": 12.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 7.0, 4.6], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-portico", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}}, "material": "stone-olive", "materialLayers": ["stone-olive"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(179, 166, 126, 1.0)", "secondaryAlbedo": "rgba(164, 151, 114, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_entrance_portico_4.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-portico", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}};
  (nodes["root"] ?? root).add(node_entrance_portico_4);
  nodes["entrance-portico"] = node_entrance_portico_4;
  const mesh_entrance_portico_4Geometry = endpoint_entrance_portico_4
    ? new THREE.CylinderGeometry(endpoint_entrance_portico_4.endRadius, endpoint_entrance_portico_4.baseRadius, endpoint_entrance_portico_4.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_entrance_portico_4) {
    mesh_entrance_portico_4Geometry.scale(28.0, 9.2, 12.6);
  }
  const mesh_entrance_portico_4 = new THREE.Mesh(
    mesh_entrance_portico_4Geometry,
    materialMap["stone-olive"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_entrance_portico_4.name = "Entrance portico";
  if (endpoint_entrance_portico_4) {
    mesh_entrance_portico_4.position.copy(endpoint_entrance_portico_4.midpoint);
    mesh_entrance_portico_4.quaternion.copy(endpoint_entrance_portico_4.quaternion);
  }
  mesh_entrance_portico_4.castShadow = options.castShadow ?? true;
  mesh_entrance_portico_4.receiveShadow = options.receiveShadow ?? true;
  mesh_entrance_portico_4.userData.sculptComponent = {"id": "entrance-portico", "name": "Entrance portico", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Columned entrance on the axis: podium, columns, entablature, recessed glass wall, banners.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 28, "height": 9.2, "depth": 12.6, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 7.0, 4.6], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "entrance-portico", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "stone-olive"}}, "material": "stone-olive", "materialLayers": ["stone-olive"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(179, 166, 126, 1.0)", "secondaryAlbedo": "rgba(164, 151, 114, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_entrance_portico_4.add(mesh_entrance_portico_4);
  meshes["entrance-portico"] = mesh_entrance_portico_4;
  colliders["entrance-portico"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["entrance-portico"] ??= [];
  destructionGroups["entrance-portico"].push(node_entrance_portico_4);

  const endpoint_west_hall_5 = makeAttachmentEndpoint(null);
  const node_west_hall_5 = new THREE.Group();
  node_west_hall_5.name = "West hall__pivot";
  node_west_hall_5.scale.set(1, 1, 1);
  if (endpoint_west_hall_5) {
    node_west_hall_5.position.copy(endpoint_west_hall_5.start);
    node_west_hall_5.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_west_hall_5.position.set(-40.0, 12.1, -10.0);
    node_west_hall_5.rotation.set(0.0, 0.0, 0.0);
  }
  node_west_hall_5.userData.sculptComponent = {"id": "west-hall", "name": "West hall", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Five-storey side hall with regular window grid, string courses and a hip roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [-40, 12.1, -10], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_west_hall_5.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_west_hall_5);
  nodes["west-hall"] = node_west_hall_5;
  const mesh_west_hall_5Geometry = endpoint_west_hall_5
    ? new THREE.CylinderGeometry(endpoint_west_hall_5.endRadius, endpoint_west_hall_5.baseRadius, endpoint_west_hall_5.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_west_hall_5) {
    mesh_west_hall_5Geometry.scale(38.0, 19.4, 20.0);
  }
  const mesh_west_hall_5 = new THREE.Mesh(
    mesh_west_hall_5Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_west_hall_5.name = "West hall";
  if (endpoint_west_hall_5) {
    mesh_west_hall_5.position.copy(endpoint_west_hall_5.midpoint);
    mesh_west_hall_5.quaternion.copy(endpoint_west_hall_5.quaternion);
  }
  mesh_west_hall_5.castShadow = options.castShadow ?? true;
  mesh_west_hall_5.receiveShadow = options.receiveShadow ?? true;
  mesh_west_hall_5.userData.sculptComponent = {"id": "west-hall", "name": "West hall", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Five-storey side hall with regular window grid, string courses and a hip roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [-40, 12.1, -10], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "west-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_west_hall_5.add(mesh_west_hall_5);
  meshes["west-hall"] = mesh_west_hall_5;
  colliders["west-hall"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["west-hall"] ??= [];
  destructionGroups["west-hall"].push(node_west_hall_5);

  const endpoint_tower_west_6 = makeAttachmentEndpoint(null);
  const node_tower_west_6 = new THREE.Group();
  node_tower_west_6.name = "Tower (west)__pivot";
  node_tower_west_6.scale.set(1, 1, 1);
  if (endpoint_tower_west_6) {
    node_tower_west_6.position.copy(endpoint_tower_west_6.start);
    node_tower_west_6.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_west_6.position.set(-60.2, 17.0, -0.5);
    node_tower_west_6.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_west_6.userData.sculptComponent = {"id": "tower-west", "name": "Tower (west)", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Square terminal tower: brick shaft, cream front panel with paired slots, belfry stage with arches, balustrade, pyramid cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 7.0, "height": 29.2, "depth": 7.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [-60.2, 17.0, -0.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png", "zones-ref04/zone-r0c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_west_6.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_tower_west_6);
  nodes["tower-west"] = node_tower_west_6;
  const mesh_tower_west_6Geometry = endpoint_tower_west_6
    ? new THREE.CylinderGeometry(endpoint_tower_west_6.endRadius, endpoint_tower_west_6.baseRadius, endpoint_tower_west_6.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_west_6) {
    mesh_tower_west_6Geometry.scale(7.0, 29.2, 7.2);
  }
  const mesh_tower_west_6 = new THREE.Mesh(
    mesh_tower_west_6Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_west_6.name = "Tower (west)";
  if (endpoint_tower_west_6) {
    mesh_tower_west_6.position.copy(endpoint_tower_west_6.midpoint);
    mesh_tower_west_6.quaternion.copy(endpoint_tower_west_6.quaternion);
  }
  mesh_tower_west_6.castShadow = options.castShadow ?? true;
  mesh_tower_west_6.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_west_6.userData.sculptComponent = {"id": "tower-west", "name": "Tower (west)", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Square terminal tower: brick shaft, cream front panel with paired slots, belfry stage with arches, balustrade, pyramid cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 7.0, "height": 29.2, "depth": 7.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [-60.2, 17.0, -0.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png", "zones-ref04/zone-r0c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_west_6.add(mesh_tower_west_6);
  meshes["tower-west"] = mesh_tower_west_6;
  colliders["tower-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-west"] ??= [];
  destructionGroups["tower-west"].push(node_tower_west_6);

  const endpoint_pavilion_west_7 = makeAttachmentEndpoint(null);
  const node_pavilion_west_7 = new THREE.Group();
  node_pavilion_west_7.name = "Front pavilion (west)__pivot";
  node_pavilion_west_7.scale.set(1, 1, 1);
  if (endpoint_pavilion_west_7) {
    node_pavilion_west_7.position.copy(endpoint_pavilion_west_7.start);
    node_pavilion_west_7.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pavilion_west_7.position.set(-22.0, 8.7, 4.0);
    node_pavilion_west_7.rotation.set(0.0, 0.0, 0.0);
  }
  node_pavilion_west_7.userData.sculptComponent = {"id": "pavilion-west", "name": "Front pavilion (west)", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low two-storey mass with a hip roof flanking the portico in front of the hall junction.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 13, "height": 12.6, "depth": 13, "units": "relative", "confidence": 0.8}, "transform": {"position": [-22.0, 8.7, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_west_7.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_pavilion_west_7);
  nodes["pavilion-west"] = node_pavilion_west_7;
  const mesh_pavilion_west_7Geometry = endpoint_pavilion_west_7
    ? new THREE.CylinderGeometry(endpoint_pavilion_west_7.endRadius, endpoint_pavilion_west_7.baseRadius, endpoint_pavilion_west_7.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pavilion_west_7) {
    mesh_pavilion_west_7Geometry.scale(13.0, 12.6, 13.0);
  }
  const mesh_pavilion_west_7 = new THREE.Mesh(
    mesh_pavilion_west_7Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pavilion_west_7.name = "Front pavilion (west)";
  if (endpoint_pavilion_west_7) {
    mesh_pavilion_west_7.position.copy(endpoint_pavilion_west_7.midpoint);
    mesh_pavilion_west_7.quaternion.copy(endpoint_pavilion_west_7.quaternion);
  }
  mesh_pavilion_west_7.castShadow = options.castShadow ?? true;
  mesh_pavilion_west_7.receiveShadow = options.receiveShadow ?? true;
  mesh_pavilion_west_7.userData.sculptComponent = {"id": "pavilion-west", "name": "Front pavilion (west)", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low two-storey mass with a hip roof flanking the portico in front of the hall junction.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 13, "height": 12.6, "depth": 13, "units": "relative", "confidence": 0.8}, "transform": {"position": [-22.0, 8.7, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_west_7.add(mesh_pavilion_west_7);
  meshes["pavilion-west"] = mesh_pavilion_west_7;
  colliders["pavilion-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pavilion-west"] ??= [];
  destructionGroups["pavilion-west"].push(node_pavilion_west_7);

  const endpoint_rear_block_west_8 = makeAttachmentEndpoint(null);
  const node_rear_block_west_8 = new THREE.Group();
  node_rear_block_west_8.name = "Rear block (west)__pivot";
  node_rear_block_west_8.scale.set(1, 1, 1);
  if (endpoint_rear_block_west_8) {
    node_rear_block_west_8.position.copy(endpoint_rear_block_west_8.start);
    node_rear_block_west_8.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_rear_block_west_8.position.set(-46.0, 12.1, -45.0);
    node_rear_block_west_8.rotation.set(0.0, 0.0, 0.0);
  }
  node_rear_block_west_8.userData.sculptComponent = {"id": "rear-block-west", "name": "Rear block (west)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Rear hall closing the courtyard; inferred from aerials, front rhythm assumed continued.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 19.4, "depth": 22, "units": "relative", "confidence": 0.6}, "transform": {"position": [-46.0, 12.1, -45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_block_west_8.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_rear_block_west_8);
  nodes["rear-block-west"] = node_rear_block_west_8;
  const mesh_rear_block_west_8Geometry = endpoint_rear_block_west_8
    ? new THREE.CylinderGeometry(endpoint_rear_block_west_8.endRadius, endpoint_rear_block_west_8.baseRadius, endpoint_rear_block_west_8.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_rear_block_west_8) {
    mesh_rear_block_west_8Geometry.scale(17.0, 19.4, 22.0);
  }
  const mesh_rear_block_west_8 = new THREE.Mesh(
    mesh_rear_block_west_8Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_rear_block_west_8.name = "Rear block (west)";
  if (endpoint_rear_block_west_8) {
    mesh_rear_block_west_8.position.copy(endpoint_rear_block_west_8.midpoint);
    mesh_rear_block_west_8.quaternion.copy(endpoint_rear_block_west_8.quaternion);
  }
  mesh_rear_block_west_8.castShadow = options.castShadow ?? true;
  mesh_rear_block_west_8.receiveShadow = options.receiveShadow ?? true;
  mesh_rear_block_west_8.userData.sculptComponent = {"id": "rear-block-west", "name": "Rear block (west)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Rear hall closing the courtyard; inferred from aerials, front rhythm assumed continued.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 19.4, "depth": 22, "units": "relative", "confidence": 0.6}, "transform": {"position": [-46.0, 12.1, -45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-west", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_block_west_8.add(mesh_rear_block_west_8);
  meshes["rear-block-west"] = mesh_rear_block_west_8;
  colliders["rear-block-west"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["rear-block-west"] ??= [];
  destructionGroups["rear-block-west"].push(node_rear_block_west_8);

  const endpoint_east_hall_9 = makeAttachmentEndpoint(null);
  const node_east_hall_9 = new THREE.Group();
  node_east_hall_9.name = "East hall__pivot";
  node_east_hall_9.scale.set(1, 1, 1);
  if (endpoint_east_hall_9) {
    node_east_hall_9.position.copy(endpoint_east_hall_9.start);
    node_east_hall_9.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_east_hall_9.position.set(40.0, 12.1, -10.0);
    node_east_hall_9.rotation.set(0.0, 0.0, 0.0);
  }
  node_east_hall_9.userData.sculptComponent = {"id": "east-hall", "name": "East hall", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Five-storey side hall with regular window grid, string courses and a hip roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [40, 12.1, -10], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_east_hall_9.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_east_hall_9);
  nodes["east-hall"] = node_east_hall_9;
  const mesh_east_hall_9Geometry = endpoint_east_hall_9
    ? new THREE.CylinderGeometry(endpoint_east_hall_9.endRadius, endpoint_east_hall_9.baseRadius, endpoint_east_hall_9.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_east_hall_9) {
    mesh_east_hall_9Geometry.scale(38.0, 19.4, 20.0);
  }
  const mesh_east_hall_9 = new THREE.Mesh(
    mesh_east_hall_9Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_east_hall_9.name = "East hall";
  if (endpoint_east_hall_9) {
    mesh_east_hall_9.position.copy(endpoint_east_hall_9.midpoint);
    mesh_east_hall_9.quaternion.copy(endpoint_east_hall_9.quaternion);
  }
  mesh_east_hall_9.castShadow = options.castShadow ?? true;
  mesh_east_hall_9.receiveShadow = options.receiveShadow ?? true;
  mesh_east_hall_9.userData.sculptComponent = {"id": "east-hall", "name": "East hall", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Five-storey side hall with regular window grid, string courses and a hip roof.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 38, "height": 19.4, "depth": 20, "units": "relative", "confidence": 0.8}, "transform": {"position": [40, 12.1, -10], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "east-hall", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "zones-ref03/zone-r1c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_east_hall_9.add(mesh_east_hall_9);
  meshes["east-hall"] = mesh_east_hall_9;
  colliders["east-hall"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["east-hall"] ??= [];
  destructionGroups["east-hall"].push(node_east_hall_9);

  const endpoint_tower_east_10 = makeAttachmentEndpoint(null);
  const node_tower_east_10 = new THREE.Group();
  node_tower_east_10.name = "Tower (east)__pivot";
  node_tower_east_10.scale.set(1, 1, 1);
  if (endpoint_tower_east_10) {
    node_tower_east_10.position.copy(endpoint_tower_east_10.start);
    node_tower_east_10.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tower_east_10.position.set(60.2, 17.0, -0.5);
    node_tower_east_10.rotation.set(0.0, 0.0, 0.0);
  }
  node_tower_east_10.userData.sculptComponent = {"id": "tower-east", "name": "Tower (east)", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Square terminal tower: brick shaft, cream front panel with paired slots, belfry stage with arches, balustrade, pyramid cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 7.0, "height": 29.2, "depth": 7.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [60.2, 17.0, -0.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png", "zones-ref04/zone-r0c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_east_10.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_tower_east_10);
  nodes["tower-east"] = node_tower_east_10;
  const mesh_tower_east_10Geometry = endpoint_tower_east_10
    ? new THREE.CylinderGeometry(endpoint_tower_east_10.endRadius, endpoint_tower_east_10.baseRadius, endpoint_tower_east_10.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tower_east_10) {
    mesh_tower_east_10Geometry.scale(7.0, 29.2, 7.2);
  }
  const mesh_tower_east_10 = new THREE.Mesh(
    mesh_tower_east_10Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tower_east_10.name = "Tower (east)";
  if (endpoint_tower_east_10) {
    mesh_tower_east_10.position.copy(endpoint_tower_east_10.midpoint);
    mesh_tower_east_10.quaternion.copy(endpoint_tower_east_10.quaternion);
  }
  mesh_tower_east_10.castShadow = options.castShadow ?? true;
  mesh_tower_east_10.receiveShadow = options.receiveShadow ?? true;
  mesh_tower_east_10.userData.sculptComponent = {"id": "tower-east", "name": "Tower (east)", "level": "macro", "role": "structure", "importance": 0.95, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Square terminal tower: brick shaft, cream front panel with paired slots, belfry stage with arches, balustrade, pyramid cap.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 7.0, "height": 29.2, "depth": 7.2, "units": "relative", "confidence": 0.8}, "transform": {"position": [60.2, 17.0, -0.5], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tower-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r1c2.png", "zones-ref04/zone-r0c0.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_tower_east_10.add(mesh_tower_east_10);
  meshes["tower-east"] = mesh_tower_east_10;
  colliders["tower-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tower-east"] ??= [];
  destructionGroups["tower-east"].push(node_tower_east_10);

  const endpoint_pavilion_east_11 = makeAttachmentEndpoint(null);
  const node_pavilion_east_11 = new THREE.Group();
  node_pavilion_east_11.name = "Front pavilion (east)__pivot";
  node_pavilion_east_11.scale.set(1, 1, 1);
  if (endpoint_pavilion_east_11) {
    node_pavilion_east_11.position.copy(endpoint_pavilion_east_11.start);
    node_pavilion_east_11.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_pavilion_east_11.position.set(22.0, 8.7, 4.0);
    node_pavilion_east_11.rotation.set(0.0, 0.0, 0.0);
  }
  node_pavilion_east_11.userData.sculptComponent = {"id": "pavilion-east", "name": "Front pavilion (east)", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low two-storey mass with a hip roof flanking the portico in front of the hall junction.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 13, "height": 12.6, "depth": 13, "units": "relative", "confidence": 0.8}, "transform": {"position": [22.0, 8.7, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_east_11.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_pavilion_east_11);
  nodes["pavilion-east"] = node_pavilion_east_11;
  const mesh_pavilion_east_11Geometry = endpoint_pavilion_east_11
    ? new THREE.CylinderGeometry(endpoint_pavilion_east_11.endRadius, endpoint_pavilion_east_11.baseRadius, endpoint_pavilion_east_11.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_pavilion_east_11) {
    mesh_pavilion_east_11Geometry.scale(13.0, 12.6, 13.0);
  }
  const mesh_pavilion_east_11 = new THREE.Mesh(
    mesh_pavilion_east_11Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_pavilion_east_11.name = "Front pavilion (east)";
  if (endpoint_pavilion_east_11) {
    mesh_pavilion_east_11.position.copy(endpoint_pavilion_east_11.midpoint);
    mesh_pavilion_east_11.quaternion.copy(endpoint_pavilion_east_11.quaternion);
  }
  mesh_pavilion_east_11.castShadow = options.castShadow ?? true;
  mesh_pavilion_east_11.receiveShadow = options.receiveShadow ?? true;
  mesh_pavilion_east_11.userData.sculptComponent = {"id": "pavilion-east", "name": "Front pavilion (east)", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Low two-storey mass with a hip roof flanking the portico in front of the hall junction.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 13, "height": 12.6, "depth": 13, "units": "relative", "confidence": 0.8}, "transform": {"position": [22.0, 8.7, 4.0], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "pavilion-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_pavilion_east_11.add(mesh_pavilion_east_11);
  meshes["pavilion-east"] = mesh_pavilion_east_11;
  colliders["pavilion-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["pavilion-east"] ??= [];
  destructionGroups["pavilion-east"].push(node_pavilion_east_11);

  const endpoint_rear_block_east_12 = makeAttachmentEndpoint(null);
  const node_rear_block_east_12 = new THREE.Group();
  node_rear_block_east_12.name = "Rear block (east)__pivot";
  node_rear_block_east_12.scale.set(1, 1, 1);
  if (endpoint_rear_block_east_12) {
    node_rear_block_east_12.position.copy(endpoint_rear_block_east_12.start);
    node_rear_block_east_12.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_rear_block_east_12.position.set(46.0, 12.1, -45.0);
    node_rear_block_east_12.rotation.set(0.0, 0.0, 0.0);
  }
  node_rear_block_east_12.userData.sculptComponent = {"id": "rear-block-east", "name": "Rear block (east)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Rear hall closing the courtyard; inferred from aerials, front rhythm assumed continued.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 19.4, "depth": 22, "units": "relative", "confidence": 0.6}, "transform": {"position": [46.0, 12.1, -45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_block_east_12.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}};
  (nodes["root"] ?? root).add(node_rear_block_east_12);
  nodes["rear-block-east"] = node_rear_block_east_12;
  const mesh_rear_block_east_12Geometry = endpoint_rear_block_east_12
    ? new THREE.CylinderGeometry(endpoint_rear_block_east_12.endRadius, endpoint_rear_block_east_12.baseRadius, endpoint_rear_block_east_12.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_rear_block_east_12) {
    mesh_rear_block_east_12Geometry.scale(17.0, 19.4, 22.0);
  }
  const mesh_rear_block_east_12 = new THREE.Mesh(
    mesh_rear_block_east_12Geometry,
    materialMap["brick-terracotta"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_rear_block_east_12.name = "Rear block (east)";
  if (endpoint_rear_block_east_12) {
    mesh_rear_block_east_12.position.copy(endpoint_rear_block_east_12.midpoint);
    mesh_rear_block_east_12.quaternion.copy(endpoint_rear_block_east_12.quaternion);
  }
  mesh_rear_block_east_12.castShadow = options.castShadow ?? true;
  mesh_rear_block_east_12.receiveShadow = options.receiveShadow ?? true;
  mesh_rear_block_east_12.userData.sculptComponent = {"id": "rear-block-east", "name": "Rear block (east)", "level": "macro", "role": "structure", "importance": 0.7, "confidence": 0.6, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Rear hall closing the courtyard; inferred from aerials, front rhythm assumed continued.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 17, "height": 19.4, "depth": 22, "units": "relative", "confidence": 0.6}, "transform": {"position": [46.0, 12.1, -45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.6}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "rear-block-east", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "brick-terracotta"}}, "material": "brick-terracotta", "materialLayers": ["brick-terracotta"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:close-aerial", "view:rear-quarter"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(178, 100, 60, 1.0)", "secondaryAlbedo": "rgba(156, 85, 51, 1.0)", "materialClass": "ceramic", "materialClassConfidence": 0.8}};
  node_rear_block_east_12.add(mesh_rear_block_east_12);
  meshes["rear-block-east"] = mesh_rear_block_east_12;
  colliders["rear-block-east"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["rear-block-east"] ??= [];
  destructionGroups["rear-block-east"].push(node_rear_block_east_12);

  const endpoint_plaza_grounds_13 = makeAttachmentEndpoint(null);
  const node_plaza_grounds_13 = new THREE.Group();
  node_plaza_grounds_13.name = "Plaza grounds__pivot";
  node_plaza_grounds_13.scale.set(1, 1, 1);
  if (endpoint_plaza_grounds_13) {
    node_plaza_grounds_13.position.copy(endpoint_plaza_grounds_13.start);
    node_plaza_grounds_13.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_plaza_grounds_13.position.set(0.0, 0.0, 45.0);
    node_plaza_grounds_13.rotation.set(0.0, 0.0, 0.0);
  }
  node_plaza_grounds_13.userData.sculptComponent = {"id": "plaza-grounds", "name": "Plaza grounds", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Axial plaza field: paving, lawn edges, parterre and tree rows.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 220, "height": 1.2, "depth": 120, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0, 45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-grounds", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "paving-plaza"}}, "material": "paving-plaza", "materialLayers": ["paving-plaza"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(205, 197, 176, 1.0)", "secondaryAlbedo": "rgba(190, 181, 160, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_grounds_13.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-grounds", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "paving-plaza"}};
  (nodes["root"] ?? root).add(node_plaza_grounds_13);
  nodes["plaza-grounds"] = node_plaza_grounds_13;
  const mesh_plaza_grounds_13Geometry = endpoint_plaza_grounds_13
    ? new THREE.CylinderGeometry(endpoint_plaza_grounds_13.endRadius, endpoint_plaza_grounds_13.baseRadius, endpoint_plaza_grounds_13.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_plaza_grounds_13) {
    mesh_plaza_grounds_13Geometry.scale(220.0, 1.2, 120.0);
  }
  const mesh_plaza_grounds_13 = new THREE.Mesh(
    mesh_plaza_grounds_13Geometry,
    materialMap["paving-plaza"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_plaza_grounds_13.name = "Plaza grounds";
  if (endpoint_plaza_grounds_13) {
    mesh_plaza_grounds_13.position.copy(endpoint_plaza_grounds_13.midpoint);
    mesh_plaza_grounds_13.quaternion.copy(endpoint_plaza_grounds_13.quaternion);
  }
  mesh_plaza_grounds_13.castShadow = options.castShadow ?? true;
  mesh_plaza_grounds_13.receiveShadow = options.receiveShadow ?? true;
  mesh_plaza_grounds_13.userData.sculptComponent = {"id": "plaza-grounds", "name": "Plaza grounds", "level": "macro", "role": "structure", "importance": 0.75, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Axial plaza field: paving, lawn edges, parterre and tree rows.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 220, "height": 1.2, "depth": 120, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0, 45], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-grounds", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "paving-plaza"}}, "material": "paving-plaza", "materialLayers": ["paving-plaza"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-elevation", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(205, 197, 176, 1.0)", "secondaryAlbedo": "rgba(190, 181, 160, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_grounds_13.add(mesh_plaza_grounds_13);
  meshes["plaza-grounds"] = mesh_plaza_grounds_13;
  colliders["plaza-grounds"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["plaza-grounds"] ??= [];
  destructionGroups["plaza-grounds"].push(node_plaza_grounds_13);

  const endpoint_plaza_pool_14 = makeAttachmentEndpoint(null);
  const node_plaza_pool_14 = new THREE.Group();
  node_plaza_pool_14.name = "Plaza pool__pivot";
  node_plaza_pool_14.scale.set(1, 1, 1);
  if (endpoint_plaza_pool_14) {
    node_plaza_pool_14.position.copy(endpoint_plaza_pool_14.start);
    node_plaza_pool_14.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_plaza_pool_14.position.set(0.0, 0.25, 47.0);
    node_plaza_pool_14.rotation.set(0.0, 0.0, 0.0);
  }
  node_plaza_pool_14.userData.sculptComponent = {"id": "plaza-pool", "name": "Plaza pool", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Big water basin on the axis with scalloped coping and two stepped circular fountains.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 46, "height": 1.0, "depth": 26, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.25, 47], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-pool", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_pool_14.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-pool", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}};
  (nodes["root"] ?? root).add(node_plaza_pool_14);
  nodes["plaza-pool"] = node_plaza_pool_14;
  const mesh_plaza_pool_14Geometry = endpoint_plaza_pool_14
    ? new THREE.CylinderGeometry(endpoint_plaza_pool_14.endRadius, endpoint_plaza_pool_14.baseRadius, endpoint_plaza_pool_14.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_plaza_pool_14) {
    mesh_plaza_pool_14Geometry.scale(46.0, 1.0, 26.0);
  }
  const mesh_plaza_pool_14 = new THREE.Mesh(
    mesh_plaza_pool_14Geometry,
    materialMap["pool-stone"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_plaza_pool_14.name = "Plaza pool";
  if (endpoint_plaza_pool_14) {
    mesh_plaza_pool_14.position.copy(endpoint_plaza_pool_14.midpoint);
    mesh_plaza_pool_14.quaternion.copy(endpoint_plaza_pool_14.quaternion);
  }
  mesh_plaza_pool_14.castShadow = options.castShadow ?? true;
  mesh_plaza_pool_14.receiveShadow = options.receiveShadow ?? true;
  mesh_plaza_pool_14.userData.sculptComponent = {"id": "plaza-pool", "name": "Plaza pool", "level": "macro", "role": "structure", "importance": 0.8, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Big water basin on the axis with scalloped coping and two stepped circular fountains.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 46, "height": 1.0, "depth": 26, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 0.25, 47], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "plaza-pool", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "pool-stone"}}, "material": "pool-stone", "materialLayers": ["pool-stone"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["zones-ref03/zone-r2c1.png", "view:front-aerial-3q"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(224, 220, 208, 1.0)", "secondaryAlbedo": "rgba(210, 206, 194, 1.0)", "materialClass": "stone", "materialClassConfidence": 0.8}};
  node_plaza_pool_14.add(mesh_plaza_pool_14);
  meshes["plaza-pool"] = mesh_plaza_pool_14;
  colliders["plaza-pool"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["plaza-pool"] ??= [];
  destructionGroups["plaza-pool"].push(node_plaza_pool_14);

  const endpoint_tree_rows_15 = makeAttachmentEndpoint(null);
  const node_tree_rows_15 = new THREE.Group();
  node_tree_rows_15.name = "Plaza tree rows__pivot";
  node_tree_rows_15.scale.set(1, 1, 1);
  if (endpoint_tree_rows_15) {
    node_tree_rows_15.position.copy(endpoint_tree_rows_15.start);
    node_tree_rows_15.rotation.set(0.0, 0.0, 0.0);
  } else {
    node_tree_rows_15.position.set(0.0, 7.0, 35.0);
    node_tree_rows_15.rotation.set(0.0, 0.0, 0.0);
  }
  node_tree_rows_15.userData.sculptComponent = {"id": "tree-rows", "name": "Plaza tree rows", "level": "macro", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Two rows of plane trees flanking the parterre and pool; looped in code with scale variance.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 30, "height": 14, "depth": 46, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 7.0, 35], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-rows", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q", "zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_tree_rows_15.userData.actionProfile = {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-rows", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}};
  (nodes["root"] ?? root).add(node_tree_rows_15);
  nodes["tree-rows"] = node_tree_rows_15;
  const mesh_tree_rows_15Geometry = endpoint_tree_rows_15
    ? new THREE.CylinderGeometry(endpoint_tree_rows_15.endRadius, endpoint_tree_rows_15.baseRadius, endpoint_tree_rows_15.length, 32, 12)
    : new THREE.BoxGeometry(1, 1, 1, 12, 12, 12);
  if (!endpoint_tree_rows_15) {
    mesh_tree_rows_15Geometry.scale(30.0, 14.0, 46.0);
  }
  const mesh_tree_rows_15 = new THREE.Mesh(
    mesh_tree_rows_15Geometry,
    materialMap["foliage-green"] ?? new THREE.MeshStandardMaterial({ color: 0x888888 })
  );
  mesh_tree_rows_15.name = "Plaza tree rows";
  if (endpoint_tree_rows_15) {
    mesh_tree_rows_15.position.copy(endpoint_tree_rows_15.midpoint);
    mesh_tree_rows_15.quaternion.copy(endpoint_tree_rows_15.quaternion);
  }
  mesh_tree_rows_15.castShadow = options.castShadow ?? true;
  mesh_tree_rows_15.receiveShadow = options.receiveShadow ?? true;
  mesh_tree_rows_15.userData.sculptComponent = {"id": "tree-rows", "name": "Plaza tree rows", "level": "macro", "role": "structure", "importance": 0.65, "confidence": 0.8, "primitive": "box", "topologyClass": "assembled-solid", "topologyRationale": "Discrete rigid mass with flat faces; genuinely built from a box.", "geometryDescriptor": {"topologyIntent": "Two rows of plane trees flanking the parterre and pool; looped in code with scale variance.", "edgeTreatment": {"type": "none", "bevelRadius": 0.0, "segments": 1}, "deformationStack": [], "uvStrategy": "generated procedural coordinates", "normalStrategy": "vertex normals from generated geometry"}, "parent": "root", "attachment": null, "dimensions": {"width": 30, "height": 14, "depth": 46, "units": "relative", "confidence": 0.8}, "transform": {"position": [0, 7.0, 35], "rotation": [0.0, 0.0, 0.0]}, "actionProfile": {"animationRole": "static-part", "pivot": {"mode": "center", "localPosition": [0, 0, 0], "axis": [0, 1, 0], "confidence": 0.8}, "transformChannels": {"translate": true, "rotate": true, "scale": true, "bend": false, "twist": false, "detach": true, "visibility": true, "materialState": true}, "sockets": [], "collider": {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""}, "constraints": [], "destruction": {"breakable": false, "fractureGroup": "tree-rows", "seamRefs": [], "detachableFragments": [], "breakImpulse": 0.0, "debrisMaterial": "foliage-green"}}, "material": "foliage-green", "materialLayers": ["foliage-green"], "deformations": [], "joints": [], "seams": [], "localFeatures": [], "surfaceDetail": {"macroRoughness": 0.35, "microRoughness": 0.12, "bumpAmplitude": 0.05, "normalPattern": "", "displacementPattern": "", "occlusionPattern": "", "edgeWearPattern": "", "notes": ""}, "evidenceRefs": ["view:front-aerial-3q", "zones-ref03/zone-r2c1.png"], "details": [], "fidelityTier": "blockout", "colorMaterialRecipe": {"dominantAlbedo": "rgba(76, 107, 59, 1.0)", "secondaryAlbedo": "rgba(60, 90, 48, 1.0)", "materialClass": "unknown", "materialClassConfidence": 0.8}};
  node_tree_rows_15.add(mesh_tree_rows_15);
  meshes["tree-rows"] = mesh_tree_rows_15;
  colliders["tree-rows"] = {"type": "box", "offset": [0, 0, 0], "scale": [1, 1, 1], "isTrigger": false, "notes": ""};
  destructionGroups["tree-rows"] ??= [];
  destructionGroups["tree-rows"].push(node_tree_rows_15);
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

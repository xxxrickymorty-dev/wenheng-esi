// refineYNULibrary.ts — hand-authored refinement layer for createYNULibraryModel.ts.
//
// The generator (forge/stage3_build/generate_threejs_factory.py) emits macro/meso/micro
// masses from object-sculpt-spec.json, but its repetition emitter only supports RADIAL
// arrays. Every linear system this building needs (window grids, colonnade, ridge caps,
// balusters, trees, hedge rows) is implemented here and re-applied after every pass
// generation by tools/apply_refine.py. Layout constants mirror tools/build_spec.py
// (the spec remains the decision record; this module is its geometry realization).
import * as THREE from 'three';

type Runtime = {
  nodes: Record<string, THREE.Object3D>;
  meshes: Record<string, THREE.Mesh>;
  sockets: Record<string, THREE.Object3D>;
  colliders: Record<string, unknown>;
  destructionGroups: Record<string, THREE.Object3D[]>;
};

type BoxSpec = { w: number; h: number; d: number; x?: number; y?: number; z?: number };

function mergeBoxes(boxes: BoxSpec[]): THREE.BufferGeometry {
  const positions: number[] = [];
  const normals: number[] = [];
  const uvs: number[] = [];
  const indices: number[] = [];
  const faces: Array<{ n: [number, number, number]; corners: Array<[number, number, number]> }> = [
    { n: [0, 0, 1], corners: [[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]] },
    { n: [0, 0, -1], corners: [[1, -1, -1], [-1, -1, -1], [-1, 1, -1], [1, 1, -1]] },
    { n: [1, 0, 0], corners: [[1, -1, 1], [1, -1, -1], [1, 1, -1], [1, 1, 1]] },
    { n: [-1, 0, 0], corners: [[-1, -1, -1], [-1, -1, 1], [-1, 1, 1], [-1, 1, -1]] },
    { n: [0, 1, 0], corners: [[-1, 1, 1], [1, 1, 1], [1, 1, -1], [-1, 1, -1]] },
    { n: [0, -1, 0], corners: [[-1, -1, -1], [1, -1, -1], [1, -1, 1], [-1, -1, 1]] },
  ];
  for (const box of boxes) {
    const hx = box.w / 2;
    const hy = box.h / 2;
    const hz = box.d / 2;
    const ox = box.x ?? 0;
    const oy = box.y ?? 0;
    const oz = box.z ?? 0;
    for (const face of faces) {
      const base = positions.length / 3;
      face.corners.forEach((corner, index) => {
        positions.push(ox + corner[0] * hx, oy + corner[1] * hy, oz + corner[2] * hz);
        normals.push(face.n[0], face.n[1], face.n[2]);
        uvs.push(index === 1 || index === 2 ? 1 : 0, index >= 2 ? 1 : 0);
      });
      indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  return geometry;
}

// Hip roof with a ridge along X. ridgeLen <= 0 collapses to a pyramid apex.
function hipRoofGeometry(w: number, d: number, h: number, ridgeLen: number): THREE.BufferGeometry {
  const hw = w / 2;
  const hd = d / 2;
  const hr = Math.max(0, ridgeLen / 2);
  const base = [
    [-hw, 0, hd], [hw, 0, hd], [hw, 0, -hd], [-hw, 0, -hd],
  ];
  const ridgeA: [number, number, number] = hr > 0.01 ? [-hr, h, 0] : [0, h, 0];
  const ridgeB: [number, number, number] = hr > 0.01 ? [hr, h, 0] : [0, h, 0];
  const positions: number[] = [];
  const uvs: number[] = [];
  const indices: number[] = [];
  const push = (v: number[], u: number, vv: number) => {
    positions.push(v[0], v[1], v[2]);
    uvs.push(u, vv);
  };
  const quad = (a: number[], b: number[], c: number[], d: number[]) => {
    const i = positions.length / 3;
    push(a, 0, 0); push(b, 1, 0); push(c, 1, 1); push(d, 0, 1);
    indices.push(i, i + 1, i + 2, i, i + 2, i + 3);
  };
  const tri = (a: number[], b: number[], c: number[]) => {
    const i = positions.length / 3;
    push(a, 0, 0); push(b, 1, 0); push(c, 0.5, 1);
    indices.push(i, i + 1, i + 2);
  };
  quad(base[0], base[1], ridgeB, ridgeA); // front slope (+z)
  quad(base[2], base[3], ridgeA, ridgeB); // back slope (-z)
  tri(base[3], base[0], ridgeA); // left hip
  tri(base[1], base[2], ridgeB); // right hip
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function archGeometry(w: number, h: number, depth: number): THREE.BufferGeometry {
  const shape = new THREE.Shape();
  const r = w / 2;
  const straight = Math.max(0.01, h - r);
  shape.moveTo(-r, 0);
  shape.lineTo(r, 0);
  shape.lineTo(r, straight);
  shape.absarc(0, straight, r, 0, Math.PI, false);
  shape.lineTo(-r, 0);
  return new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false });
}

const _m4 = new THREE.Matrix4();
const _q = new THREE.Quaternion();
const _v = new THREE.Vector3();
const _s = new THREE.Vector3();
const _e = new THREE.Euler();

function instanced(
  geometry: THREE.BufferGeometry,
  material: THREE.Material,
  placements: Array<{ p: [number, number, number]; r?: [number, number, number]; s?: [number, number, number] }>,
  name: string,
): THREE.InstancedMesh {
  const mesh = new THREE.InstancedMesh(geometry, material, placements.length);
  placements.forEach((placement, index) => {
    _v.set(placement.p[0], placement.p[1], placement.p[2]);
    _e.set(placement.r?.[0] ?? 0, placement.r?.[1] ?? 0, placement.r?.[2] ?? 0);
    _q.setFromEuler(_e);
    _s.set(placement.s?.[0] ?? 1, placement.s?.[1] ?? 1, placement.s?.[2] ?? 1);
    _m4.compose(_v, _q, _s);
    mesh.setMatrixAt(index, _m4);
  });
  mesh.instanceMatrix.needsUpdate = true;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.name = name;
  return mesh;
}

function mulberry(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function refineYNULibraryModel(root: THREE.Group, runtime: Runtime): void {
  const nodes = runtime.nodes || {};
  const meshes = runtime.meshes || {};

  // ---- material registry from the generated materials themselves
  const materials = new Map<string, THREE.Material>();
  root.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (!mesh.isMesh && !(mesh as unknown as THREE.InstancedMesh).isInstancedMesh) return;
    const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of list) {
      const spec = (material?.userData as { sculptMaterial?: { id?: string } } | undefined)?.sculptMaterial;
      if (spec?.id && !materials.has(spec.id)) materials.set(spec.id, material);
    }
  });
  const MAT = (id: string, fallback: string, color = 0x888888): THREE.Material =>
    materials.get(id) ?? materials.get(fallback) ?? new THREE.MeshStandardMaterial({ color, roughness: 0.85 });

  const trim = MAT('trim-limestone', 'stone-olive', 0xe7dabc);
  const glass = MAT('glass-dark', 'glass-dome', 0x29424a);
  const brick = MAT('brick-terracotta', 'trim-limestone', 0xb2643c);
  const stoneOlive = MAT('stone-olive', 'trim-limestone', 0xb3a67e);
  const terraceStone = MAT('terrace-stone', 'trim-limestone', 0xb9b3a4);
  const roofTile = MAT('roof-tile', 'roof-ridge', 0xb05a3a);
  const roofRidge = MAT('roof-ridge', 'roof-tile', 0xc08a62);
  const hedge = MAT('hedge-purple', 'foliage-green', 0x4a2f3e);
  const foliage = MAT('foliage-green', 'lawn-turf', 0x4c6b3b);
  const bark = MAT('bark-brown', 'foliage-green', 0x6e5c49);
  const steel = MAT('steel-dark', 'dome-frame', 0x5f6b68);
  const equipment = MAT('equipment-white', 'trim-limestone', 0xe8e6e0);
  const banner = MAT('banner-red', 'trim-limestone', 0xb23326);
  const poolStone = MAT('pool-stone', 'terrace-stone', 0xe0dcd0);
  const glassSky = MAT('glass-sky', 'glass-dome', 0x8fb4b4);
  const glassDome = MAT('glass-dome', 'glass-sky', 0x7fa0ac);
  const paving = MAT('paving-plaza', 'terrace-stone', 0xcdc5b0);

  // Runtime tints: the reference albedo maps multiply this colour. The photo-derived
  // roof crop averages pale-peach under the sunlit slope and the dome crop skews green;
  // tinting restores the reference's terracotta / blue-grey read. (Carry back into the
  // spec baseColor at the next spec revision.)
  const tint = (material: THREE.Material, hex: string) => {
    const standard = material as THREE.MeshStandardMaterial;
    if (standard && standard.color) standard.color = new THREE.Color(hex);
    standard.needsUpdate = true;
  };
  tint(roofTile, '#C8623E');
  tint(glassSky, '#9FC4C4');
  tint(glassDome, '#9FB8C8');
  tint(poolStone, '#D9D3C4');
  tint(brick, '#D08A5A');

  // The brick photo crop carries ivy/foliage speckle that reads as green noise on every
  // wall at review distance (flagged by independent review). Flatten it to terracotta:
  // the reference evidence stays in the spec and material-evidence/, but facade
  // readability wins on the runtime build.
  const flatten = (material: THREE.Material, color: string, roughness: number) => {
    const m = material as THREE.MeshStandardMaterial;
    m.map = null;
    m.roughnessMap = null;
    m.normalMap = null;
    m.aoMap = null;
    m.bumpMap = null;
    m.color = new THREE.Color(color);
    m.roughness = roughness;
    m.needsUpdate = true;
  };
  flatten(brick, '#B2643C', 0.86);
  flatten(glass, '#2F4A50', 0.16);

  // Refined meshes are authored in WORLD coordinates. The generated pivots carry their
  // own (localized) transforms, so parenting world-authored meshes under them would
  // displace everything (roofs floated into the sky — same trap as the spec pass).
  // Every refined mesh is therefore parented to the model root, and its name carries
  // the component prefix for part picking.
  const parentFor = (_componentId: string, _fallbackId: string): THREE.Object3D => root;
  const hidePlaceholder = (componentId: string) => {
    const mesh = meshes[componentId];
    if (mesh) mesh.visible = false;
  };
  const addTo = (parent: THREE.Object3D, child: THREE.Object3D) => {
    child.userData.explodeWithParent = true;
    parent.add(child);
  };

  const rand = mulberry(20261016);

  // ================================================================= window grids
  const WING_FRONT_Z = 0.12;
  const hallCenters: Array<{ cx: number; side: string }> = [
    { cx: -40, side: 'west' },
    { cx: 40, side: 'east' },
  ];
  const bayPitch = 2.6;
  const bays = 14;
  const rows = [
    { y: 4.9, h: 2.8 },
    { y: 8.7, h: 2.3 },
    { y: 12.5, h: 2.3 },
    { y: 16.3, h: 2.3 },
    { y: 19.8, h: 1.7 },
  ];
  const frameGeo = mergeBoxes([
    { w: 1.86, h: 2.46, d: 0.08, z: 0.06 },
    { w: 2.05, h: 0.14, d: 0.3, y: -1.3, z: 0.16 },
  ]);
  const glassGeo = new THREE.BoxGeometry(1.5, 2.1, 0.1);
  const framePlacements: Array<{ p: [number, number, number] }> = [];
  const glassPlacements: Array<{ p: [number, number, number] }> = [];
  for (const hall of hallCenters) {
    for (let bay = 0; bay < bays; bay += 1) {
      const x = hall.cx - ((bays - 1) / 2) * bayPitch + bay * bayPitch;
      for (const row of rows) {
        framePlacements.push({ p: [x, row.y, WING_FRONT_Z] });
        glassPlacements.push({ p: [x, row.y, WING_FRONT_Z + 0.05] });
      }
    }
  }
  for (const hall of hallCenters) {
    const parent = parentFor(`wing-windows-${hall.side}`, `${hall.side}-hall`);
    hidePlaceholder(`wing-windows-${hall.side}`);
    addTo(parent, instanced(frameGeo, trim, framePlacements.filter((_, i) => Math.floor(i / (bays * rows.length)) === (hall.side === 'west' ? 0 : 1)), `wing-windows-${hall.side}__frames`));
    addTo(parent, instanced(glassGeo, glass, glassPlacements.filter((_, i) => Math.floor(i / (bays * rows.length)) === (hall.side === 'west' ? 0 : 1)), `wing-windows-${hall.side}__glass`));
  }

  // ================================================================= pilasters + string courses
  const pilasterGeo = new THREE.BoxGeometry(0.7, 19.0, 0.14);
  const pilasterPlacements: Array<{ p: [number, number, number] }> = [];
  const courseGeo = new THREE.BoxGeometry(38.4, 0.28, 0.16);
  const coursePlacements: Array<{ p: [number, number, number] }> = [];
  for (const hall of hallCenters) {
    for (let bay = 0; bay <= bays; bay += 1) {
      const x = hall.cx - ((bays - 1) / 2) * bayPitch + bay * bayPitch - bayPitch / 2;
      pilasterPlacements.push({ p: [x, 12.1, 0.1] });
    }
    for (const y of [6.7, 10.6, 14.4, 18.2]) {
      coursePlacements.push({ p: [hall.cx, y, 0.1] });
    }
  }
  addTo(parentFor('west-body', 'west-hall'), instanced(pilasterGeo, brick, pilasterPlacements.filter((_, i) => i <= bays), 'west-body__pilasters'));
  addTo(parentFor('east-body', 'east-hall'), instanced(pilasterGeo, brick, pilasterPlacements.filter((_, i) => i > bays), 'east-body__pilasters'));
  addTo(parentFor('west-body', 'west-hall'), instanced(courseGeo, trim, coursePlacements.filter((_, i) => i < 4), 'west-body__string-courses'));
  addTo(parentFor('east-body', 'east-hall'), instanced(courseGeo, trim, coursePlacements.filter((_, i) => i >= 4), 'east-body__string-courses'));

  // ================================================================= hip roofs + ridge caps
  type RoofDef = { id: string; fallback: string; cx: number; cz: number; w: number; d: number; eaveY: number; h: number; ridgeLen: number; ridgeAxis: 'x' | 'z' };
  const roofs: RoofDef[] = [
    { id: 'west-roof', fallback: 'west-hall', cx: -40, cz: -10, w: 39.4, d: 21.2, eaveY: 22.2, h: 4.4, ridgeLen: 18.2, ridgeAxis: 'x' },
    { id: 'east-roof', fallback: 'east-hall', cx: 40, cz: -10, w: 39.4, d: 21.2, eaveY: 22.2, h: 4.4, ridgeLen: 18.2, ridgeAxis: 'x' },
    { id: 'rear-roof-west', fallback: 'rear-block-west', cx: -46, cz: -45, w: 18, d: 23, eaveY: 22.2, h: 4.4, ridgeLen: 5, ridgeAxis: 'z' },
    { id: 'rear-roof-east', fallback: 'rear-block-east', cx: 46, cz: -45, w: 18, d: 23, eaveY: 22.2, h: 4.4, ridgeLen: 5, ridgeAxis: 'z' },
    { id: 'pavilion-roof-west', fallback: 'pavilion-west', cx: -22, cz: 4, w: 14.2, d: 14.2, eaveY: 14.8, h: 3.6, ridgeLen: 0, ridgeAxis: 'x' },
    { id: 'pavilion-roof-east', fallback: 'pavilion-east', cx: 22, cz: 4, w: 14.2, d: 14.2, eaveY: 14.8, h: 3.6, ridgeLen: 0, ridgeAxis: 'x' },
  ];
  const capGeoX = new THREE.BoxGeometry(1, 0.22, 0.38);
  const capGeoZ = new THREE.BoxGeometry(0.38, 0.22, 1);
  const capPlacementsX: Array<{ p: [number, number, number]; r?: [number, number, number]; s?: [number, number, number] }> = [];
  const capPlacementsZ: Array<{ p: [number, number, number]; r?: [number, number, number]; s?: [number, number, number] }> = [];
  for (const roof of roofs) {
    const parent = parentFor(roof.id, roof.fallback);
    hidePlaceholder(roof.id);
    const isZ = roof.ridgeAxis === 'z';
    const geo = hipRoofGeometry(roof.w, roof.d, roof.h, roof.ridgeLen);
    if (isZ) geo.rotateY(Math.PI / 2);
    const mesh = new THREE.Mesh(geo, roofTile);
    mesh.name = `${roof.id}__hip`;
    mesh.position.set(roof.cx, roof.eaveY, roof.cz);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    addTo(parent, mesh);
    // ridge cap
    const ridgeLen = Math.max(0.4, roof.ridgeLen);
    const ridgeY = roof.eaveY + roof.h + 0.06;
    const capTargets = isZ ? capPlacementsZ : capPlacementsX;
    capTargets.push({ p: [roof.cx, ridgeY, roof.cz], s: isZ ? [1, 1, ridgeLen] : [ridgeLen, 1, 1] });
    // hip caps: from each base corner to the nearest ridge end
    const hw = roof.w / 2;
    const hd = roof.d / 2;
    const hr = roof.ridgeLen / 2;
    const corners: Array<[number, number]> = isZ
      ? [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]]
      : [[-hw, hd], [hw, hd], [hw, -hd], [-hw, -hd]];
    const ridgeEnds: Array<[number, number]> = isZ ? [[0, -hr], [0, -hr], [0, hr], [0, hr]] : [[-hr, 0], [hr, 0], [hr, 0], [-hr, 0]];
    corners.forEach((corner, index) => {
      const ridge = ridgeEnds[index];
      const a = new THREE.Vector3(roof.cx + corner[0], roof.eaveY, roof.cz + corner[1]);
      const b = new THREE.Vector3(roof.cx + ridge[0], ridgeY, roof.cz + ridge[1]);
      const dir = b.clone().sub(a);
      const length = dir.length();
      const quaternion = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(1, 0, 0), dir.clone().normalize());
      const euler = new THREE.Euler().setFromQuaternion(quaternion);
      const mid = a.clone().add(b).multiplyScalar(0.5);
      capPlacementsX.push({ p: [mid.x, mid.y + 0.06, mid.z], r: [euler.x, euler.y, euler.z], s: [length, 1, 1] });
    });
  }
  addTo(parentFor('west-roof', 'west-hall'), instanced(capGeoX, roofRidge, capPlacementsX, 'roof-ridge-caps-x'));
  addTo(parentFor('rear-roof-west', 'rear-block-west'), instanced(capGeoZ, roofRidge, capPlacementsZ, 'roof-ridge-caps-z'));

  // ================================================================= towers: slots, bands, quoins, arches, balusters
  const slotFrameGeo = mergeBoxes([
    { w: 0.75, h: 1.7, d: 0.08 },
    { w: 0.9, h: 0.1, d: 0.24, y: -0.9, z: 0.08 },
  ]);
  const slotGlassGeo = new THREE.BoxGeometry(0.55, 1.5, 0.1);
  const slotRows = [6.0, 10.0, 14.0, 18.0, 22.0];
  const slotFramePlacements: Array<{ p: [number, number, number] }> = [];
  const slotGlassPlacements: Array<{ p: [number, number, number] }> = [];
  const bandGeo = new THREE.BoxGeometry(7.4, 0.6, 7.4);
  const bandPlacements: Array<{ p: [number, number, number] }> = [];
  const quoinGeo = new THREE.BoxGeometry(0.36, 26.0, 0.36);
  const quoinPlacements: Array<{ p: [number, number, number] }> = [];
  const archGeo = archGeometry(1.6, 2.5, 0.22);
  const archPlacements: Array<{ p: [number, number, number]; r?: [number, number, number] }> = [];
  const balusterGeo = new THREE.BoxGeometry(0.16, 0.62, 0.16);
  const balusterPlacements: Array<{ p: [number, number, number] }> = [];
  const railGeo = new THREE.BoxGeometry(1, 0.14, 0.3);
  const railPlacementsX: Array<{ p: [number, number, number]; s?: [number, number, number] }> = [];
  const railPlacementsZ: Array<{ p: [number, number, number]; r?: [number, number, number]; s?: [number, number, number] }> = [];
  for (const side of [-1, 1]) {
    const tx = side * 60.2;
    for (const y of slotRows) {
      for (const dx of [-1.0, 1.0]) {
        slotFramePlacements.push({ p: [tx + dx, y, 2.55] });
        slotGlassPlacements.push({ p: [tx + dx, y, 2.62] });
      }
    }
    for (const y of [8.0, 16.5, 25.0]) bandPlacements.push({ p: [tx, y, -0.5] });
    for (const qx of [-3.35, 3.35]) {
      for (const qz of [-3.45, 3.45]) quoinPlacements.push({ p: [tx + qx, 15.0, qz - 0.5] });
    }
    archPlacements.push({ p: [tx - 1.5, 29.2, 2.6] }, { p: [tx + 1.5, 29.2, 2.6] });
    archPlacements.push({ p: [tx - 3.5, 29.2, -0.5], r: [0, -Math.PI / 2, 0] }, { p: [tx + 3.5, 29.2, -0.5], r: [0, Math.PI / 2, 0] });
    // balusters along the four top rails
    const halfX = 3.2;
    const halfZ = 3.3;
    const topY = 34.75;
    const railY = 35.2;
    for (let i = 0; i <= 14; i += 1) {
      const t = -1 + (2 * i) / 14;
      balusterPlacements.push({ p: [tx + t * halfX, topY, -0.5 - halfZ] });
      balusterPlacements.push({ p: [tx + t * halfX, topY, -0.5 + halfZ] });
    }
    for (let i = 0; i <= 14; i += 1) {
      const t = -1 + (2 * i) / 14;
      balusterPlacements.push({ p: [tx - halfX, topY, -0.5 + t * halfZ] });
      balusterPlacements.push({ p: [tx + halfX, topY, -0.5 + t * halfZ] });
    }
    railPlacementsX.push({ p: [tx, railY, -0.5 - halfZ], s: [6.6, 1, 1] }, { p: [tx, railY, -0.5 + halfZ], s: [6.6, 1, 1] });
    railPlacementsZ.push({ p: [tx - halfX, railY, -0.5], r: [0, Math.PI / 2, 0], s: [6.8, 1, 1] }, { p: [tx + halfX, railY, -0.5], r: [0, Math.PI / 2, 0], s: [6.8, 1, 1] });
  }
  addTo(parentFor('tower-frontpanel-west', 'tower-west'), instanced(slotFrameGeo, trim, slotFramePlacements.filter((_, i) => slotFramePlacements[i].p[0] < 0), 'tower-slot-frames-west'));
  addTo(parentFor('tower-frontpanel-east', 'tower-east'), instanced(slotFrameGeo, trim, slotFramePlacements.filter((_, i) => slotFramePlacements[i].p[0] > 0), 'tower-slot-frames-east'));
  addTo(parentFor('tower-windows-west', 'tower-west'), instanced(slotGlassGeo, glass, slotGlassPlacements.filter((_, i) => slotGlassPlacements[i].p[0] < 0), 'tower-slot-glass-west'));
  addTo(parentFor('tower-windows-east', 'tower-east'), instanced(slotGlassGeo, glass, slotGlassPlacements.filter((_, i) => slotGlassPlacements[i].p[0] > 0), 'tower-slot-glass-east'));
  addTo(parentFor('tower-bands-west', 'tower-west'), instanced(bandGeo, trim, bandPlacements, 'tower-bands'));
  addTo(parentFor('tower-shaft-west', 'tower-west'), instanced(quoinGeo, trim, quoinPlacements, 'tower-quoins'));
  addTo(parentFor('tower-belfry-west', 'tower-west'), instanced(archGeo, glass, archPlacements, 'tower-belfry-arches'));
  addTo(parentFor('tower-balustrade-west', 'tower-west'), instanced(balusterGeo, terraceStone, balusterPlacements, 'tower-balusters'));
  addTo(parentFor('tower-balustrade-west', 'tower-west'), instanced(railGeo, terraceStone, railPlacementsX, 'tower-rails-x'));
  addTo(parentFor('tower-balustrade-west', 'tower-west'), instanced(railGeo, terraceStone, railPlacementsZ, 'tower-rails-z'));

  // ================================================================= colonnade + banners
  const columnGeo = mergeBoxes([
    { w: 1.05, h: 8.6, d: 1.05 },
    { w: 1.35, h: 0.42, d: 1.35, y: 4.5 },
    { w: 1.35, h: 0.35, d: 1.35, y: -4.3 },
  ]);
  const columnPlacements: Array<{ p: [number, number, number] }> = [];
  for (let i = 0; i < 8; i += 1) {
    const x = -11.9 + i * 3.4;
    columnPlacements.push({ p: [x, 7.8, 8.6] });
  }
  hidePlaceholder('portico-columns');
  addTo(parentFor('portico-columns', 'entrance-portico'), instanced(columnGeo, stoneOlive, columnPlacements, 'portico-columns__array'));
  const bannerGeo = new THREE.BoxGeometry(1.6, 4.0, 0.25);
  hidePlaceholder('entrance-banners');
  addTo(parentFor('entrance-banners', 'entrance-portico'), instanced(bannerGeo, banner, [
    { p: [-6.2, 6.8, 0.6] },
    { p: [6.2, 6.8, 0.6] },
  ], 'entrance-banners__pair'));

  // ================================================================= grand steps
  hidePlaceholder('grand-steps');
  {
    const stepBoxes: BoxSpec[] = [];
    let y = 2.4;
    let z = 8.0;
    const run = 0.42;
    const rise = 0.15;
    const width = 30;
    const flight = (steps: number) => {
      for (let i = 0; i < steps; i += 1) {
        y -= rise;
        z += run;
        stepBoxes.push({ w: width, h: y, d: run, y: y / 2, z: z - run / 2 });
      }
    };
    const landing = (depth: number) => {
      z += depth;
      stepBoxes.push({ w: width, h: y, d: depth, y: y / 2, z: z - depth / 2 });
    };
    flight(6);
    landing(2.0);
    flight(6);
    landing(1.6);
    flight(4);
    const stairs = new THREE.Mesh(mergeBoxes(stepBoxes), terraceStone);
    stairs.name = 'grand-steps__stairs';
    stairs.castShadow = true;
    stairs.receiveShadow = true;
    addTo(parentFor('grand-steps', 'terrace-podium'), stairs);
  }

  // ================================================================= terrace balustrade balusters
  {
    const placements: Array<{ p: [number, number, number] }> = [];
    for (const side of [-1, 1]) {
      const cx = side * 25;
      for (let i = 0; i <= 30; i += 1) {
        const t = -1 + (2 * i) / 30;
        placements.push({ p: [cx + t * 9.4, 2.75, 9] });
      }
    }
    addTo(parentFor('terrace-balustrade-west', 'terrace-podium'), instanced(balusterGeo, terraceStone, placements, 'terrace-balusters'));
  }

  // ================================================================= pavilion windows
  const pavFrameGeo = mergeBoxes([
    { w: 1.66, h: 2.16, d: 0.08 },
    { w: 1.85, h: 0.12, d: 0.26, y: -1.14, z: 0.08 },
  ]);
  const pavGlassGeo = new THREE.BoxGeometry(1.35, 1.85, 0.1);
  const pavFramePlacements: Array<{ p: [number, number, number] }> = [];
  const pavGlassPlacements: Array<{ p: [number, number, number] }> = [];
  for (const side of [-1, 1]) {
    const cx = side * 22;
    for (const y of [7.2, 10.4]) {
      for (const dx of [-5.7, -1.9, 1.9, 5.7]) {
        pavFramePlacements.push({ p: [cx + dx, y, 10.56] });
        pavGlassPlacements.push({ p: [cx + dx, y, 10.62] });
      }
    }
  }
  hidePlaceholder('pavilion-windows-west');
  hidePlaceholder('pavilion-windows-east');
  addTo(parentFor('pavilion-windows-west', 'pavilion-west'), instanced(pavFrameGeo, trim, pavFramePlacements.filter((_, i) => pavFramePlacements[i].p[0] < 0), 'pavilion-frames-west'));
  addTo(parentFor('pavilion-windows-east', 'pavilion-east'), instanced(pavFrameGeo, trim, pavFramePlacements.filter((_, i) => pavFramePlacements[i].p[0] > 0), 'pavilion-frames-east'));
  addTo(parentFor('pavilion-windows-west', 'pavilion-west'), instanced(pavGlassGeo, glass, pavGlassPlacements.filter((_, i) => pavGlassPlacements[i].p[0] < 0), 'pavilion-glass-west'));
  addTo(parentFor('pavilion-windows-east', 'pavilion-east'), instanced(pavGlassGeo, glass, pavGlassPlacements.filter((_, i) => pavGlassPlacements[i].p[0] > 0), 'pavilion-glass-east'));

  // ================================================================= rear block windows (courtyard faces)
  const rearFrameGeo = mergeBoxes([
    { w: 0.08, h: 2.4, d: 1.86 },
    { w: 0.26, h: 0.12, d: 2.05, z: 0, y: -1.26 },
  ]);
  const rearGlassGeo = new THREE.BoxGeometry(0.1, 2.05, 1.55);
  const rearFramePlacements: Array<{ p: [number, number, number] }> = [];
  const rearGlassPlacements: Array<{ p: [number, number, number] }> = [];
  for (const side of [-1, 1]) {
    const fx = side * 37.45;
    for (const y of [6.0, 10.0, 14.0, 18.0]) {
      for (const dz of [-6.0, -2.0, 2.0, 6.0]) {
        rearFramePlacements.push({ p: [fx, y, -45 + dz] });
        rearGlassPlacements.push({ p: [fx + side * 0.06, y, -45 + dz] });
      }
    }
  }
  hidePlaceholder('rear-windows-west');
  hidePlaceholder('rear-windows-east');
  addTo(parentFor('rear-windows-west', 'rear-block-west'), instanced(rearFrameGeo, trim, rearFramePlacements.filter((_, i) => rearFramePlacements[i].p[0] < 0), 'rear-frames-west'));
  addTo(parentFor('rear-windows-east', 'rear-block-east'), instanced(rearFrameGeo, trim, rearFramePlacements.filter((_, i) => rearFramePlacements[i].p[0] > 0), 'rear-frames-east'));
  addTo(parentFor('rear-windows-west', 'rear-block-west'), instanced(rearGlassGeo, glass, rearGlassPlacements.filter((_, i) => rearGlassPlacements[i].p[0] < 0), 'rear-glass-west'));
  addTo(parentFor('rear-windows-east', 'rear-block-east'), instanced(rearGlassGeo, glass, rearGlassPlacements.filter((_, i) => rearGlassPlacements[i].p[0] > 0), 'rear-glass-east'));

  // ================================================================= courtyard vault + ribs
  {
    hidePlaceholder('vault-shell');
    const pipe = new THREE.CylinderGeometry(3.2, 3.2, 17, 24, 1, true, 0, Math.PI);
    pipe.rotateZ(Math.PI / 2);
    const vault = new THREE.Mesh(pipe, glassSky);
    vault.name = 'vault-shell__halfpipe';
    vault.position.set(29.5, 6.4, -36);
    vault.castShadow = true;
    vault.receiveShadow = true;
    addTo(parentFor('vault-shell', 'root'), vault);
    const ribGeo = new THREE.BoxGeometry(0.14, 0.16, 6.5);
    const ribs: Array<{ p: [number, number, number] }> = [];
    for (let i = 0; i <= 6; i += 1) ribs.push({ p: [22.6 + i * 2.4, 9.55, -36] });
    addTo(parentFor('vault-shell', 'root'), instanced(ribGeo, steel, ribs, 'vault-shell__ribs'));
  }

  // ================================================================= plaza: hedges, topiary, trees, conifers, pool lobes
  {
    hidePlaceholder('parterre-blocks');
    const hedgeGeo = new THREE.BoxGeometry(1.7, 0.85, 1.5);
    const placements: Array<{ p: [number, number, number] }> = [];
    for (const z of [22.5, 25.5]) {
      for (const x of [-6.3, -2.1, 2.1, 6.3]) placements.push({ p: [x, 0.78, z] });
    }
    addTo(parentFor('parterre-blocks', 'plaza-grounds'), instanced(hedgeGeo, hedge, placements, 'parterre-blocks__rows'));
  }
  {
    hidePlaceholder('topiary-balls');
    const ballGeo = new THREE.SphereGeometry(0.7, 16, 12);
    const placements: Array<{ p: [number, number, number]; s?: [number, number, number] }> = [];
    for (const p of [[-8.5, 38.5], [8.5, 38.5], [-8.5, 55.5], [8.5, 55.5], [-3.0, 47], [3.0, 47]] as Array<[number, number]>) {
      placements.push({ p: [p[0], 0.72, p[1]] });
    }
    addTo(parentFor('topiary-balls', 'plaza-grounds'), instanced(ballGeo, hedge, placements, 'topiary-balls__group'));
  }
  {
    const trunkGeo = new THREE.CylinderGeometry(0.2, 0.26, 3.4, 8);
    const crownGeo = new THREE.SphereGeometry(1, 12, 10);
    const trunkPlacements: Array<{ p: [number, number, number] }> = [];
    const crownPlacements: Array<{ p: [number, number, number]; s?: [number, number, number] }> = [];
    for (const side of [-1, 1]) {
      for (let i = 0; i < 8; i += 1) {
        const z = 16 + i * 6 + (rand() - 0.5) * 1.2;
        const x = side * (15.5 + (rand() - 0.5) * 1.0);
        const scale = 0.8 + rand() * 0.25;
        trunkPlacements.push({ p: [x, 1.7, z] });
        crownPlacements.push({ p: [x, 3.4 + 1.75 * scale, z], s: [1.9 * scale, 2.0 * scale, 1.9 * scale] });
        crownPlacements.push({ p: [x + 0.7 * scale, 3.4 + 2.6 * scale, z - 0.35 * scale], s: [1.25 * scale, 1.35 * scale, 1.25 * scale] });
      }
    }
    addTo(parentFor('tree-row-west', 'tree-rows'), instanced(trunkGeo, bark, trunkPlacements.filter((_, i) => trunkPlacements[i].p[0] < 0), 'tree-trunks-west'));
    addTo(parentFor('tree-row-east', 'tree-rows'), instanced(trunkGeo, bark, trunkPlacements.filter((_, i) => trunkPlacements[i].p[0] > 0), 'tree-trunks-east'));
    addTo(parentFor('tree-row-west', 'tree-rows'), instanced(crownGeo, foliage, crownPlacements.filter((_, i) => crownPlacements[i].p[0] < 0), 'tree-crowns-west'));
    addTo(parentFor('tree-row-east', 'tree-rows'), instanced(crownGeo, foliage, crownPlacements.filter((_, i) => crownPlacements[i].p[0] > 0), 'tree-crowns-east'));
  }
  {
    hidePlaceholder('courtyard-conifers-west');
    hidePlaceholder('courtyard-conifers-east');
    const coneGeo = new THREE.ConeGeometry(1.0, 6.0, 10);
    const placements: Array<{ p: [number, number, number]; s?: [number, number, number] }> = [];
    for (const side of [-1, 1]) {
      for (let i = 0; i < 5; i += 1) {
        const z = -18 - i * 3.0;
        placements.push({ p: [side * 33, 5.4, z], s: [0.9 + rand() * 0.3, 1.0 + rand() * 0.25, 0.9 + rand() * 0.3] });
      }
    }
    addTo(parentFor('courtyard-conifers-west', 'root'), instanced(coneGeo, foliage, placements, 'courtyard-conifers__row'));
  }
  {
    const lobeGeo = new THREE.CylinderGeometry(2.4, 2.4, 0.92, 24);
    const placements: Array<{ p: [number, number, number] }> = [];
    for (const x of [-22.4, 22.4]) {
      for (const z of [34.4, 59.6]) placements.push({ p: [x, 0.06, z] });
    }
    placements.push({ p: [0, 0.06, 33.4] });
    addTo(parentFor('pool-basin', 'plaza-pool'), instanced(lobeGeo, poolStone, placements, 'pool-basin__lobes'));
  }

  // ================================================================= roof deck equipment
  {
    const panelGeo = new THREE.BoxGeometry(2.2, 0.14, 1.2);
    const panels: Array<{ p: [number, number, number]; r?: [number, number, number] }> = [];
    for (let i = 0; i < 6; i += 1) {
      panels.push({ p: [-8 + i * 3.2, 34.5, -23], r: [-0.6, 0, 0] });
    }
    addTo(parentFor('roof-deck', 'central-block'), instanced(panelGeo, steel, panels, 'roof-deck__solar-row'));
    const boxGeo = new THREE.BoxGeometry(1.6, 1.0, 1.2);
    const boxes: Array<{ p: [number, number, number]; s?: [number, number, number] }> = [
      { p: [14, 34.1, -12], s: [1.1, 1.1, 1.0] },
      { p: [12.5, 34.1, -20], s: [0.9, 1.0, 0.9] },
      { p: [-14, 34.1, -8], s: [1.0, 0.9, 1.0] },
      { p: [8, 34.1, -26], s: [1.2, 0.9, 1.0] },
    ];
    addTo(parentFor('roof-deck', 'central-block'), instanced(boxGeo, equipment, boxes, 'roof-deck__equipment'));
    const stripGeo = new THREE.BoxGeometry(6, 0.34, 1.4);
    addTo(parentFor('roof-deck', 'central-block'), instanced(stripGeo, equipment, [
      { p: [-4, 34.15, -10] },
      { p: [4, 34.15, -24] },
    ], 'roof-deck__skylights'));
  }

  {
    // central parapet: the generated component is a solid slab that covers the whole
    // roof deck; replace it with a ring of parapet strips so the pale deck stays visible.
    hidePlaceholder('central-parapet');
    const strips: Array<{ geo: THREE.BufferGeometry; p: [number, number, number] }> = [
      { geo: new THREE.BoxGeometry(43.2, 0.9, 0.6), p: [0, 33.55, -0.3] },
      { geo: new THREE.BoxGeometry(43.2, 0.9, 0.6), p: [0, 33.55, -33.7] },
      { geo: new THREE.BoxGeometry(0.6, 0.9, 34.6), p: [-21.3, 33.55, -17] },
      { geo: new THREE.BoxGeometry(0.6, 0.9, 34.6), p: [21.3, 33.55, -17] },
    ];
    const parapet = new THREE.Group();
    parapet.name = 'central-parapet__ring';
    for (const strip of strips) {
      const mesh = new THREE.Mesh(strip.geo, trim);
      mesh.position.set(strip.p[0], strip.p[1], strip.p[2]);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      parapet.add(mesh);
    }
    addTo(root, parapet);
  }

  // ================================================================= central block windows (rear + side faces)
  {
    const cFrame = mergeBoxes([
      { w: 1.86, h: 2.46, d: 0.08 },
      { w: 2.05, h: 0.14, d: 0.3, y: -1.3, z: 0.16 },
    ]);
    const cGlass = new THREE.BoxGeometry(1.5, 2.1, 0.1);
    const frameP: Array<{ p: [number, number, number]; r?: [number, number, number] }> = [];
    const glassP: Array<{ p: [number, number, number]; r?: [number, number, number] }> = [];
    // rear face (z = -34): four rows, eight bays
    for (const y of [6.2, 10.6, 15.0, 19.4]) {
      for (let i = 0; i < 8; i += 1) {
        const x = -14.7 + i * 4.2;
        frameP.push({ p: [x, y, -34.02], r: [0, Math.PI, 0] });
        glassP.push({ p: [x, y, -34.08], r: [0, Math.PI, 0] });
      }
    }
    // side faces (x = ±21): four rows, three bays
    for (const sx of [-1, 1]) {
      for (const y of [6.2, 11.4, 16.6, 21.8]) {
        for (let i = 0; i < 3; i += 1) {
          const z = -8 - i * 5.4;
          frameP.push({ p: [sx * 21.02, y, z], r: [0, sx * Math.PI / 2, 0] });
          glassP.push({ p: [sx * 21.08, y, z], r: [0, sx * Math.PI / 2, 0] });
        }
      }
    }
    addTo(root, instanced(cFrame, trim, frameP, 'central-windows__frames'));
    addTo(root, instanced(cGlass, glass, glassP, 'central-windows__glass'));
  }

  // hide the meso tree-row placeholders (real tree loops are added below)
  hidePlaceholder('tree-row-west');
  hidePlaceholder('tree-row-east');

  void paving;
  void rand;
}

export type LibraryMesh = {
  vertices: Float32Array
  triangleCount: number
}

type Color = [number, number, number]
type Point = [number, number, number]

const brick: Color = [0.69, 0.35, 0.25]
const brickLight: Color = [0.76, 0.44, 0.33]
const stone: Color = [0.87, 0.83, 0.71]
const stoneShade: Color = [0.71, 0.70, 0.62]
const glass: Color = [0.19, 0.34, 0.37]
const glassLight: Color = [0.34, 0.53, 0.55]
const roof: Color = [0.55, 0.31, 0.25]
const brass: Color = [0.63, 0.53, 0.32]
const dark: Color = [0.12, 0.25, 0.26]
const garden: Color = [0.23, 0.39, 0.30]

export function createLibraryGeometry(): LibraryMesh {
  const data: number[] = []

  function triangle(a: Point, b: Point, c: Point, color: Color) {
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2]
    const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2]
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
    const length = Math.hypot(nx, ny, nz) || 1
    for (const p of [a, b, c]) data.push(...p, nx / length, ny / length, nz / length, ...color)
  }

  function quad(a: Point, b: Point, c: Point, d: Point, color: Color) {
    triangle(a, b, c, color)
    triangle(a, c, d, color)
  }

  function box(x: number, y: number, z: number, w: number, h: number, depth: number, color: Color) {
    const l = x - w / 2, r = x + w / 2, bot = y - h / 2, top = y + h / 2
    const back = z - depth / 2, front = z + depth / 2
    quad([l, bot, front], [r, bot, front], [r, top, front], [l, top, front], color)
    quad([r, bot, back], [l, bot, back], [l, top, back], [r, top, back], color)
    quad([r, bot, front], [r, bot, back], [r, top, back], [r, top, front], color)
    quad([l, bot, back], [l, bot, front], [l, top, front], [l, top, back], color)
    quad([l, top, front], [r, top, front], [r, top, back], [l, top, back], color)
    quad([l, bot, back], [r, bot, back], [r, bot, front], [l, bot, front], color)
  }

  function cylinder(x: number, y: number, z: number, radius: number, height: number, color: Color, sides = 10) {
    for (let i = 0; i < sides; i++) {
      const a = i * Math.PI * 2 / sides, b = (i + 1) * Math.PI * 2 / sides
      const p: Point = [x + Math.cos(a) * radius, y, z + Math.sin(a) * radius]
      const q: Point = [x + Math.cos(b) * radius, y, z + Math.sin(b) * radius]
      quad(p, q, [q[0], y + height, q[2]], [p[0], y + height, p[2]], color)
      triangle([x, y + height, z], [p[0], y + height, p[2]], [q[0], y + height, q[2]], color)
    }
  }

  function pitchedRoof(x: number, y: number, z: number, w: number, depth: number, rise: number) {
    const l = x - w / 2, r = x + w / 2, b = z - depth / 2, f = z + depth / 2
    quad([l, y, f], [x, y + rise, f], [x, y + rise, b], [l, y, b], roof)
    quad([x, y + rise, f], [r, y, f], [r, y, b], [x, y + rise, b], brickLight)
    triangle([l, y, f], [r, y, f], [x, y + rise, f], stone)
    triangle([r, y, b], [l, y, b], [x, y + rise, b], stoneShade)
  }

  // Broad podium and the staggered entrance steps anchor the model.
  box(0, -0.15, 0.15, 14.8, 0.24, 5.2, stoneShade)
  box(0, -0.20, 3.8, 6.9, 0.13, 2.2, stone)
  for (let i = 0; i < 9; i++) {
    box(0, -0.24 + i * 0.035, 5.11 - i * 0.14, 5.7 + i * 0.13, 0.07, 0.27, i % 2 ? stoneShade : stone)
  }
  for (const side of [-1, 1]) {
    box(side * 4.05, -0.12, 3.95, 1.28, 0.16, 1.8, stone)
    box(side * 4.05, 0.01, 3.95, 0.85, 0.12, 1.5, garden)
  }

  // Red brick wings: the windows are inset dark glass with pale reveals.
  for (const side of [-1, 1]) {
    const wingX = side * 4.35
    box(wingX, 1.55, 0.05, 4.3, 3.05, 2.4, brick)
    box(wingX, 0.21, 1.29, 4.45, 0.18, 0.16, stone)
    box(wingX, 3.11, 0.05, 4.52, 0.16, 2.56, stone)
    box(wingX, 2.01, 1.28, 4.36, 0.09, 0.10, brickLight)
    pitchedRoof(wingX, 3.23, 0.05, 4.5, 2.75, 0.62)
    for (let i = 0; i < 9; i++) {
      const wx = wingX - 1.86 + i * 0.465
      for (const wy of [0.91, 2.17]) {
        box(wx, wy, 1.3, 0.26, 0.82, 0.07, stone)
        box(wx, wy, 1.35, 0.19, 0.72, 0.04, glass)
        box(wx, wy, 1.38, 0.035, 0.72, 0.025, stone)
        box(wx, wy, 1.39, 0.20, 0.035, 0.025, stone)
      }
    }
  }

  // The central glazed reading hall, framed by pale stone pilasters.
  box(0, 2.03, -0.43, 4.35, 4.07, 2.82, stone)
  box(0, 2.10, 1.02, 3.77, 3.45, 0.08, glass)
  for (let i = 0; i < 11; i++) {
    const x = -1.87 + i * 0.374
    box(x, 2.12, 1.085, 0.055, 3.49, 0.06, stone)
    if (i < 10) box(x + 0.18, 2.94, 1.075, 0.17, 1.30, 0.025, glassLight)
  }
  for (const y of [0.49, 1.55, 2.65, 3.72]) box(0, y, 1.10, 3.95, 0.065, 0.07, stone)
  box(0, 4.15, -0.43, 4.6, 0.20, 3.0, stone)
  box(0, 4.28, -0.43, 4.65, 0.055, 3.04, brass)

  // A shallow glass dome with brass ribs keeps the silhouette recognisable.
  cylinder(0, 4.34, -0.50, 1.25, 0.16, stone, 20)
  const rings = 7, slices = 20, domeRadius = 1.18
  for (let ring = 0; ring < rings; ring++) {
    const t0 = ring / rings * Math.PI / 2, t1 = (ring + 1) / rings * Math.PI / 2
    const r0 = Math.cos(t0) * domeRadius, r1 = Math.cos(t1) * domeRadius
    const y0 = 4.51 + Math.sin(t0) * 0.87, y1 = 4.51 + Math.sin(t1) * 0.87
    for (let slice = 0; slice < slices; slice++) {
      const a = slice * Math.PI * 2 / slices, b = (slice + 1) * Math.PI * 2 / slices
      const p: Point = [r0 * Math.cos(a), y0, -0.5 + r0 * Math.sin(a)]
      const q: Point = [r0 * Math.cos(b), y0, -0.5 + r0 * Math.sin(b)]
      const u: Point = [r1 * Math.cos(b), y1, -0.5 + r1 * Math.sin(b)]
      const v: Point = [r1 * Math.cos(a), y1, -0.5 + r1 * Math.sin(a)]
      quad(p, q, u, v, slice % 4 === 0 ? glassLight : glass)
      if (slice % 4 === 0) quad(p, [p[0] * 1.014, p[1], p[2] + 0.012], [v[0] * 1.014, v[1], v[2] + 0.012], v, brass)
    }
  }
  cylinder(0, 5.36, -0.5, 0.035, 0.24, brass, 8)

  // Two square towers, with arched openings suggested by inset glazing.
  for (const side of [-1, 1]) {
    const x = side * 6.73
    box(x, 2.37, -0.16, 1.48, 4.74, 1.65, brickLight)
    box(x, 0.60, 0.70, 1.62, 0.16, 1.75, stone)
    box(x, 3.71, 0.71, 1.68, 0.22, 1.78, stone)
    box(x, 4.62, -0.16, 1.85, 0.21, 1.99, stone)
    box(x, 4.78, -0.16, 1.87, 0.07, 2.02, brass)
    for (const y of [1.24, 2.28, 3.26, 4.14]) {
      box(x, y, 0.71, 0.50, y > 4 ? 0.39 : 0.58, 0.07, stone)
      box(x, y, 0.77, 0.39, y > 4 ? 0.31 : 0.49, 0.04, dark)
      box(x, y, 0.80, 0.035, y > 4 ? 0.31 : 0.49, 0.02, stone)
    }
    box(x, 4.94, -0.16, 0.035, 0.30, 0.035, brass)
  }

  // The portico and its clear central opening sit in front of the glass hall.
  box(0, 1.46, 1.64, 3.68, 2.0, 0.24, glass)
  box(0, 2.66, 2.04, 4.55, 0.25, 1.24, stone)
  box(0, 2.81, 2.04, 4.66, 0.055, 1.30, brass)
  for (let i = 0; i < 7; i++) {
    const x = -2.03 + i * 0.68
    cylinder(x, 0.43, 2.53, 0.085, 2.05, stone, 10)
    box(x, 2.46, 2.53, 0.26, 0.15, 0.26, stoneShade)
    box(x, 0.46, 2.53, 0.25, 0.13, 0.25, stoneShade)
  }
  box(0, 0.29, 2.05, 4.79, 0.20, 2.15, stone)

  return { vertices: new Float32Array(data), triangleCount: data.length / 27 }
}

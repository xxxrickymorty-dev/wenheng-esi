import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createLibraryGeometry } from './geometry'

export type LibraryBuildingModelProps = {
  className?: string
  style?: CSSProperties
  /** The surrounding page can turn off rotation when the model is decorative. */
  interactive?: boolean
  /** Right leaves room for the entrance heading and its primary action. */
  placement?: 'right' | 'center'
}

const vertexSource = `
attribute vec3 aPosition;
attribute vec3 aNormal;
attribute vec3 aColor;
uniform float uYaw;
uniform float uAspect;
uniform float uShift;
varying vec3 vColor;
varying float vLight;
void main() {
  float cs = cos(uYaw), sn = sin(uYaw);
  float x = cs * aPosition.x + sn * aPosition.z;
  float z = -sn * aPosition.x + cs * aPosition.z;
  float y = aPosition.y - 2.3;
  float elevatedY = 0.955 * y - 0.296 * z;
  float depth = 0.296 * y + 0.955 * z;
  float halfWidth = max(8.45, 4.75 * uAspect);
  float scale = uShift > 0.0 ? 0.80 : 1.0;
  float verticalShift = uAspect < 0.75 ? -0.27 : 0.0;
  gl_Position = vec4(x / halfWidth * scale + uShift, elevatedY / (halfWidth / uAspect) * scale + verticalShift, -depth / 15.0, 1.0);
  vec3 normal = normalize(vec3(cs * aNormal.x + sn * aNormal.z, aNormal.y, -sn * aNormal.x + cs * aNormal.z));
  vLight = 0.70 + 0.30 * max(dot(normal, normalize(vec3(-0.45, 0.85, 0.75))), 0.0);
  vColor = aColor;
}`

const fragmentSource = `
precision mediump float;
varying vec3 vColor;
varying float vLight;
void main() {
  gl_FragColor = vec4(vColor * vLight, 1.0);
}`

function shader(gl: WebGLRenderingContext, type: number, source: string) {
  const result = gl.createShader(type)
  if (!result) throw new Error('无法绘制建筑模型')
  gl.shaderSource(result, source)
  gl.compileShader(result)
  if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) {
    gl.deleteShader(result)
    throw new Error('无法绘制建筑模型')
  }
  return result
}

function createRenderer(canvas: HTMLCanvasElement, placement: 'right' | 'center') {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: true, powerPreference: 'low-power' })
  if (!gl) return null
  const vertex = shader(gl, gl.VERTEX_SHADER, vertexSource)
  const fragment = shader(gl, gl.FRAGMENT_SHADER, fragmentSource)
  const program = gl.createProgram()
  if (!program) throw new Error('无法绘制建筑模型')
  gl.attachShader(program, vertex)
  gl.attachShader(program, fragment)
  gl.linkProgram(program)
  gl.deleteShader(vertex)
  gl.deleteShader(fragment)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('无法绘制建筑模型')

  const mesh = createLibraryGeometry()
  const buffer = gl.createBuffer()
  if (!buffer) throw new Error('无法绘制建筑模型')
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
  gl.bufferData(gl.ARRAY_BUFFER, mesh.vertices, gl.STATIC_DRAW)
  gl.useProgram(program)
  const stride = 9 * 4
  const position = gl.getAttribLocation(program, 'aPosition')
  const normal = gl.getAttribLocation(program, 'aNormal')
  const color = gl.getAttribLocation(program, 'aColor')
  for (const [location, size, offset] of [[position, 3, 0], [normal, 3, 12], [color, 3, 24]]) {
    gl.enableVertexAttribArray(location)
    gl.vertexAttribPointer(location, size, gl.FLOAT, false, stride, offset)
  }
  const yawLocation = gl.getUniformLocation(program, 'uYaw')
  const aspectLocation = gl.getUniformLocation(program, 'uAspect')
  const shiftLocation = gl.getUniformLocation(program, 'uShift')
  gl.enable(gl.DEPTH_TEST)
  gl.depthFunc(gl.LEQUAL)
  let yaw = -0.095

  function draw() {
    const width = Math.max(1, canvas.clientWidth)
    const height = Math.max(1, canvas.clientHeight)
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    const pixelWidth = Math.round(width * ratio), pixelHeight = Math.round(height * ratio)
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth
      canvas.height = pixelHeight
    }
    gl!.viewport(0, 0, pixelWidth, pixelHeight)
    gl!.clearColor(0, 0, 0, 0)
    gl!.clear(gl!.COLOR_BUFFER_BIT | gl!.DEPTH_BUFFER_BIT)
    gl!.uniform1f(yawLocation, yaw)
    gl!.uniform1f(aspectLocation, width / height)
    gl!.uniform1f(shiftLocation, placement === 'right' ? 0.18 : 0)
    gl!.drawArrays(gl!.TRIANGLES, 0, mesh.triangleCount * 3)
  }

  draw()
  return {
    draw,
    setYaw(next: number) { yaw = Math.max(-0.32, Math.min(0.32, next)); draw(); return yaw },
    getYaw() { return yaw },
    triangleCount: mesh.triangleCount,
    dispose() { gl.deleteBuffer(buffer); gl.deleteProgram(program) },
  }
}

type Renderer = NonNullable<ReturnType<typeof createRenderer>>

/** A self-contained architectural impression; no images, external scripts or data are loaded. */
export function LibraryBuildingModel({ className, style, interactive = true, placement = 'right' }: LibraryBuildingModelProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rendererRef = useRef<Renderer | null>(null)
  const dragRef = useRef<{ x: number, yaw: number } | null>(null)
  const [ready, setReady] = useState(false)
  const [angle, setAngle] = useState(-5)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    let renderer: Renderer | null = null
    try { renderer = createRenderer(canvas, placement) } catch { renderer = null }
    if (!renderer) return
    rendererRef.current = renderer
    setReady(true)
    const observer = new ResizeObserver(() => renderer?.draw())
    observer.observe(canvas)
    const onLost = (event: Event) => { event.preventDefault(); setReady(false) }
    canvas.addEventListener('webglcontextlost', onLost)
    return () => {
      observer.disconnect()
      canvas.removeEventListener('webglcontextlost', onLost)
      renderer?.dispose()
      rendererRef.current = null
    }
  }, [placement])

  function rotate(next: number) {
    const yaw = rendererRef.current?.setYaw(next)
    if (yaw !== undefined) setAngle(Math.round(yaw * 180 / Math.PI))
  }

  return <div className={className} style={{ position: 'relative', width: '100%', aspectRatio: '1.72', ...style }}>
    <canvas
      ref={canvasRef}
      role={interactive && ready ? 'slider' : 'img'}
      aria-label={interactive && ready ? '图书馆建筑模型，可用左右方向键转动' : '图书馆建筑示意模型'}
      aria-valuemin={interactive && ready ? -18 : undefined}
      aria-valuemax={interactive && ready ? 18 : undefined}
      aria-valuenow={interactive && ready ? angle : undefined}
      tabIndex={interactive && ready ? 0 : -1}
      style={{ display: 'block', width: '100%', height: '100%', touchAction: interactive ? 'none' : 'auto', cursor: interactive && ready ? 'grab' : 'default' }}
      onPointerDown={event => {
        if (!interactive || !ready) return
        dragRef.current = { x: event.clientX, yaw: rendererRef.current?.getYaw() ?? 0 }
        event.currentTarget.setPointerCapture(event.pointerId)
      }}
      onPointerMove={event => {
        if (!dragRef.current) return
        rotate(dragRef.current.yaw + (event.clientX - dragRef.current.x) * 0.003)
      }}
      onPointerUp={() => { dragRef.current = null }}
      onPointerCancel={() => { dragRef.current = null }}
      onKeyDown={event => {
        if (!interactive || !ready) return
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault()
          rotate((rendererRef.current?.getYaw() ?? 0) + (event.key === 'ArrowRight' ? 0.055 : -0.055))
        } else if (event.key === 'Home') {
          event.preventDefault()
          rotate(-0.095)
        }
      }}
    />
    {!ready && <svg aria-label="图书馆建筑示意图" role="img" viewBox="0 0 1000 580" preserveAspectRatio="xMidYMid meet" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', transform: placement === 'right' ? 'translateX(9%) scale(0.8)' : undefined }}>
      <path d="M55 477h890v31H55z" fill="#b3aa94" />
      <path d="M95 288h810v185H95z" fill="#b45d48" />
      <path d="M95 288l49-42h712l49 42z" fill="#805044" />
      <path d="M373 201h254v269H373z" fill="#d4cab1" />
      <path d="M389 224h222v201H389z" fill="#344f53" />
      {Array.from({ length: 11 }, (_, i) => <path key={`m${i}`} d={`M${394 + i * 21} 224v201`} stroke="#d4cab1" strokeWidth="6" />)}
      <path d="M389 291h222M389 360h222" stroke="#d4cab1" strokeWidth="7" />
      <path d="M415 201a85 70 0 0 1 170 0z" fill="#58787a" stroke="#b4a16e" strokeWidth="5" />
      <path d="M500 131v70M458 143l22 58M542 143l-22 58" stroke="#c6b177" strokeWidth="4" fill="none" />
      {[115, 817].map(x => <g key={x}><path d={`M${x} 187h68v282h-68z`} fill="#b66a53" /><path d={`M${x - 9} 182h86v17h-86z`} fill="#d5c9ad" /><path d={`M${x + 15} 223h38v38h-38z`} fill="#364f50" stroke="#d5c9ad" strokeWidth="6" /></g>)}
      {Array.from({ length: 11 }, (_, i) => <g key={`w${i}`}><path d={`M${204 + i * 54} 321h22v47h-22zM${204 + i * 54} 394h22v47h-22z`} fill="#304b4b" stroke="#d3c6ad" strokeWidth="5" /></g>)}
      <path d="M350 350h300v30H350z" fill="#e2d9c3" />
      <path d="M360 380h280v88H360z" fill="#324a4a" />
      {Array.from({ length: 7 }, (_, i) => <path key={`c${i}`} d={`M${376 + i * 41} 380v88`} stroke="#e2d9c3" strokeWidth="10" />)}
      <path d="M321 470h358l75 70H246z" fill="#d8d0bd" />
      {Array.from({ length: 6 }, (_, i) => <path key={`s${i}`} d={`M${314 - i * 11} ${478 + i * 11}h${372 + i * 22}`} stroke="#a8a18f" strokeWidth="4" />)}
    </svg>}
  </div>
}

export default LibraryBuildingModel

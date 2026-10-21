/**
 * 书阶的粒子层（实验）
 * ------------------------------------------------------------
 * 五册书脊不再是一块实色，而是 8000 多颗点：位置按同一套几何算，
 * 鼠标靠近会散开，当前这一册更亮、点更大。
 * 文字仍由 DOM 出——粒子里写不出清楚的期号。
 */
import { useEffect, useRef } from "react";

const W = 860;
const H = 500;
const DX = 110;
const DY = 78;
const SPINE_W = 300;
const SPINE_H = 54;
const PER_BOOK = 2600;

type Props = { active: number; books: number };

export function StairParticles({ active, books }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const gl = useRef<WebGL2RenderingContext | null>(null);
  const uActive = useRef<WebGLUniformLocation | null>(null);
  const mouse = useRef({ x: -9999, y: -9999 });
  const target = useRef({ x: -9999, y: -9999 });

  useEffect(() => {
    const cv = canvas.current;
    if (!cv) return;
    const ctx = cv.getContext("webgl2", { antialias: true, alpha: true });
    if (!ctx) return;
    gl.current = ctx;

    const vs = `#version 300 es
      in vec2 aPos; in float aSeed; in float aBook; in float aEdge;
      uniform float uTime, uActive, uScale;
      uniform vec2 uMouse;
      out float vA;
      void main(){
        vec2 p = aPos;
        // 呼吸
        p += vec2(sin(uTime*0.7 + aSeed*9.0), cos(uTime*0.6 + aSeed*7.0)) * 0.9;
        // 鼠标推开
        vec2 d = p - uMouse;
        float dist = length(d);
        float f = smoothstep(90.0, 0.0, dist);
        p += normalize(d + 0.0001) * f * 26.0;
        // 世界坐标 → 裁剪空间
        gl_Position = vec4((p.x / ${W}.0) * 2.0 - 1.0, 1.0 - (p.y / ${H}.0) * 2.0, 0.0, 1.0);
        // 书脊：左边是实心，越往书口越散——粒子只负责"化开"的那一半
        float ramp = mix(0.06, 1.0, smoothstep(0.34, 0.92, aEdge));
        float on = step(abs(aBook - uActive), 0.5);
        gl_PointSize = (1.6 + aSeed * 1.2 + on * 0.8) * uScale * (0.7 + 0.3 * ramp);
        vA = (0.55 + aSeed * 0.25) * ramp * (0.8 + on * 0.35);
      }`;

    const fs = `#version 300 es
      precision mediump float;
      in float vA; out vec4 o;
      uniform vec3 uColor;
      void main(){
        vec2 uv = gl_PointCoord - 0.5;
        float a = smoothstep(0.5, 0.2, length(uv));
        o = vec4(uColor, a * vA);
      }`;

    const mk = (t: number, src: string) => {
      const s = ctx.createShader(t)!;
      ctx.shaderSource(s, src);
      ctx.compileShader(s);
      return s;
    };
    const prog = ctx.createProgram()!;
    ctx.attachShader(prog, mk(ctx.VERTEX_SHADER, vs));
    ctx.attachShader(prog, mk(ctx.FRAGMENT_SHADER, fs));
    ctx.linkProgram(prog);
    ctx.useProgram(prog);

    // 点位：五册书脊各一片
    const n = books * PER_BOOK;
    const pos = new Float32Array(n * 2);
    const seed = new Float32Array(n);
    const book = new Float32Array(n);
    const edge = new Float32Array(n);
    let k = 0;
    for (let b = 0; b < books; b++) {
      for (let i = 0; i < PER_BOOK; i++) {
        // 书脊在 world 里的矩形：左 = b*DX，底 = b*DY（世界 y 向下，故用 H 兜）
        const ex = Math.random();
        const x = b * DX + ex * SPINE_W;
        const y = H - (b * DY + Math.random() * SPINE_H);
        pos[k * 2] = x;
        pos[k * 2 + 1] = y;
        seed[k] = Math.random();
        book[k] = b;
        edge[k] = ex;
        k++;
      }
    }

    const buf = (data: Float32Array, loc: number, size: number) => {
      const b = ctx.createBuffer();
      ctx.bindBuffer(ctx.ARRAY_BUFFER, b);
      ctx.bufferData(ctx.ARRAY_BUFFER, data, ctx.STATIC_DRAW);
      ctx.enableVertexAttribArray(loc);
      ctx.vertexAttribPointer(loc, size, ctx.FLOAT, false, 0, 0);
    };
    buf(pos, ctx.getAttribLocation(prog, "aPos"), 2);
    buf(seed, ctx.getAttribLocation(prog, "aSeed"), 1);
    buf(book, ctx.getAttribLocation(prog, "aBook"), 1);
    buf(edge, ctx.getAttribLocation(prog, "aEdge"), 1);

    const uTime = ctx.getUniformLocation(prog, "uTime");
    uActive.current = ctx.getUniformLocation(prog, "uActive");
    const uMouse = ctx.getUniformLocation(prog, "uMouse");
    const uScale = ctx.getUniformLocation(prog, "uScale");
    const uColor = ctx.getUniformLocation(prog, "uColor");

    ctx.uniform3f(uColor, 0.149, 0.282, 0.231); // pine-300
    ctx.enable(ctx.BLEND);
    ctx.blendFunc(ctx.SRC_ALPHA, ctx.ONE_MINUS_SRC_ALPHA);

    let raf = 0;
    const t0 = performance.now();
    const draw = (now: number) => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (cv.width !== W * dpr || cv.height !== H * dpr) {
        cv.width = W * dpr;
        cv.height = H * dpr;
        ctx.viewport(0, 0, cv.width, cv.height);
      }
      mouse.current.x += (target.current.x - mouse.current.x) * 0.14;
      mouse.current.y += (target.current.y - mouse.current.y) * 0.14;

      ctx.uniform1f(uTime, (now - t0) / 1000);
      ctx.uniform2f(uMouse, mouse.current.x, mouse.current.y);
      ctx.uniform1f(uScale, dpr);
      ctx.clearColor(0, 0, 0, 0);
      ctx.clear(ctx.COLOR_BUFFER_BIT);
      ctx.drawArrays(ctx.POINTS, 0, n);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    // 指针：换到 world 坐标（画布被父级缩放过，要除掉比例）
    const onMove = (e: PointerEvent) => {
      const r = cv.getBoundingClientRect();
      target.current.x = ((e.clientX - r.left) / r.width) * W;
      target.current.y = ((e.clientY - r.top) / r.height) * H;
    };
    window.addEventListener("pointermove", onMove);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", onMove);
    };
  }, [books]);

  useEffect(() => {
    const ctx = gl.current;
    if (ctx && uActive.current) ctx.uniform1f(uActive.current, active);
  }, [active]);

  return <canvas ref={canvas} className="stair-particles" aria-hidden="true" />;
}

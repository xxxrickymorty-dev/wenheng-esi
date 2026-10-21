/**
 * 书阶的粒子层（全粒子版）
 * ------------------------------------------------------------
 * 不做"五块板子"，做一段台地：五级平台连成一条上升的阶梯地形，
 * 全部由点组成。视点是斜的，所以每条平台都有进深。
 * 文字由 DOM 出，压在每个平台的前沿——粒子里写不出清楚的期号。
 */
import { useEffect, useRef } from "react";

const W = 860;
const H = 500;

type Props = { active: number; books: number };

/** 一册一级：向右一格、向上一级。与 DOM 里的标签用同一套数。 */
export const STEP = {
  padX: 120,
  padY: 400,
  w: 150,
  rise: 78,
  depthX: 62,
  depthY: -34,
};

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
      in vec2 aPos; in float aSeed; in float aBook;
      uniform float uTime, uActive, uScale;
      uniform vec2 uMouse;
      out float vA;
      void main(){
        vec2 p = aPos;
        // 呼吸：整片台地一起轻轻浮动
        p += vec2(sin(uTime*0.55 + aSeed*8.0), cos(uTime*0.42 + aSeed*5.0)) * 1.1;
        // 鼠标扫过：把点推开，像手掠过一层尘
        vec2 d = p - uMouse;
        float dist = length(d);
        float f = smoothstep(110.0, 0.0, dist);
        p += normalize(d + 0.0001) * f * 34.0;
        gl_Position = vec4((p.x / ${W}.0) * 2.0 - 1.0, 1.0 - (p.y / ${H}.0) * 2.0, 0.0, 1.0);
        float on = step(abs(aBook - uActive), 0.5);
        gl_PointSize = (1.2 + aSeed * 0.9 + on * 0.6) * uScale;
        vA = (0.30 + aSeed * 0.22 + on * 0.34) * (0.75 + 0.25 * f);
      }`;

    const fs = `#version 300 es
      precision mediump float;
      in float vA; out vec4 o;
      uniform vec3 uColor;
      void main(){
        vec2 uv = gl_PointCoord - 0.5;
        float a = smoothstep(0.5, 0.18, length(uv));
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

    // 台地：一级一册，每级是一片斜的矩形，全部由点组成
    const PER = 3200;
    const n = books * PER;
    const pos = new Float32Array(n * 2);
    const seed = new Float32Array(n);
    const book = new Float32Array(n);
    let k = 0;
    for (let b = 0; b < books; b++) {
      for (let i = 0; i < PER; i++) {
        const u = Math.random(); // 沿级向右
        const v = Math.random(); // 进深
        const x = STEP.padX + b * STEP.w + u * STEP.w + v * STEP.depthX;
        const y =
          STEP.padY - b * STEP.rise - v * STEP.depthY - u * STEP.rise * 0.18 +
          (Math.random() - 0.5) * 3;
        pos[k * 2] = x;
        pos[k * 2 + 1] = y;
        seed[k] = Math.random();
        book[k] = b;
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

    const uTime = ctx.getUniformLocation(prog, "uTime");
    uActive.current = ctx.getUniformLocation(prog, "uActive");
    const uMouse = ctx.getUniformLocation(prog, "uMouse");
    const uScale = ctx.getUniformLocation(prog, "uScale");
    const uColor = ctx.getUniformLocation(prog, "uColor");

    ctx.uniform3f(uColor, 0.80, 0.89, 0.83);
    ctx.enable(ctx.BLEND);
    ctx.blendFunc(ctx.SRC_ALPHA, ctx.ONE); // 加色：叠起来才有雾里的光

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

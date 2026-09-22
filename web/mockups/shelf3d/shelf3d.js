/* ==================================================================
   书架的三维场景（Three.js）· v3「三层 + 焦点切换」
   ------------------------------------------------------------------
   三层＝三个报告系列（rick 定的信息架构）：
     顶  年报（每年一本）
     中  学科发展态势报告（每期一本）
     底  ESI 双月报告（每期一本）★ 已有真实四期

   切换不是"换页面"，是**相机推近 / 拉远**：
     · 概览（整柜）  →  点某层的书 / ↑↓  →  相机滑到那一层（600ms，可打断）
     · 焦点层受光最亮，非焦点层压暗 —— 用光说"你在哪层"，不用标签
     · 层间过渡用 easeInOutCubic；中途再点一次会打断上一个（不留半路状态）

   质感按 wenheng-threejs 技能的配方：IBL + 主光投影 + 五盏擦光 + 材质分层 +
   颜色贴图声明 sRGB（少了这一条整体发灰发粉，见技能里的坑 1）。
   ================================================================== */
(function () {
'use strict';

var W = window.WH3D;
if (!W) { console.error('[3D] three-bundle.js 未加载'); return; }
var THREE = W.THREE;
var OrbitControls = W.OrbitControls;
var RoundedBoxGeometry = W.RoundedBoxGeometry;
var RectAreaLightUniformsLib = W.RectAreaLightUniformsLib;
var RoomEnvironment = W.RoomEnvironment;

/* ------------------------------------------------------------------
   小工具
   ------------------------------------------------------------------ */
function seededRandom(seed) {
  var s = seed >>> 0;
  return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}
function makeCanvas(w, h) {
  var c = document.createElement('canvas');
  c.width = w; c.height = h;
  return c;
}
function hexToRgb(hex) {
  var h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function aniso(n) { return Math.min(n, renderer.capabilities.getMaxAnisotropy()); }
function easeInOutCubic(t) {
  return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

/* ------------------------------------------------------------------
   程序化贴图
   ------------------------------------------------------------------ */
/* 布面：颜色 / 法线 / 粗糙度 **同源**（同一个高度场导出）。织纹要细。 */
function clothMaps(hex, seed) {
  var S = 256, r = seededRandom(seed || 1);
  var h = new Float32Array(S * S);
  var p1 = r() * 6.283, p2 = r() * 6.283, p3 = r() * 6.283;
  var x, y;
  for (y = 0; y < S; y++) {
    for (x = 0; x < S; x++) {
      var u = x / S * Math.PI * 2, v = y / S * Math.PI * 2;
      h[y * S + x] = Math.sin(u * 72 + p1) * .34
                   + Math.sin(v * 72 + p2) * .34
                   + Math.sin((u + v) * 34 + p3) * .18
                   + Math.sin((u - v) * 19 + p1 * 2) * .14;
    }
  }
  var rgb = hexToRgb(hex);
  var colC = makeCanvas(S, S), cx = colC.getContext('2d');
  var img = cx.createImageData(S, S);
  for (var i = 0; i < S * S; i++) {
    var shade = 1 + h[i] * .055 + (r() - .5) * .035;
    img.data[i * 4] = Math.max(0, Math.min(255, rgb[0] * shade));
    img.data[i * 4 + 1] = Math.max(0, Math.min(255, rgb[1] * shade));
    img.data[i * 4 + 2] = Math.max(0, Math.min(255, rgb[2] * shade));
    img.data[i * 4 + 3] = 255;
  }
  cx.putImageData(img, 0, 0);
  var col = new THREE.CanvasTexture(colC);
  col.colorSpace = THREE.SRGBColorSpace;   /* 颜色贴图必须声明 sRGB，否则整体发灰 */
  col.wrapS = col.wrapT = THREE.RepeatWrapping;

  var nC = makeCanvas(S, S), nx = nC.getContext('2d');
  var nImg = nx.createImageData(S, S), K = 1.6;
  for (y = 0; y < S; y++) {
    for (x = 0; x < S; x++) {
      var dx = (h[y * S + ((x + 1) % S)] - h[y * S + ((x - 1 + S) % S)]) * K;
      var dy = (h[((y + 1) % S) * S + x] - h[((y - 1 + S) % S) * S + x]) * K;
      var len = Math.sqrt(dx * dx + dy * dy + 1);
      var k = (y * S + x) * 4;
      nImg.data[k] = (-dx / len * .5 + .5) * 255;
      nImg.data[k + 1] = (-dy / len * .5 + .5) * 255;
      nImg.data[k + 2] = (1 / len * .5 + .5) * 255;
      nImg.data[k + 3] = 255;
    }
  }
  nx.putImageData(nImg, 0, 0);
  var nor = new THREE.CanvasTexture(nC);
  nor.wrapS = nor.wrapT = THREE.RepeatWrapping;

  var rC = makeCanvas(S, S), rx = rC.getContext('2d');
  var rImg = rx.createImageData(S, S);
  for (i = 0; i < S * S; i++) {
    var g = Math.max(0, Math.min(255, 188 + h[i] * 56));
    rImg.data[i * 4] = rImg.data[i * 4 + 1] = rImg.data[i * 4 + 2] = g;
    rImg.data[i * 4 + 3] = 255;
  }
  rx.putImageData(rImg, 0, 0);
  var rou = new THREE.CanvasTexture(rC);
  rou.wrapS = rou.wrapT = THREE.RepeatWrapping;

  return { map: col, normalMap: nor, roughnessMap: rou };
}

/* 封面：同心波纹 + 竖排书名 + 期次 + 钤印。
   ⚠ 画布比例必须等于书封比例（0.44:0.68），否则字被纵向拉长（技能里的坑 6）。 */
function coverArtTexture(bk, baseHex) {
  var CW = 384, CH = 594;
  var c = makeCanvas(CW, CH), x = c.getContext('2d');
  var r = seededRandom(parseInt(bk.period, 10) || 202607);
  x.fillStyle = baseHex; x.fillRect(0, 0, CW, CH);

  var cx = CW * (.46 + r() * .12), cy = CH * (.40 + r() * .08);
  var rings = 7 + Math.floor(r() * 4), base = CW * (.055 + r() * .02);
  x.lineCap = 'round';
  for (var i = rings; i >= 1; i--) {
    var t = i / rings, rx = base * i * (.9 + r() * .18), ry = base * i * (1.15 + r() * .2);
    var wob = .13 + r() * .16;
    x.beginPath();
    for (var a = 0; a <= 72; a++) {
      var th = a / 72 * Math.PI * 2;
      var kk = 1 + Math.sin(th * 3 + i) * wob * .5 + Math.cos(th * 5 - i) * wob * .3;
      var px = cx + Math.cos(th) * rx * kk, py = cy + Math.sin(th) * ry * kk;
      a ? x.lineTo(px, py) : x.moveTo(px, py);
    }
    x.closePath();
    x.strokeStyle = 'rgba(244,232,206,' + (.14 + (1 - t) * .42).toFixed(2) + ')';
    x.lineWidth = 1.2 + (1 - t) * 1.5;
    x.stroke();
  }
  x.beginPath(); x.arc(cx, cy, 6, 0, Math.PI * 2);
  x.fillStyle = 'rgba(244,232,206,.75)'; x.fill();

  x.fillStyle = 'rgba(246,236,212,.94)';
  x.textAlign = 'center';
  x.font = '600 30px "Songti SC", SimSun, serif';
  var title = '学科信息参考';
  for (var k = 0; k < title.length; k++) {
    x.fillText(title[k], CW - 44, 74 + k * 40);
  }
  x.textAlign = 'left';
  x.font = '500 17px Consolas, monospace';
  x.fillStyle = 'rgba(246,236,212,.80)';
  x.fillText(String(bk.period), 26, CH - 54);
  x.font = '500 15px "Songti SC", SimSun, serif';
  x.fillStyle = 'rgba(246,236,212,.62)';
  x.fillText(bk.caption || ('第 ' + bk.no + ' 期'), 26, CH - 30);

  /* 钤印：已签发＝朱印（把"可签发"画在封面上） */
  x.fillStyle = bk.placeholder ? 'rgba(120,110,96,.85)' : 'rgba(178,58,42,.92)';
  x.fillRect(24, 26, 44, 44);
  x.fillStyle = 'rgba(255,248,238,.95)';
  x.textAlign = 'center';
  x.font = '600 30px "Songti SC", SimSun, serif';
  x.fillText(bk.placeholder ? '示' : '衡', 46, 60);

  /* 示意书：盖一道斜的水印，别让人误以为是真出的报告（技能里的"真实"门） */
  if (bk.placeholder) {
    x.save();
    x.translate(CW / 2, CH / 2);
    x.rotate(-Math.PI / 7);
    x.textAlign = 'center';
    x.font = '600 54px "Songti SC", SimSun, serif';
    x.fillStyle = 'rgba(250,242,226,.22)';
    x.fillText('示 意', 0, 0);
    x.restore();
  }

  var t2 = new THREE.CanvasTexture(c);
  t2.colorSpace = THREE.SRGBColorSpace;
  t2.anisotropy = aniso(12);
  return t2;
}

function pageEdgeTexture() {
  var S = 256, c = makeCanvas(S, S), x = c.getContext('2d');
  var r = seededRandom(9);
  x.fillStyle = '#F3EADA'; x.fillRect(0, 0, S, S);
  for (var i = 0; i < S; i += 2) {
    var v = 224 + (r() * 22 | 0);
    x.fillStyle = 'rgba(' + v + ',' + (v - 8) + ',' + (v - 28) + ',.92)';
    x.fillRect(0, i, S, 1);
  }
  var t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(1, 6);
  t.anisotropy = aniso(16);
  return t;
}

function woodTexture(seed) {
  var S = 512, c = makeCanvas(S, S), x = c.getContext('2d'), r = seededRandom(seed || 7);
  x.fillStyle = '#6B5340'; x.fillRect(0, 0, S, S);
  for (var i = 0; i < 130; i++) {
    var y = r() * S;
    x.strokeStyle = 'rgba(' + (150 + r() * 60 | 0) + ',' + (116 + r() * 46 | 0) + ',' + (80 + r() * 34 | 0) + ',' + (r() * .18 + .05).toFixed(3) + ')';
    x.lineWidth = .8 + r() * 2.2;
    x.beginPath(); x.moveTo(0, y);
    for (var xx = 0; xx <= S; xx += 16) x.lineTo(xx, y + Math.sin(xx / 46 + i) * 3);
    x.stroke();
  }
  var t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = aniso(16);
  return t;
}

function backdropTexture() {
  var Wd = 8, Ht = 256, c = makeCanvas(Wd, Ht), x = c.getContext('2d');
  var g = x.createLinearGradient(0, 0, 0, Ht);
  g.addColorStop(0, '#2a2723');
  g.addColorStop(.55, '#211e1b');
  g.addColorStop(1, '#171513');
  x.fillStyle = g; x.fillRect(0, 0, Wd, Ht);
  var t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/* ------------------------------------------------------------------
   阅览室（背景）：地板 + 台灯光池 + 左侧高窗 + 远处书架剪影
   ------------------------------------------------------------------
   纪律：**全部压暗、低对比**——背景一抢眼，书就不是主角了。
   （"花木纹背景"是最容易翻车的一处，所以地板只给微弱的木纹 + 低粗糙度，
     让灯光能在上面拖出一条光带，而不是把纹理画清楚。）
   ------------------------------------------------------------------ */
function buildRoom() {
  var g = new THREE.Group();

  /* 地板：暗木 + 低粗糙度（灯光会在上面拖出光带） */
  var floorTex = woodTexture(5);
  floorTex.repeat.set(7, 7);
  var floor = new THREE.Mesh(
    new THREE.PlaneGeometry(30, 22),
    new THREE.MeshPhysicalMaterial({
      map: floorTex, roughness: .50, metalness: .04, color: 0x6f5844
    })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(0, 0, 5.5);
  floor.receiveShadow = true;
  g.add(floor);

  /* 台灯光池：柜脚前的一片暖光晕（"有人在这看书"的暗示） */
  var pool = new THREE.Mesh(
    new THREE.PlaneGeometry(11, 7),
    new THREE.MeshBasicMaterial({
      map: contactShadowTexture(), transparent: true, opacity: .30,
      color: 0xffcf94, depthWrite: false
    })
  );
  pool.rotation.x = -Math.PI / 2;
  pool.position.set(0, .006, 1.5);
  g.add(pool);

  /* 左侧高窗：暖白的光块 + 一圈柔光晕 + 暗窗框（阅览室的标志） */
  var glow = makeCanvas(256, 256), gx = glow.getContext('2d');
  var gg = gx.createRadialGradient(128, 128, 6, 128, 128, 128);
  gg.addColorStop(0, 'rgba(255,232,196,.85)');
  gg.addColorStop(.45, 'rgba(255,226,184,.28)');
  gg.addColorStop(1, 'rgba(255,220,180,0)');
  gx.fillStyle = gg; gx.fillRect(0, 0, 256, 256);
  var glowTex = new THREE.CanvasTexture(glow);
  glowTex.colorSpace = THREE.SRGBColorSpace;
  var glowMesh = new THREE.Mesh(
    new THREE.PlaneGeometry(7, 5.4),
    new THREE.MeshBasicMaterial({ map: glowTex, transparent: true, opacity: .55,
      depthWrite: false, blending: THREE.AdditiveBlending })
  );
  glowMesh.position.set(-2.85, 2.0, -1.4);
  glowMesh.rotation.y = .9;
  g.add(glowMesh);

  var pane = new THREE.Mesh(
    new THREE.PlaneGeometry(1.05, 2.5),
    new THREE.MeshBasicMaterial({ color: 0xffe6c0, transparent: true, opacity: .34 })
  );
  pane.position.set(-2.9, 2.05, -1.35);
  pane.rotation.y = .9;
  g.add(pane);

  /* 远处书架剪影：竖条纹理的暗块，低对比、只说"这里还有书" */
  var sil = makeCanvas(256, 256), sx2 = sil.getContext('2d');
  sx2.fillStyle = '#1b1815'; sx2.fillRect(0, 0, 256, 256);
  var r2 = seededRandom(21);
  for (var i = 0; i < 46; i++) {
    var w = 3 + r2() * 7, x0 = r2() * 256;
    sx2.fillStyle = 'rgba(' + (70 + r2() * 60 | 0) + ',' + (58 + r2() * 46 | 0) + ',' + (44 + r2() * 34 | 0) + ',' + (r2() * .5 + .25).toFixed(2) + ')';
    sx2.fillRect(x0, 24, w, 208);
  }
  sx2.fillStyle = '#141110';
  for (var b2 = 0; b2 < 4; b2++) sx2.fillRect(0, 24 + b2 * 52 + 44, 256, 8);
  var silTex = new THREE.CanvasTexture(sil);
  silTex.colorSpace = THREE.SRGBColorSpace;
  [-1, 1].forEach(function (s) {
    var m = new THREE.Mesh(
      new THREE.PlaneGeometry(2.6, 2.6),
      new THREE.MeshBasicMaterial({ map: silTex, transparent: true, opacity: .26 })
    );
    m.position.set(s * 3.7, 1.5, -2.3);
    m.rotation.y = -s * .45;
    g.add(m);
  });

  return g;
}
function contactShadowTexture() {
  var S = 128, c = makeCanvas(S, S), x = c.getContext('2d');
  var g = x.createRadialGradient(S / 2, S / 2, 2, S / 2, S / 2, S / 2);
  g.addColorStop(0, 'rgba(0,0,0,.85)');
  g.addColorStop(.55, 'rgba(0,0,0,.35)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  x.fillStyle = g; x.fillRect(0, 0, S, S);
  return new THREE.CanvasTexture(c);
}

/* 空位：层板上的虚线方框 —— 「这一格还在等它那一期」
   ⚠ 线要画粗（14px/256）：细虚线在远处被 mipmap 平均掉，等于没画（实测过）。 */
function emptySlotTexture() {
  var Wd = 256, Ht = 180, c = makeCanvas(Wd, Ht), x = c.getContext('2d');
  x.clearRect(0, 0, Wd, Ht);
  x.setLineDash([22, 16]);
  x.lineWidth = 14;
  x.strokeStyle = 'rgba(242,226,192,.88)';
  x.strokeRect(12, 12, Wd - 24, Ht - 24);
  var t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = aniso(16);
  return t;
}

/* ------------------------------------------------------------------
   调色板与层配置
   ------------------------------------------------------------------ */
var PALETTE = {
  '202607': { vol: '#B8422C', deep: '#8A2A18', lift: '#D65A38' },
  '202605': { vol: '#8A6A34', deep: '#5C441E', lift: '#B08C4C' },
  '202603': { vol: '#2E4B5E', deep: '#1A2E3C', lift: '#446C82' },
  '202601': { vol: '#3F5C42', deep: '#25362A', lift: '#5B7F60' },
  'TREND':  { vol: '#5B4A6B', deep: '#3A2E48', lift: '#7C6A8E' },   /* 学科态势：紫 */
  'ANNUAL': { vol: '#4A5A63', deep: '#2E3B42', lift: '#6B7F8A' }    /* 年报：青灰 */
};
function paletteOf(p) { return PALETTE[p] || PALETTE['202607']; }
var FOIL_GOLD = 0xe8cf9a;

var D = {
  bookW: .44, bookH: .68, bookT: .105,
  slot: .52,          /* 架位间距：封面朝外，必须 > 书宽 */
  boardT: .028,
  headGap: .17,
  depth: .27,
  plinth: .075,
  sideT: .03
};
var SLOTS = 5;

/* 三层＝三个系列，**从下往上**排（数组 0 是最底层）。
   rick 2026-09-22 定：ESI 在最上、年报在最下。
   每层用 items 描述（从左到右）：
     {kind:'dense', count:n, label:'更早 34 期'}  密排书脊——表示"还有很多期，放不下"
     {kind:'book', period, no}                   封面朝外的真书
     {kind:'empty'}                              虚线空位（这一期还没出刊）
   为什么用密排：38 期书架放不下，真图书馆也是"最近几本立着、更早的密排"。 */
var DEFAULT_TIERS = [
  { key: 'annual', label: '年报', short: '年报', sub: '每年一本 · 待出刊',
    items: [{ kind: 'empty' }, { kind: 'empty' },
            { kind: 'book', period: 'ANNUAL', no: 1, placeholder: true, caption: '示意 · 未出刊' },
            { kind: 'empty' }, { kind: 'empty' }] },
  { key: 'trend', label: '学科发展态势报告', short: '学科态势', sub: '每期一本 · 待出刊',
    items: [{ kind: 'empty' }, { kind: 'empty' },
            { kind: 'book', period: 'TREND', no: 1, placeholder: true, caption: '示意 · 未出刊' },
            { kind: 'empty' }, { kind: 'empty' }] },
  { key: 'esi', label: 'ESI 双月报告', short: 'ESI 双月', sub: '已出 38 期',
    items: [{ kind: 'dense', count: 5, label: '更早 34 期' },
            { kind: 'book', period: '202601', no: 35 },
            { kind: 'book', period: '202603', no: 36 },
            { kind: 'book', period: '202605', no: 37 },
            { kind: 'book', period: '202607', no: 38 },
            { kind: 'empty' }] }
];

/* ------------------------------------------------------------------
   场景
   ------------------------------------------------------------------ */
var scene, camera, renderer, controls, root, rafId = null;
var tiers = [];                 /* [{group, books:[], y, mats:[]}] */
var focusIndex = 0;             /* 当前焦点层（0 = 最底） */
var tween = null;               /* 相机过渡状态 */
var clock = null;

function tierY(i) {             /* 第 i 层：层板上表面高度 */
  return D.plinth + D.boardT + i * (D.bookH + D.headGap + D.boardT);
}

/* ------------------------------------------------------------------
   打光（配方：IBL + 一盏投影主光 + 五盏各自对准部件的擦光）
   ------------------------------------------------------------------ */
function buildLights() {
  var pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), .04).texture;
  scene.environmentIntensity = .55;
  RectAreaLightUniformsLib.init();

  var key = new THREE.DirectionalLight(0xffe8c2, 1.25);
  key.position.set(-2.6, 3.6, 1.6);      /* 偏侧：否则影子全落在书背后看不见 */
  key.target.position.set(0, 1.3, 0);
  scene.add(key.target);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -2.8;
  key.shadow.camera.right = 2.8;
  key.shadow.camera.top = 3.4;
  key.shadow.camera.bottom = -.4;
  key.shadow.camera.near = .5;
  key.shadow.camera.far = 22;
  key.shadow.camera.updateProjectionMatrix();
  scene.add(key);

  var rakes = [
    { c: 0xfff1e0, i: .70, w: 1.5, h: 1.3, p: [-1.0, 1.15, 1.15] },
    { c: 0xffd9a0, i: .95, w: .30, h: 1.1, p: [-1.15, .80, .55] },
    { c: 0xffe6c0, i: .55, w: .26, h: .95, p: [.55, .95, .95] },
    { c: 0xfff4e6, i: .50, w: .30, h: .85, p: [1.05, .55, .45] },
    { c: 0xd9e2ea, i: .40, w: 1.2, h: 1.0, p: [0, 1.05, -1.35] }
  ];
  rakes.forEach(function (r) {
    var l = new THREE.RectAreaLight(r.c, r.i, r.w, r.h);
    l.position.set(r.p[0], r.p[1] + 1.1, r.p[2]);
    l.lookAt(0, 1.4, 0);
    scene.add(l);
  });

  var cold = new THREE.DirectionalLight(0xd8e3e7, .28);
  cold.position.set(2.4, 2.2, -1.2);
  scene.add(cold);

  var hemi = new THREE.HemisphereLight(0xfff8e8, 0x5b4030, .35);
  scene.add(hemi);
}

/* ---------- 一本书 ---------- */
function buildBook(bk, dimmable) {
  var p = paletteOf(bk.period);
  var g = new THREE.Group();
  var seed = parseInt(bk.period, 10) || 2026;

  var cloth = clothMaps(p.vol, seed);
  var clothMat = new THREE.MeshPhysicalMaterial({
    map: cloth.map, normalMap: cloth.normalMap, roughnessMap: cloth.roughnessMap,
    roughness: .98, metalness: .02, sheen: .30, sheenRoughness: .72,
    sheenColor: new THREE.Color(FOIL_GOLD)
  });
  clothMat.normalScale.set(.6, .6);

  var clothSpine = clothMaps(p.deep, seed + 11);
  var spineMat = new THREE.MeshPhysicalMaterial({
    map: clothSpine.map, normalMap: clothSpine.normalMap, roughnessMap: clothSpine.roughnessMap,
    roughness: .98, metalness: .02, sheen: .30, sheenRoughness: .72,
    sheenColor: new THREE.Color(FOIL_GOLD)
  });
  spineMat.normalScale.set(.6, .6);

  var paperMat = new THREE.MeshPhysicalMaterial({
    map: pageEdgeTexture(), roughness: .95, metalness: 0, sheen: .025
  });

  var blockW = D.bookW - .022, blockH = D.bookH - .018, blockD = D.bookT * .72;
  var block = new THREE.Mesh(new THREE.BoxGeometry(blockW, blockH, blockD), paperMat);
  block.position.z = -D.bookT * .06;
  block.castShadow = true;
  g.add(block);

  var boardGeo = new RoundedBoxGeometry(D.bookW, D.bookH, .014, 3, .003);
  var frontMat = new THREE.MeshPhysicalMaterial({
    map: coverArtTexture(bk, p.vol),
    roughness: .92, metalness: .035, clearcoat: .06, clearcoatRoughness: .5, sheen: .26
  });
  var front = new THREE.Mesh(boardGeo, frontMat);
  front.position.z = D.bookT / 2 - .007;
  front.castShadow = true;
  g.add(front);

  var back = new THREE.Mesh(boardGeo, clothMat);
  back.position.z = -D.bookT / 2 + .007;
  back.castShadow = true;
  g.add(back);

  var spineGeo = new RoundedBoxGeometry(D.bookT * .96, D.bookH, .05, 3, .008);
  var spine = new THREE.Mesh(spineGeo, spineMat);
  spine.rotation.y = Math.PI / 2;
  spine.position.x = -D.bookW / 2 + .012;
  spine.castShadow = true;
  g.add(spine);

  var bandMat = new THREE.MeshPhysicalMaterial({
    color: p.lift, roughness: .58, metalness: .16, sheen: .14
  });
  [1, -1].forEach(function (s) {
    var b = new THREE.Mesh(
      new THREE.CylinderGeometry(.011, .011, blockD * .92, 12), bandMat);
    b.rotation.z = Math.PI / 2;
    b.rotation.y = Math.PI / 2;
    b.position.set(-blockW / 2 + .004, s * (blockH / 2 - .012), -.006);
    g.add(b);
  });

  var cs = new THREE.Mesh(
    new THREE.PlaneGeometry(D.bookT * 2.9, D.depth * .58),
    new THREE.MeshBasicMaterial({
      map: contactShadowTexture(), transparent: true, opacity: .85,
      depthWrite: false, color: 0x140d08
    })
  );
  cs.rotation.x = -Math.PI / 2;
  cs.position.set(0, -D.bookH / 2 + .003, .004);
  g.add(cs);

  var cast = new THREE.Mesh(
    new THREE.PlaneGeometry(D.bookT * 3.4, D.depth * .78),
    new THREE.MeshBasicMaterial({
      map: contactShadowTexture(), transparent: true, opacity: .85,
      depthWrite: false, color: 0x0f0906
    })
  );
  cast.rotation.x = -Math.PI / 2;
  cast.position.set(.21, -D.bookH / 2 + .002, -.04);
  g.add(cast);

  g.userData = { period: bk.period, bk: bk, placeholder: !!bk.placeholder };
  g.rotation.y = -.20;                    /* 斜 ~11°：不斜就是一张"平卡" */
  /* 焦点切换时按这个乘数压暗非焦点层的书（贴图 × color，改 color 最省事） */
  g.userData.mats = [clothMat, spineMat, paperMat, frontMat, bandMat];
  return g;
}

/* 本层各件的位置与宽度（以层中心为 0） */
var BOOK_W = .46, DENSE_W = .082, ITEM_GAP = .05;
function tierLayout(tier) {
  var widths = tier.items.map(function (it) {
    return it.kind === 'dense' ? it.count * DENSE_W : BOOK_W;
  });
  var total = widths.reduce(function (a, b) { return a + b; }, 0)
            + ITEM_GAP * (tier.items.length - 1);
  var x = -total / 2, list = [];
  tier.items.forEach(function (it, k) {
    list.push({ item: it, x: x + widths[k] / 2, w: widths[k] });
    x += widths[k] + ITEM_GAP;
  });
  return { list: list, total: total };
}

/* 密排书脊：表示"还有更多期，放不下"。薄、只做布面 + 一条烫金细线，省开销。 */
function buildDenseRun(count) {
  var g = new THREE.Group();
  var DENSE_T = .066, pitch = DENSE_W;
  var start = -(count - 1) * pitch / 2;
  var PAL = ['#B8422C', '#8A6A34', '#2E4B5E', '#3F5C42', '#7A3B2E'];
  for (var k = 0; k < count; k++) {
    var cm = clothMaps(PAL[k % PAL.length], 500 + k * 7);
    var mat = new THREE.MeshPhysicalMaterial({
      map: cm.map, normalMap: cm.normalMap, roughnessMap: cm.roughnessMap,
      roughness: .98, metalness: .02, sheen: .30, sheenRoughness: .72,
      sheenColor: new THREE.Color(FOIL_GOLD)
    });
    mat.normalScale.set(.6, .6);
    var b = new THREE.Mesh(
      new THREE.BoxGeometry(DENSE_T, D.bookH - .035, D.depth * .8), mat);
    b.position.set(start + k * pitch, 0, .01);
    b.castShadow = true;
    g.add(b);
    /* 书脊上的烫金细线（真书脊上就是这么一条） */
    var foil = new THREE.Mesh(
      new THREE.PlaneGeometry(DENSE_T * .42, .34),
      new THREE.MeshPhysicalMaterial({
        color: 0xe8cf9a, metalness: .90, roughness: .22,
        transparent: true, opacity: .8
      }));
    foil.position.set(b.position.x, .10, D.depth * .4 + .012);
    g.add(foil);
  }
  g.userData.mats = g.children.map(function (o) { return o.material; });
  return g;
}

/* 案头小标签：写在层板前沿的一行小字（如「更早 34 期」） */
function makeCaption(text, wm) {
  var Wd = 512, Ht = 64, c = makeCanvas(Wd, Ht), x = c.getContext('2d');
  x.clearRect(0, 0, Wd, Ht);
  x.textAlign = 'center';
  x.font = '500 40px "Songti SC", SimSun, serif';
  x.fillStyle = 'rgba(236,220,178,.72)';
  x.fillText(text, Wd / 2, 46);
  var tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  var m = new THREE.Mesh(
    new THREE.PlaneGeometry(wm, wm * Ht / Wd),
    new THREE.MeshBasicMaterial({ map: tex, transparent: true }));
  return m;
}

/* ---------- 一层 ---------- */
function buildTier(tier, i, innerW) {
  var g = new THREE.Group();
  var y0 = tierY(i);
  var outerW = innerW + .14;

  var wood = new THREE.MeshPhysicalMaterial({
    map: woodTexture(31), roughness: .62, metalness: .02, sheen: .10, color: 0xd9c3a6
  });

  /* 层板 */
  var board = new THREE.Mesh(new THREE.BoxGeometry(outerW, D.boardT, D.depth), wood);
  board.position.set(0, y0 - D.boardT / 2, 0);
  board.castShadow = true;
  board.receiveShadow = true;
  g.add(board);

  /* 层标：层板前沿左侧的一枚小铜牌（只写系列短名）。
     ⚠ 别做大：做成 2 米宽就成"大字报"了（第一版就是这么翻车的）。 */
  var plate = makeCanvas(512, 96), px = plate.getContext('2d');
  px.clearRect(0, 0, 512, 96);
  px.textAlign = 'left';
  px.font = '600 52px "Songti SC", SimSun, serif';
  px.fillStyle = 'rgba(236,220,178,.95)';
  px.fillText(tier.short || tier.label, 4, 66);
  px.font = '400 30px "Microsoft YaHei", sans-serif';
  px.fillStyle = 'rgba(236,220,178,.60)';
  px.fillText(tier.sub, 250, 64);
  var plateTex = new THREE.CanvasTexture(plate);
  plateTex.colorSpace = THREE.SRGBColorSpace;
  var plateMesh = new THREE.Mesh(
    new THREE.PlaneGeometry(.34, .34 * 96 / 512),
    new THREE.MeshBasicMaterial({ map: plateTex, transparent: true })
  );
  plateMesh.position.set(-outerW / 2 + .28, y0 - D.boardT / 2 - .001, D.depth / 2 + .005);
  g.add(plateMesh);

  /* 逐件摆：密排段 / 封面朝外的书 / 虚线空位 */
  var L = tierLayout(tier);
  var books = [], mats = [];
  var emptyTex = emptySlotTexture();
  L.list.forEach(function (slot) {
    var it = slot.item;
    if (it.kind === 'book') {
      var b = buildBook(it, true);
      b.position.set(slot.x, y0 + D.bookH / 2, .01);
      b.userData.baseY = b.position.y;
      b.userData.tierIndex = i;
      g.add(b);
      books.push(b);
      mats = mats.concat(b.userData.mats);
    } else if (it.kind === 'dense') {
      var run = buildDenseRun(it.count);
      run.position.set(slot.x, y0 + (D.bookH - .035) / 2, 0);
      g.add(run);
      mats = mats.concat(run.userData.mats);
      if (it.label) {
        var cap = makeCaption(it.label, slot.w * .95);
        cap.position.set(slot.x, y0 - D.boardT / 2 - .001, D.depth / 2 + .006);
        g.add(cap);
      }
    } else {
      var m = new THREE.Mesh(
        new THREE.PlaneGeometry(slot.w * .82, D.depth * .7),
        new THREE.MeshBasicMaterial({
          map: emptyTex, transparent: true, opacity: .95, depthWrite: false
        })
      );
      m.rotation.x = -Math.PI / 2;
      m.position.set(slot.x, y0 + .004, .01);
      g.add(m);
    }
  });

  return { group: g, books: books, mats: mats, y: y0, outerW: outerW };
}

/* ---------- 柜体：背板 + 三层 + 踢脚 ---------- */
function buildShelf() {
  var cfg = (window.WH_DATA && window.WH_DATA.tiers) || DEFAULT_TIERS;
  var g = new THREE.Group();
  /* 统一层宽＝最宽那层（各层件数不同，宽度要对齐才像柜子） */
  var innerW = 0;
  cfg.forEach(function (tier) { innerW = Math.max(innerW, tierLayout(tier).total); });
  var outerW = innerW + .14;
  var topY = tierY(cfg.length - 1) + D.bookH + .16;
  var outerH = topY + D.boardT;

  var woodDark = new THREE.MeshPhysicalMaterial({
    map: woodTexture(77), roughness: .74, metalness: .02, color: 0x8a755e, sheen: .08
  });

    /* 背板去掉了（rick 2026-09-22）：柜子通透，后面直接是阅览室的暗处 */

  /* 侧板：薄，只用来收边 */
  [-1, 1].forEach(function (s) {
    var side = new THREE.Mesh(new THREE.BoxGeometry(D.sideT, outerH, D.depth), woodDark);
    side.position.set(s * (outerW / 2 - D.sideT / 2), outerH / 2, 0);
    side.receiveShadow = true;
    g.add(side);
  });

  /* 顶板 + 踢脚 */
  var top = new THREE.Mesh(new THREE.BoxGeometry(outerW + .04, .03, D.depth + .03), woodDark);
  top.position.set(0, topY + .015, .012);
  top.castShadow = true;
  g.add(top);
  var plinth = new THREE.Mesh(new THREE.BoxGeometry(outerW - .04, D.plinth, D.depth + .02), woodDark);
  plinth.position.set(0, D.plinth / 2, .008);
  g.add(plinth);

  /* 三层（数据顺序＝从下往上） */
  cfg.forEach(function (tier, i) {
    var t = buildTier(tier, i, innerW);
    g.add(t.group);
    tiers.push(t);
  });

  return { group: g, outerW: outerW, outerH: outerH, topY: topY };
}

/* ------------------------------------------------------------------
   焦点与相机
   ------------------------------------------------------------------ */
var VIEW = {
  overview: { pos: [0, 1.45, 5.05], target: [0, 1.34, 0] },
  focused: function (i) {
    var y = tierY(i) + D.bookH / 2;
    return { pos: [0, y + .08, 2.55], target: [0, y - .02, 0] };
  }
};
var OVERVIEW_Z = 5.05;          /* 相机比这近 → 算"推近"状态 */

function applyFocusVisuals() {
  tiers.forEach(function (t, i) {
    var f = (i === focusIndex) ? 1 : .55;
    (t.mats || []).forEach(function (m) {
      if (!m.userData.base) m.userData.base = m.color.clone();
      m.color.copy(m.userData.base).multiplyScalar(f);
    });
  });
}

function moveCamera(dest, ms) {
  tween = {
    t0: performance.now(), ms: ms,
    from: { p: camera.position.clone(), t: controls.target.clone() },
    to: { p: new THREE.Vector3(dest.pos[0], dest.pos[1], dest.pos[2]),
          t: new THREE.Vector3(dest.target[0], dest.target[1], dest.target[2]) }
  };
  if (controls) controls.enabled = false;
}

function stepTween(now) {
  if (!tween) return;
  var k = Math.min(1, (now - tween.t0) / tween.ms);
  var e = easeInOutCubic(k);
  camera.position.lerpVectors(tween.from.p, tween.to.p, e);
  controls.target.lerpVectors(tween.from.t, tween.to.t, e);
  camera.lookAt(controls.target);
  if (k >= 1) {
    tween = null;
    if (controls) controls.enabled = true;
  }
}

/* 概览 ↔ 某层。再调一次会**打断**上一个过渡（不留半路状态） */
function focus(i, opts) {
  opts = opts || {};
  if (i == null) {
    if (camera.position.z < OVERVIEW_Z - .6) moveCamera(VIEW.overview, 620);
    return;
  }
  focusIndex = Math.max(0, Math.min(tiers.length - 1, i));
  applyFocusVisuals();
  if (opts.visualOnly) { render(); return; }
  moveCamera(VIEW.focused(focusIndex), 620);
}

/* 概览：整柜拉远 */
function overview() {
  if (camera.position.z >= OVERVIEW_Z - .6) return;
  moveCamera(VIEW.overview, 620);
}

/* ------------------------------------------------------------------
   初始化
   ------------------------------------------------------------------ */
/* ------------------------------------------------------------------
   Blender 道具（增量③起）：从 meshes.js 读顶点，摆进阅览室
   几何在 Blender 里做（wh_models.py），这里只管「读进来 + 摆位 + 上材质」。
   ------------------------------------------------------------------ */
function decodeF32(s) {
  var bin = atob(s), u8 = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Float32Array(u8.buffer);
}
function decodeU16(s) {
  var bin = atob(s), u8 = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Uint16Array(u8.buffer);
}
function geomFromPart(part) {
  var g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(decodeF32(part.pos), 3));
  g.setAttribute('normal', new THREE.BufferAttribute(decodeF32(part.nrm), 3));
  g.setAttribute('uv', new THREE.BufferAttribute(decodeF32(part.uv), 2));
  g.setIndex(new THREE.BufferAttribute(decodeU16(part.idx), 1));
  return g;
}

/* 阅览桌：右下前景、**只露一角**（被画幅裁切）——整张摆进来就成了玩具箱 */
function buildReadingDesk() {
  var g = new THREE.Group();
  var entry = (window.WH_MESHES || {})['reading-desk'];
  if (!entry) return g;                 /* meshes.js 没跟上就安静跳过，不挡书架 */

  var wood = new THREE.MeshPhysicalMaterial({
    map: woodTexture(12), roughness: .62, metalness: .04, color: 0x7a5f45
  });
  var metal = new THREE.MeshPhysicalMaterial({
    color: 0x8a8b8e, roughness: .19, metalness: .90
  });

  entry.parts.forEach(function (part) {
    var mat = (part.mat === 'metal') ? metal : wood;
    var mesh = new THREE.Mesh(geomFromPart(part), mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    g.add(mesh);
  });

  /* 桌下压一片接触影（软件渲染下实时阴影不出影，见技能坑 4） */
  var cs = new THREE.Mesh(
    new THREE.PlaneGeometry(1.5, 1.0),
    new THREE.MeshBasicMaterial({
      map: contactShadowTexture(), transparent: true, opacity: .5,
      color: 0x000000, depthWrite: false
    })
  );
  cs.rotation.x = -Math.PI / 2;
  cs.position.y = .004;
  g.add(cs);

  /* 摆位：右下前景；斜 12°（不斜就是一张平卡，看不到厚度） */
  g.position.set(1.5, 0, 1.7);
  g.rotation.y = -.21;
  return g;
}

function init(canvasEl) {
  if (!canvasEl) return false;
  if (!renderer) {
    renderer = new THREE.WebGLRenderer({ canvas: canvasEl, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = .95;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  }
  var w = canvasEl.clientWidth || 800, h = canvasEl.clientHeight || 600;
  renderer.setSize(w, h, false);

  if (!scene) {
    scene = new THREE.Scene();
    clock = new THREE.Clock();
    camera = new THREE.PerspectiveCamera(32, w / h, .05, 60);
    buildLights();
    var built = buildShelf();
    root = built.group;
    scene.add(root);
    scene.add(buildRoom());          /* 阅览室背景（全部压暗、低对比） */
    scene.add(buildReadingDesk());   /* 阅览桌（增量③）：右下前景，只露一角 */
    /* 默认焦点＝ESI 层（最上面那层，主系列） */
    focusIndex = tiers.length - 1;

    controls = new OrbitControls(camera, canvasEl);
    controls.enableDamping = true;
    controls.dampingFactor = .08;
    controls.minDistance = 1.2;
    controls.maxDistance = 7.5;
    controls.maxPolarAngle = Math.PI * .54;
    controls.target.set(0, 1.34, 0);
    camera.position.set(0, 1.45, 5.05);       /* 默认：概览（整柜） */
    controls.update();

    applyFocusVisuals();
  } else {
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  render();
  return true;
}

function render() {
  if (!renderer || !scene) return;
  stepTween(performance.now());
  controls && controls.enabled && controls.update();
  renderer.render(scene, camera);
}
function loop() {
  render();
  rafId = requestAnimationFrame(loop);
}
function start() { if (!rafId) loop(); }
function stop() { if (rafId) { cancelAnimationFrame(rafId); rafId = null; } }

/* ------------------------------------------------------------------
   拾取
   ------------------------------------------------------------------ */
var raycaster = new THREE.Raycaster();
var pointerNDC = new THREE.Vector2();

function allBooks() {
  var out = [];
  tiers.forEach(function (t) { out = out.concat(t.books); });
  return out;
}

function projectGroupRect(obj) {
  var box = new THREE.Box3().setFromObject(obj);
  var min = box.min, max = box.max;
  var xs = [], ys = [];
  for (var i = 0; i < 8; i++) {
    var v = new THREE.Vector3(
      (i & 1) ? max.x : min.x, (i & 2) ? max.y : min.y, (i & 4) ? max.z : min.z);
    v.project(camera);
    var el = renderer.domElement;
    xs.push((v.x * .5 + .5) * el.clientWidth);
    ys.push((-v.y * .5 + .5) * el.clientHeight);
  }
  var r = renderer.domElement.getBoundingClientRect();
  return {
    left: r.left + Math.min.apply(null, xs), top: r.top + Math.min.apply(null, ys),
    width: Math.max.apply(null, xs) - Math.min.apply(null, xs),
    height: Math.max.apply(null, ys) - Math.min.apply(null, ys)
  };
}

/* 返回 {tierIndex, period, rect} 或 {tierIndex: n}（点到层板/空位）或 null */
function hitTest(clientX, clientY) {
  if (!renderer || !camera) return null;
  var r = renderer.domElement.getBoundingClientRect();
  pointerNDC.x = ((clientX - r.left) / r.width) * 2 - 1;
  pointerNDC.y = -((clientY - r.top) / r.height) * 2 + 1;
  raycaster.setFromCamera(pointerNDC, camera);
  var hits = raycaster.intersectObjects(root.children, true);
  if (!hits.length) return null;
  var o = hits[0].object;
  var books = allBooks();
  while (o && books.indexOf(o) < 0) o = o.parent;
  if (o) {
    return {
      tierIndex: o.userData.tierIndex, period: o.userData.period,
      placeholder: o.userData.placeholder, rect: projectGroupRect(o)
    };
  }
  /* 没点中书 → 看落在哪一层的柜体上，按高度判层 */
  var p = hits[0].point;
  var idx = 0;
  for (var i = 0; i < tiers.length; i++) {
    if (p.y >= tierY(i) - D.boardT - .04) idx = i;
  }
  return { tierIndex: idx };
}

window.WH_SHELF3D = {
  init: init, render: render, start: start, stop: stop,
  hitTest: hitTest, focus: focus, overview: overview,
  tiers: function () {
    return tiers.map(function (t, i) {
      return { index: i, y: t.y, books: t.books.length };
    });
  },
  focusIndex: function () { return focusIndex; },
  books: function () { return allBooks().length; },
  info: function () {
    return {
      revision: THREE.REVISION, tiers: tiers.length, books: allBooks().length,
      drawn: renderer ? renderer.info.render.triangles : 0,
      shadows: renderer ? renderer.shadowMap.enabled : false,
      cameraZ: camera ? +camera.position.z.toFixed(2) : null
    };
  },
  scene: function () { return scene; },
  camera: function () { return camera; },
  renderer: function () { return renderer; }
};
})();

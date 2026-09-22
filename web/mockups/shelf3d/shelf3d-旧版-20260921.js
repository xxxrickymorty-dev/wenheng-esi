/* ==================================================================
   书架的三维场景（Three.js）
   ------------------------------------------------------------------
   为什么另起一个文件、而不是继续用 CSS 3D：
   rick 看过参考站后判定 CSS 版「太丑」—— 差别不在结构，在**材质**。
   参考站的布面、烫金、纸口都是 PBR 材质 + 程序化贴图 + 环境光照下的
   真实高光，CSS 的渐变模拟不出这一层。所以这一版按参考站的做法重做：
     · 程序化几何（书板 / 书脊 / 铰链 / 页芯 / 堵头布 / 书签），不下模型
     · 程序化贴图（布纹 / 木纹 / 纸边 / 烫金），零素材文件
     · RoomEnvironment 提供 IBL + RectAreaLight 做柔光
   参考站本身也没有用 GLTFLoader（其源码里 gltf 出现 0 次），
   书与架子都是代码拼出来的 —— 与我们这套思路一致。

   与仓库的关系：
     · three-bundle.js = three@0.165.0 + 4 个 addons，esbuild 打成 IIFE
       （file:// 下 ES module 会被 CORS 拦，必须非模块化）
     · 本文件只负责「书架 + 书」的三维呈现与交互
     · 翻开后的图表与文字仍走 StPageFlip（DOM）—— 那是要给人读的报告，
       做成 3D 贴图会牺牲可读性，这是与参考站**有意不同**的一处
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
   程序化贴图：布面 / 木纹 / 纸口
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
/* 布面：经纬交织 + 细噪点。书封与书脊都靠它，是「精装书」的第一眼质感 */
function clothTexture(hex, seed) {
  var S = 256, c = makeCanvas(S, S), x = c.getContext('2d'), r = seededRandom(seed || 1);
  x.fillStyle = hex; x.fillRect(0, 0, S, S);
  for (var i = 0; i < S; i += 2) {
    x.fillStyle = 'rgba(255,255,255,' + (r() * .05 + .012).toFixed(3) + ')';
    x.fillRect(i, 0, 1, S);
  }
  for (var j = 0; j < S; j += 2) {
    x.fillStyle = 'rgba(0,0,0,' + (r() * .07 + .015).toFixed(3) + ')';
    x.fillRect(0, j, S, 1);
  }
  for (var k = 0; k < 2600; k++) {
    x.fillStyle = 'rgba(0,0,0,' + (r() * .05).toFixed(3) + ')';
    x.fillRect(r() * S | 0, r() * S | 0, 1, 1);
  }
  var t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}
/* 封面图案：同心波纹（linocut 味），每卷一张（seed = 期次） */
function coverArtTexture(period, baseHex) {
  var S = 512, c = makeCanvas(S, S), x = c.getContext('2d');
  var r = seededRandom(parseInt(period, 10) || 202607);
  x.fillStyle = baseHex; x.fillRect(0, 0, S, S);
  var cx = S * (.42 + r() * .16), cy = S * (.36 + r() * .1);
  var rings = 8 + Math.floor(r() * 4), base = S * (.05 + r() * .025);
  x.lineCap = 'round';
  for (var i = rings; i >= 1; i--) {
    var t = i / rings, rx = base * i * (.9 + r() * .2), ry = base * i * (1.3 + r() * .22);
    var wob = .14 + r() * .18;
    x.beginPath();
    for (var a = 0; a <= 72; a++) {
      var th = a / 72 * Math.PI * 2;
      var kk = 1 + Math.sin(th * 3 + i) * wob * .5 + Math.cos(th * 5 - i) * wob * .3;
      var px = cx + Math.cos(th) * rx * kk, py = cy + Math.sin(th) * ry * kk;
      a ? x.lineTo(px, py) : x.moveTo(px, py);
    }
    x.closePath();
    x.strokeStyle = 'rgba(240,226,196,' + (.16 + (1 - t) * .5).toFixed(2) + ')';
    x.lineWidth = 1.4 + (1 - t) * 1.6;
    x.stroke();
  }
  x.beginPath(); x.arc(cx, cy, 7, 0, Math.PI * 2);
  x.fillStyle = 'rgba(240,226,196,.8)'; x.fill();
  return new THREE.CanvasTexture(c);
}
/* 书脊烫金：竖排书名 + 期号。做成带透明通道的贴图，叠在书脊布面上 */
function spineFoilTexture(bk) {
  var Wd = 128, Ht = 1024;
  var c = makeCanvas(Wd, Ht), x = c.getContext('2d');
  x.clearRect(0, 0, Wd, Ht);
  x.fillStyle = 'rgba(232,214,166,.95)';
  x.textAlign = 'center';
  x.font = '600 62px "Songti SC", SimSun, serif';
  var title = '学科信息参考';
  for (var i = 0; i < title.length; i++) {
    x.fillText(title[i], Wd / 2, 130 + i * 78);
  }
  x.font = '500 30px Consolas, monospace';
  x.fillStyle = 'rgba(232,214,166,.78)';
  x.fillText('第' + bk.no + '期', Wd / 2, Ht - 86);
  var t = new THREE.CanvasTexture(c);
  return t;
}
/* 页口：细密横纹 —— 一摞纸的侧切面 */
function pageEdgeTexture() {
  var S = 256, c = makeCanvas(S, S), x = c.getContext('2d');
  x.fillStyle = '#F3EADA'; x.fillRect(0, 0, S, S);
  for (var i = 0; i < S; i += 2) {
    var v = 226 + Math.random() * 20 | 0;
    x.fillStyle = 'rgba(' + v + ',' + (v - 8) + ',' + (v - 26) + ',.9)';
    x.fillRect(0, i, S, 1);
  }
  var t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(1, 6);
  return t;
}
/* 木纹 */
function woodTexture(seed) {
  var S = 512, c = makeCanvas(S, S), x = c.getContext('2d'), r = seededRandom(seed || 7);
  x.fillStyle = '#4A3728'; x.fillRect(0, 0, S, S);
  for (var i = 0; i < 220; i++) {
    var y = r() * S;
    x.strokeStyle = 'rgba(' + (90 + r() * 60 | 0) + ',' + (66 + r() * 44 | 0) + ',' + (44 + r() * 30 | 0) + ',' + (r() * .28 + .06).toFixed(3) + ')';
    x.lineWidth = .8 + r() * 2.4;
    x.beginPath(); x.moveTo(0, y);
    for (var xx = 0; xx <= S; xx += 16) x.lineTo(xx, y + Math.sin(xx / 40 + i) * 3);
    x.stroke();
  }
  var t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

/* ------------------------------------------------------------------
   调色板（与页面同一套卷色）
   ------------------------------------------------------------------ */
var PALETTE = {
  '202607': { vol: '#B8422C', deep: '#8A2A18', lift: '#D65A38' },
  '202605': { vol: '#8A6A34', deep: '#5C441E', lift: '#B08C4C' },
  '202603': { vol: '#2E4B5E', deep: '#1A2E3C', lift: '#446C82' },
  '202601': { vol: '#3F5C42', deep: '#25362A', lift: '#5B7F60' }
};
function paletteOf(p) { return PALETTE[p] || PALETTE['202607']; }

/* ------------------------------------------------------------------
   尺寸（单位：米，按真实比例）
   ------------------------------------------------------------------ */
var D = {
  bookW: .44, bookH: .68, bookT: .105,   /* 书：宽 / 高 / 厚 */
  gap: .022,                              /* 书与书的间隙 */
  boardT: .028,                           /* 层板厚 */
  sideT: .034,                            /* 侧板厚 */
  backT: .022,                            /* 背板厚 */
  depth: .27,                             /* 柜深 */
  headGap: .15,                           /* 书顶到顶板的空当 */
  plinth: .07                             /* 踢脚高 */
};
var SLOTS = 5;                            /* 4 本 + 1 个空位 */

/* ------------------------------------------------------------------
   场景
   ------------------------------------------------------------------ */
var scene, camera, renderer, controls, shelfGroup, rafId = null;
var bookGroups = [];                      /* 每本书的 Object3D */
var currentIndex = 0;
var clock = null;

function buildLights() {
  /* 环境光用 RoomEnvironment 生成 IBL —— 参考站也这么做。
     没有它，PBR 材质会显得又平又脏；有了它高光才有"环境"可反射。 */
  var pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), .04).texture;

  RectAreaLightUniformsLib.init();

  /* 光强与曝光是配套的：面光给太强 + ACES 色调映射会把朱砂红直接推到接近白
     （像素统计里出现过 rgb(242,205,186) 这种色，说明红封已经过曝掉色了）。
     宁可暗一点，布面的颜色才留得住。 */
  var key = new THREE.RectAreaLight(0xfff2e0, 2.0, 1.6, 1.6);
  key.position.set(-1.1, 1.35, 1.5);
  key.lookAt(0, .55, 0);
  scene.add(key);

  var fill = new THREE.RectAreaLight(0xd8e4ff, .75, 2.0, 2.0);
  fill.position.set(1.5, .9, 1.2);
  fill.lookAt(0, .5, 0);
  scene.add(fill);

  var rim = new THREE.RectAreaLight(0xffd9b0, .95, 1.2, 1.6);
  rim.position.set(.4, 1.1, -1.6);
  rim.lookAt(0, .5, 0);
  scene.add(rim);

  var amb = new THREE.AmbientLight(0xffffff, .12);
  scene.add(amb);
}

/* ---------- 书：精装本，逐件拼出来 ---------- */
function buildBook(bk) {
  var p = paletteOf(bk.period);
  var g = new THREE.Group();

  var cloth = new THREE.MeshStandardMaterial({
    map: clothTexture(p.vol, parseInt(bk.period, 10)),
    roughness: .74, metalness: .02
  });
  var clothSpine = new THREE.MeshStandardMaterial({
    map: clothTexture(p.deep, parseInt(bk.period, 10) + 11),
    roughness: .78, metalness: .02
  });
  var paper = new THREE.MeshStandardMaterial({
    map: pageEdgeTexture(), roughness: .92, metalness: 0
  });

  /* 页芯：比封面略小，四边露出纸口（精装书就是这样） */
  var blockW = D.bookW - .022, blockH = D.bookH - .018, blockD = D.bookT * .72;
  var block = new THREE.Mesh(new THREE.BoxGeometry(blockW, blockH, blockD), paper);
  block.position.z = -D.bookT * .06;
  g.add(block);

  /* 前后书板：用 RoundedBoxGeometry，边缘才不会像一块砖 */
  var boardGeo = new RoundedBoxGeometry(D.bookW, D.bookH, .014, 3, .003);
  var front = new THREE.Mesh(boardGeo, new THREE.MeshStandardMaterial({
    map: coverArtTexture(bk.period, p.vol), roughness: .68, metalness: .04
  }));
  front.position.z = D.bookT / 2 - .007;
  g.add(front);

  var back = new THREE.Mesh(boardGeo, cloth);
  back.position.z = -D.bookT / 2 + .007;
  g.add(back);

  /* 书脊：一段圆角柱，颜色比封面深 */
  var spineGeo = new RoundedBoxGeometry(D.bookT * .96, D.bookH, .05, 3, .008);
  var spine = new THREE.Mesh(spineGeo, clothSpine);
  spine.rotation.y = Math.PI / 2;
  spine.position.x = -D.bookW / 2 + .012;
  g.add(spine);

  /* 书脊烫金：透明贴图叠在书脊上 */
  var foil = new THREE.Mesh(
    new THREE.PlaneGeometry(D.bookT * .78, D.bookH * .82),
    new THREE.MeshStandardMaterial({
      map: spineFoilTexture(bk), transparent: true,
      roughness: .34, metalness: .82, color: 0xffffff
    })
  );
  foil.rotation.y = -Math.PI / 2;
  foil.position.set(-D.bookW / 2 - .014, .01, 0);
  g.add(foil);

  /* 堵头布：书脊上下两端那圈彩色细带 */
  var bandMat = new THREE.MeshStandardMaterial({ color: p.lift, roughness: .6 });
  [1, -1].forEach(function (s) {
    var b = new THREE.Mesh(
      new THREE.CylinderGeometry(.011, .011, blockD * .92, 12), bandMat);
    b.rotation.z = Math.PI / 2;
    b.rotation.y = Math.PI / 2;
    b.position.set(-blockW / 2 + .004, s * (blockH / 2 - .012), -.006);
    g.add(b);
  });

  /* 书签带：从书顶垂下来 */
  var ribbon = new THREE.Mesh(
    new THREE.BoxGeometry(.016, .1, .002),
    new THREE.MeshStandardMaterial({ color: p.deep, roughness: .85 })
  );
  ribbon.position.set(D.bookW * .12, D.bookH / 2 + .03, -D.bookT * .1);
  g.add(ribbon);

  g.userData = { period: bk.period, bk: bk, baseY: 0 };
  /* 🔴 架上要「书脊朝外」。
     不转这一下的话，封面会正面朝观众 —— 屏幕上每本宽 ~500px，
     而架位间距只有 ~126px，四本书会互相盖住，点哪本都点不准。
     绕 Y 轴 +90° 把书脊（本地 -x 侧）转到 +z 朝向相机。 */
  g.rotation.y = Math.PI / 2;
  return g;
}

/* ---------- 书架：木结构 ---------- */
function buildShelf() {
  var g = new THREE.Group();
  var wood = new THREE.MeshStandardMaterial({
    map: woodTexture(31), roughness: .82, metalness: .02
  });
  var woodDark = new THREE.MeshStandardMaterial({
    map: woodTexture(77), roughness: .86, metalness: .02, color: 0x9a8570
  });

  var innerW = SLOTS * D.bookT + (SLOTS - 1) * D.gap + .04;
  var outerW = innerW + D.sideT * 2;
  var innerH = D.bookH + D.headGap;
  var outerH = innerH + D.boardT + D.plinth;

  /* 背板 */
  var back = new THREE.Mesh(new THREE.BoxGeometry(outerW, outerH, D.backT), woodDark);
  back.position.set(0, outerH / 2, -D.depth / 2 + D.backT / 2);
  g.add(back);
  /* 侧板 ×2 */
  [-1, 1].forEach(function (s) {
    var side = new THREE.Mesh(new THREE.BoxGeometry(D.sideT, outerH, D.depth), wood);
    side.position.set(s * (outerW / 2 - D.sideT / 2), outerH / 2, 0);
    g.add(side);
  });
  /* 底板（书站上面）+ 顶板 + 中间层板 */
  [[D.boardT / 2, outerW]].forEach(function (cfg) {
    var board = new THREE.Mesh(new THREE.BoxGeometry(cfg[1], D.boardT, D.depth), wood);
    board.position.set(0, D.plinth + D.boardT / 2, 0);
    g.add(board);
  });
  var top = new THREE.Mesh(new THREE.BoxGeometry(outerW + .03, .034, D.depth + .03), wood);
  top.position.set(0, outerH + .017, .012);
  g.add(top);
  /* 踢脚 */
  var plinth = new THREE.Mesh(new THREE.BoxGeometry(outerW + .02, D.plinth, D.depth + .02), woodDark);
  plinth.position.set(0, D.plinth / 2, .008);
  g.add(plinth);

  /* 书排：4 本真书 + 1 个空位（数据来自页面已加载的 data.js） */
  var books = (window.WH_DATA && window.WH_DATA.books) || [];
  var slotX = function (i) {
    var total = SLOTS * D.bookT + (SLOTS - 1) * D.gap;
    return -total / 2 + D.bookT / 2 + i * (D.bookT + D.gap);
  };
  books.forEach(function (bk, i) {
    var b = buildBook(bk);
    b.position.set(slotX(i), D.plinth + D.boardT + D.bookH / 2, .01);
    b.userData.baseY = b.position.y;
    b.userData.slotIndex = i;
    g.add(b);
    bookGroups.push(b);
  });

  /* 地面接触阴影：一块软阴影贴片，比实时阴影便宜得多 */
  var shadowCanvas = makeCanvas(256, 64), sx = shadowCanvas.getContext('2d');
  var grd = sx.createRadialGradient(128, 32, 4, 128, 32, 126);
  grd.addColorStop(0, 'rgba(0,0,0,.55)');
  grd.addColorStop(1, 'rgba(0,0,0,0)');
  sx.fillStyle = grd; sx.fillRect(0, 0, 256, 64);
  var shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(outerW * 1.25, D.depth * 1.7),
    new THREE.MeshBasicMaterial({
      map: new THREE.CanvasTexture(shadowCanvas), transparent: true,
      depthWrite: false, opacity: .75
    })
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(0, .002, .01);
  g.add(shadow);

  return { group: g, outerW: outerW, outerH: outerH };
}

/* ------------------------------------------------------------------
   初始化
   ------------------------------------------------------------------ */
function init(canvasEl) {
  if (!canvasEl) return false;
  if (!renderer) {
    renderer = new THREE.WebGLRenderer({
      canvas: canvasEl, antialias: true, alpha: true
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = .92;
    renderer.shadowMap.enabled = false;   /* 用贴片阴影，省一次全屏 pass */
  }
  var w = canvasEl.clientWidth || 800, h = canvasEl.clientHeight || 600;
  renderer.setSize(w, h, false);

  if (!scene) {
    scene = new THREE.Scene();
    clock = new THREE.Clock();
    camera = new THREE.PerspectiveCamera(34, w / h, .05, 40);
    /* 取景按「画面高 ≈ 0.9m、书架高 0.8m」反推：
       fov 34° 时 z = 0.9 / (2·tan17°) ≈ 1.45。
       原先给 1.72，架子只占中间一条，两侧空了一大片。 */
    camera.position.set(0, .72, 1.30);
    buildLights();
    var built = buildShelf();
    shelfGroup = built.group;
    scene.add(shelfGroup);

    controls = new OrbitControls(camera, canvasEl);
    controls.target.set(0, .44, 0);
    controls.enableDamping = true;
    controls.dampingFactor = .08;
    controls.minDistance = .9;
    controls.maxDistance = 3.2;
    controls.maxPolarAngle = Math.PI * .54;
    controls.update();
  } else {
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  render();
  return true;
}

function render() {
  if (!renderer || !scene) return;
  controls && controls.update();
  renderer.render(scene, camera);
}
function loop() {
  render();
  rafId = requestAnimationFrame(loop);
}
function start() { if (!rafId) loop(); }
function stop() { if (rafId) { cancelAnimationFrame(rafId); rafId = null; } }

/* ------------------------------------------------------------------
   拾取：点哪本书就取哪本
   ------------------------------------------------------------------
   陈列态仍是 CSS 3D 做的（那是与参考站**有意不同**的一处，理由见文件头），
   所以这里只需要把「被点的书」变成两样东西交给调用方：
     · index —— 切换到对应的那卷数据
     · rect  —— 它在屏幕上的矩形，用作 FLIP 过渡的起点
   矩形由 3D 包围盒的 8 个角投影到屏幕后取包围框得到 —— 这样 3D 与 DOM
   两套坐标系能对上，过渡落点才不会跳。
   ------------------------------------------------------------------ */
var raycaster = new THREE.Raycaster();
var pointerNDC = new THREE.Vector2();

function projectGroupRect(obj) {
  var box = new THREE.Box3().setFromObject(obj);
  var min = box.min, max = box.max;
  var xs = [], ys = [];
  for (var i = 0; i < 8; i++) {
    var v = new THREE.Vector3(
      (i & 1) ? max.x : min.x,
      (i & 2) ? max.y : min.y,
      (i & 4) ? max.z : min.z
    );
    v.project(camera);
    var el = renderer.domElement;
    xs.push((v.x * .5 + .5) * el.clientWidth);
    ys.push((-v.y * .5 + .5) * el.clientHeight);
  }
  var r = el_getRect();
  return {
    left: r.left + Math.min.apply(null, xs),
    top: r.top + Math.min.apply(null, ys),
    width: Math.max.apply(null, xs) - Math.min.apply(null, xs),
    height: Math.max.apply(null, ys) - Math.min.apply(null, ys)
  };
}
function el_getRect() { return renderer.domElement.getBoundingClientRect(); }

/* 传入视口坐标，返回 { index, period, rect } 或 null */
function hitTest(clientX, clientY) {
  if (!renderer || !camera) return null;
  var r = el_getRect();
  pointerNDC.x = ((clientX - r.left) / r.width) * 2 - 1;
  pointerNDC.y = -((clientY - r.top) / r.height) * 2 + 1;
  raycaster.setFromCamera(pointerNDC, camera);
  var hits = raycaster.intersectObjects(bookGroups, true);
  if (!hits.length) return null;
  var o = hits[0].object;
  while (o && bookGroups.indexOf(o) < 0) o = o.parent;
  if (!o) return null;
  return {
    index: o.userData.slotIndex,
    period: o.userData.period,
    rect: projectGroupRect(o)
  };
}

/* 让某本书亮起来（hover 反馈）：抬高 + 略前移 */
function highlight(index) {
  bookGroups.forEach(function (g, i) {
    var on = i === index;
    var targetY = g.userData.baseY + (on ? .045 : 0);
    var targetZ = .01 + (on ? .05 : 0);
    g.position.y += (targetY - g.position.y) * .22;
    g.position.z += (targetZ - g.position.z) * .22;
  });
  if (bookGroups.length) render();
}
/* 取走某本：让它淡出并缩进去，腾给 FLIP 的 ghost */
function takeAway(index) {
  var g = bookGroups[index];
  if (!g) return;
  g.traverse(function (o) {
    if (o.material) {
      o.material.transparent = true;
      o.material.opacity = 0;
    }
  });
  g.visible = false;
  render();
}
function putBack(index) {
  var g = bookGroups[index];
  if (!g) return;
  g.visible = true;
  g.traverse(function (o) {
    if (o.material) o.material.opacity = 1;
  });
  g.position.set(g.position.x, g.userData.baseY, .01);
  render();
}
/* 取某本书在屏幕上的矩形（归架时用作 FLIP 的终点）。
   书被 takeAway 隐藏后这个矩形照样算得出来 —— Box3 不看 visible。 */
function slotRect(index) {
  var g = bookGroups[index];
  if (!g) return null;
  return projectGroupRect(g);
}

/* 供外部（页面与自测）使用 */
window.WH_SHELF3D = {
  init: init, render: render, start: start, stop: stop,
  hitTest: hitTest, highlight: highlight, takeAway: takeAway, putBack: putBack,
  slotRect: slotRect,
  books: function () { return bookGroups.length; },
  info: function () {
    return {
      revision: THREE.REVISION,
      books: bookGroups.length,
      hasShelf: !!shelfGroup,
      children: shelfGroup ? shelfGroup.children.length : 0,
      drawn: renderer ? renderer.info.render.triangles : 0
    };
  },
  scene: function () { return scene; }
};
})();

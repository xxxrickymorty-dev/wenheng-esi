# -*- coding: utf-8 -*-
"""一次性：把「阅览桌」版式扩成「入馆—取书—归架」动线版（生成 flow.template.html）。

之后 flow.template.html 就是独立源码，直接改它，不再跑本脚本。
"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "reader.template.html"
DST = HERE / "flow.template.html"

s = SRC.read_text(encoding="utf-8")

# ── 1. 数据：五册 → ALL.books ───────────────────────────────────────────
s = s.replace(
    "const B = /*__PAYLOAD__*/null;",
    "const ALL = /*__PAYLOAD__*/null;\n"
    "const BOOKS = (ALL && ALL.books) || {};\n"
    "const SOUNDS = (ALL && ALL.sounds) || [];\n"
    "let B = null;")
s = s.replace("this.pool = (B.sounds || []).map", "this.pool = (SOUNDS || []).map")

# ── 2. boot() → loadBook(period) ────────────────────────────────────────
s = s.replace("""function boot() {
  fit();""", """function loadBook(period) {
  if (!BOOKS[period]) return false;
  B = BOOKS[period];
  open = false; busy = false; pending = 0;
  $('book').dataset.shut = 'true';
  $('closed').hidden = false;
  fit();""")
s = s.replace("""  spread = 0;
  paint();
}

Sound.init();
boot();
wire();""", """  spread = 0;
  paint();
  return true;
}

Sound.init();
fit();
buildShelf();
wire();
wireFlow();""")

# ── 3. 合上之后给动线一个回调（飞回书架） ──────────────────────────────
s = s.replace("""      open = false;
      $('closed').hidden = false;
      $('live').textContent = '已合上';
    }, 300);""", """      open = false;
      $('closed').hidden = false;
      $('live').textContent = '已合上';
      if (typeof onClosed === 'function') onClosed();
    }, 300);""")

# ── 4. 桌面层改成覆盖式舞台 ────────────────────────────────────────────
s = s.replace(".desk{position:relative;z-index:10;height:100%;display:grid;place-items:center;padding:58px 0 44px}",
              ".desk{position:fixed;z-index:20;inset:0;display:grid;place-items:center;padding:58px 0 44px;\n"
              "  opacity:0;pointer-events:none;transition:opacity 420ms var(--ease)}\n"
              ".scene-desk .desk{opacity:1;pointer-events:auto}")
s = s.replace(".bar{position:fixed;z-index:40;left:0;right:0;top:0;height:58px;",
              ".bar{position:fixed;z-index:40;left:0;right:0;top:0;height:58px;opacity:0;pointer-events:none;\n"
              "  transition:opacity 300ms var(--ease);")
s = s.replace(".foot{position:fixed;z-index:40;left:0;right:0;bottom:0;height:3px;background:rgba(201,169,97,.10)}",
              ".foot{position:fixed;z-index:40;left:0;right:0;bottom:0;height:3px;background:rgba(201,169,97,.10);\n"
              "  opacity:0;transition:opacity 300ms var(--ease)}\n"
              ".scene-desk .bar,.scene-desk .foot{opacity:1;pointer-events:auto}")
s = s.replace(".room{position:fixed;inset:0;z-index:0;pointer-events:none;",
              ".room{position:fixed;inset:0;z-index:1;pointer-events:none;opacity:0;\n"
              "  transition:opacity 520ms var(--ease);")
s = s.replace(".scene-desk .desk{opacity:1;pointer-events:auto}",
              ".scene-desk .desk{opacity:1;pointer-events:auto}\n.scene-desk .room{opacity:1}")

FLOW_CSS = r"""
/* ══════════════════════════════════════════════════════════════════
   动线：进馆（中庭）→ 走近（展台）→ 取书（桌面）→ 归架
   一个空间，一次推近；书离架留下的空槽就是仪式留下的凭据。
   ══════════════════════════════════════════════════════════════════ */
.walk-track{position:relative;z-index:0;height:200vh}
.walk-stage{position:sticky;top:0;height:100svh;overflow:hidden;isolation:isolate}
.walk{position:absolute;inset:0;z-index:0;overflow:hidden;background:#0B0F0C}
.walk-img{position:absolute;inset:-4%;width:108%;height:108%;object-fit:cover;object-position:50% 58%;
  transform-origin:50% 46%;will-change:transform,filter;transition:filter 120ms linear}
.walk-veil{position:absolute;inset:0;pointer-events:none;
  background:
    radial-gradient(120% 88% at 50% 42%,transparent 30%,rgba(6,10,8,.66) 100%),
    linear-gradient(180deg,rgba(6,10,8,.62),transparent 26%,transparent 62%,rgba(4,8,6,.88))}
.walk::after{content:"";position:absolute;inset:0;opacity:.16;mix-blend-mode:overlay;pointer-events:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.5'/%3E%3C/svg%3E")}

/* 门前：馆名与一句刊训 */
.foyer{position:absolute;z-index:4;left:0;right:0;top:16vh;display:flex;flex-direction:column;
  align-items:center;gap:0;text-align:center;color:var(--ivory);pointer-events:none}
.foyer .eye{font:11px/1 var(--sans);letter-spacing:.42em;color:rgba(224,203,146,.86);margin-bottom:2.1em}
.foyer h1{font-size:clamp(34px,4.6vw,64px);font-weight:600;letter-spacing:.2em;text-indent:.2em;
  color:#F6F1E2;text-shadow:0 2px 26px rgba(0,0,0,.55)}
.foyer .motto{margin-top:1.5em;font-size:13px;letter-spacing:.34em;color:rgba(242,237,225,.72);text-indent:.34em}
.foyer .motto i{font-style:normal;margin:0 .7em;color:rgba(201,169,97,.7)}
.foyer .rule{width:1px;height:52px;margin-top:2.6em;background:linear-gradient(180deg,rgba(201,169,97,.75),transparent)}
.cue{position:absolute;z-index:5;left:50%;bottom:3.2vh;translate:-50% 0;color:rgba(224,203,146,.82);
  transition:opacity .3s var(--ease)}
.cue svg{width:22px;height:22px;animation:cue 2.4s var(--ease) infinite}
@keyframes cue{0%,100%{transform:translateY(0);opacity:.35}50%{transform:translateY(7px);opacity:.95}}

/* 展台：一张托板，五册书 */
.exhibit{position:absolute;z-index:3;left:50%;top:50%;width:min(64vw,1020px);
  translate:-50% -50%;transform-origin:50% 62%;opacity:0;pointer-events:none;will-change:transform,opacity;
  transition:filter 420ms var(--ease)}
.exhibit.is-live{pointer-events:auto}
.lamp{position:absolute;z-index:0;left:50%;top:48%;width:132%;height:150%;translate:-50% -50%;
  pointer-events:none;opacity:.5;
  background:radial-gradient(46% 40% at 50% 46%,rgba(201,169,97,.20),rgba(201,169,97,.06) 46%,transparent 72%)}
.shelf{position:relative;z-index:2;display:flex;flex-direction:column;align-items:center}
.slots{display:flex;align-items:flex-end;justify-content:center;gap:2.4%;width:100%}
.svol{position:relative;flex:0 0 15.4%;aspect-ratio:210/297;padding:0;border:0;background:none;
  cursor:pointer;transform-origin:50% 100%;transition:transform 460ms var(--ease),filter 460ms var(--ease);
  filter:drop-shadow(0 16px 18px rgba(0,0,0,.5))}
.svol img{display:block;width:100%;height:100%;object-fit:cover;
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.07);transition:opacity .35s var(--ease)}
.svol::before{content:"";position:absolute;left:0;top:0;bottom:0;width:9%;z-index:2;pointer-events:none;
  background:linear-gradient(90deg,rgba(0,0,0,.5),rgba(0,0,0,.06) 62%,transparent);opacity:.9}
.svol::after{content:"";position:absolute;inset:-6% -8% -10%;z-index:-1;pointer-events:none;opacity:0;
  background:radial-gradient(60% 46% at 50% 92%,rgba(0,0,0,.6),transparent 72%);
  transition:opacity .4s var(--ease)}
.svol:hover,.svol:focus-visible{transform:translateY(-14px)}
.svol:hover::after,.svol:focus-visible::after{opacity:1}
.svol .cap{position:absolute;left:0;right:0;top:calc(100% + 12px);display:flex;align-items:baseline;
  justify-content:center;gap:.5em;font-size:12px;letter-spacing:.08em;color:var(--ivory);white-space:nowrap}
.svol .cap b{font-weight:600;font-family:var(--mono);letter-spacing:.06em;color:#F6F1E2}
.svol .cap em{font-style:normal;font-size:11px;color:rgba(242,237,225,.5)}
/* 取走的那一册：槽位空着，书名留着淡淡的影——这是仪式留下的凭据 */
.svol.is-gone img{opacity:.08}
.svol.is-gone .cap{opacity:.28}
.svol.is-gone{box-shadow:inset 0 0 0 1px rgba(201,169,97,.30),inset 0 18px 40px rgba(0,0,0,.7);
  background:linear-gradient(180deg,rgba(0,0,0,.5),rgba(0,0,0,.22))}
.svol.is-gone::before{opacity:0}
.plank{position:relative;z-index:3;width:108%;height:15px;margin-top:-2px;border-radius:1px;
  background:linear-gradient(180deg,#5A3D24,#3A2515 62%,#2A1A0E);
  box-shadow:0 16px 26px -8px rgba(0,0,0,.65),inset 0 1px 0 rgba(255,255,255,.14)}
.plank::after{content:"";position:absolute;left:0;right:0;top:100%;height:12px;
  background:linear-gradient(180deg,rgba(0,0,0,.55),transparent)}

/* 取书：一册离架，飞到手边 */
.take{position:fixed;z-index:60;pointer-events:none;left:0;top:0;width:0;height:0}
.take img{position:absolute;object-fit:cover;box-shadow:0 30px 60px rgba(0,0,0,.6);
  will-change:transform}
body.is-taking .walk-img{filter:blur(9px) brightness(.34)!important}
body.is-taking .foyer,body.is-taking .cue{opacity:0}
body.is-taking .exhibit{filter:blur(3px) brightness(.6)}

/* 桌面态：世界退到后面去 */
body.scene-desk .walk-img{filter:blur(14px) brightness(.22)!important}
body.scene-desk .foyer,body.scene-desk .cue{opacity:0;pointer-events:none}
body.scene-desk .exhibit{opacity:.16;filter:blur(6px)}

/* 走完展台之后：一句交代，不多占 */
.after{position:relative;z-index:2;background:#0C120E;color:var(--ivory);
  padding:clamp(56px,9vh,110px) clamp(24px,6vw,120px)}
.after .wrap{max-width:1080px;margin:0 auto}
.after h2{font-size:clamp(20px,2.2vw,28px);font-weight:600;letter-spacing:.14em;margin-bottom:.5em}
.after p{font-size:14px;line-height:2;color:rgba(242,237,225,.6);max-width:44em}
.after .chain{display:flex;flex-wrap:wrap;gap:10px 0;margin-top:2.4em;
  font-size:12.5px;letter-spacing:.16em;color:rgba(224,203,146,.9)}
.after .chain span{display:flex;align-items:center}
.after .chain span+span::before{content:"";width:34px;height:1px;margin:0 16px;
  background:linear-gradient(90deg,rgba(201,169,97,.5),rgba(201,169,97,.12))}

@media (max-width:900px){
  .walk-track{height:100svh}
  .foyer{top:12vh}
  .foyer h1{font-size:32px}
  .foyer .motto{font-size:11px;letter-spacing:.22em}
  .exhibit{width:88vw}
  .svol .cap{font-size:10px;top:calc(100% + 8px)}
  .svol .cap em{display:none}
  .svol:hover,.svol:focus-visible{transform:translateY(-8px)}
  .cue{bottom:2.4vh}
}
"""

FLOW_HTML = r"""
<div class="walk-track" id="walkTrack">
  <div class="walk-stage" id="walkStage">
    <div class="walk">
      <img class="walk-img" id="walkImg" alt="" aria-hidden="true">
      <span class="walk-veil" aria-hidden="true"></span>
    </div>

    <section class="foyer" id="foyer" aria-label="陈列馆">
      <p class="eye">雲南大學圖書館 · 學科情報館藏</p>
      <h1>学科信息参考</h1>
      <p class="motto">一年六期<i>·</i>一期一册</p>
      <span class="rule" aria-hidden="true"></span>
    </section>

    <div class="exhibit" id="exhibit">
      <span class="lamp" aria-hidden="true"></span>
      <div class="shelf">
        <div class="slots" id="slots"></div>
        <span class="plank" aria-hidden="true"></span>
      </div>
    </div>

    <span class="cue" id="cue" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M12 4v14M6 13l6 6 6-6"/></svg>
    </span>
  </div>
</div>

<div class="take" id="take" aria-hidden="true"></div>
"""

FLOW_JS = r"""
/* ═══════════ 八、动线：进馆 → 走近 → 取书 → 归架 ═══════════ */
let onClosed = null;
let scene = 'foyer';
let flight = null;

function buildShelf() {
  const slots = $('slots');
  if (!slots) return;
  slots.innerHTML = '';
  Object.keys(BOOKS).sort().reverse().forEach((period, i) => {
    const b = BOOKS[period];
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'svol';
    el.dataset.period = period;
    el.style.transitionDelay = (i * 40) + 'ms';
    el.setAttribute('aria-label', '取阅 ' + period + '，' + b.issue + '，' + b.design + '装帧');
    el.innerHTML = '<img src="' + b.cover + '" alt="" draggable="false">'
      + '<span class="cap"><b>' + period + '</b><em>' + b.design + '</em></span>';
    el.addEventListener('click', () => takeBook(period, el));
    slots.appendChild(el);
  });
}

/* 滚动＝走近。p=0 站在中庭看馆，p=1 停在展台前。 */
const CUE = $('cue');
function place() {
  const narrow = window.innerWidth <= 900;
  const img = $('walkImg');
  const exhibit = $('exhibit');
  const foyer = $('foyer');
  if (!img || !exhibit) return;
  let p = 1;
  if (!narrow) {
    const track = $('walkTrack');
    const span = Math.max(1, track.offsetHeight - window.innerHeight);
    p = Math.min(1, Math.max(0, window.scrollY / span));
  }
  exhibit.style.opacity = String(narrow ? 1 : Math.min(1, Math.max(0, (p - .18) / .62)));
  exhibit.style.transform = 'translate(-50%,-50%) scale(' + (0.52 + p * 0.48).toFixed(3) + ')'
    + ' translateY(' + ((1 - p) * 12).toFixed(2) + '%)';
  exhibit.classList.toggle('is-live', p > .82 || narrow);
  img.style.transform = 'scale(' + (1 + p * 0.26).toFixed(3) + ') translateY(' + (p * -1.5).toFixed(2) + '%)';
  img.style.filter = 'blur(' + (p * 6).toFixed(1) + 'px) brightness(' + (1 - p * 0.5).toFixed(3) + ')';
  foyer.style.opacity = String(Math.max(0, 1 - p * 1.9));
  foyer.style.transform = 'translateY(' + (-p * 40).toFixed(1) + 'px)';
  if (CUE) CUE.style.opacity = p > .06 ? '0' : '1';
}

function takeBook(period, el) {
  if (scene === 'desk' || flight) return;
  const img = el.querySelector('img');
  if (!img) return;
  loadBook(period);
  const from = img.getBoundingClientRect();
  el.classList.add('is-gone');
  document.body.classList.add('is-taking');
  Sound.play(.8, .9);

  const target = $('closed').getBoundingClientRect();
  const fly = $('take');
  const copy = document.createElement('img');
  copy.src = img.src;
  copy.style.left = from.left + 'px';
  copy.style.top = from.top + 'px';
  copy.style.width = from.width + 'px';
  copy.style.height = from.height + 'px';
  fly.appendChild(copy);

  const dx = target.left - from.left;
  const dy = target.top - from.top;
  const sx = target.width / from.width;
  const sy = target.height / from.height;
  flight = copy.animate(
    [{ transform: 'translate(0,0) scale(1,1)' },
     { transform: 'translate(' + dx + 'px,' + dy + 'px) scale(' + sx + ',' + sy + ')' }],
    { duration: 720, easing: 'cubic-bezier(.32,.72,0,1)', fill: 'forwards' });

  flight.onfinish = () => {
    copy.remove();
    flight = null;
    document.body.classList.remove('is-taking');
    document.body.classList.add('scene-desk');
    scene = 'desk';
    $('closed').hidden = false;
    if (window.scrollY > 0) window.scrollTo({ top: 0 });
    openBook();
    $('back').textContent = '归架';
  };
}

/* 归架：合上 → 飞回原槽 → 槽位复原 */
function returnBook() {
  const period = B && B.period;
  const el = period ? document.querySelector('.svol[data-period="' + period + '"]') : null;
  if (!el) { document.body.classList.remove('scene-desk'); scene = 'foyer'; return; }
  const img = el.querySelector('img');
  const from = $('closed').getBoundingClientRect();
  const to = img.getBoundingClientRect();
  document.body.classList.remove('scene-desk');
  scene = 'foyer';
  $('book').dataset.shut = 'true';
  const copy = document.createElement('img');
  copy.src = img.src;
  copy.style.left = from.left + 'px';
  copy.style.top = from.top + 'px';
  copy.style.width = from.width + 'px';
  copy.style.height = from.height + 'px';
  $('take').appendChild(copy);
  Sound.play(.74, 1);
  flight = copy.animate(
    [{ transform: 'translate(0,0) scale(1,1)' },
     { transform: 'translate(' + (to.left - from.left) + 'px,' + (to.top - from.top) + 'px) scale('
        + (to.width / from.width) + ',' + (to.height / from.height) + ')' }],
    { duration: 620, easing: 'cubic-bezier(.4,.06,.24,1)', fill: 'forwards' });
  flight.onfinish = () => {
    copy.remove();
    flight = null;
    el.classList.remove('is-gone');
    $('closed').hidden = true;
    place();
  };
}

function wireFlow() {
  onClosed = () => window.setTimeout(returnBook, 260);
  $('walkImg').src = window.innerWidth <= 900 ? (ALL.interior || ALL.panorama) : ALL.panorama;

  let raf = 0;
  const kick = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; place(); }); };
  window.addEventListener('scroll', kick, { passive: true });
  window.addEventListener('resize', () => {
    $('walkImg').src = window.innerWidth <= 900 ? (ALL.interior || ALL.panorama) : ALL.panorama;
    kick();
  }, { passive: true });
  place();

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || scene !== 'desk') return;
    /* 关书由阅读器自己处理，归架在 onClosed 里接 */
  });
}
"""

# ── 5. 注入 ────────────────────────────────────────────────────────────
s = s.replace("</style>", FLOW_CSS + "\n</style>", 1)
s = s.replace('<div class="room" aria-hidden="true"></div>',
              '<div class="room" aria-hidden="true"></div>\n' + FLOW_HTML, 1)
s = s.replace("</script>\n</body>", FLOW_JS + "\n</script>\n</body>", 1)

DST.write_text(s, encoding="utf-8")
print("wrote", DST, len(s.split("\n")), "lines")

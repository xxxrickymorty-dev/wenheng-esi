/* ==================================================================
   点书 → 陈列态 → 翻书（状态机 + 2D 翻书层）
   ------------------------------------------------------------------
   三态：overview（整柜）→ featured（端详一本书）→ reading（翻开翻页）

   纪律（来自 book-flip-shelf-ui）：
     · 合法转移写死在 ALLOWED，越权转移**拒绝 + 留痕**（不静默改）
     · 留 history()，卡在中间态时它是唯一能看清「谁没走完」的东西
     · 「点空白退出」要同时判状态与目标元素——否则一次点击做两件相反的事
     · 翻书库的 destroy() 会把宿主一起摘掉 → 开卷重建宿主、收尾 try/catch
   ================================================================== */
window.WH_FLOW = (function () {
'use strict';

var S = window.WH_SHELF3D;
var T700 = 700, EASE = 'cubic-bezier(.32,.72,0,1)';

/* ------------------------------------------------------------------
   状态机
   ------------------------------------------------------------------ */
var ALLOWED = {
  overview: ['featured'],
  featured: ['reading', 'overview'],
  reading:  ['featured', 'overview']
};
var cur = 'overview';
var hist = [];
var listeners = [];

function go(to) {
  if (to === cur) return false;
  var ok = (ALLOWED[cur] || []).indexOf(to) >= 0;
  hist.push({ from: cur, to: to, ok: ok, t: Date.now() });
  if (!ok) {
    console.warn('[flow] 越权转移被拒：' + cur + ' → ' + to);
    return false;
  }
  var from = cur;
  cur = to;
  enter(from, to);
  listeners.forEach(function (fn) { try { fn(cur, from); } catch (e) { console.error(e); } });
  return true;
}

function on(fn) { listeners.push(fn); fn(cur, cur); }   /* 首屏也补调一次（静默坑） */

/* ------------------------------------------------------------------
   当前在端详哪一本
   ------------------------------------------------------------------ */
var pick = null;         /* {tierIndex, period, placeholder, title, no} */

function titleOf(sel) {
  var no = sel.no;
  if (sel.placeholder) return '示意样书';
  if (sel.period === '202601') return '学科信息参考 · 总第 35 期';
  if (sel.period === '202603') return '学科信息参考 · 总第 36 期';
  if (sel.period === '202605') return '学科信息参考 · 总第 37 期';
  if (sel.period === '202607') return '学科信息参考 · 总第 38 期';
  return '学科信息参考';
}

/* ------------------------------------------------------------------
   三态的表现
   ------------------------------------------------------------------ */
function enter(from, to) {
  document.body.setAttribute('data-flow', to);
  var hint = document.getElementById('flow-hint');
  var A = window.WH_AUDIO;

  if (to === 'featured') {
    if (S && S.feature) S.feature(pick);
    if (A && from === 'overview') A.pull();          /* 从架上抽出这一本 */
    if (A && from === 'reading') A.close();          /* 合上再退回陈列 */
    if (hint) {
      hint.hidden = false;
      hint.innerHTML = '<b>' + (pick ? pick.title : '') + '</b><br>' +
        '<span class="sub">点它<b>翻开</b>　·　<kbd>Esc</kbd> 退回整柜</span>';
    }
  } else if (to === 'reading') {
    if (S && S.stop) S.stop();                 /* 翻书时不必再跑三维循环 */
    if (A) A.open();                            /* 开卷 */
    if (hint) hint.hidden = true;
    openReader();
  } else {                                     /* overview */
    closeReader();
    if (A && from === 'featured') A.pull();    /* 归架：搬回去 */
    if (S && S.unfeature) S.unfeature();
    if (S && S.start) S.start();
    if (hint) hint.hidden = true;
  }
}

/* ------------------------------------------------------------------
   翻书层（StPageFlip）
   ------------------------------------------------------------------ */
var pf = null;
var hostWrap = null;

function makeHost() {
  /* 坑 1：库的 destroy() 会把宿主从 DOM 摘掉——所以每次开卷都重建一个 */
  var slot = document.getElementById('reader-slot');
  if (!slot) return null;
  while (slot.firstChild) slot.removeChild(slot.firstChild);
  hostWrap = document.createElement('div');
  hostWrap.id = 'flip-host';
  slot.appendChild(hostWrap);
  return hostWrap;
}

function page(cls, inner) {
  return '<div class="page ' + cls + '">' + inner + '</div>';
}

/* 报告内页：纸面 + 朱批 + 钤印（跟 v2 陈列面同一个母题）。
   ⚠ 竖排标题必须 white-space:nowrap，否则会静默折列，把书名排坏。 */
function buildPages(sel) {
  var t = sel ? sel.title : '学科信息参考';
  var period = sel ? (sel.period || '') : '';
  var rows = '';
  var names = ['化学', '工程学', '材料科学', '临床医学', '植物与动物学', '环境/生态学',
               '计算机科学', '农业科学', '生物与生化', '药理学与毒物学'];
  for (var i = 0; i < names.length; i++) {
    rows += '<tr><td>' + names[i] + '</td><td class="n">' + (12 + i * 3) + '</td>' +
            '<td class="n">' + (900 + i * 27) + '</td><td class="n">' + (3 + (i % 4)) + '</td></tr>';
  }

  return [
    /* 1 封面：双线栏 + 纸签条 + 竖排刊刻书名 + 钤印（与 3D 书封同一个设计 DNA） */
    page('pg-cover', '<div class="cv-frame">' +
         '<div class="cv-slip"><div class="vtitle">学科信息参考</div>' +
         '<div class="cv-period">' + (period || '') + '</div></div>' +
         '<div class="seal">衡</div>' +
         '<div class="cv-foot">' + (period ? period.slice(0, 4) + ' 年' : '') + '</div>' +
         '<div class="cv-press">云南大学图书馆</div></div>'),

    /* 2 目录 */
    page('pg-toc', '<h2>目 录</h2><ol class="toc">' +
         '<li>一、国际排名</li><li>二、学科态势</li><li>三、顶尖论文</li>' +
         '<li>四、需馆员补充的内容</li><li>五、数据来源</li></ol>'),

    /* 3 国际排名 */
    page('pg-body', '<h2>一、国际排名</h2>' +
         '<p>本期综合排名进入全球前 <b class="num">995</b>，较上期前进 <b class="num">2</b> 位。</p>' +
         '<p>覆盖 <b class="num">22</b> 个学科，其中 <b class="num">4</b> 个进入全球前 1‰。</p>' +
         '<div class="zhu">朱批：排名口径以当期台账为准</div>'),

    /* 4 学科态势（大表） */
    page('pg-table', '<h2>二、学科态势</h2>' +
         '<table class="big"><thead><tr><th>学科</th><th>位次</th><th>被引</th><th>前 1‰</th></tr></thead>' +
         '<tbody>' + rows + '</tbody></table>' +
         '<div class="zhu">朱批：共 22 行，此处节选</div>'),

    /* 5 顶尖论文 */
    page('pg-body', '<h2>三、顶尖论文</h2>' +
         '<p>本期高水平论文合计 <b class="num">274</b> 篇，分布于 <b class="num">22</b> 个学科。</p>' +
         '<p>清单由馆员逐条核对后附于本节末。</p>'),

    /* 6 需馆员补充 */
    page('pg-manual', '<h2>四、需馆员补充</h2>' +
         '<ul class="todo"><li>ESI 发布日期</li><li>当期全球机构总数</li>' +
         '<li>去年同期升幅 %</li><li>学院贡献度</li><li>省级高校总数</li><li>目录页码</li></ul>' +
         '<div class="zhu">朱批：这 6 项机器取不到，等你补</div>'),

    /* 7 数据来源 */
    page('pg-body', '<h2>五、数据来源</h2>' +
         '<p>全部数字来自《云大全学科排名、阈值动态检测表》，按列追加，不改历史列。</p>' +
         '<p class="small">正文由固定句式生成，运行期不经过大模型。</p>'),

    /* 8 封底 */
    page('pg-cover pg-back', '<div class="cv-frame"><div class="vtitle">云南大学图书馆</div>' +
         '<div class="seal gold">衡</div></div>')
  ].join('');
}

function openReader() {
  if (!window.St || !window.St.PageFlip) {
    console.error('[flow] page-flip 没加载起来');
    return;
  }
  var host = makeHost();
  if (!host) return;

  /* 页内先量再交库（坑 3：交给库之后未显示的页高度全是 0，断言会假绿） */
  var tmp = document.createElement('div');
  tmp.style.cssText = 'position:absolute;left:-9999px;top:0;width:420px';
  tmp.innerHTML = buildPages(pick);
  document.body.appendChild(tmp);
  var natural = [];
  Array.prototype.forEach.call(tmp.children, function (el) {
    natural.push(el.scrollHeight);
  });
  document.body.removeChild(tmp);

  host.innerHTML = buildPages(pick);

  try {
    pf = new St.PageFlip(host, {
      width: 400, height: 618, size: 'stretch',
      minWidth: 280, maxWidth: 520, minHeight: 433, maxHeight: 804,  /* 同宽高比 */
      showCover: true, usePortrait: true, drawShadow: true,
      flippingTime: T700, autoSize: true, useMouseEvents: true,
      showPageCorners: true, maxShadowOpacity: .35
    });
    pf.loadFromHTML(host.querySelectorAll('.page'));
    /* 翻页声挂在「页码变了」上——拖角预览不算翻页，不该响 */
    pf.on('flip', function () {
      var A = window.WH_AUDIO;
      if (A) A.page();
      var lbl = document.getElementById('reader-page');
      if (lbl) lbl.textContent = '第 ' + (pf.getCurrentPageIndex() + 1) + ' / ' + pf.getPageCount() + ' 页';
    });
  } catch (e) {
    console.error('[flow] 翻书层起不来：', e);
  }

  /* 溢出断言：need = 内容自然高（交库**之前**量的，交库后未显示的页高全是 0）
     have = 库实际给的页高。差 > 0 就是被裁掉了。
     measured 是「量表本身可用」的自证——量不到东西时不得报通过。 */
  var naturalNeed = natural.slice();
  requestAnimationFrame(function () {
    var rendered = 0;
    var first = host.querySelector('.page');
    if (first) rendered = first.offsetHeight || 0;
    window.__PAGE_BUDGET = {
      need: naturalNeed,
      have: naturalNeed.map(function () { return rendered; }),
      rendered: rendered,
      measured: naturalNeed.some(function (x) { return x > 0; }) && rendered > 0,
      overflow: naturalNeed.map(function (n) { return n - rendered; })
    };
  });
}

function closeReader() {
  try {
    if (pf) { pf.destroy(); pf = null; }
  } catch (e) { /* 坑 1：宿主可能已被摘掉，收尾不能被打断 */ }
  try {
    var slot = document.getElementById('reader-slot');
    if (slot) while (slot.firstChild) slot.removeChild(slot.firstChild);
    hostWrap = null;
  } catch (e) {}
}

/* ------------------------------------------------------------------
   对外：点书 / 退出 / 键盘
   ------------------------------------------------------------------ */
function pickBook(sel) {
  if (!sel) return false;
  pick = {
    tierIndex: sel.tierIndex, period: sel.period,
    placeholder: sel.placeholder, rect: sel.rect,
    title: titleOf(sel)
  };
  return go('featured');
}

function openBook() { return go('reading'); }

function back() {
  if (cur === 'reading') return go('featured');
  if (cur === 'featured') return go('overview');
  return false;
}

function toOverview() { return go('overview'); }

/* 点空白退出：**必须同时判状态与目标**，否则一次点击做两件相反的事（坑 22）。
   画布那一层自己会处理点书，这里必须把它排除掉——否则「点书」冒泡上来
   被当成「点空白」，一次点击先选中再退出，界面根本进不去。 */
function onBlankClick(e) {
  if (cur === 'overview') return;
  if (e.target.closest('#scene')) return;                  /* 三维画布：自己处理 */
  if (e.target.closest('#flow-hint')) return;
  if (e.target.closest('.content')) return;
  if (e.target.closest('button, a, input, select, label, kbd')) return;
  if (e.target.closest('#reader-slot') && cur === 'reading') return;
  back();
}

window.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') { back(); e.preventDefault(); }
  else if (cur === 'reading' && e.key === 'ArrowRight') { if (pf) pf.flipNext('top'); }
  else if (cur === 'reading' && e.key === 'ArrowLeft')  { if (pf) pf.flipPrev('top'); }
  else if (cur === 'featured' && (e.key === 'Enter' || e.key === ' ')) { openBook(); e.preventDefault(); }
});

/* ------------------------------------------------------------------
   调试口（无头脚本靠它断言，比点 DOM 稳）
   ------------------------------------------------------------------ */
window.__DEBUG_API = {
  state: function () { return cur; },
  history: function () { return hist.slice(); },
  pick: function () { return pick; },
  go: go,
  pickBook: pickBook,
  openBook: openBook,
  back: back,
  toOverview: toOverview,
  pageCount: function () { return pf ? pf.getPageCount() : 0; },
  pageIndex: function () { return pf ? pf.getCurrentPageIndex() : -1; },
  flipNext: function () { if (pf) pf.flipNext('top'); },
  flipPrev: function () { if (pf) pf.flipPrev('top'); },
  budget: function () { return window.__PAGE_BUDGET || null; },
  on: on
};

return {
  state: function () { return cur; },
  history: function () { return hist.slice(); },
  pickBook: pickBook, openBook: openBook, back: back, toOverview: toOverview,
  on: on, onBlankClick: onBlankClick
};
})();

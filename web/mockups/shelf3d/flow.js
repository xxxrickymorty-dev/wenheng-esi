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
  if (sel.placeholder) return '示意样书';
  var b = bookRec(sel.period);
  if (b) return '学科信息参考 · 总第 ' + b.no + ' 期';
  return '学科信息参考';
}

/* 这一期的真实数字（来自 data.js，可回溯到台账） */
function bookRec(period) {
  var list = (window.WH_DATA && window.WH_DATA.books) || [];
  for (var i = 0; i < list.length; i++) if (list[i].period === period) return list[i];
  return null;
}

function cnNo(n) {
  var d = '〇一二三四五六七八九', s = String(n), out = '';
  if (s.length === 2) {
    if (s[0] !== '1') out += d[+s[0]];
    out += '十';
    if (s[1] !== '0') out += d[+s[1]];
  } else out = d[+s] || s;
  return out;
}

function fmt(n) {
  return (n == null) ? '—' : String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function deltaTxt(v) {
  if (v == null) return '—';
  return v > 0 ? '↑' + v : v < 0 ? '↓' + (-v) : '持平';
}

/* 陈列态右栏：规格表。**每一条都来自台账**，不编。 */
function renderSpec() {
  var el = document.getElementById('dSpecs');
  if (!el) return;
  var b = pick ? bookRec(pick.period) : null;
  var eb = document.getElementById('dEyebrow');
  var tt = document.getElementById('dTitle');
  var ld = document.getElementById('dLead');
  if (!b) {
    if (eb) eb.textContent = pick && pick.placeholder ? '示意 · 未出刊' : '—';
    if (tt) tt.textContent = pick ? pick.title : '学科信息参考';
    if (ld) ld.textContent = '这一册还没有出刊。架上留位子是为了让「连续的架」读得出来。';
    el.innerHTML = '';
    return;
  }
  if (eb) eb.textContent = '卷之' + cnNo(b.no) + ' — 学科态势';
  if (tt) tt.textContent = '学科信息参考';
  if (ld) ld.textContent = '以 ESI / InCites 指标为基准的双月学科态势报告。' +
    '数字只来自台账，正文由骨架出句，模型不进入数据路径 —— 本期覆盖 ' +
    (b.coverage || '—') + '，流水线断言 ' + b.n_assert_pass + '/' + b.n_assert_total + ' 全绿。';

  var tpTxt = b.top_papers_delta == null ? '—' : deltaTxt(b.top_papers_delta);
  var specs = [
    ['期次', b.period + ' · 总第 ' + b.no + ' 期'],
    ['覆盖窗口', (b.coverage || '—').replace(/-/g, ' – ')],
    ['数据源', '台账 · ESI/InCites 原始包'],
    ['断言', b.n_assert_pass + ' / ' + b.n_assert_total + ' <span class="u">全绿</span>'],
    ['国际排名', fmt(b.rank_intl_now) + ' <span class="u">位 ' + deltaTxt(b.rank_intl_delta) + '</span>'],
    ['顶尖论文', fmt(b.top_papers_now) + ' <span class="u">篇 ' + tpTxt + '</span>']
  ];
  el.innerHTML = specs.map(function (s) {
    return '<div class="spec"><div class="k">' + s[0] + '</div><div class="v">' + s[1] + '</div></div>';
  }).join('');
}

/* ------------------------------------------------------------------
   三态的表现
   ------------------------------------------------------------------ */
/* 命令区随状态变——拿掉「关闭」按钮换成点背景退出之后，
   不把退出方式写出来就没人知道。同一屏不重复说两遍。
   ⚠ 首屏也要调一次：只挂「状态变化」回调，初始态没变化就永远同步不到。
   ⚠ 「抽取」在书架态就在（G 的做法）：单击即命中，但**显式按钮**才是可发现的那条路。 */
function syncCommands() {
  var fh = document.getElementById('footHint');
  var cmdOpen = document.getElementById('cmdOpen');
  var cmdShelf = document.getElementById('cmdShelf');
  var cmdReset = document.getElementById('cmdReset');
  if (fh) {
    fh.textContent = cur === 'overview'
      ? '↑↓ 换层 · 点书或「抽取」取下一册 ·'
      : cur === 'featured'
        ? '「翻开」进正文 · 点背景或「归架」放回去 ·'
        : '点书页外的背景合上 · ← → 翻页 ·';
  }
  if (cmdOpen) {
    cmdOpen.hidden = (cur === 'reading');
    cmdOpen.textContent = (cur === 'featured') ? '翻开' : '抽取';
  }
  if (cmdShelf) cmdShelf.hidden = (cur === 'overview');
  if (cmdReset) cmdReset.hidden = (cur === 'reading');
}

function enter(from, to) {
  document.body.setAttribute('data-flow', to);
  var hint = document.getElementById('flow-hint');
  var A = window.WH_AUDIO;
  syncCommands();

  if (to === 'featured') {
    if (S && S.feature) S.feature(pick);
    if (A && from === 'overview') A.pull();          /* 从架上抽出这一本 */
    if (A && from === 'reading') A.close();          /* 合上再退回陈列 */
    renderSpec();
    if (hint) {
      hint.hidden = false;
      hint.innerHTML = '<b>' + (pick ? pick.title : '') + '</b>';
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
   **数字全部来自 data.js**（out/<期>/ 的真实产物，可回溯），不编。
   ⚠ 竖排标题必须 white-space:nowrap，否则会静默折列，把书名排坏。 */
function buildPages(sel) {
  var b = sel ? bookRec(sel.period) : null;
  var period = sel ? (sel.period || '') : '';
  var rows = '';
  var tbl = (b && b.table) || [];
  for (var i = 0; i < Math.min(tbl.length, 10); i++) {
    var r = tbl[i];
    rows += '<tr><td>' + r.cn + '</td><td class="n">' + fmt(r.papers) + '</td>' +
            '<td class="n">' + fmt(r.cites) + '</td><td class="n">' + r.top + '</td>' +
            '<td class="n">' + r.prox + '</td></tr>';
  }
  if (!rows) {
    ['化学', '工程学', '材料科学', '临床医学', '植物与动物学'].forEach(function (nm, i) {
      rows += '<tr><td>' + nm + '</td><td class="n">—</td><td class="n">—</td>' +
              '<td class="n">—</td><td class="n">—</td></tr>';
    });
  }
  var rankNow = b ? fmt(b.rank_intl_now) : '—';
  var rankD = b ? deltaTxt(b.rank_intl_delta) : '—';
  var topNow = b ? fmt(b.top_papers_now) : '—';
  var topD = b ? deltaTxt(b.top_papers_delta) : '—';
  var disc1 = b ? b.n_disc_1pct : '—';
  var cov = b ? (b.coverage || '—') : '—';
  var asn = b ? (b.n_assert_pass + ' / ' + b.n_assert_total) : '—';
  var top3 = (b && b.top3) || [];

  return [
    /* 1 封面 */
    page('pg-cover', '<div class="cv-frame">' +
         '<div class="cv-slip"><div class="vtitle">学科信息参考</div>' +
         '<div class="cv-period">' + (period || '') + '</div></div>' +
         '<div class="seal">衡</div>' +
         '<div class="cv-foot">' + (b ? ('总第 ' + b.no + ' 期') : '') + '</div>' +
         '<div class="cv-press">云南大学图书馆</div></div>'),

    /* 2 目录 */
    page('pg-toc', '<h2>目 录</h2><ol class="toc">' +
         '<li>一、国际排名</li><li>二、学科态势</li><li>三、顶尖论文</li>' +
         '<li>四、需馆员补充的内容</li><li>五、数据来源</li></ol>'),

    /* 3 国际排名 */
    page('pg-body', '<h2>一、国际排名</h2>' +
         '<p>本期综合排名进入全球前 <b class="num">' + rankNow + '</b>，较上期 <b class="num">' + rankD + '</b>。</p>' +
         '<p>顶尖论文 <b class="num">' + topNow + '</b> 篇（' + topD + '），其中 <b class="num">' + disc1 + '</b> 个学科进入全球前 1‰。</p>' +
         (top3.length ? '<p>贡献前三：' + top3.map(function (t) {
             return t[0] + ' <b class="num">' + t[1] + '</b>';
           }).join('、') + '。</p>' : '') +
         '<div class="zhu">朱批：排名口径以当期台账为准</div>'),

    /* 4 学科态势（大表） */
    page('pg-table', '<h2>二、学科态势</h2>' +
         '<table class="big"><thead><tr><th>学科</th><th>论文</th><th>被引</th><th>顶尖</th><th>逼近</th></tr></thead>' +
         '<tbody>' + rows + '</tbody></table>' +
         '<div class="zhu">朱批：共 ' + ((b && b.table && b.table.length) || '—') + ' 行，此处节选</div>'),

    /* 5 顶尖论文 */
    page('pg-body', '<h2>三、顶尖论文</h2>' +
         '<p>本期高水平论文合计 <b class="num">' + topNow + '</b> 篇，较上期 <b class="num">' + topD + '</b>。</p>' +
         '<p>清单由馆员逐条核对后附于本节末。</p>'),

    /* 6 需馆员补充 */
    page('pg-manual', '<h2>四、需馆员补充</h2>' +
         '<ul class="todo"><li>ESI 发布日期</li><li>当期全球机构总数</li>' +
         '<li>去年同期升幅 %</li><li>学院贡献度</li><li>省级高校总数</li><li>目录页码</li></ul>' +
         '<div class="zhu">朱批：这 6 项机器取不到，等你补</div>'),

    /* 7 数据来源 */
    page('pg-body', '<h2>五、数据来源</h2>' +
         '<p>全部数字来自《云大全学科排名、阈值动态检测表》，按列追加，不改历史列。</p>' +
         '<p>本期覆盖 <b class="num">' + cov + '</b>，流水线自检 <b class="num">' + asn + '</b> 全绿。</p>' +
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
      if (lbl) lbl.textContent = (pf.getCurrentPageIndex() + 1) + ' / ' + pf.getPageCount();
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

/* 抽取：书架态取「焦点层里第一本真书」。跟点那本书是同一个动作，
   但按钮是可发现的那条路（G 的做法：单击即命中，命令区再给一个显式入口）。 */
function pullFocused() {
  if (cur !== 'featured') {
    var S3 = window.WH_SHELF3D;
    var list = (S3 && S3.bookRects) ? S3.bookRects() : [];
    var pick2 = null;
    for (var i = 0; i < list.length; i++) {
      if (!list[i].placeholder && list[i].rect && list[i].rect.width > 8) { pick2 = list[i]; break; }
    }
    if (!pick2) return false;
    return pickBook(pick2);
  }
  return openBook();
}

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

/* 首屏补调一次（技能里的静默坑：只挂「状态变化」回调，初始态没变化就永远同步不到） */
document.body.setAttribute('data-flow', cur);
syncCommands();

return {
  state: function () { return cur; },
  history: function () { return hist.slice(); },
  pickBook: pickBook, openBook: openBook, back: back, toOverview: toOverview,
  pullFocused: pullFocused,
  on: on, onBlankClick: onBlankClick
};
})();

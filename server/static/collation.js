/* 文衡 · 对勘本前端。数据来自 window.__COLLATION__（模板或快照注入）。 */
(function () {
  'use strict';

  var D = window.__COLLATION__ || null;
  var root = document.getElementById('whc');
  if (!root) return;
  if (!D || !D.sections) { root.innerHTML = '<div class="whc-empty">没有可对勘的数据。</div>'; return; }

  var state = { sec: null, q: '', manualOnly: false, zhu: true, focus: null, expandCells: null, signPanel: false };
  var CELL_CAP = 120;

  /* ---------------- 工具 ---------------- */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function fmt(s) {
    return esc(s).replace(/【手工：([^】]*)】/g, '<span class="hand" title="流水线判定为编辑判断项，需人工补录">$1</span>');
  }
  function manualCount(s) {
    var m = String(s || '').match(/【手工：[^】]*】/g);
    return m ? m.length : 0;
  }
  function has(t, s) { return String(t).indexOf(s) >= 0; }
  function haystack(sl) { return (sl.loc + ' ' + sl.old + ' ' + sl.new + ' ' + sl.source).toLowerCase(); }

  /* ---------------- 字符级 diff（LCS） ---------------- */
  function diffOps(a, b) {
    var n = a.length, m = b.length, dp = [], i, j;
    for (i = 0; i <= n; i++) { dp.push(new Array(m + 1)); for (j = 0; j <= m; j++) dp[i][j] = 0; }
    for (i = n - 1; i >= 0; i--) {
      for (j = m - 1; j >= 0; j--) {
        dp[i][j] = a.charAt(i) === b.charAt(j) ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    var ops = [], push = function (t, ch) {
      if (ops.length && ops[ops.length - 1].t === t) ops[ops.length - 1].s += ch;
      else ops.push({ t: t, s: ch });
    };
    i = 0; j = 0;
    while (i < n && j < m) {
      if (a.charAt(i) === b.charAt(j)) { push('eq', a.charAt(i)); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { push('del', a.charAt(i)); i++; }
      else { push('ins', b.charAt(j)); j++; }
    }
    while (i < n) push('del', a.charAt(i++));
    while (j < m) push('ins', b.charAt(j++));
    return ops;
  }

  /* 只取改动附近的一段窗口，避免把 50 字截断串整行摊开 */
  function diffWindow(oldS, newS, pad) {
    pad = pad || 14;
    if (oldS === newS) return null;
    var ops = diffOps(oldS, newS), i0 = -1, i1 = -1, k;
    for (k = 0; k < ops.length; k++) {
      if (ops[k].t !== 'eq') { if (i0 < 0) i0 = k; i1 = k; }
    }
    if (i0 < 0) return null;
    var s = Math.max(0, i0 - pad), e = Math.min(ops.length - 1, i1 + pad);
    var up = '', dn = '';
    for (k = s; k <= e; k++) {
      var o = ops[k];
      if (o.t === 'eq') { up += fmt(o.s); dn += fmt(o.s); }
      else if (o.t === 'del') up += '<span class="del">' + fmt(o.s) + '</span>';
      else dn += '<span class="ins">' + fmt(o.s) + '</span>';
    }
    var head = s > 0 ? '<span class="el">…</span>' : '';
    var tail = e < ops.length - 1 ? '<span class="el">…</span>' : '';
    return { up: head + up + tail, dn: head + dn + tail };
  }

  /* ---------------- 卡片 ---------------- */
  function cardHTML(sl) {
    var w = diffWindow(sl.old, sl.new, 14);
    var lab = sl.oldLabel || '母版原文';
    var head = '<div class="dc-h"><span class="dc-loc">' + esc(sl.loc) + '</span>' +
      (sl.manual ? '<span class="dc-tag m">待人工 ' + manualCount(sl.new) + '</span>' : '<span class="dc-tag z">已替换</span>') +
      '<span class="dc-src">' + esc(sl.source) + '</span></div>';
    var body;
    if (!w) {
      body = '<div class="dv-r up"><span class="dv-k">本期</span><div class="dv-v">' +
        (esc(sl.new) || '<span class="el">（空）</span>') + '</div></div>' +
        '<div class="dc-note">与' + esc(lab) + '逐字一致（本槽无改动，或为整段替换）。</div>';
    } else {
      body = '<div class="dv-r dn"><span class="dv-k">' + esc(lab) + '</span><div class="dv-v">' + w.up + '</div></div>' +
        '<div class="dv-r up"><span class="dv-k">本期</span><div class="dv-v">' + w.dn + '</div></div>';
    }
    return '<article class="dc" data-loc="' + esc(sl.loc) + '">' + head + '<div class="dc-b">' + body + '</div></article>';
  }

  function chartsHTML(list) {
    var out = '<div class="charts">';
    list.forEach(function (sl) {
      var fn = String(sl.new).replace('[图] ', '');
      out += '<div class="chc" data-loc="' + esc(sl.loc) + '">' +
        '<b>' + esc(sl.loc.replace('正文/', '')) + '</b>' +
        '<span class="fn">' + esc(fn) + '</span>' +
        '<div class="from">原状：' + esc(sl.old) + '</div>' +
        '<div class="src">' + esc(sl.source) + '</div></div>';
    });
    return out + '</div>';
  }

  function cellsHTML(list, expanded) {
    var shown = expanded ? list : list.slice(0, CELL_CAP);
    var out = '<div class="cellwrap"><table class="cells"><thead><tr>' +
      '<th>位置</th><th>对照值</th><th>本期填充</th><th>来源</th></tr></thead><tbody>';
    shown.forEach(function (sl) {
      var w = diffWindow(sl.old, sl.new, 6);
      var up = w ? w.up : esc(sl.old);
      /* 空格提示用「这一行自己的」参照标签：大表里 T01/表头、上期值、学科名列三者来源不同，
         取列表首项的标签会串味（学科名列曾被写成「母版表头为空」） */
      if (!up || !strip(up).length) up = '<span class="el">（' + esc(sl.oldLabel || '对照值') + '为空）</span>';
      out += '<tr data-loc="' + esc(sl.loc) + '">' +
        '<td class="c-loc">' + esc(sl.loc) + '</td>' +
        '<td class="c-old">' + up + '</td>' +
        '<td class="c-new">' + (w ? w.dn : esc(sl.new)) + '</td>' +
        '<td class="c-loc">' + esc(sl.source) + '</td></tr>';
    });
    out += '</tbody></table></div>';
    var note = '共 ' + list.length + ' 格 · 对照值出处逐行见「来源」列';
    if (!expanded && list.length > CELL_CAP) {
      out += '<p class="whc-more">' + note + '，先显示前 ' + CELL_CAP + ' 格。' +
        '<button data-expand="1">展开全部 ' + list.length + ' 格</button>' +
        ' <button data-csv="1">复制为 TSV</button></p>';
    } else if (list.length) {
      out += '<p class="whc-more">' + note + '。<button data-csv="1">复制为 TSV</button></p>';
    }
    return out;
  }

  /* ---------------- 过滤 ---------------- */
  function filtered(sec) {
    var q = state.q.trim().toLowerCase();
    return sec.slots.filter(function (sl) {
      if (state.manualOnly && !sl.manual) return false;
      if (q && haystack(sl).indexOf(q) < 0) return false;
      return true;
    });
  }
  function sectionCount(sec) { return filtered(sec).length; }

  /* ---------------- 渲染 ---------------- */
  var C = D.counts || { total: 0, text: 0, cell: 0, chart: 0, manual: 0 };
  var T = D.totals || C;          /* 题首/汇总用全量；快照可只内联抽样 */
  var A = D.assertions || { total: 0, fail: 0 };
  var AP = D.approval || {};                                   /* 审批（签单）记录 */
  var AS = D.approvalStatus || (AP.signed ? 'signed' : 'unsigned');
  var FL = D.flash || {};                                      /* POST 后的闪回 */
  var JOB = D.jobId || '';
  /* 签单/撤回统一按期次投递（服务端给 signUrl/revokeUrl）；任务入口是由期次页
     共用的同一套端点，所以这里不再从 JOB 拼路径——拼接在看板/期次两个入口下
     会各造一个 URL，签完回跳就会跳错页。 */
  var SIGN = D.signUrl || (JOB ? '/jobs/' + encodeURIComponent(JOB) + '/collation/sign' : '');
  var REVOKE = D.revokeUrl || (JOB ? '/jobs/' + encodeURIComponent(JOB) + '/collation/revoke' : '');
  var BACK = D.backUrl || '';
  var LIVE = !!SIGN;

  function hiddenBack() {
    return BACK ? '<input type="hidden" name="back" value="' + esc(BACK) + '">' : '';
  }

  /* 期次印记链：每期一枚印，点开进当期对勘本。这是首屏的主导航。 */
  function periodChainHTML() {
    var ps = D.periods || [];
    if (ps.length < 2) return '';
    var cur = D.periodDir || D.period;
    var out = '<div class="whc-chain"><span class="ch-l">期 次 印 记</span>';
    ps.forEach(function (p) {
      var cls = 'ch-i' + (p.period === cur ? ' on' : '') +
        (p.status === 'signed' ? ' sg' : p.status === 'stale' ? ' st' : '');
      var tag = p.status === 'signed' ? '已钤印' : p.status === 'stale' ? '失效' : '待签';
      out += '<a class="' + cls + '" href="' + esc(p.url) + '"' +
        (p.period === cur ? ' aria-current="page"' : '') +
        ' title="' + esc((p.signed_at ? p.signed_at + ' · ' + p.signed_actor : '尚未签单')) + '">' +
        esc(p.period) + '<i>' + tag + '</i></a>';
    });
    return out + '</div>';
  }

  /* 签单区：签单是审批动作，不是动画。真实表单 POST，状态由服务端落库后回带。 */
  function signFormHTML() {
    return '<form class="whc-signpanel form" method="post" action="' + esc(SIGN) + '">' + hiddenBack() +
      '<div class="ro-t">钤印签单 · 逐条核对后方可放行</div>' +
      (T.manual
        ? '<label class="ro-ack"><input type="checkbox" name="ack" value="1" required>' +
          '我已知悉仍有 <b>' + T.manual + '</b> 处【手工：…】待人工补录项，确认放行</label>'
        : '<label class="ro-ack"><input type="checkbox" checked disabled>' +
          '待人工补录项为 0，机器断言全绿</label>') +
      '<input class="ro-note" type="text" name="note" maxlength="120"' +
      ' placeholder="批注（可选，会写进审批记录）">' +
      '<div class="ro-btns">' +
      '<button type="submit" class="whc-btn">确 认 签 单</button>' +
      '<button type="button" class="whc-btn ghost" id="whcSignCancel">取消</button>' +
      '</div></form>';
  }

  function signZoneHTML() {
    if (!LIVE) {
      return '<div class="whc-signpanel ro">' +
        '<span class="ro-t">静态快照 · 签单动作需在演示站内进行</span>' +
        '<span class="ro-d">签单要绑住当时那份报告并落库，快照里没有服务端，故只作只读展示。</span></div>';
    }
    if (AS === 'signed') {
      return '<div class="whc-signpanel ok">' +
        '<span class="ro-t">已钤印 · 放行报送</span>' +
        '<span class="ro-d">' + esc(AP.actor || '') + ' · ' + esc(AP.signed_at || '') +
        (AP.note ? ' · 批注：' + esc(AP.note) : '') + '</span>' +
        '<form method="post" action="' + esc(REVOKE) + '" class="ro-f"' + hiddenBack() +
        ' onsubmit="return confirm(\'确认撤回本次签单？撤回会保留操作历史。\')">' +
        '<button type="submit" class="whc-btn ghost">撤 回 签 单</button></form></div>';
    }
    if (AS === 'stale') {
      /* 失效后可以直接重签（服务端允许），不必先撤销——少一步，别给人添堵 */
      if (state.signPanel) return signFormHTML();
      return '<div class="whc-signpanel stale">' +
        '<span class="ro-t">签名已失效 · 需重新签单</span>' +
        '<span class="ro-d">上次签单（' + esc(AP.actor || '') + ' · ' + esc(AP.signed_at || '') +
        '）之后报告初稿或红色件数据被重新生成，签名不再对应当前稿件。核对后可直接重签。</span>' +
        '<form method="post" action="' + esc(REVOKE) + '" class="ro-f">' + hiddenBack() +
        '<button type="submit" class="whc-btn ghost">清 除 失 效 记 录</button></form></div>';
    }
    return state.signPanel ? signFormHTML() : '';
  }

  function heroHTML() {
    var lead = '上期 <b>' + esc(D.periodPrev || '—') + '</b> → 本期 <b>' + esc(D.period) + '</b>' +
      ' · 机器断言 <b class="' + (A.fail ? '' : 'z') + '">' + (A.total - A.fail) + '/' + A.total +
      (A.fail ? ' 有 ' + A.fail + ' 项未过' : ' 全绿') + '</b>' +
      ' · 文字槽 <b>' + T.text + '</b> · 大表格 <b>' + T.cell + '</b> · 图表 <b>' + T.chart + '</b>' +
      ' · 待人工补录 <b class="z">' + T.manual + '</b> 处';
    var signState;
    if (AS === 'signed') {
      /* 文案保留占位但不可见：签单区已写明「已钤印」，这里再写一遍会和钤印图章压字。
         visibility 而非 display，是为了让 .whc-hr 保住高度，图章落点才不会偏。 */
      signState = '<span class="todo" style="display:none"></span>' +
        '<span class="done" style="visibility:hidden">已钤印 · 放行报送</span>';
    } else if (AS === 'stale') {
      signState = '<span class="done" style="display:block;color:var(--gold)">签名已失效</span>';
    } else {
      signState = '<span class="todo">待签人<b>' + esc(D.actor || '馆员') + ' · 学科服务部</b>' + esc(D.signedAt || '') + '</span>';
    }
    var canSign = (AS === 'unsigned' || AS === 'stale') && LIVE && !state.signPanel;
    var btn = canSign
      ? '<button class="whc-btn sign" id="whcSign"' + (A.fail ? ' disabled title="机器断言未过，闸门不放行"' : '') + '>钤 印 签 单</button>'
      : '';
    return '<div>' +
      '<div class="whc-kicker">期次 ' + esc(D.period) + ' · 槽位级对勘 · <em>全链路确定性脚本</em></div>' +
      '<h1>本期改动<span class="big">' + T.total + '</span>处，逐条指向台账单元格</h1>' +
      '<p class="lead">' + lead + '</p>' +
      periodChainHTML() + '</div>' +
      '<div class="whc-hr">' +
      '<div class="whc-sign">' + signState + '</div>' +
      btn +
      '<div class="whc-stamp">文衡<small>学 科 服 务</small></div></div>' +
      signZoneHTML();
  }

  function flashHTML() {
    if (FL.err) return '<p class="whc-flash err">闸门未放行：' + esc(FL.err) + '</p>';
    if (FL.signed) return '<p class="whc-flash ok">签单已落库，写入 out/' + esc(D.outDir || D.period) + '/approval.json 与《审批记录.md》</p>';
    if (FL.revoked) return '<p class="whc-flash warn">已撤回签单，操作历史保留在审批记录中</p>';
    if (AS === 'stale') return '<p class="whc-flash warn">上次签单之后报告被重新生成，签名已失效，请重新核对后签单</p>';
    return '';
  }

  function barHTML() {
    return flashHTML() +
      '<span class="whc-sw' + (state.zhu ? ' on' : '') + '" id="whcSw"><span class="dot"></span>朱批层</span>' +
      '<input class="whc-q" id="whcQ" placeholder="搜索位置 / 改动文字 / 来源…">' +
      '<span class="whc-sw' + (state.manualOnly ? ' on' : '') + '" id="whcSwM"><span class="dot"></span>仅看待人工 <b>' + T.manual + '</b></span>' +
      '<span class="whc-hint">点击 <b>位置</b> 查看台账来源 · 按 ← → 换分组</span>';
  }

  function navHTML() {
    var total = 0, out = '<div class="whc-nav-h">槽 位 分 组</div>';
    D.sections.forEach(function (sec) {
      var n = sectionCount(sec);
      total += n;
      out += '<a class="whc-ni' + (state.sec === sec.id ? ' on' : '') + '" data-sec="' + sec.id + '">' +
        '<span class="no">' + sec.count + '</span>' +
        '<span class="nm">' + esc(sec.name) + '</span>' +
        '<span class="ct">' + n + '</span></a>';
    });
    out += '<div class="whc-nav-t"><span>命中</span><b>' + total + '</b></div>';
    return out;
  }

  function mainHTML() {
    var sec = D.sections.filter(function (s) { return s.id === state.sec; })[0];
    if (!sec) return '<div class="whc-empty">该分组不存在。</div>';
    var list = filtered(sec);
    var head = '<div class="whc-mh"><h2>' + esc(sec.name) + '<em>' + esc(sec.note || '') + '</em></h2>' +
      '<span class="tip">' + list.length + ' / ' + sec.count + ' 处 · 朱色为改动</span></div>';
    if (!list.length) return head + '<div class="whc-empty">没有匹配的槽位。</div>';

    var texts = [], charts = [], cells = [];
    list.forEach(function (sl) {
      (sl.kind === 'chart' ? charts : sl.kind === 'cell' ? cells : texts).push(sl);
    });
    var out = head;
    texts.forEach(function (sl) { out += cardHTML(sl); });
    if (charts.length) out += chartsHTML(charts);
    if (cells.length) out += cellsHTML(cells, state.expandCells === sec.id);
    return out;
  }

  function sideHTML() {
    var sl = state.focus;
    var h = '<div class="whc-sh"><h2>校 记</h2><em>' + (sl ? esc(sl.loc) : esc(D.period) + ' · 汇总') + '</em></div>';
    if (!sl) {
      return h + '<dl class="sd">' +
        '<dt>本期槽位</dt><dd class="mono">' + T.total + ' 处</dd>' +
        '<dt>文字 / 大表 / 图表</dt><dd class="mono">' + T.text + ' / ' + T.cell + ' / ' + T.chart + '</dd>' +
        '<dt>待人工补录</dt><dd class="z">' + T.manual + ' 处</dd>' +
        '<dt>机器断言</dt><dd class="mono">' + (A.total - A.fail) + ' / ' + A.total + (A.fail ? ' · ' + A.fail + ' 项未过' : ' · 全绿') + '</dd>' +
        '</dl><p class="ph">把光标移到左侧任意一条改动上，这里显示它的台账出处。</p>' +
        gatesHTML();
    }
    var body = '';
    if (sl.kind === 'chart') {
      body = '<dt>槽位类型</dt><dd>图表' + (has(sl.old, '母版旧图') ? '（替换母版旧图）' : '（新插入）') + '</dd>' +
        '<dt>插入文件</dt><dd class="mono z">' + esc(String(sl.new).replace('[图] ', '')) + '</dd>' +
        '<dt>原状</dt><dd>' + esc(sl.old) + '</dd>' +
        '<dt>来源</dt><dd class="mono">' + esc(sl.source) + '</dd>';
    } else if (sl.kind === 'cell') {
      body = '<dt>槽位类型</dt><dd>大表数值格</dd>' +
        '<dt>' + esc(sl.oldLabel || '母版此格') + '</dt><dd class="mono">' + (esc(sl.old) || '（空）') + '</dd>' +
        '<dt>本期填充</dt><dd class="mono z">' + esc(sl.new) + '</dd>' +
        '<dt>来源</dt><dd class="mono">' + esc(sl.source) + '</dd>';
    } else {
      body = '<dt>槽位类型</dt><dd>正文段落</dd>' +
        '<dt>改动字符</dt><dd class="mono z">' + changedChars(sl) + ' 字</dd>' +
        '<dt>待人工</dt><dd class="mono">' + (manualCount(sl.new) || 0) + ' 处</dd>' +
        '<dt>来源</dt><dd class="mono">' + esc(sl.source) + '</dd>';
    }
    var bar = '<div class="sd-bar"><button data-copy="' + esc(sl.loc) + '">复制位置</button>' +
      (sl.kind === 'cell' ? '' : '<button data-quote="1">看原文片段</button>') + '</div>';
    return h + '<dl class="sd">' + body + '</dl>' + bar + gatesHTML();
  }

  function changedChars(sl) {
    var ops = diffOps(sl.old, sl.new), n = 0;
    ops.forEach(function (o) { if (o.t !== 'eq') n += o.s.length; });
    return n;
  }

  function gatesHTML() {
    var gate;
    if (AS === 'signed') {
      gate = '<div class="g" id="whcGateSign"><span class="gd"></span>人工审批门<span class="gs">已签单 · 放行</span></div>';
    } else if (AS === 'stale') {
      gate = '<div class="g stale" id="whcGateSign"><span class="gd"></span>人工审批门<span class="gs">签名失效 · 需重签</span></div>';
    } else {
      gate = '<div class="g wait" id="whcGateSign"><span class="gd"></span>人工审批门<span class="gs">待签单</span></div>';
    }
    return '<div class="whc-gates">' +
      '<div class="g"><span class="gd"></span>机器断言闸<span class="gs">' + (A.fail ? A.fail + ' 项未过' : '全绿') + '</span></div>' +
      '<div class="g"><span class="gd"></span>金样回测闸<span class="gs">逐格比对</span></div>' +
      gate +
      '</div>';
  }

  function tailHTML() {
    var src = '<span>数据源：out/' + esc(D.outDir || D.period) + '/red_slots.json · 与红色件清单同源 · 大模型不进入数据路径</span>';
    var B = D.bigtable || null;
    var mid = (B && B.enriched)
      ? '<span>大表跨期对勘：' + B.enriched + ' 格已补入上期值（out/' + esc(B.prevDir || B.prevPeriod) + '/table2.csv，按学科名对齐）</span>'
      : '<span>大表母版为空白模板，未接上期数据</span>';
    var note;
    if (D.snapshotNote) {
      note = '<span class="z">' + esc(D.snapshotNote) + '</span>';
    } else if (AS === 'signed') {
      note = '<span>审批已落库：out/' + esc(D.outDir || D.period) + '/approval.json · 已绑定签单时的报告指纹</span>';
    } else if (AS === 'stale') {
      note = '<span class="z">签单指纹与当前稿件不符，签名失效</span>';
    } else {
      note = '<span>机器跑完不等于可以报送，需人工钤印签单</span>';
    }
    return src + mid + note;
  }

  /* ---------------- 事件 ---------------- */
  function bindOnce(el, ev, fn) { el.addEventListener(ev, fn); }

  function paint() {
    root.querySelector('#whcHero').innerHTML = heroHTML();
    root.querySelector('#whcBar').innerHTML = barHTML();
    root.querySelector('#whcNav').innerHTML = navHTML();
    root.querySelector('#whcMain').innerHTML = mainHTML();
    root.querySelector('#whcSide').innerHTML = sideHTML();
    root.querySelector('#whcFoot').innerHTML = tailHTML();
    wire();
  }

  function pickFocus(sl) {
    state.focus = sl || null;
    root.querySelector('#whcSide').innerHTML = sideHTML();
    wireSide();
    root.querySelectorAll('.dc, .chc, tr[data-loc]').forEach(function (n) {
      n.classList.toggle('hi', !!(state.focus && n.dataset.loc === state.focus.loc));
    });
  }

  function wire() {
    var sw = root.querySelector('#whcSw');
    bindOnce(sw, 'click', function () {
      state.zhu = !state.zhu;
      sw.classList.toggle('on', state.zhu);
      root.classList.toggle('clean', !state.zhu);
    });
    var swm = root.querySelector('#whcSwM');
    bindOnce(swm, 'click', function () {
      state.manualOnly = swm.classList.toggle('on');
      ensureVisible();
      paint();
    });
    var q = root.querySelector('#whcQ');
    if (q) {
      q.value = state.q;
      bindOnce(q, 'input', function () {
        state.q = q.value;
        var nav = root.querySelector('#whcNav');
        nav.innerHTML = navHTML();
        nav.querySelectorAll('.whc-ni').forEach(function (a) {
          bindOnce(a, 'click', function () { goto(a.dataset.sec); });
        });
        ensureVisible(true);
        root.querySelector('#whcMain').innerHTML = mainHTML();
        wireMain();
      });
    }
    root.querySelectorAll('.whc-ni').forEach(function (a) {
      bindOnce(a, 'click', function () { goto(a.dataset.sec); });
    });
    var s = root.querySelector('#whcSign');
    if (s) bindOnce(s, 'click', function () { state.signPanel = true; paint(); });
    var sc = root.querySelector('#whcSignCancel');
    if (sc) bindOnce(sc, 'click', function () { state.signPanel = false; paint(); });
    wireMain();
    wireSide();
  }

  function wireMain() {
    var main = root.querySelector('#whcMain');
    main.querySelectorAll('.dc, .chc').forEach(function (n) {
      var sl = findSlot(n.dataset.loc);
      bindOnce(n, 'mouseenter', function () { if (sl) pickFocus(sl); });
      var loc = n.querySelector('.dc-loc') || n.querySelector('b');
      if (loc) {
        bindOnce(loc, 'click', function (ev) { ev.stopPropagation(); if (sl) popup(ev, sl); });
      }
    });
    main.querySelectorAll('tr[data-loc]').forEach(function (n) {
      var sl = findSlot(n.dataset.loc);
      bindOnce(n, 'mouseenter', function () { if (sl) pickFocus(sl); });
    });
    main.querySelectorAll('button[data-expand]').forEach(function (b) {
      bindOnce(b, 'click', function () { state.expandCells = state.sec; paint(); });
    });
    main.querySelectorAll('button[data-csv]').forEach(function (b) {
      bindOnce(b, 'click', function () {
        var rows = filtered(currentSection()).filter(function (x) { return x.kind === 'cell'; });
        var tsv = '位置\t母版原值\t本期填充\t来源\n' + rows.map(function (r) {
          return [r.loc, r.old, r.new, r.source].join('\t');
        }).join('\n');
        copy(tsv, b, '已复制 ' + rows.length + ' 行');
      });
    });
  }

  function wireSide() {
    root.querySelectorAll('#whcSide button[data-copy]').forEach(function (b) {
      bindOnce(b, 'click', function () { copy(b.dataset.copy, b, '已复制'); });
    });
    var qb = root.querySelector('#whcSide button[data-quote]');
    if (qb) bindOnce(qb, 'click', function (ev) {
      ev.stopPropagation();
      if (state.focus) popup(ev, state.focus);
    });
  }

  function strip(h) { return String(h).replace(/<[^>]+>/g, ''); }

  function copy(text, btn, okMsg) {
    var done = function () { var t = btn.textContent; btn.textContent = okMsg; setTimeout(function () { btn.textContent = t; }, 1200); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(); });
    } else fallback();
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { }
      document.body.removeChild(ta);
    }
  }

  function currentSection() {
    return D.sections.filter(function (s) { return s.id === state.sec; })[0] || D.sections[0];
  }
  function findSlot(loc) {
    for (var i = 0; i < D.sections.length; i++) {
      var arr = D.sections[i].slots;
      for (var j = 0; j < arr.length; j++) if (arr[j].loc === loc) return arr[j];
    }
    return null;
  }
  function goto(id) {
    state.sec = id;
    state.expandCells = null;
    if (window.history && window.history.replaceState) window.history.replaceState(null, '', '#' + id);
    paint();
    window.scrollTo(0, 0);
  }
  function ensureVisible(silent) {
    var sec = currentSection();
    if (sec && sectionCount(sec)) return;
    var next = D.sections.filter(function (s) { return sectionCount(s); })[0];
    if (next) state.sec = next.id;
  }

  /* 溯源浮层 */
  var pop = document.getElementById('whcPop');
  function popup(ev, sl) {
    if (!pop) return;
    pop.innerHTML = '<div class="ph">台 账 槽 位</div><div class="pc">' + esc(sl.loc) + '</div>' +
      '<div class="pr"><span>' + esc(sl.oldLabel || '母版原值') + '</span><b>' + esc(sl.old || '（空）') + '</b></div>' +
      '<div class="pr"><span>本期写入</span><b>' + esc(sl.new) + '</b></div>' +
      '<div class="pf">' + esc(sl.source) + (sl.manual ? ' · 待人工补录' : '') + '</div>';
    pop.classList.add('on');
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var x = ev.clientX + 14, y = ev.clientY + 16;
    if (x + w > window.innerWidth - 16) x = ev.clientX - w - 14;
    if (y + h > window.innerHeight - 16) y = ev.clientY - h - 12;
    pop.style.left = Math.max(12, x) + 'px';
    pop.style.top = Math.max(12, y) + 'px';
  }
  document.addEventListener('click', function () { if (pop) pop.classList.remove('on'); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && pop) pop.classList.remove('on');
    if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      var ids = D.sections.map(function (s) { return s.id; });
      var i = ids.indexOf(state.sec);
      var next = e.key === 'ArrowRight' ? (i + 1) % ids.length : (i + ids.length - 1) % ids.length;
      goto(ids[next]);
    }
  });

  /* 首发：URL 哈希可直达某分组（#bigtable / #forecast …），便于分享与复核 */
  var first = D.sections.filter(function (s) { return s.count; })[0];
  state.sec = first ? first.id : (D.sections[0] || {}).id;
  var hash = (location.hash || '').replace(/^#/, '');
  if (hash && D.sections.some(function (s) { return s.id === hash; })) state.sec = hash;
  /* 已签单：给根节点挂 signed，钤印动画在签单后回带的那一屏上落下 */
  if (AS === 'signed') root.classList.add('signed');
  paint();
})();

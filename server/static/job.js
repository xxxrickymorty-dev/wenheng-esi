(function () {
  var job = window.__JOB__ || {};

  // ---- 任务状态（10 态）------------------------------------------------------
  // 口径由服务端注入（job.html 里渲染 window.__STATUS_LABELS__ / __TERMINAL__），
  // 唯一来源是 src/agent/states.py。这里不要自己列状态名。
  var LABELS = window.__STATUS_LABELS__ || {};
  var TERMINAL = window.__TERMINAL__ || ['completed', 'warned', 'escalated', 'failed', 'cancelled'];
  // 旧名兜底：历史页面/缓存里的 done/warn/interrupted
  var LEGACY = { done: 'completed', warn: 'warned', interrupted: 'failed' };
  function norm(s) { return LEGACY[s] || s; }
  function isTerminal(s) { return TERMINAL.indexOf(norm(s)) >= 0; }

  // ⚠️ 下面这些 'start'/'done'/'warn'/'failed' 是**步骤级进度**的 CSS 类名，
  //    不是任务状态机。别顺手把它们改成 10 态名——那会改坏样式。
  var stepsEl = document.getElementById('steps');
  var consoleEl = document.getElementById('console');
  var badge = document.getElementById('status-badge');
  var elapsedEl = document.getElementById('elapsed');
  var resultsEl = document.getElementById('results');
  var wfEl = document.getElementById('waterfall');
  var rerunBtn = document.getElementById('rerun');
  var stepMeta = {};

  function setBadge(status) {
    if (!badge) return;
    var s = norm(status);
    badge.className = 'badge ' + s;
    badge.textContent = LABELS[s] || s;
  }

  function resetSteps() {
    Array.prototype.forEach.call(stepsEl.querySelectorAll('.step'), function (li) {
      li.classList.remove('start', 'done', 'warn', 'failed');
      var d = li.querySelector('.detail');
      if (d) d.textContent = '';
    });
    stepMeta = {};
    if (wfEl) wfEl.innerHTML = '';
  }

  function setStep(id, status, detail) {
    var li = stepsEl && stepsEl.querySelector('[data-step="' + id + '"]');
    if (!li) return;
    li.classList.remove('start', 'done', 'warn', 'failed');
    if (status) li.classList.add(status);
    var d = li.querySelector('.detail');
    if (d && detail != null) d.textContent = detail || '';
  }

  function applyEvent(ev) {
    if (!ev) return;
    if (ev.step === 'done') {
      Array.prototype.forEach.call(stepsEl.querySelectorAll('.step'), function (li) {
        if (!li.classList.contains('failed') && !li.classList.contains('warn')) {
          li.classList.remove('start');
          li.classList.add('done');
        }
      });
      return;
    }
    setStep(ev.step, ev.status, ev.detail);
  }

  function trackStep(ev) {
    if (!ev || !ev.step || ev.step === 'done') return;
    var s = stepMeta[ev.step] || (stepMeta[ev.step] = { name: ev.name || ev.step, start: null, end: null, status: 'running' });
    if (ev.status === 'start') {
      s.start = ev.elapsed;
      s.status = 'running';
    } else {
      s.end = ev.elapsed;
      s.status = ev.status || 'done';
    }
    renderWaterfall();
  }

  function renderWaterfall() {
    if (!wfEl) return;
    var ids = Object.keys(stepMeta);
    if (!ids.length) return;
    var total = 0;
    ids.forEach(function (id) { var s = stepMeta[id]; if (s.end != null) total = Math.max(total, s.end); });
    if (job.stats && job.stats.elapsed_sec) total = Math.max(total, job.stats.elapsed_sec);
    if (!total) total = 1;
    var html = '';
    ids.forEach(function (id) {
      var s = stepMeta[id];
      var start = s.start != null ? s.start : 0;
      var end = s.end != null ? s.end : start;
      var left = Math.max(0, Math.min(100, start / total * 100));
      var width = Math.max(1, (end - start) / total * 100);
      var cls = s.end == null ? 'running' : (s.status === 'warn' ? 'warn' : 'done');
      html += '<div class="wf-row"><span class="wf-label">' + s.name + '</span>'
        + '<div class="wf-track"><div class="wf-bar ' + cls + '" style="left:' + left.toFixed(2) + '%;width:' + width.toFixed(2) + '%"></div></div>'
        + '<span class="wf-time">' + (s.end != null ? (end - start).toFixed(1) + 's' : '…') + '</span></div>';
    });
    wfEl.innerHTML = html;
  }

  function appendLog(line) {
    if (!consoleEl) return;
    consoleEl.textContent += line + '\n';
    var lines = consoleEl.textContent.split('\n');
    if (lines.length > 700) consoleEl.textContent = lines.slice(-500).join('\n');
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  function fmtSize(n) {
    if (!n && n !== 0) return '';
    if (n > 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    return (n / 1024).toFixed(1) + ' KB';
  }

  function renderArtifacts(list) {
    if (!resultsEl || !list || !list.length) return;
    var html = '';
    list.forEach(function (a) {
      var dl = a.key === 'red_view' ? '' : ' download';
      html += '<a class="artifact' + (a.primary ? ' primary' : '') + '" href="' + a.url + '"' + dl + '>'
        + '<b>' + a.label + '</b>'
        + '<span class="muted small">' + a.name + (a.size ? ' · ' + fmtSize(a.size) : '') + '</span></a>';
    });
    resultsEl.innerHTML = html;
  }

  function updateStats(j) {
    var s = j && j.stats;
    if (!s) return;
    var el;
    el = document.getElementById('st-assert');
    if (el) el.textContent = s.assertions_ok ? '全绿' : (s.assertions_fail + ' 项未过');
    el = document.getElementById('st-mape');
    if (el) el.textContent = s.predict_mape_overall + '%';
    el = document.getElementById('st-charts');
    if (el) el.textContent = s.charts + ' 张';
    el = document.getElementById('st-elapsed');
    if (el) el.textContent = s.elapsed_sec + ' 秒';
  }

  function loadArtifacts() {
    fetch('/api/jobs/' + job.id + '/artifacts')
      .then(function (r) { return r.json(); })
      .then(function (d) { renderArtifacts(d.artifacts); updateStats(d.job); })
      .catch(function () {});
  }

  function setRerunVisible(show) {
    if (rerunBtn) rerunBtn.style.display = show ? '' : 'none';
  }

  function startTimer(started, finished) {
    if (!elapsedEl) return;
    var t0 = Date.parse((started || '').replace(' ', 'T'));
    if (isNaN(t0)) return;
    function fmt(ms) { return (ms / 1000).toFixed(1) + ' 秒'; }
    if (finished) {
      var t1 = Date.parse(String(finished).replace(' ', 'T'));
      if (!isNaN(t1)) { elapsedEl.textContent = fmt(t1 - t0); return; }
    }
    elapsedEl.textContent = fmt(Date.now() - t0);
    var iv = setInterval(function () { elapsedEl.textContent = fmt(Date.now() - t0); }, 200);
    window.__timerIv = iv;
  }

  // 页面刷新时的静态回放（SSE 连接后还会重放一遍，幂等）
  (window.__EVENTS__ || []).forEach(function (ev) { applyEvent(ev); trackStep(ev); });
  if (job.status && isTerminal(job.status)) setBadge(job.status);
  setRerunVisible(isTerminal(job.status));
  startTimer(job.started_at, job.finished_at);

  if (rerunBtn) {
    rerunBtn.addEventListener('click', function () {
      if (!window.confirm('重跑本期将生成一条新的运行记录（旧记录保留），继续？')) return;
      rerunBtn.disabled = true;
      fetch('/api/jobs/' + job.id + '/rerun', { method: 'POST' })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok) throw new Error(res.d.error || '重跑失败');
          location.href = res.d.url;
        })
        .catch(function (err) {
          window.alert('重跑失败：' + err.message);
          rerunBtn.disabled = false;
        });
    });
  }

  var es = new EventSource('/api/jobs/' + job.id + '/events');

  es.onopen = function () {
    // 每次(重)连服务端都从头重放：清空本地回放状态，避免重复
    if (consoleEl) consoleEl.textContent = '';
    resetSteps();
  };
  es.addEventListener('progress', function (e) {
    try {
      var ev = JSON.parse(e.data);
      applyEvent(ev);
      trackStep(ev);
    } catch (_) {}
  });
  es.addEventListener('log', function (e) {
    try { appendLog(JSON.parse(e.data).line); } catch (_) {}
  });
  es.addEventListener('status', function (e) {
    var j = JSON.parse(e.data);
    setBadge(j.status);
    if (isTerminal(j.status)) {
      es.close();
      if (window.__timerIv) clearInterval(window.__timerIv);
      setRerunVisible(true);
      loadArtifacts();
    }
  });
})();

(function () {
  var job = window.__JOB__ || {};
  var TERMINAL = ['done', 'warn', 'failed', 'interrupted'];
  var stepsEl = document.getElementById('steps');
  var consoleEl = document.getElementById('console');
  var badge = document.getElementById('status-badge');
  var elapsedEl = document.getElementById('elapsed');
  var resultsEl = document.getElementById('results');

  function setBadge(status) {
    if (!badge) return;
    badge.className = 'badge ' + status;
    badge.textContent = {
      done: '完成', warn: '断言未过（已出稿待复核）', failed: '失败',
      running: '运行中', interrupted: '已中断'
    }[status] || status;
  }

  function resetSteps() {
    Array.prototype.forEach.call(stepsEl.querySelectorAll('.step'), function (li) {
      li.classList.remove('start', 'done', 'warn', 'failed');
      var d = li.querySelector('.detail');
      if (d) d.textContent = '';
    });
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

  function startTimer(started) {
    var t0 = Date.parse((started || '').replace(' ', 'T'));
    if (isNaN(t0)) return;
    function tick() {
      if (elapsedEl) elapsedEl.textContent = ((Date.now() - t0) / 1000).toFixed(1) + ' 秒';
    }
    tick();
    setInterval(tick, 200);
  }

  // 页面刷新时的静态回放（SSE 连接后还会重放一遍，幂等）
  (window.__EVENTS__ || []).forEach(applyEvent);
  if (job.status && TERMINAL.indexOf(job.status) >= 0) setBadge(job.status);
  startTimer(job.started_at);

  var es = new EventSource('/api/jobs/' + job.id + '/events');

  es.onopen = function () {
    // 每次(重)连服务端都从头重放：清空本地回放状态，避免重复
    if (consoleEl) consoleEl.textContent = '';
    resetSteps();
  };
  es.addEventListener('progress', function (e) {
    try { applyEvent(JSON.parse(e.data)); } catch (_) {}
  });
  es.addEventListener('log', function (e) {
    try { appendLog(JSON.parse(e.data).line); } catch (_) {}
  });
  es.addEventListener('status', function (e) {
    var j = JSON.parse(e.data);
    setBadge(j.status);
    if (TERMINAL.indexOf(j.status) >= 0) {
      es.close();
      loadArtifacts();
    }
  });
})();

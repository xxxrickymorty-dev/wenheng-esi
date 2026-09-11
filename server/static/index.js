(function () {
  var form = document.getElementById('run-form');
  if (!form) return;
  var msg = document.getElementById('run-msg');
  var btn = form.querySelector('button[type=submit]');

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var sel = form.querySelector('[name=period_sel]').value;
    var neu = (form.querySelector('[name=period_new]').value || '').trim();
    var fileInput = form.querySelector('[name=file]');
    var period = fileInput.files.length ? neu : sel;
    if (!/^\d{6}$/.test(period)) {
      msg.textContent = '请先选择期次；如上传承台账，请填写 6 位期次（如 202609）';
      msg.className = 'alert err';
      return;
    }
    var fd = new FormData();
    if (fileInput.files.length) fd.append('file', fileInput.files[0]);
    fd.append('period', period);
    var bt = form.querySelector('[name=backtest]');
    fd.append('backtest', bt && bt.checked ? '1' : '0');

    btn.disabled = true;
    msg.textContent = '正在创建任务…';
    msg.className = 'muted small';

    fetch('/api/jobs', { method: 'POST', body: fd })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.d.error || '请求失败');
        msg.textContent = '任务已创建，正在跳转…';
        location.href = res.d.url;
      })
      .catch(function (err) {
        msg.textContent = '创建失败：' + err.message;
        msg.className = 'alert err';
        btn.disabled = false;
      });
  });
})();

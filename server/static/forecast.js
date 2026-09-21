(function () {
  "use strict";
  const form = document.getElementById("forecast-form");
  if (!form) return;
  const message = document.getElementById("forecast-message");
  const target = document.getElementById("forecast-result");
  const esc = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const period = (value) => value ? `${String(value).slice(0,4)}-${String(value).slice(4)}` : "预测期内未过线";
  const num = (value, digits=2) => value == null || !Number.isFinite(Number(value))
    ? "—"
    : Number(value).toLocaleString("zh-CN", {maximumFractionDigits: digits, minimumFractionDigits: digits});

  function resultCard(data, item) {
    const recommended = item.model === data.recommended_model;
    const rows = item.forecast.map((r) => `<tr class="${r.crossed ? "crossed" : ""}"><td>${period(r.period)}</td><td class="num">${num(r.metric1,1)}</td><td class="num">${num(r.metric2,1)}</td><td class="num">${num(r.proximity,2)}%</td></tr>`).join("");
    return `<article class="forecast-model ${recommended ? "recommended" : ""}">
      <div class="model-title"><h2>${esc(item.model)}</h2>${recommended ? '<span class="badge running">V1 基线推荐</span>' : ''}${data.compared_all && item.model === data.comparison_best_model ? '<span class="badge completed">本次误差最低</span>' : ''}</div>
      <div class="model-body">
        <div class="forecast-metrics"><div><b>${num(item.rolling_mape)}%</b><span>综合滚动MAPE</span></div><div><b>${num(item.fit_mape)}%</b><span>历史拟合MAPE</span></div><div><b>${period(item.first_crossing)}</b><span>首次模型过线</span></div><div><b>${item.status === "PASS" ? "通过" : "需复核"}</b><span>V1运行状态</span></div></div>
        <img class="forecast-chart" src="${item.chart}" alt="${esc(data.subject)} ${esc(item.model)}预测趋势图">
        <div class="table-scroll"><table class="forecast-table"><thead><tr><th>期次</th><th>${esc(data.metric_names[0])}</th><th>${esc(data.metric_names[1])}</th><th>接近度</th></tr></thead><tbody>${rows}</tbody></table></div>
      </div></article>`;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    const body = Object.fromEntries(new FormData(form).entries());
    body.horizon = Number(body.horizon);
    button.disabled = true;
    message.className = "forecast-message running";
    message.textContent = body.model === "all" ? "正在运行五模型滚动回测与预测，请稍候……" : "正在运行V1模型，请稍候……";
    target.hidden = true;
    try {
      const response = await fetch("/api/forecast/run", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "预测运行失败");
      const errors = data.errors.length ? `<div class="alert warn model-error-list">${data.errors.map((x) => `${esc(x.model)}：${esc(x.error)}`).join("<br>")}</div>` : "";
      target.innerHTML = `<div class="readouts forecast-summary"><div class="readout"><div class="v">${esc(data.subject)}</div><div class="k">预测学科</div></div><div class="readout"><div class="v">${esc(data.model_version)}</div><div class="k">模型版本</div></div><div class="readout"><div class="v">${data.history_periods}</div><div class="k">有效历史期数</div></div><div class="readout"><div class="v">${period(data.data_end)}</div><div class="k">数据截止期</div></div></div>${errors}${data.results.map((x) => resultCard(data,x)).join("")}<div class="alert warn">${esc(data.notice)}</div>`;
      target.hidden = false;
      message.className = "forecast-message";
      message.textContent = `完成：${data.results.length}个模型，数据来源 ${data.source_period} 期派生产物。`;
    } catch (error) {
      message.className = "forecast-message error";
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
})();

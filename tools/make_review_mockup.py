# -*- coding: utf-8 -*-
"""生成「审核台 · 试排报告」静态稿（单文件、双击即开、零外链）。

数据来自真实产物：`out/<期次>/报告初稿_*.docx` → `server.report_preview`。
样式与将来的 React 版共用同一套令牌（web/src/index.css 的 :root）。

用法（在仓库根）：
    .venv\\Scripts\\python.exe tools\\make_review_mockup.py [期次]
默认期次 202609；输出 `web/mockups/审核台-试排报告.html`。
"""
from __future__ import annotations

import base64
import html
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "src")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from server import report_preview                                  # noqa: E402

#: 静态稿里给 rick 看的「已填」示例（重出后这些值会出现在报告正文里）
PRE_FILL = {"正文/p1::ESI发布日期": "2026年9月23日"}

#: main() 里装入 rId → (bytes, content_type)
IMAGES: dict = {}


def esc(s):
    return html.escape(str(s or ""), quote=True)


def run_html(seg):
    if "ph" in seg:
        fid = seg["ph"]
        val = PRE_FILL.get(fid, "")
        filled = ' data-filled="1"' if val else ""
        return (f'<span class="ph"><input value="{esc(val)}"{filled} '
                f'placeholder="{esc(seg.get("title") or "填在这里")}" '
                f'title="{esc(seg.get("title") or "")}"></span>')
    text = esc(seg.get("t")).replace("\n", "<br>")
    if seg.get("b"):
        text = f"<b>{text}</b>"
    size = seg.get("size")
    if size:
        return f'<span style="font-size:{size * 1.333:.1f}px">{text}</span>'
    return text


def img_tag(rid, w_cm=None):
    blob, ctype = IMAGES[rid]
    b64 = base64.b64encode(blob).decode()
    style = f' style="width:{w_cm * 37.8:.0f}px"' if w_cm else ""
    return f'<img src="data:{ctype};base64,{b64}"{style} alt="报告插图">'


def block_html(b):
    kind = b.get("t")
    if kind == "p":
        inner = "".join(run_html(seg) for seg in b["runs"])
        align = f' style="text-align:{b["align"]}"' if b.get("align") else ""
        cls = "rp-para"
        if b.get("align") == "center":
            cls += " rp-center"
        return f'<p class="{cls}"{align}>{inner}</p>'
    if kind == "img":
        return f'<p class="rp-img">{img_tag(b["rid"], b.get("w_cm"))}</p>'
    if kind == "tbl":
        rows = []
        for row in b["rows"]:
            tds = []
            for cell in row:
                attrs = f' colspan="{cell["span"]}"' if cell.get("span") else ""
                content = esc(cell["text"]).replace("\n", "<br>")
                for rid in cell.get("imgs") or []:
                    content += img_tag(rid)
                tds.append(f"<td{attrs}>{content}</td>")
            rows.append("<tr>" + "".join(tds) + "</tr>")
        return '<div class="tblwrap"><table>' + "".join(rows) + "</table></div>"
    return ""


CSS = """
:root{
  --bg:#F4F3ED; --card:#FFFDF8; --panel:#F0F1EB;
  --ink:#222B25; --ink-2:#3F4C42; --ink-3:#58655C;
  --line:#DDE1D8; --line-2:#E6E9E2;
  --zhu:#1A4B27; --zhu-soft:#E3EDE4;
  --gold:#B19A65; --gold-soft:#F1EBDD; --gold-ink:#62501F;
  --ok:#28643A; --ok-soft:#E2EEE4;
  --warn:#75622D; --warn-soft:#F6EED8;
  --bad:#B43B31; --bad-soft:#F4E6E2;
  --serif:"Source Han Serif SC","Noto Serif SC","Songti SC",SimSun,serif;
  --sans:system-ui,-apple-system,"Microsoft YaHei","PingFang SC",sans-serif;
  --mono:"Cascadia Mono",Consolas,"Courier New",monospace;
  --r:14px; --r-sm:10px;
  --shadow:0 1px 2px rgba(34,43,37,.06),0 8px 24px rgba(34,43,37,.06);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.7 var(--sans)}
h1,h2,h3{font-family:var(--serif);font-weight:600;margin:0}
.topbar{display:flex;align-items:center;gap:18px;padding:13px 22px;background:var(--card);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:baseline;gap:10px;font-family:var(--serif)}
.brand strong{font-size:22px;letter-spacing:.05em}
.brand span{font-size:13px;color:var(--ink-3);letter-spacing:.16em}
.nav{display:flex;gap:4px;margin-left:auto}
.nav a{display:flex;align-items:center;gap:7px;padding:9px 13px;border-radius:10px;color:var(--ink-2);text-decoration:none;font-size:15px}
.nav a[aria-current="page"]{background:var(--zhu-soft);color:var(--zhu);font-weight:600}
.wrap{max-width:1400px;margin:0 auto;padding:22px 22px 70px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow)}
.pill{border-radius:999px;padding:3px 11px;font-size:13.5px;display:inline-block}
.pill.signed{background:var(--zhu-soft);color:var(--zhu)}
.pill.unsigned{background:var(--panel);color:var(--ink-3)}
.pill.stale{background:var(--gold-soft);color:var(--gold-ink)}
.hint{color:var(--ink-3);font-size:13.5px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:11px 18px;border-radius:9px;
  border:1px solid var(--line);background:var(--card);cursor:pointer;font:inherit;font-size:15.5px;font-weight:600;color:inherit;text-decoration:none}
.btn.primary{background:var(--zhu);border-color:var(--zhu);color:#fff;font-size:16.5px}
.btn[disabled],.btn.disabled{opacity:.45;cursor:not-allowed;filter:none}
.lead{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:14px 2px}
.lead h1{font-size:23px}
.review-grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px;align-items:start}
@media (max-width:1080px){.review-grid{grid-template-columns:1fr}.side{position:static!important}}
/* ---- 报告纸 ---- */
.report{padding:34px 42px 46px;font-family:var(--serif);background:#FFFEFA}
.rp-para{margin:0 0 10px;text-indent:2em;font-size:15.5pt;line-height:1.95;text-align:justify}
.rp-center{text-indent:0;text-align:center!important}
.rp-img{text-indent:0;text-align:center;margin:14px 0}
.rp-img img,.tblwrap img{max-width:100%;height:auto}
.tblwrap{overflow-x:auto;margin:12px 0 16px}
.tblwrap table{border-collapse:collapse;width:100%;font-size:13.5px;font-family:var(--sans);line-height:1.6}
.tblwrap td{border:1px solid var(--line);padding:4px 7px;vertical-align:middle}
.tblwrap tr:first-child td{background:var(--panel);font-weight:600}
.tblwrap img{max-width:230px}
/* ---- 就地填空 ---- */
.ph{display:inline-flex;vertical-align:baseline}
.ph input{font:inherit;font-size:.92em;color:var(--bad);min-width:120px;max-width:210px;width:150px;
  padding:1px 8px;margin:0 2px;border:1.5px dashed var(--bad);border-radius:7px;background:var(--bad-soft);
  text-align:center}
.ph input::placeholder{color:var(--bad);opacity:.75}
.ph input[data-filled="1"]{border-style:solid;background:#FFF;color:var(--ink);font-weight:600}
.ph input:focus{outline:3px solid var(--zhu-soft);outline-offset:1px}
/* ---- 右栏 ---- */
.side{position:sticky;top:16px;display:grid;gap:14px}
.side .card{padding:18px 18px 16px}
.side h3{font-size:17px;display:flex;align-items:center;gap:8px}
.side .kv{display:flex;justify-content:space-between;font-size:14.5px;padding:6px 0;border-bottom:1px dashed var(--line-2)}
.side .kv b{font-variant-numeric:tabular-nums}
.side label{display:flex;gap:9px;align-items:flex-start;font-size:14.5px;margin-top:10px;line-height:1.55}
.side label span{flex:1}
.side textarea{width:100%;font:inherit;font-size:14px;margin-top:10px;padding:8px 10px;border:1px solid var(--line);
  border-radius:9px;background:var(--card);color:inherit;resize:vertical}
.side .btns{display:flex;gap:9px;flex-wrap:wrap;margin-top:12px}
.side .btns .btn{flex:1;min-width:120px}
.dl a{width:100%}
.fillstat .bar{height:8px;border-radius:99px;background:var(--panel);overflow:hidden;margin:9px 0 2px}
.fillstat .bar i{display:block;height:100%;background:var(--gold);border-radius:99px}
.ok-note{color:var(--ok)}
.reg-note{color:var(--bad)}
.footer{max-width:1400px;margin:26px auto 0;padding:0 22px;color:var(--ink-3);font-size:13px}
details.notes{margin-top:10px}
details.notes summary{cursor:pointer;color:var(--ink-3);font-size:13.5px}
/* 演示开关 */
.stage-switch{display:flex;gap:6px;align-items:center;background:var(--panel);border:1px solid var(--line);
  border-radius:999px;padding:4px 6px;font-size:13px;color:var(--ink-3)}
.stage-switch button{border:0;background:transparent;font:inherit;font-size:13px;color:var(--ink-2);
  border-radius:999px;padding:4px 12px;cursor:pointer}
.stage-switch button[aria-pressed="true"]{background:var(--zhu);color:#fff;font-weight:600}
"""


def build_html(period, data):
    fields_n = len(data["fields"])
    n_ph = data["n_manual_ph"]
    blocks_html = "\n".join(block_html(b) for b in data["blocks"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>审核台 · 试排报告 · {esc(period)} · 文衡（静态稿）</title>
<style>{CSS}</style>
</head>
<body>
<header class="topbar">
  <div class="brand"><strong>文衡</strong><span>学科信息参考</span></div>
  <nav class="nav">
    <a href="#">生成台</a><a href="#">报告</a><a href="#" aria-current="page">审核台</a><a href="#">台账</a><a href="#">分析台</a>
  </nav>
  <span class="hint">期次 <b>{esc(period)}</b></span>
</header>

<main class="wrap">
  <div class="lead">
    <a class="hint" href="#" style="text-decoration:none">← 回报告 · 期次 {esc(period)}</a>
    <h1 style="margin-left:6px">审核 · 试排报告</h1>
    <span class="pill unsigned" id="st-pill">未签单</span>
    <span class="hint">数据核对 48/48 全部通过 · 待人工 {fields_n} 处</span>
    <span class="stage-switch" style="margin-left:auto" title="静态稿演示用：切换签单状态，看下载按钮两态">
      <button aria-pressed="true" onclick="setStage(false)">未签单态</button>
      <button aria-pressed="false" onclick="setStage(true)">已签单态</button>
    </span>
  </div>

  <div class="review-grid">
    <section class="card report">
      {blocks_html}
    </section>

    <aside class="side">
      <section class="card">
        <h3>审核 · 签单</h3>
        <div class="kv"><span>报告版本</span><b>{esc(data['docx'])}</b></div>
        <div class="kv"><span>生成时间</span><b>{esc(data['updated_at'])}</b></div>
        <div class="kv"><span>待人工</span><b>{fields_n} 处</b></div>
        <label><input type="checkbox" checked><span>我已逐项看过<b>待人工</b>与<b>存疑</b>处（当前还剩 {fields_n - 1} 处未填），同意放行。</span></label>
        <textarea rows="2" placeholder="批注（可选）：这一版为什么可以签单、还有哪些已知问题"></textarea>
        <div class="btns">
          <button class="btn primary">签单</button>
          <button class="btn">撤回</button>
        </div>
        <p class="hint" style="margin-top:8px">签单会绑定这一版报告；重跑或重出后签名自动失效。</p>
      </section>

      <section class="card dl">
        <h3>报告文件</h3>
        <a class="btn disabled" id="dl-btn" href="#" onclick="return false">下载报告（Word，{esc(period)}）</a>
        <p class="hint" id="dl-hint" style="margin-top:8px">签单后可下载到本地。</p>
      </section>

      <section class="card fillstat">
        <h3>填空</h3>
        <div class="bar"><i style="width:14%"></i></div>
        <p class="hint">报告里 {fields_n} 处要人填：已填 1 处（含 0 处未写入报告），还剩 {fields_n - 1} 处。</p>
        <div class="btns">
          <button class="btn">保存填写</button>
          <button class="btn primary" style="flex-basis:100%">保存并重出报告</button>
        </div>
        <p class="hint" style="margin-top:8px">填的值只进报告，台账一个字节不动。</p>
      </section>
    </aside>
  </div>

  <div class="footer">
    <details class="notes">
      <summary>说明（口径 · 来源 · 只读声明）</summary>
      <p>报告文字与表格按当前试排稿（Word）原样呈现；带虚线框的空是机器留下的「待人工」处，就地填、保存后重出即写入报告。数字均来自台账与 ESI 官方数据，改数字请回台账。</p>
    </details>
  </div>
</main>

<script>
function setStage(signed){{
  document.getElementById('st-pill').className = 'pill ' + (signed ? 'signed' : 'unsigned');
  document.getElementById('st-pill').textContent = signed ? '已签单' : '未签单';
  var b = document.getElementById('dl-btn'), h = document.getElementById('dl-hint');
  if (signed) {{ b.classList.remove('disabled'); h.textContent = '已签单，可下载这一版报告。'; }}
  else {{ b.classList.add('disabled'); h.textContent = '签单后可下载到本地。'; }}
  document.querySelectorAll('.stage-switch button').forEach(function(x,i){{
    x.setAttribute('aria-pressed', String(signed ? i===1 : i===0));
  }});
}}
</script>
</body>
</html>
"""


def main():
    period = sys.argv[1] if len(sys.argv) > 1 else "202609"
    out_dir = REPO / "out" / period
    data = report_preview.build(out_dir)
    if not data.get("docx"):
        print(f"out/{period}/ 下没有报告初稿 docx —— 先生成这一期")
        return 1
    loaded = report_preview.load(out_dir)
    assert loaded is not None
    IMAGES.update(loaded["images"])
    page = build_html(period, data)
    out = REPO / "web" / "mockups" / "审核台-试排报告.html"
    out.write_text(page, encoding="utf-8")
    print(f"静态稿已生成：{out}（{len(page)/1024/1024:.1f} MB，含 {len(IMAGES)} 张内联图）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

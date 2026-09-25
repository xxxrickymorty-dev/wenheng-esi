# -*- coding: utf-8 -*-
"""把 out/<期次>/ 的真实对勘数据内联成 server/static/collation-demo.html。

为什么要它：
- 演示站入口 `/jobs/<任务id>/collation` 需要登录 + 起服务，评审/离线场景不便；
- 这个静态快照不启动服务器即可打开，且与模板同源（同一个 `collation.build`）。

2026-09-24（⑦）：快照升级为**单文件自足**——样式与脚本就地内联
（`<style id="whc-snapshot-style">` / `<script id="whc-snapshot-script">`），
`static/collation.css`、`static/collation.js` 已随之删除：老对勘页 302 后它们没有别的消费者。
两个文件的内容此后**只存在于快照里**，所以本生成器优先读 static/ 源文件（若从 git 历史恢复），
否则从现有快照提取内联块——「新版快照 = 冻结的样式/脚本 + 新期次数据」，样式不会漂。

用法（跑完 run_pipeline 后执行）：
    .venv\\Scripts\\python.exe server\\make_collation_snapshot.py 202607
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from collation import build  # noqa: E402

STATIC = HERE / "static"
OUT_HTML = STATIC / "collation-demo.html"
STYLE_ID = "whc-snapshot-style"
SCRIPT_ID = "whc-snapshot-script"

SHELL = """<!doctype html>
<!--
  文衡 · 对勘本 · 静态快照（__PERIOD__ 期真实数据 · 全量 __TOTAL__ 处）
  用途：不启动服务器即可查看对勘本；**单文件自足**——样式与脚本已内联
  （whc-snapshot-style / whc-snapshot-script 两块），拷走这一个文件就能离线打开。
  数据取自 out/__PERIOD__/red_slots.json + meta.json，由 server/make_collation_snapshot.py 生成，
  与 templates/collation.html 走同一个 collation.build()——不要手改本文件，改生成器。
  正式入口：演示站 `/app/?view=reading&period=__PERIOD__`（老 /p/<期次> 已 302）
-->
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>对勘本 · __PERIOD__ · 文衡（静态快照）</title>
<style id="whc-snapshot-style">
__INLINE_CSS__
</style>
</head>
<body class="whc-body">

<div class="reg tl"></div><div class="reg tr"></div><div class="reg bl"></div><div class="reg br"></div>

<header class="topbar">
  <div class="wrap">
    <a class="brand" href="#"><span class="seal seal-sm">衡</span><span class="logo">文衡</span><span class="sub">学科信息参考 · 对 勘 本</span></a>
    <nav><span class="who">静态快照</span></nav>
  </div>
</header>

<main class="wrap">
  <p class="whc-crumb">静态快照 · __PERIOD__ 期真实数据 · 全量 __TOTAL__ 槽位 · 与演示站报告阅读同源同构</p>

  <div class="whc" id="whc">
    <header class="whc-hero" id="whcHero"></header>
    <div class="whc-bar" id="whcBar"></div>
    <div class="whc-grid">
      <nav class="whc-nav" id="whcNav"></nav>
      <div class="whc-main" id="whcMain"></div>
      <aside class="whc-side" id="whcSide"></aside>
    </div>
    <div class="whc-tail" id="whcFoot"></div>
  </div>

  <div class="whc-pop" id="whcPop"></div>
</main>

<footer class="foot"><span>演示环境 · 数据为公开 ESI / InCites 指标 · 大模型不进入数据路径 · 数字 100% 可回溯台账</span></footer>

<script>window.__COLLATION__ = __DATA__;</script>
<script id="whc-snapshot-script">
__INLINE_JS__
</script>
</body>
</html>
"""


def _inlined_block(html, tag, tag_id):
    """从已有快照里取内联块内容（按标记定位，不拿第一个 <style> 猜）。"""
    m = re.search(r"<%s id=\"%s\">\n(.*?)\n</%s>" % (tag, re.escape(tag_id), tag),
                  html, flags=re.S)
    return m.group(1) if m else None


def load_assets():
    """(css, js, 来源说明)。

    优先读 static/ 源文件（2026-09-24 前的形态，可从 git 历史恢复）；
    源文件已删后从现有快照提取——样式/脚本的**唯一现役副本就是快照**。
    """
    css = js = None
    css_files = [STATIC / "style.css", STATIC / "collation.css"]
    if all(p.exists() for p in css_files):
        css = "\n".join(p.read_text(encoding="utf-8") for p in css_files)
    if (STATIC / "collation.js").exists():
        js = (STATIC / "collation.js").read_text(encoding="utf-8")
    source = "static/ 源文件"
    if css is None or js is None:
        if OUT_HTML.exists():
            old = OUT_HTML.read_text(encoding="utf-8")
            css = css if css is not None else _inlined_block(old, "style", STYLE_ID)
            js = js if js is not None else _inlined_block(old, "script", SCRIPT_ID)
            source = f"{OUT_HTML.name} 的内联块"
    if not css or not js:
        raise SystemExit(
            "找不到对勘本样式/脚本：static/ 源文件已删（2026-09-24 ⑦），"
            f"{OUT_HTML.name} 里也没有 {STYLE_ID}/{SCRIPT_ID} 内联块。\n"
            "从 git 历史恢复源文件再跑：\n"
            "  git show <老提交>:server/static/collation.css > server/static/collation.css\n"
            "  git show <老提交>:server/static/collation.js  > server/static/collation.js")
    return css, js, source


def render(data, root="out"):
    d = dict(data)
    d["actor"] = "馆员"
    d["signedAt"] = ""
    # 快照是静态文件，没有服务端可落库 → 签单区切换为只读说明，不假造「已签单」
    d["jobId"] = ""
    d["signUrl"] = ""
    d["revokeUrl"] = ""
    d["backUrl"] = ""
    d["crumbs"] = []
    d["periods"] = []
    d["approval"] = {}
    d["approvalStatus"] = "unsigned"
    d["flash"] = {}
    d["snapshotNote"] = (
        "静态快照：全量内联 %d 个槽位（与演示站同源同构）；签单要绑住当时那份报告并落库，"
        "快照里没有服务端，故签单区为只读。线上入口是报告阅读："
        "/app/?view=reading&period=%s" % (d["counts"]["total"], d["period"])
    )
    payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    # 防止正文里出现 </script> 提前闭合
    payload = payload.replace("</", "<\\/")
    css, js, _source = load_assets()
    return (SHELL
            .replace("__PERIOD__", d["period"])
            .replace("__TOTAL__", str(d["counts"]["total"]))
            .replace("__INLINE_CSS__", css)
            .replace("__INLINE_JS__", js)
            .replace("__DATA__", payload))


def main():
    period = sys.argv[1] if len(sys.argv) > 1 else "202607"
    out_root = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("out")
    target = out_root / period
    if not (target / "red_slots.json").exists():
        print("找不到 %s/red_slots.json" % target)
        return 1
    data = build(target)
    css, js, source = load_assets()
    html = render(data)
    OUT_HTML.write_text(html, encoding="utf-8")
    c = data["counts"]
    print("快照 → %s" % OUT_HTML)
    print("期次 %s（上期 %s）· 槽位 %d（文字 %d / 大表 %d / 图 %d）· 待人工 %d"
          % (data["period"], data["periodPrev"], c["total"], c["text"], c["cell"], c["chart"], c["manual"]))
    print("样式/脚本来源：%s（内联 CSS %d + JS %d 字节，单文件自足）"
          % (source, len(css.encode("utf-8")), len(js.encode("utf-8"))))
    print("字节 %d" % len(html.encode("utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

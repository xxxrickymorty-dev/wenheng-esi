# -*- coding: utf-8 -*-
"""把 out/<期次>/ 的真实对勘数据内联成 server/static/collation-demo.html。

为什么要它：
- 演示站入口 `/jobs/<任务id>/collation` 需要登录 + 起服务，评审/离线场景不便；
- 这个静态快照不启动服务器即可打开，且与模板同源（同一个 `collation.build`），
  CSS / JS 共用 `static/collation.css` 与 `static/collation.js`，不存在两套实现。

用法（跑完 run_pipeline 后执行）：
    .venv\\Scripts\\python.exe server\\make_collation_snapshot.py 202607
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from collation import build  # noqa: E402

OUT_HTML = HERE / "static" / "collation-demo.html"

SHELL = """<!doctype html>
<!--
  文衡 · 对勘本 · 静态快照（__PERIOD__ 期真实数据 · 全量 __TOTAL__ 处）
  用途：不启动服务器即可查看对勘本；CSS / JS 与演示站同一份文件（style.css / collation.css / collation.js）。
  数据取自 out/__PERIOD__/red_slots.json + meta.json，由 server/make_collation_snapshot.py 生成，
  与 templates/collation.html 走同一个 collation.build()——不要手改本文件，改生成器。
  正式入口：演示站登录后的首屏 `/`（即最新一期对勘本），或按期次 /p/<期次>
-->
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>对勘本 · __PERIOD__ · 文衡（静态快照）</title>
<link rel="stylesheet" href="style.css">
<link rel="stylesheet" href="collation.css">
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
  <p class="whc-crumb">静态快照 · __PERIOD__ 期真实数据 · 全量 __TOTAL__ 槽位 · 与演示站首屏 <span class="mono">/</span> 同一套模板与脚本</p>

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
<script src="collation.js"></script>
</body>
</html>
"""


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
        "快照里没有服务端，故签单区为只读。线上入口即登录后的首屏 /" % d["counts"]["total"]
    )
    payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    # 防止正文里出现 </script> 提前闭合
    payload = payload.replace("</", "<\\/")
    return (SHELL
            .replace("__PERIOD__", d["period"])
            .replace("__TOTAL__", str(d["counts"]["total"]))
            .replace("__DATA__", payload))


def main():
    period = sys.argv[1] if len(sys.argv) > 1 else "202607"
    out_root = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("out")
    target = out_root / period
    if not (target / "red_slots.json").exists():
        print("找不到 %s/red_slots.json" % target)
        return 1
    data = build(target)
    html = render(data)
    OUT_HTML.write_text(html, encoding="utf-8")
    c = data["counts"]
    print("快照 → %s" % OUT_HTML)
    print("期次 %s（上期 %s）· 槽位 %d（文字 %d / 大表 %d / 图 %d）· 待人工 %d"
          % (data["period"], data["periodPrev"], c["total"], c["text"], c["cell"], c["chart"], c["manual"]))
    print("字节 %d" % len(html.encode("utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

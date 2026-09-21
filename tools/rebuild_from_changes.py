# -*- coding: utf-8 -*-
"""从 change 全文快照里重建 index.html，并按特征判断是哪个版本。

特征：
  .sbook / buildShelf   → CSS 3D 书架版
  WH_SHELF3D /shelf3d.js → Three.js 书架版
  browse-ui / detailPanel → 参考站 UI 版
"""
import datetime
import json
import re
from pathlib import Path

D = Path(r"C:\Users\damn\.workbuddy\changes-detail\afa605d6-361f-4a90-8233-8aa11e68ed44")
OUT = Path(r"C:\Users\damn\Desktop\首届高校图书馆\wenheng\tmp\_rebuild")
OUT.mkdir(exist_ok=True)

rows = []
for f in D.glob("*.json"):
    d = json.loads(f.read_text(encoding="utf-8"))
    ch = d.get("change", {})
    for x in ch.get("files", []):
        fp = x.get("filePath", "")
        if "WorkingVolumes" in fp and fp.endswith("index.html"):
            # 拼接所有 hunk 的 "+" 行 = 该时点全文
            full = []
            for h in x.get("hunks", []):
                for ln in h.get("lines", []):
                    if ln.startswith("+"):
                        full.append(ln[1:])
                    elif ln.startswith(" "):
                        full.append(ln[1:])
            rows.append({
                "t": f.stat().st_mtime,
                "file": f,
                "text": "\n".join(full),
                "action": x.get("action"),
            })

print(f"共 {len(rows)} 个时点快照\n")
print("  时间  行数    CSS书架  Threejs  参考站UI   判定")
print("  " + "-" * 62)
for r in sorted(rows, key=lambda r: r["t"]):
    t = datetime.datetime.fromtimestamp(r["t"]).strftime("%H:%M")
    s = r["text"]
    css = (".sbook" in s) or ("buildShelf" in s)
    three = ("WH_SHELF3D" in s) or ("shelf3d.js" in s)
    ui = ("browse-ui" in s) or ("detailPanel" in s)
    tags = []
    if css:
        tags.append("CSS书架")
    if three:
        tags.append("Three.js")
    if ui:
        tags.append("参考站UI")
    verdict = "+".join(tags) if tags else "?"
    n = s.count("\n") + 1
    print(f"  {t}  {n:5d}   {str(css):5s}   {str(three):5s}   {str(ui):5s}    {verdict}")

# 落盘：每个时点存一份，便于逐个看
import os
for r in sorted(rows, key=lambda r: r["t"]):
    t = datetime.datetime.fromtimestamp(r["t"]).strftime("%H%M")
    (OUT / f"index-{t}.html").write_text(r["text"], encoding="utf-8")
print(f"\n已落盘到 {OUT}")
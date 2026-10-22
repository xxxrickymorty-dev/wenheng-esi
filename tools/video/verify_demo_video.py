# -*- coding: utf-8 -*-
"""抽帧验证字幕是否真的烧上：底部区域应出现「暗像素块」（黑底字幕框）。

静态卡段背景是浅色 #EFEDE7，若字幕没渲染/渲染成方块，底部不会有成片暗像素。
"""
import io, os, pathlib, subprocess, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from PIL import Image

WINGET_BIN = (pathlib.Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
              / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
              / "ffmpeg-8.1.1-full_build/bin")
BIN = pathlib.Path(os.environ.get("WENHENG_FFMPEG_BIN") or WINGET_BIN)
FFMPEG = str(BIN / "ffmpeg.exe")
BASE = pathlib.Path(__file__).resolve().parents[3]      # 工作区根（tools/<x>/ 上溯三层）
FINAL = BASE / "申报材料/文衡演示视频_20260917.mp4"
TMP = BASE / "wenheng/tmp/video/_frames"
TMP.mkdir(parents=True, exist_ok=True)

# (时间点, 段名, 该段是否有字幕)
PROBES = [(12, "01_pain1", True), (30, "02_pain2", True),
          (60, "04_login", True), (150, "06_redslots", True),
          (290, "11_value", True), (5, "00_title", False)]

for t, name, has_sub in PROBES:
    out = TMP / f"f{t}.png"
    # output seek（-ss 在 -i 之后）：input seek 会落到关键帧，抽到的不是目标时刻
    subprocess.run([FFMPEG, "-y", "-i", str(FINAL), "-ss", str(t),
                    "-frames:v", "1", "-update", "1", str(out)],
                   capture_output=True)
    im = Image.open(out).convert("L")
    w, h = im.size
    # 探「字幕框」：画面下部、去掉左右留白，统计成片暗像素（半透明黑底框）
    band = im.crop((int(w * 0.12), int(h * 0.62), int(w * 0.88), h))
    px = list(band.get_flattened_data()) if hasattr(band, "get_flattened_data") else list(band.getdata())
    ratio = sum(1 for v in px if v < 80) / len(px)
    verdict = ("有字幕框 ✓" if ratio > 0.015 else "✗ 无字幕") if has_sub else \
              ("应为无字幕 ✓" if ratio < 0.015 else f"意外暗区 {ratio:.3f}")
    print(f"t={t:3d}s {name:12s} 下部暗像素={ratio:.4f}  {verdict}")

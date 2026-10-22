# -*- coding: utf-8 -*-
"""文衡演示视频 · 合成：webm → mp4 → 生成 SRT → 拼接 → 烧录字幕。

依赖：ffmpeg / ffprobe（PATH 内）。
输入：tmp/video/seg_list.json + 各段 .webm
输出：申报材料/文衡演示视频_20260917.mp4
"""
import io, json, os, pathlib, subprocess, sys, tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = pathlib.Path(__file__).resolve().parents[3]      # 工作区根（tools/<x>/ 上溯三层）
VID = BASE / "wenheng/tmp/video"
BUILD = VID / "build"
BUILD.mkdir(parents=True, exist_ok=True)
FINAL = BASE / "申报材料/文衡演示视频_20260917.mp4"

#: ffmpeg 目录：写死 `C:/Users/<用户名>/…` 等于把本机账号打进仓库，改按家目录推导同一位置；
#: 装在别处时用 `WENHENG_FFMPEG_BIN` 覆盖。
WINGET_BIN = (pathlib.Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
              / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
              / "ffmpeg-8.1.1-full_build/bin")
BIN = pathlib.Path(os.environ.get("WENHENG_FFMPEG_BIN") or WINGET_BIN)
FFMPEG = str(BIN / "ffmpeg.exe")
FFPROBE = str(BIN / "ffprobe.exe")
FONTS = r"C:/Windows/Fonts"
FONT = "Microsoft YaHei"

#: 静态卡段：段号 -> (PNG 锚点, 目标秒数)。
#: 这些段不用 Playwright 录像（它只写「变化帧」，静止页面会被压成 1 秒），
#: 改用 cards/*.png + ffmpeg `-loop 1 -t N` 生成，时长精确可控。
CARD_SEGS = {0: ("s0", 8), 1: ("s1a", 13), 2: ("s1b", 13), 3: ("s1c", 13),
             9: ("s7", 45), 11: ("s9", 30), 12: ("s10", 12)}
CARDS_DIR = VID / "cards"
#: 字幕走纯 ASCII 路径：libass 对中文路径 + 冒号转义都不友好，放 Temp 最稳
SUB_DIR = pathlib.Path(tempfile.gettempdir()) / "wenheng_video"
SUB_DIR.mkdir(parents=True, exist_ok=True)

# 每段字幕（按顺序；每条在该段内均分时长）
SUBS = {
    "00_title":     [],
    "01_pain1":     ["“双一流”动态调整、五年一考核，图书馆长期拿不出可审计的贡献指标。"],
    "02_pain2":     ["每期九十余张图、逐格誊进 Word —— 这不是智力劳动，是重复劳动。"],
    "03_pain3":     ["只能报投入，报不出贡献：馆藏多少万册、经费多少万元。"],
    "04_login":     ["公网演示站已上线（116.62.37.161:8080），评审可随时自测。"],
    "05_collation": ["对勘本：机器稿与已出版的人工原件逐格并列，差异一眼可见。",
                     "与第 4 期金样逐格比对，一致率 99.5%（219/220 格）。"],
    "06_redslots":  ["不做整篇重排：只替换每期必改的“红色件”，固定件零改动。",
                     "99 张图表可在线预览；每个数字都能回溯到台账的具体单元格。"],
    "07_run":       ["主干六步由代码预定义，模型不得增删步骤、变更顺序。",
                     "数值全部来自确定性脚本 —— 大模型不进入数值路径。",
                     "全链路公网实测 24 秒，产出近百张图表与 3 张数据大表。"],
    "08_archive":   ["每次运行（含失败）全程留痕：状态机轨迹、审计结论、环境快照，随期可回放。",
                     "审计预检：大表 242 格全量回查差异 0，抽查槽位 35/354 差异 0。"],
    "09_heal":      ["自愈只改“怎么读”，不改台账 —— 6 例实测，原件零字节改动。",
                     "自愈只有一发子弹，用完仍不过闸就升级馆员，绝不静默放行。"],
    "10_sign":      ["三道闸：机器断言 → 金样回测 → 人工审批门。",
                     "报告发布 100% 经馆员签单，一期三件同出。"],
    "11_value":     ["换校＝换配置包与修复规则库，首次部署一天。"],
    "12_demo":      ["让 AI 进入图书馆最核心的管理业务 —— 可审计、可复现、可交接。"],
}


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def probe_dur(p):
    r = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(p)])
    return float(r.stdout.strip() or 0)


def main():
    segs = json.loads((VID / "seg_list.json").read_text(encoding="utf-8"))
    mp4s, plans = [], []
    t = 0.0
    for s in segs:
        i, name = s["i"], s["name"]
        dst = BUILD / f"{i:02d}_{name}.mp4"
        if i in CARD_SEGS:                      # ---- 静态卡：PNG → 定长
            anchor, dur = CARD_SEGS[i]
            png = CARDS_DIR / f"{anchor}.png"
            if not png.exists():
                print("缺卡片图:", png); continue
            r = run([FFMPEG, "-y", "-loop", "1", "-framerate", "30", "-i", str(png),
                     "-t", str(dur), "-vf", "fps=30,format=yuv420p",
                     "-color_range", "tv", "-colorspace", "bt709",
                     "-color_primaries", "bt709", "-color_trc", "bt709",
                     "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                     "-movflags", "+faststart", "-an", str(dst)])
            if r.returncode != 0:
                print("卡片转码失败", name, r.stderr[-300:]); continue
            d = float(dur)
            print(f"[{i:02d}] {name:14s} {d:6.2f}s  (卡片 {anchor})")
        else:                                   # ---- 录像段
            if not s.get("video"):
                print("跳过（无录像）:", name); continue
            r = run([FFMPEG, "-y", "-i", s["video"],
                     "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=EFEDE7,fps=30,format=yuv420p",
                     "-color_range", "tv", "-colorspace", "bt709",
                     "-color_primaries", "bt709", "-color_trc", "bt709",
                     "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                     "-movflags", "+faststart", "-an", str(dst)])
            if r.returncode != 0:
                print("转码失败", name, r.stderr[-400:]); continue
            d = probe_dur(dst)
            print(f"[{i:02d}] {name:14s} {d:6.2f}s  -> {dst.name}")
        mp4s.append(dst)
        plans.append({"name": name, "start": t, "dur": d,
                      "lines": SUBS.get(name, [])})
        t += d
    print(f"\n总时长 {t:.1f}s = {int(t)//60}′{int(t)%60:02d}″")

    # ---- ASS 字幕（不用 SRT）----
    # 🔴 SRT 没有 PlayRes 声明，libass 一律按 288 行折算出画布，1080 高的视频里
    #    字号被放大 1080/288≈3.75 倍，字幕直接糊掉半个屏幕。ffmpeg subtitles 的
    #    `original_size` 实测压不住这个缩放。ASS 能在文件头写死 PlayResX/Y，
    #    字号就是像素，才可控。
    def ts(x):
        h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60
        return f"{h:d}:{m:02d}:{s:05.2f}"

    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        # 白字 + 半透明黑底框（BorderStyle=3），浅色演示站上也读得清
        "Style: Default,Microsoft YaHei,38,&H00FFFFFF,&H000000FF,&H00111111,"
        "&HA8000000,0,0,0,0,100,100,0,0,3,1,0,2,120,120,48,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text",
    ]
    body, n = [], 0
    for p in plans:
        ls = p["lines"]
        if not ls:
            continue
        slot = p["dur"] / len(ls)
        for k, txt in enumerate(ls):
            a = p["start"] + k * slot
            b = a + slot - 0.25
            body.append(f"Dialogue: 0,{ts(a)},{ts(b)},Default,,0,0,0,,{txt}")
            n += 1
    ass = SUB_DIR / "subs.ass"          # 纯 ASCII 路径给 libass 用
    ass.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    (BUILD / "subs.ass").write_text("\n".join(head + body) + "\n", encoding="utf-8")
    print("字幕 ->", ass, f"（{n} 条）")

    # ---- 拼接 ----
    lst = BUILD / "concat.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in mp4s), encoding="utf-8")
    merged = BUILD / "merged.mp4"
    r = run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", str(merged)])
    if r.returncode != 0:
        print("拼接失败:", r.stderr[-500:]); return
    print("拼接 ->", merged, f"{probe_dur(merged):.1f}s")

    # ---- 归一化（关键）----
    # concat -c copy 出来的流，各段色彩参数/编码细节不同，烧字幕时 ffmpeg 会
    # 「Reconfiguring filter graph because video parameters changed」——滤波器图被重建，
    # libass 实例随之重置，结果**整片字幕静默消失**（ffmpeg 退出码仍是 0，不报错）。
    # 先统一重编码成同参数的一整段，再烧字幕，问题消失。
    norm = BUILD / "normalized.mp4"
    r = run([FFMPEG, "-y", "-i", str(merged),
             "-vf", "scale=1920:1080,format=yuv420p",
             "-color_range", "tv", "-colorspace", "bt709",
             "-color_primaries", "bt709", "-color_trc", "bt709",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium",
             "-movflags", "+faststart", "-an", str(norm)])
    if r.returncode != 0:
        print("归一化失败:", r.stderr[-400:]); return
    print("归一化 ->", norm, f"{probe_dur(norm):.1f}s")

    # ---- 烧录字幕 ----
    # Windows 上 filter 内出现盘符冒号必炸：`C:` 被当选项分隔符；
    # 写成 `C\:` 也不行（ffmpeg 报错 "No option name near '/Users/...'"，指向 force_style，很误导）。
    # 最稳的办法：把 cwd 切到字幕目录，filter 里只用相对文件名，路径里一个冒号都没有。
    # 样式全部写在 ASS 文件头，这里不再传 force_style（避免两处样式打架）。
    vf = "ass=subs.ass"
    print("vf =", vf)
    r = run([FFMPEG, "-y", "-i", str(norm), "-vf", vf,
             "-c:v", "libx264", "-crf", "20", "-preset", "medium",
             "-movflags", "+faststart", str(FINAL)], cwd=str(SUB_DIR))
    if r.returncode != 0 or "Reconfiguring filter graph" in (r.stderr or ""):
        print("烧录异常，退化为无字幕版:", r.stderr[-600:])
        run([FFMPEG, "-y", "-i", str(norm), "-c", "copy", str(FINAL)])
    print("\n最终 ->", FINAL)
    if FINAL.exists():
        print(f"大小 {FINAL.stat().st_size/1024/1024:.1f} MB  时长 {probe_dur(FINAL):.1f}s")


if __name__ == "__main__":
    main()

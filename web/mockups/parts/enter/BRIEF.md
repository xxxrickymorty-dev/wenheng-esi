# 入馆屏方向探索 · 共同约束（2026-11-03）

## 任务
给文衡「陈列馆」加**一屏新的入馆页**（用图书馆照片），并让它**丝滑过渡**到现有的「书架屏」。
书架屏是已上线、rick 已定稿的版面：**一个像素都不许改**（DOM、类名、样式、书的位置都不动）。

## 唯一底座
`web/mockups/parts/enter/shelf-base.html`（38KB，双击即开，已与线上首屏逐屏对过）
- 它已经把 `shelf-landing.css` 全文 + `--lib-*` 令牌 + 首屏结构搬进来了。
- 你的做法：**复制它**成你的方向文件，在 `<body>` 最前面插入你的入馆屏，然后只做「入馆屏 + 过渡」。
- 🔴 不要改 `.brand` / `.shelf-view` / `.wallframe` / `.headline` / `.vol` / `.down` / `.index` 的任何声明；
  不要改 `#shelf` 里五个 `<a class="vol">` 的结构与顺序。
- 允许：给 `.shelf-view` 外面套一层容器做「入场」（opacity/transform），
  以及在入馆屏滚出后给 body 加类。**不允许**改书架屏自身的尺寸、间距、字体、颜色。

## 素材（真实文件，别自己造图）
根目录：`C:/Users/damn/Desktop/yunnan-library-360/assets/`
| 文件 | 尺寸 | 内容 |
|---|---|---|
| `library-exterior.png` | 1672×941 (16:9) | 馆外立面＋倒影池，黄昏 |
| `library-interior.png` | 1448×1086 (4:3) | 中庭仰视，环形书架＋玻璃穹顶 |
| `top.png` | 1254×1254 (1:1) | 正对穹顶俯拍，同心圆 |
| `library-panorama.png` | 1774×887 (2:1) | 中庭全景，左右对称 |
| `微信图片_20261103112305_26_2.jpg` | 1440×960 (3:2) | 实拍穹顶，夜，偏蓝 |

🔴 **硬规则：照片只准缩小、不准放大。**
- 显示宽度 ≤ 原图宽度 ÷ 2（按 2 倍屏反算）。
- 不同比例的照片并排时用**等高不等宽**（统一高度、宽度按各自比例），不裁不变形。
- 单张铺满整屏是最容易糊的做法（1774px 铺 1440 视口＋缩放＝二次放大）——**上一版就是死在这里**。

## 视觉纪律（陈列馆已有的语言，别另起一套）
- 色：夜 `#191310` / 纸 `#F4F1E8` / 金 `#C9A961`；米墙 `#F5EDDA`。只用这几族。
- 字：`"Noto Serif SC","Source Han Serif SC","Songti SC",SimSun,Georgia,serif`；英文间隔字用 Georgia。
- 零圆角；细金线（1px）是唯一的装饰手段；不要阴影堆叠、不要发光、不要新图标。
- 文案用中文、克制：可用的词只有「学科信息参考」「云南大学图书馆」「一年六期　一期一册」「学科情报馆藏 A 区 01」。
  **不要**写解释性副标题、不要写「点击进入」这类说明。

## 交付物
`web/mockups/parts/enter/dir-<你的代号>.html`，单文件、双击即开、零外链。
- 首屏＝你的入馆屏；滚动（或一次点击）后**平滑**落到书架屏，落定后书架屏与底座逐像素一致。
- 过渡必须真的能看：不是硬切。用 CSS transform/opacity/scale/filter，时长 600–1200ms。
- 必须验：1440×900 与 390×844 两档截图看一眼；控制台无报错。

## 自检（写完自己跑一遍）
```bash
# 截图（把 <名字> 换掉）
"C:/Users/damn/.workbuddy/../AppData/Local/Programs/Python/Python313/python.exe" - <<'EOF'
import pathlib
from playwright.sync_api import sync_playwright
SRC = pathlib.Path("web/mockups/parts/enter/dir-XXX.html").resolve()
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg.goto(SRC.as_uri()); pg.wait_for_timeout(1200)
    pg.screenshot(path="wenheng/tmp/dir-XXX-1.png")
    pg.mouse.wheel(0, 700); pg.wait_for_timeout(1400)
    pg.screenshot(path="wenheng/tmp/dir-XXX-2.png")
    b.close()
EOF
```
（工作目录 `C:/Users/damn/Desktop/首届高校图书馆`；playwright 只有系统 Python 有。）

## 别做的事
- 不引 CDN、不引字体文件、不引 three.js / GSAP。
- 不改 `wenheng/src/` 下任何文件；不提交 git（主 Agent 统一收口）。
- 不做「进入 3D」「加载中」这类假状态。

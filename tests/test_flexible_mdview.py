# -*- coding: utf-8 -*-
"""`flexible.mdview`（零依赖 Markdown 渲染）渲染侧回归。

为什么单列一文件：网页（`server/app.py` 灵活报告路由）与下载件（`report.py`
写 `report.html`）共用这一份实现，「网页上对、导出件上错」只能在这里拦。

全部用例为纯函数 / 内存输入（真实小图只写 `tmp_path`），不碰 `out/`、`input/`
数据，任何环境可跑——因此无需 `_guard_registry` 跳过登记。

锁死的关键契约（口径以 `src/flexible/mdview.py` 实际行为为准）：

1. 行内是「**先 html.escape 再还原自有标记**」，顺序不能反——图片标记还原成
   HTML 属性时，引号必须已转义（防 `onerror` 注入）；
2. `render` 的 `img_prefix` / `img_map` 两条图片路径改写分支，只作用于
   **独立成行**的图（产线出稿一律图独占一行，见 `report._render_charts`）；
3. 尾部「## 本稿如何产生」起的固定附录收进折叠块，尾部页脚行不再渲染；
4. 旧导语条（…母版 704 槽位、三道闸、可签发…）渲染时剥离，同图例保留；
5. 独立件自包含：title 转义、页脚标注一次、相对图内联成 data URI。
"""
import base64

import pytest

from flexible import mdview

#: 最小 PNG 头字节（inline_images 只读字节做 base64，不解析图片，无需真图）
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 8


def _png_b64(data: bytes = PNG_BYTES) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


# ================================================================ 1. 行内标记
class Test行内标记:
    """粗体 / 行内码 / 待审线，以及「先转义再还原」的顺序契约。"""

    def test_粗体成strong(self):
        assert mdview.render("**重点**结论") == "<p><strong>重点</strong>结论</p>"

    def test_行内代码成code(self):
        assert mdview.render("来源在 `ledger_long` 里") == \
            "<p>来源在 <code>ledger_long</code> 里</p>"

    def test_待审线成对标记成span(self):
        h = mdview.render("总被引升至 ==11,558== 次。")
        assert '<span class="fx-mark">11,558</span>' in h
        assert "==" not in h, "成对标记不该有字面等号残留"

    def test_单侧等号原样保留不吞正文(self):
        h = mdview.render("写作位降级 == 时回退空位。")
        assert "fx-mark" not in h and "==" in h and "时回退空位" in h

    def test_同一行多组待审线各自成span(self):
        h = mdview.render("==第一句==与==第二句==都需馆员过目")
        assert '<span class="fx-mark">第一句</span>' in h
        assert '<span class="fx-mark">第二句</span>' in h

    def test_先转义再还原_标签不逃逸且标记仍生效(self):
        """html.escape 在前、还原标记在后：`<script>` 进不了正文，粗体照样出。"""
        h = mdview.render("**粗 <script>x</script>** 与 ==<i>y</i>==")
        assert "<script>" not in h and "<i>" not in h
        assert "<strong>粗 &lt;script&gt;x&lt;/script&gt;</strong>" in h
        assert '<span class="fx-mark">&lt;i&gt;y&lt;/i&gt;</span>' in h

    def test_引号先转义_自有标记不被破坏(self):
        h = mdview.render('**a"b** 与 ==c"d==')
        assert '<strong>a&quot;b</strong>' in h
        assert '<span class="fx-mark">c&quot;d</span>' in h

    def test_行内转义链完整(self):
        assert mdview._inline('说 "引" 用 & <i>') == "说 &quot;引&quot; 用 &amp; &lt;i&gt;"

    def test_行内图片属性引号已转义(self):
        """图片标记会还原成 HTML 属性：`src`/`alt` 里的引号必须是 &quot;。"""
        h = mdview.render('看 ![a" o](b.png" s) 图')
        assert '<img src="b.png&quot; s" alt="a&quot; o">' in h
        assert ' onerror=' not in h

    def test_段落里的行内图不走路径改写(self):
        """img_prefix/img_map 只作用于独立成行的图；夹在段落文字里的图原样输出
        （产线出稿图一律独占一行，这是有意的子集边界，不是漏改）。"""
        h = mdview.render("看这 ![x](a.png) 图", img_prefix="P/",
                          img_map={"a.png": "/MAP/a.png"})
        assert '<img src="a.png" alt="x">' in h


# ================================================================ 2. 块级元素
class Test块级元素:
    def test_标题层级h1到h6且封顶(self):
        """`#`→h2（页面已有 h1）逐级 +1，`######` 封顶 h6。"""
        h = mdview.render("# t1\n## t2\n### t3\n#### t4\n##### t5\n###### t6")
        assert h == ("<h2>t1</h2>\n<h3>t2</h3>\n<h4>t3</h4>\n"
                     "<h5>t4</h5>\n<h6>t5</h6>\n<h6>t6</h6>")

    def test_七个井号不是标题(self):
        assert mdview.render("####### t7") == "<p>####### t7</p>"

    def test_标题内容走行内链(self):
        assert mdview.render("## 标 **粗**") == "<h3>标 <strong>粗</strong></h3>"

    def test_引用多行合并为一个blockquote(self):
        h = mdview.render("> a\n> b")
        assert h == "<blockquote>\n<p>a</p>\n<p>b</p>\n</blockquote>"

    def test_引用后接段落闭合(self):
        h = mdview.render("> a\n\npara")
        assert h == "<blockquote>\n<p>a</p>\n</blockquote>\n<p>para</p>"

    def test_无序列表短横与星合流(self):
        assert mdview.render("- x\n* y") == "<ul>\n<li>x</li>\n<li>y</li>\n</ul>"

    def test_有序列表(self):
        assert mdview.render("1. z\n2. w") == "<ol>\n<li>z</li>\n<li>w</li>\n</ol>"

    def test_无序切有序各自闭合(self):
        h = mdview.render("- x\n1. z")
        assert h == "<ul>\n<li>x</li>\n</ul>\n<ol>\n<li>z</li>\n</ol>"

    def test_空行闭合列表后重开(self):
        h = mdview.render("- a\n\n隔断\n\n- b")
        assert h.count("<ul>") == 2 and "<p>隔断</p>" in h

    def test_水平线三横及以上(self):
        assert mdview.render("----") == "<hr>"

    def test_两横不是水平线(self):
        assert mdview.render("--") == "<p>--</p>"

    def test_水平线紧贴前后文也成立(self):
        assert mdview.render("前\n---\n后") == "<p>前</p>\n<hr>\n<p>后</p>"

    def test_星号开头的粗体不误判为列表项(self):
        assert mdview.render("*斜体*不支持，原样") == "<p>*斜体*不支持，原样</p>"
        assert mdview.render("**粗**起头") == "<p><strong>粗</strong>起头</p>"


# ================================================================ 3. 表格
class Test表格:
    def test_基本表格结构(self):
        h = mdview.render("| a | b |\n|---|---|\n| 1 | 2 |")
        assert h == ('<table class="dense"><thead><tr><th>a</th><th>b</th>'
                     "</tr></thead><tbody>\n<tr><td>1</td><td>2</td></tr>\n"
                     "</tbody></table>")

    def test_对齐标记被分隔行吃掉不进HTML(self):
        """分隔行支持 `:---:`/`---:`；对齐信息**不**进位成 HTML 属性
        （class=dense 的对齐由 CSS 统一管，这里锁住「不进位」这一实际口径）。"""
        h = mdview.render("| 左 | 右 |\n| :---: | ---: |\n| 1 | 2 |")
        assert "<th>左</th><th>右</th>" in h and "<td>1</td><td>2</td>" in h
        assert "align" not in h and "text-align" not in h and ":---" not in h

    def test_分隔行含字母则不是表格(self):
        h = mdview.render("| a |\n|x y|\n| 1 |")
        assert "<table" not in h and "<p>| a |</p>" in h

    def test_单元格走行内链(self):
        h = mdview.render("| a | b |\n|---|---|\n| **x** | `y` |")
        assert "<td><strong>x</strong></td><td><code>y</code></td>" in h

    def test_表格遇空行闭合_后续段落在外(self):
        h = mdview.render("| a |\n|---|\n| 1 |\n\n收尾段")
        assert "</tbody></table>" in h and h.index("</tbody></table>") < h.index("<p>收尾段</p>")

    def test_数据行缺尾管道仍解析(self):
        h = mdview.render("| a | b |\n|---|---|\n| 1 | 2")
        assert "<td>1</td><td>2</td>" in h


# ================================================================ 4. 图片路径改写
class Test图片路径改写:
    """`_img_url` 三分支：img_map 命中 > img_prefix（相对路径才加）> 原样。"""

    def test_不给前缀与映射则原样输出(self):
        h = mdview.render("![图](../charts/x.png)")
        assert '<img src="../charts/x.png" alt="图">' in h

    def test_img_prefix加在文件名前(self):
        h = mdview.render("![x](../charts/a.png)", img_prefix="/p/202607/f/chart/t/")
        assert 'src="/p/202607/f/chart/t/a.png"' in h

    @pytest.mark.parametrize("src", ["https://x/y/a.png", "http://x/y/a.png", "/abs/a.png"])
    def test_网络与绝对路径不受前缀影响(self, src):
        assert mdview._img_url(src, "P/", None) == src

    def test_img_map命中优先于前缀(self):
        h = mdview.render("![x](../charts/a.png)", img_prefix="P/",
                          img_map={"a.png": "/p/202607/f/chart/t/a.png"})
        assert 'src="/p/202607/f/chart/t/a.png"' in h and "P/a.png" not in h

    def test_img_map未命中回落前缀(self):
        h = mdview.render("![x](charts/b.png)", img_prefix="P/",
                          img_map={"a.png": "/MAP/a.png"})
        assert 'src="P/b.png"' in h

    def test_img_url映射命中时网络src也改写(self):
        """map 是精确换图（按文件名对号），优先级高于「网络图不动」口径。"""
        assert mdview._img_url("https://x/y/a.png", "P/", {"a.png": "/MAP/a.png"}) \
            == "/MAP/a.png"


# ================================================================ 5. 连续图与图注
class Test连续图与图注:
    def test_单图成figure(self):
        h = mdview.render("![图](charts/a.png)")
        assert h == ('<div class="figrow"><figure><img src="charts/a.png" alt="图">'
                     "</figure></div>")

    def test_全行星号图注成figcaption(self):
        h = mdview.render("![图](charts/a.png)\n\n*这是图注*")
        assert "<figcaption>这是图注</figcaption>" in h

    def test_非图注文字不误吞(self):
        h = mdview.render("![图](charts/a.png)\n\n普通段落")
        assert "<figcaption>" not in h and "<p>普通段落</p>" in h

    def test_两张连续图合一个figrow(self):
        h = mdview.render("![a](charts/a.png)\n\n![b](charts/b.png)")
        assert h.count('<div class="figrow">') == 1 and h.count("<figure>") == 2

    def test_两图各带图注仍合一组(self):
        h = mdview.render("![a](charts/a.png)\n\n*图注A*\n\n![b](charts/b.png)\n\n*图注B*")
        assert h.count('<div class="figrow">') == 1
        assert "<figcaption>图注A</figcaption>" in h
        assert "<figcaption>图注B</figcaption>" in h


# ================================================================ 6. 尾部折叠
class Test尾部折叠:
    """「## 本稿如何产生」起的附录收进 details 折叠块；尾部页脚行不重复渲染。"""

    def test_附录收进折叠块(self):
        h = mdview.render("正文。\n\n## 本稿如何产生\n\n主张。")
        assert '<details class="fx-about">' in h
        assert "<summary>关于本稿 · 本稿如何产生与数据来源链</summary>" in h
        assert '<div class="fx-about-in">' in h
        assert h.index("<p>正文。</p>") < h.index("<details")
        assert "<h3>本稿如何产生</h3>" in h and "<p>主张。</p>" in h

    def test_尾部页脚行不渲染_头部同款保留(self):
        md = "*内部参考 · 非报送件*\n\n## 本稿如何产生\n\n尾。\n\n*内部参考 · 非报送件*"
        h = mdview.render(md)
        assert h.count("*内部参考 · 非报送件*") == 1, "只有头部那行保留"
        assert "<p>尾。</p>" in h

    def test_wrap_tail为False不折叠(self):
        h = mdview.render("## 本稿如何产生\n\n主张。", _wrap_tail=False)
        assert "fx-about" not in h
        assert h == "<h3>本稿如何产生</h3>\n<p>主张。</p>"


# ================================================================ 7. 旧导语剥离
class Test旧导语剥离:
    BANNER = ("> **本件为内部参考，非报送件** —— 正式对外件请用复刻报告产线"
              "（母版 704 槽位、三道闸、可签发）。")

    def test_声明剥掉_同行图例保留(self):
        md = self.BANNER + "　细下划线的句子＝**待审句**，需馆员拍板。\n\n正文。"
        out = mdview._strip_legacy_banner(md)
        assert "本件为内部参考" not in out and "复刻报告产线" not in out
        assert "细下划线的句子" in out, "同行的待审线图例要留下"

    def test_只剩声明的行整行丢弃(self):
        out = mdview._strip_legacy_banner(self.BANNER + "\n\n正文。")
        assert "本件为内部参考" not in out
        assert "正文。" in out, "声明后面的正文不能跟着丢"

    def test_无导语原样返回(self):
        md = "正文。\n\n> 别的导语。"
        assert mdview._strip_legacy_banner(md) == md

    def test_幂等_剥过的稿再剥不变(self):
        once = mdview._strip_legacy_banner(self.BANNER + "　图例文本。\n\n正文。")
        assert mdview._strip_legacy_banner(once) == once

    def test_后缀不符的旧口径不剥(self):
        """只认带固定后缀（母版 704 槽位…）的那一条；别的历史行不误伤。"""
        md = "> **本件为内部参考，非报送件**（旧口径，无固定后缀）。\n\n正文。"
        assert mdview._strip_legacy_banner(md) == md


# ================================================================ 8. 图片内联 data URI
class Test图片内联:
    """`inline_images`：只内联**相对且真实存在**的图，其余原样（宁少不编、不越权）。"""

    @staticmethod
    def _mk(tmp_path):
        (tmp_path / "charts").mkdir(exist_ok=True)
        (tmp_path / "charts" / "a.png").write_bytes(PNG_BYTES)

    def test_真实小图内联且载荷逐字节(self, tmp_path):
        self._mk(tmp_path)
        h = mdview.inline_images('<img src="charts/a.png">', tmp_path)
        assert h == f'<img src="{_png_b64()}">'

    def test_标签其他属性保留(self, tmp_path):
        self._mk(tmp_path)
        h = mdview.inline_images('<img class="k" src="charts/a.png" alt="x">', tmp_path)
        assert h.startswith('<img class="k" src="data:image/png;base64,')
        assert h.endswith(' alt="x">')

    def test_缺文件原样保留(self, tmp_path):
        self._mk(tmp_path)
        h = mdview.inline_images('<img src="charts/none.png">', tmp_path)
        assert h == '<img src="charts/none.png">'

    @pytest.mark.parametrize("src", ["https://x/a.png", "http://x/a.png",
                                     "//x/a.png", "/abs/a.png", "data:image/png;base64,QQ"])
    def test_网络绝对与data协议不动(self, tmp_path, src):
        assert mdview.inline_images(f'<img src="{src}">', tmp_path) == f'<img src="{src}">'

    def test_越界路径不动(self, tmp_path):
        (tmp_path / "out.png").write_bytes(b"x")
        sub = tmp_path / "d"
        sub.mkdir()
        h = mdview.inline_images('<img src="../out.png">', sub)
        assert h == '<img src="../out.png">'

    def test_多张图只改命中的(self, tmp_path):
        self._mk(tmp_path)
        h = mdview.inline_images(
            '<img src="charts/a.png"><img src="charts/none.png">', tmp_path)
        assert 'src="data:image/png;base64,' in h and h.count("charts/none.png") == 1

    def test_mime猜不出时兜底为png(self, tmp_path, monkeypatch):
        """Windows 注册表可能给怪扩展配上 mime；这里直接掐断 guess，锁 `or "image/png"` 兜底。"""
        (tmp_path / "charts").mkdir()
        (tmp_path / "charts" / "x.unknownext").write_bytes(b"x")
        monkeypatch.setattr(mdview.mimetypes, "guess_type", lambda name: (None, None))
        h = mdview.inline_images('<img src="charts/x.unknownext">', tmp_path)
        assert h == '<img src="data:image/png;base64,eA==">'


# ================================================================ 9. 独立件
class Test独立件:
    FOOTER = "内部参考 · 非报送件"

    def test_完整文档结构与页脚一次(self):
        h = mdview.standalone("# 标题\n\n正文。", "测试题")
        assert h.startswith("<!doctype html>")
        assert '<html lang="zh-CN">' in h and "<style>" in h
        assert "<title>测试题</title>" in h
        assert '<div class="wrap">' in h and "<p>正文。</p>" in h
        assert "export-mark" in h and h.count(self.FOOTER) == 1

    def test_title转义(self):
        h = mdview.standalone("正文。", 'T<b>"x"')
        assert "<title>T&lt;b&gt;&quot;x&quot;</title>" in h
        assert "<b>" not in h

    def test_无外部资源自包含(self):
        h = mdview.standalone("正文。", "t")
        assert "http://" not in h and "https://" not in h

    def test_base_dir把相对图内联_缺图保留(self, tmp_path):
        (tmp_path / "charts").mkdir()
        (tmp_path / "charts" / "a.png").write_bytes(PNG_BYTES)
        h = mdview.standalone("![图](charts/a.png)\n\n![缺](charts/none.png)",
                              "t", base_dir=tmp_path)
        assert _png_b64() in h
        assert 'src="charts/none.png"' in h, "缺图不编：原样留着"

    def test_尾部折叠在独立件同样生效(self):
        h = mdview.standalone("正文。\n\n## 本稿如何产生\n\n主张。", "t")
        assert '<details class="fx-about">' in h and ".fx-about{" in h

    def test_待审线样式随件带走(self):
        h = mdview.standalone("==待审句==", "t")
        assert '<span class="fx-mark">待审句</span>' in h
        assert ".fx-mark{" in h and "text-decoration-thickness:1px" in h


# ================================================================ 10. 整篇合成
class Test整篇合成:
    def test_产线形态的稿子各块各就各位(self):
        """一份贴近 `report._render` 实际出稿形态的 md：块序＝表→正文→列表→图→折叠附录。"""
        md = ("# 灵活分析稿\n\n> 期次：**202607**\n\n---\n\n"
              "| 指标 | 数值 |\n|---|---:|\n| 排名 | 5 |\n\n"
              "正文段。\n\n- 要点一\n\n"
              "![图](charts/a.png)\n\n*图注文字*\n\n"
              "---\n## 本稿如何产生\n\n架构主张。\n")
        h = mdview.render(md, img_map={"a.png": "/p/202607/flexible/chart/t/a.png"})
        assert "<blockquote>" in h and "<strong>202607</strong>" in h
        assert '<table class="dense">' in h
        assert 'src="/p/202607/flexible/chart/t/a.png"' in h
        assert "<figcaption>图注文字</figcaption>" in h
        # 次序：正文段在折叠块前，架构主张收进折叠块
        assert h.index("<p>正文段。</p>") < h.index("<details")
        assert h.index("<details") < h.index("架构主张")

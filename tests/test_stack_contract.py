# -*- coding: utf-8 -*-
"""技术栈契约测试（WH-DOC-09《技术栈与前后端边界决议》）。

技术栈决议最怕的不是选错，是**悄悄漂移**：某天为了一个小需求
`npm install` 了一个包、引了一个 CDN 字体、加了条 `@app.delete` ——
单看每次都很小，合起来就把"断网可跑、单文件可交付"的硬约束拆掉了。

这里把 WH-DOC-09 §6 的反选清单和 §4.3 的边界约定钉成断言。
故意的：这些约束一旦被违反**不会报错**，只会在评审现场才发现。

2026-09-22（ADR-0001）：新增 `web/` 工作区系统（React + Vite），
「零 JS 依赖」四条**限定为旧站作用域**（server/ + 仓库根）；web/ 的护栏见本节末两条。
"""
import pathlib
import re
import tomllib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = REPO / "server"

#: 违反即断网崩版的来源域名
CDN_HOSTS = (
    "cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com",
    "fonts.googleapis.com", "fonts.gstatic.com", "ajax.aspnetcdn.com",
)

#: WH-DOC-09 §1 声明的后端依赖（server 组）
REQUIRED_SERVER_DEPS = ("fastapi", "uvicorn", "jinja2", "python-multipart", "itsdangerous")

#: 扫描时排除的目录。`tmp/` 是 gitignore 的一次性脚本区、`out/` 是运行产物：
#: 技术栈契约约束的是**交付内容**，这两处即使有 npm 脚手架也不进交付物。
#: （2026-09-21 全量回归被 `tmp/three-build/` 的 node_modules 绊红，故显式排除。）
#: （2026-09-28 `数字图书馆阅览室/` 是 rick 拷进来的原型素材目录（未跟踪、非交付物），
#: 它自带 npm 工程不属旧站约束范围——显式排除，别拿它绊红回归。）
SKIP_PARTS = {".venv", "tmp", ".pytest_cache", "out", ".git", "数字图书馆阅览室"}

#: 2026-09-22 ADR-0001：`web/` 是新工作区系统（React + Vite），不受「零 JS 依赖」约束；
#: 旧站（server/ + 仓库根）继续受约束。scope 判定按目录名，别用「有没有 package.json」反推。
WEB = REPO / "web"


def _legacy_scope(p: pathlib.Path) -> bool:
    """旧站作用域：排除 web/ 与 SKIP_PARTS。"""
    parts = set(p.relative_to(REPO).parts)
    return not (parts & SKIP_PARTS) and "web" not in parts


def _pyproject():
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def _dep_names(specs):
    """`fastapi>=0.110` → `fastapi`；`uvicorn[standard]>=0.27` → `uvicorn`。"""
    out = set()
    for s in specs:
        out.add(re.split(r"[<>=!\[\s]", s, maxsplit=1)[0].strip().lower())
    return out


# ============================================================ 零 JS 依赖
def test_没有package_json():
    found = [p for p in REPO.rglob("package.json") if _legacy_scope(p)]
    assert not found, f"旧站出现了 npm 工程文件：{found}（WH-DOC-09 §6 只管旧站；web/ 见 ADR-0001）"


def test_没有node_modules():
    found = [p for p in REPO.rglob("node_modules") if p.is_dir() and _legacy_scope(p)]
    assert not found, f"旧站出现了 node_modules：{found}"


def test_没有前端构建配置():
    """只扫仓库根与 server/——web/ 是构建工程，配置本来就在那儿（ADR-0001）。"""
    banned = ("vite.config", "webpack.config", "rollup.config", "tsconfig.json",
              "tailwind.config", "postcss.config")
    found = [p.name for p in REPO.iterdir()
             if p.is_file() and p.name.startswith(banned)]
    found += [p.name for p in SERVER.rglob("*")
              if p.is_file() and p.name.startswith(banned)]
    assert not found, f"旧站出现了前端构建配置：{found}"


def test_没有typescript源码():
    found = [str(p.relative_to(REPO)) for p in REPO.rglob("*.ts") if _legacy_scope(p)]
    assert not found, f"旧站出现了 TypeScript 源码：{found}（零编译步骤，见 WH-DOC-09 §6）"


# ---- web/ 工作区系统（ADR-0001）的两条新护栏 ----
def test_web_node_modules不入库():
    """node_modules 只能存在于本机：靠 .gitignore 挡住，避免整包进仓。"""
    gi = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "web/node_modules" in gi, \
        "wenheng/.gitignore 缺 web/node_modules —— 前端依赖会被误提交"


#: dist 产物里允许出现的 http(s) 字符串——都是**字符串/命名空间，不是网络请求**：
#: - `http://www.w3.org/…`：SVG / MathML / xlink / XML 的命名空间标识符，
#:   浏览器拿它选解析器，不会真去访问这个域名（React `createElementNS` 的参数）；
#: - `https://react.dev/errors/…`：React 生产构建的报错说明链接，只拼在异常消息里；
#: - `https://tailwindcss.com`：Tailwind 生成 CSS 时的文件头注释；
#: - `https://jcgt.org/published/…`：three.js 源码里的论文引用注释（2026-09-28 登记，
#:   随 three 打进 shelf 产物；是注释文本不是资源请求）。
DIST_URL_ALLOWED = (
    "http://www.w3.org/",
    "https://react.dev/errors/",
    "https://tailwindcss.com",
    "https://jcgt.org/published/",
)

#: 抓 URL 到引号/反引号/括号/尖括号/空白为止。若还吞进尾部标点也无妨——
#: 判定用 startswith(白名单)，不为了收尾另写复杂正则。
DIST_URL_RE = re.compile(r"https?://[^\s\"'`)\]}>]+")

#: 协议相对外链（`//host/…`）只在「真会发请求的语境」里查：
#: JS 里 `//` 是注释，全局扫会满屏误报；而 src=/href= 属性与 CSS url() 里的
#: `//` 一旦存在就是跨域资源（旧守卫只查 index.html 属性，这里补齐到全产物）。
PROTO_REL_RE = re.compile(
    r"""(?:src|href)\s*=\s*["'](//[^"']+)["']|url\(\s*["']?(//[^)"']+)""")


def test_web构建产物不含外链():
    """`dist/` 要能跟着部署包上服务器（无 Node），所以它必须是自足的：
    HTML/JS/CSS 产物里只允许上面白名单里的字符串级 URL，出现会发请求的 http(s)
    外链（CDN 字体、远程脚本、`url(https://…)`、`@import "https://…"`）即断网崩版。"""
    idx = WEB / "dist" / "index.html"
    assert idx.is_file(), \
        "web/dist/index.html 不存在——改完 web/ 源码必须 `npm run build` 并提交 dist/（ADR-0001）"
    hits = set()
    for p in sorted((WEB / "dist").rglob("*")):
        if p.suffix.lower() not in (".html", ".js", ".css"):
            continue
        rel = str(p.relative_to(WEB / "dist"))
        text = p.read_text(encoding="utf-8", errors="replace")
        for url in DIST_URL_RE.findall(text):
            if not url.startswith(DIST_URL_ALLOWED):
                hits.add((rel, url))
        for m in PROTO_REL_RE.finditer(text):
            hits.add((rel, m.group(1) or m.group(2)))
    listed = "\n  ".join(f"{rel} → {url}" for rel, url in sorted(hits)[:5])
    assert not hits, (
        "构建产物里出现了白名单外的 URL（断网/拦 CDN 会崩版；"
        "确非网络请求再登记 DIST_URL_ALLOWED）：\n  "
        + listed + (f"\n  …另有 {len(hits) - 5} 条" if len(hits) > 5 else ""))


# ============================================================ 零 CDN
@pytest.mark.parametrize("sub", ["templates", "static"])
def test_前端资产不引CDN(sub):
    hits = []
    for p in (SERVER / sub).rglob("*"):
        if p.is_file() and p.suffix.lower() in (".html", ".js", ".css"):
            text = p.read_text(encoding="utf-8", errors="replace")
            for host in CDN_HOSTS:
                if host in text:
                    hits.append(f"{p.relative_to(REPO)} → {host}")
    assert not hits, f"前端资产引了 CDN：{hits}（断网/拦 CDN 会崩版）"


def _strip_css_comments(text):
    """去掉 /* … */ 注释后再断言——文件头注释里提到 `:root` 不算"自带色板"。"""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_离线快照单文件自足且色板只一份():
    """2026-09-24（⑦）：collation.css/js 已删——样式与脚本只存在于离线快照里。

    原守卫（collation.css 不得另带一套 :root 色板）换成这条：快照必须自带样式与脚本
    （无外部 `<link>`/`<script src>`），且内联的色板只有一份（防复制粘贴出第二套）。
    """
    snap = (SERVER / "static" / "collation-demo.html").read_text(encoding="utf-8")
    assert not re.findall(r'<link[^>]+href="(?!#)[^"]+"', snap), "快照还在引外部样式"
    assert not re.findall(r'<script[^>]+src="[^"]+"', snap), "快照还在引外部脚本"
    assert 'id="whc-snapshot-style"' in snap and 'id="whc-snapshot-script"' in snap, \
        "快照缺内联标记（生成器没跑新版？）"
    assert snap.count("--zhu:") == 1, "内联色板抄了多份——色板只该有一处"


def test_全站色板确实声明在style_css():
    css = _strip_css_comments(
        (SERVER / "static" / "style.css").read_text(encoding="utf-8"))
    assert ":root" in css
    for token in ("--zhu:", "--ink:", "--panel:", "--ok:", "--warn:"):
        assert token in css, f"style.css 缺令牌 {token}"


# ============================================================ 后端依赖
def test_后端依赖声明齐全():
    groups = _pyproject().get("dependency-groups", {})
    declared = _dep_names(groups.get("server", []))
    missing = [d for d in REQUIRED_SERVER_DEPS if d not in declared]
    assert not missing, f"pyproject 的 server 组缺依赖：{missing}"


def test_运行时依赖不含web框架():
    """Web 框架属可选的 server 组：引擎要能在没有 FastAPI 的机器上跑。"""
    core = _dep_names(_pyproject()["project"]["dependencies"])
    assert "fastapi" not in core and "uvicorn" not in core, \
        "FastAPI/uvicorn 应留在 [dependency-groups].server，不要混进运行时依赖"


# ============================================================ 边界约定
def _routes():
    """从 app.py 源码里抽 (method, path)。源码解析而非导入 app——
    避免测试引入 FastAPI 依赖与导入副作用。

    两类写法都要认：`@app.get("…")` 这类单方法装饰器，以及
    `@app.api_route("…", methods=["GET", "POST"])`（methods 可跨行、带空格）。
    """
    src = (SERVER / "app.py").read_text(encoding="utf-8")
    routes = [(m, p) for m, p in
              re.findall(r'@app\.(get|post|put|patch|delete)\(\s*"([^"]+)"', src)]
    for path, methods in re.findall(
            r'@app\.api_route\(\s*"([^"]+)"\s*,\s*methods\s*=\s*\[([^\]]*)\]',
            src, flags=re.S):
        routes.extend((m.lower(), path) for m in re.findall(r'"([^"]+)"', methods))
    return routes


def test_路由不为空():
    assert len(_routes()) >= 20, f"只解析到 {len(_routes())} 条路由，解析逻辑或 app.py 有问题"


def test_没有原地修改语义():
    """只追加，不原地改：审计要求历史不可变（HLD §2 N4）。
    重跑＝新建运行，签单＝签/撤两条 POST，都不需要 PUT/PATCH/DELETE。"""
    bad = [(m, p) for m, p in _routes() if m in ("put", "patch", "delete")]
    assert not bad, f"出现了原地修改语义的路由：{bad}"


#: 允许 POST 的路径后缀：状态变更一律集中在这里（边界约定 B-1 / B-2）
#: 白名单 = 允许写状态的**表单 POST** 后缀。2026-09-24 第二轮后只剩 `/login`：
#: 老站的 sign/revoke/fill/flag/rebuild/flexible 表单 POST 随各自页面下线（走 /api/* JSON 版），
#: 真正无 JS 的写路径就此消失（ADR-0002「代价」已记）。新增写路由必须在这里登记。
POST_ALLOWED_SUFFIX = ("/login",)

#: 非页面、非 API 的杂项 GET（下载/二维码/探活/登出）
MISC_PATHS = ("/download/", "/qr.png", "/healthz", "/logout")


def test_GET不改状态_变更只走POST():
    """/api/* 只允许 GET 与 POST；页面路由要么 GET，要么是白名单里的表单 POST。"""
    offenders = [(m, p) for m, p in _routes()
                 if p.startswith("/api/") and m not in ("get", "post")]
    assert not offenders, f"/api 下出现了非 GET/POST 路由：{offenders}"

    def allowed(method, path):
        if any(x in path for x in MISC_PATHS):
            return method == "get"
        if method == "get":
            return True
        return method == "post" and path.endswith(POST_ALLOWED_SUFFIX)

    offenders = [(m, p) for m, p in _routes()
                 if not p.startswith("/api/") and not allowed(m, p)]
    assert not offenders, (
        f"页面路由出现了白名单外的写操作：{offenders}\n"
        "状态变更应集中在 /login · /sign · /revoke 三类，其余页面一律只读（B-1）")


def test_状态变更都走表单POST而非AJAX():
    """登录是**传统表单**提交（303 重定向），断网或禁用 JS 也要能用。

    这是个**变更检测器**：清单多出或少了任何一条都必须有意识地改这里。
    2026-09-24 第二轮后只剩 `/login` —— 最后一条 no-JS 写路径（灵活报告表单）
    随页面下线（ADR-0002「代价」已记：写操作此后全依赖 JS）。
    """
    posts = {p for m, p in _routes() if m == "post" and not p.startswith("/api/")}
    assert posts == {"/login"}, f"表单 POST 清单变了：{sorted(posts)}"


def test_JSON接口都有登录保护():
    """app.py 里除白名单外的 /api 端点（含 `api_route` 多方法写法）都要检查登录。"""
    src = (SERVER / "app.py").read_text(encoding="utf-8")
    blocks = re.split(r"\n@app\.", src)
    pat_single = re.compile(r'(?:get|post)\("(/api/[^"]+)"\)')
    pat_route = re.compile(r'api_route\("(/api/[^"]+)"')
    unguarded = []
    for b in blocks:
        m = pat_single.match(b) or pat_route.match(b)
        if not m:
            continue
        path = m.group(1)
        if path == "/api/docs":
            continue
        guarded = ("current_user(request)" in b or "require_admin(request)" in b
                   or "@admin_route" in b or "@admin_file_route" in b)
        if not guarded:
            unguarded.append(path)
    assert not unguarded, f"这些 /api 端点没有登录检查：{unguarded}"


def test_SSE端点存在且是GET():
    paths = [p for _, p in _routes()]
    assert "/api/jobs/{job_id}/events" in paths


# ============================================================ 老站下线（ADR-0002 阶段 2）
#: 302 映射表钉死（单一事实源在 server/config.py）。老站页面逐个下线，
#: 这张表是「哪些老路由还在、各自落在哪」的变更检测器——
#: 手滑删了重定向、或改了落点，这里必须跟着有意识地改。
EXPECTED_LEGACY_REDIRECTS = {
    "/": "/app/",
    "/run": "/app/",
    "/p/{period}": "/app/?view=reading&period={period}",
    "/p/{period}/redslots": "/app/?view=red&period={period}",
    "/p/{period}/charts": "/app/?view=charts&period={period}",
    "/p/{period}/trace": "/app/?view=trace&period={period}",
    "/jobs/{job_id}": "/app/",
    "/jobs/{job_id}/collation": "/app/?view=reading&period={period}",
    "/jobs/{job_id}/redslots": "/app/?view=red&period={period}",
    "/jobs/{job_id}/charts": "/app/?view=charts&period={period}",
    "/forecast": "/app/?view=forecast",
    # 2026-09-24 第二轮：P2 两页迁完（archive → 档案视图、flexible → 分析台）。
    "/p/{period}/archive": "/app/?view=archive&period={period}",
    "/p/{period}/flexible": "/app/?view=analysis&period={period}",
    "/jobs/{job_id}/archive": "/app/?view=archive&period={period}",
}


def test_302映射表与清单一致():
    from server import config

    assert config.LEGACY_REDIRECTS == EXPECTED_LEGACY_REDIRECTS, (
        "302 映射表变了——若是有意为之，同步更新本测试与 "
        "docs/老站下线清单（阶段 2）.md §二"
    )


def test_302映射落点都指向新工作区():
    from server import config

    bad = [k for k, v in config.LEGACY_REDIRECTS.items() if not v.startswith("/app/")]
    assert not bad, f"这些映射落点不在 /app/ 下：{bad}"


def test_已下线清单是映射表的子集():
    """LEGACY_LIVE（302 已生效）只能是映射表的子集；每下线一页追加一条。"""
    from server import config

    extra = set(config.LEGACY_LIVE) - set(config.LEGACY_REDIRECTS)
    assert not extra, f"LEGACY_LIVE 里有映射表没有的路由：{extra}"


def test_第二轮两页已下线_keep清单清空():
    """2026-09-24 第二轮：archive/flexible 迁完（前端走查通过）→ 302。

    KEEP 清单清空 = 老站页面全部下线；这两页必须同时在映射表与 LEGACY_LIVE 里，
    否则「下线了但没验落点」或「清单说下了其实没下」都会静默存在。
    """
    from server import config

    assert config.LEGACY_KEEP_PAGES == (), "KEEP 清单应已清空（第二轮收口）"
    for page in ("/p/{period}/archive", "/p/{period}/flexible"):
        assert page in config.LEGACY_REDIRECTS, f"{page} 未进映射表"
        assert page in config.LEGACY_LIVE, f"{page} 未进 LEGACY_LIVE（e2e 不会验落点）"


def test_映射键都是真实路由():
    """每个映射键必须是 app.py 里真实存在的 GET 路由（离线解析源码）。"""
    paths = {p for m, p in _routes() if m == "get"}
    missing = [k for k in EXPECTED_LEGACY_REDIRECTS if k not in paths]
    assert not missing, f"映射表里有 app.py 里不存在的路由：{missing}"


def test_首页与控制台分家():
    """`/` 是对勘本（报告是主角），控制台在 `/run`。
    这条曾经踩过：验收脚本打 `/` 取「最近任务」表，一条都匹配不上。"""
    paths = [p for _, p in _routes()]
    assert "/" in paths and "/run" in paths
    # 阶段 2 起：这两个入口改为 302 到 /app/（见 test_302映射表与清单一致）
    from server import config
    assert config.LEGACY_REDIRECTS["/"] == "/app/"
    assert config.LEGACY_REDIRECTS["/run"] == "/app/"


# ============================================================ 前端不另立状态字典
#: 本站脚本的两种合法写法：直接写 `/static/...`，或走 `asset()` 版本号助手
#: （2026-09-17 起模板统一用后者，见 `test_静态资源引用都带版本号`）
_OWN_SCRIPT = re.compile(r'^(?:/static/|\{\{\s*asset\()')


def test_模板不引第三方脚本():
    for p in (SERVER / "templates").rglob("*.html"):
        text = p.read_text(encoding="utf-8")
        for src in re.findall(r'<script[^>]+src="([^"]+)"', text):
            assert _OWN_SCRIPT.match(src), \
                f"{p.name} 引了非本站脚本：{src}（前端零依赖）"


# ============================================================ 静态资源必须带版本号
#: `href="/static/style.css"` 这种不带版本号的裸引用
_BARE_ASSET = re.compile(r'(?:src|href)="/static/[^"]*\.(?:js|css)(?!\?v=)"')


def test_静态资源引用都带版本号():
    """模板里引用 JS/CSS 一律走 `asset()`，不许手写 `/static/x.js`。

    为什么钉成断言（2026-09-17 真踩过）：`StaticFiles` 只发 etag/last-modified、
    **不发 Cache-Control**，浏览器于是套用「启发式新鲜度」把 JS 缓存好几个小时且
    不回源。当时改完 `collation.js`、服务器 curl 验过是新文件，页面上照样是旧样子，
    看起来像「功能没做」，得按 Ctrl+F5 才见效——评审现场不能靠这个。
    （collation.js 2026-09-24 起已并入离线快照内联；这条守护的是所有模板资产。）
    """
    bad = []
    for p in sorted((SERVER / "templates").rglob("*.html")):
        for m in _BARE_ASSET.finditer(p.read_text(encoding="utf-8")):
            bad.append(f"{p.name}: {m.group(0)}")
    assert not bad, "以下引用没带版本号，浏览器会拿旧缓存：\n  " + "\n  ".join(bad)


def test_asset助手给缺失文件降级不带版本号():
    """文件不在就退化成不带版本号的地址——宁可 404 被看见，也不编假版本号骗缓存。"""
    from server.app import asset

    assert asset("style.css").startswith("/static/style.css?v=")
    assert asset("__不存在的文件__.js") == "/static/__不存在的文件__.js"

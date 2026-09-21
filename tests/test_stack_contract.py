# -*- coding: utf-8 -*-
"""技术栈契约测试（WH-DOC-09《技术栈与前后端边界决议》）。

技术栈决议最怕的不是选错，是**悄悄漂移**：某天为了一个小需求
`npm install` 了一个包、引了一个 CDN 字体、加了条 `@app.delete` ——
单看每次都很小，合起来就把"断网可跑、单文件可交付"的硬约束拆掉了。

这里把 WH-DOC-09 §6 的反选清单和 §4.3 的边界约定钉成断言。
故意的：这些约束一旦被违反**不会报错**，只会在评审现场才发现。
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
SKIP_PARTS = {".venv", "tmp", ".pytest_cache", "out", ".git"}


def _in_scope(p: pathlib.Path) -> bool:
    return not (set(p.relative_to(REPO).parts) & SKIP_PARTS)


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
    found = [p for p in REPO.rglob("package.json") if _in_scope(p)]
    assert not found, f"仓库里出现了 npm 工程文件：{found}（WH-DOC-09 §6 禁止）"


def test_没有node_modules():
    found = [p for p in REPO.rglob("node_modules") if p.is_dir() and _in_scope(p)]
    assert not found, f"仓库里出现了 node_modules：{found}"


def test_没有前端构建配置():
    banned = ("vite.config", "webpack.config", "rollup.config", "tsconfig.json",
              "tailwind.config", "postcss.config")
    found = [p.name for p in REPO.iterdir()
             if p.is_file() and p.name.startswith(banned)]
    found += [p.name for p in SERVER.rglob("*")
              if p.is_file() and p.name.startswith(banned)]
    assert not found, f"出现了前端构建配置：{found}"


def test_没有typescript源码():
    found = [str(p.relative_to(REPO)) for p in REPO.rglob("*.ts") if _in_scope(p)]
    assert not found, f"出现了 TypeScript 源码：{found}（零编译步骤，见 WH-DOC-09 §6）"


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


def test_样式令牌单点声明():
    """色板只在 style.css 的 :root 声明一次；collation.css 不得另立一套。"""
    coll = _strip_css_comments(
        (SERVER / "static" / "collation.css").read_text(encoding="utf-8"))
    assert ":root" not in coll, \
        "collation.css 又自带了 :root 色板——两份色板必然漂移，改色只改 style.css 一处"
    assert "--zhu:" not in coll, "collation.css 重复定义了 --zhu"


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
    避免测试引入 FastAPI 依赖与导入副作用。"""
    src = (SERVER / "app.py").read_text(encoding="utf-8")
    return [(m, p) for m, p in
            re.findall(r'@app\.(get|post|put|patch|delete)\(\s*"([^"]+)"', src)]


def test_路由不为空():
    assert len(_routes()) >= 20, f"只解析到 {len(_routes())} 条路由，解析逻辑或 app.py 有问题"


def test_没有原地修改语义():
    """只追加，不原地改：审计要求历史不可变（HLD §2 N4）。
    重跑＝新建运行，签单＝签/撤两条 POST，都不需要 PUT/PATCH/DELETE。"""
    bad = [(m, p) for m, p in _routes() if m in ("put", "patch", "delete")]
    assert not bad, f"出现了原地修改语义的路由：{bad}"


#: 允许 POST 的路径后缀：状态变更一律集中在这里（边界约定 B-1 / B-2）
#: 白名单 = 允许写状态的表单 POST 后缀。新增写路由必须在这里登记 ——
#: 登记时要回答三件事：① 真实表单 POST + 303（不依赖 JS）② 有登录校验
#: ③ 写的是产物目录还是台账。fill/flag（2026-09-19 工作台）写的是
#: out/<期次>/ 的 manual_inputs.json / review.json，**台账一个字节不碰**。
#: flexible（2026-09-20 第二条产线）写 out/<期次>/flexible/，**同样不碰台账**。
POST_ALLOWED_SUFFIX = ("/login", "/sign", "/revoke", "/fill", "/flag", "/rebuild",
                       "/flexible")

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
    """签单/撤回/登录是**传统表单**提交（303 重定向），断网或禁用 JS 也要能用。

    这是个**变更检测器**：清单多出或少了任何一条都必须有意识地改这里，
    防止有人随手加写路由。fill/flag 是工作台的在线填与存疑（见
    POST_ALLOWED_SUFFIX 处的三问），2026-09-19 rick 拍板加入。
    """
    posts = {p for m, p in _routes() if m == "post" and not p.startswith("/api/")}
    assert posts == {"/login", "/p/{period}/sign", "/p/{period}/revoke",
                     "/p/{period}/fill", "/p/{period}/flag", "/p/{period}/rebuild",
                     "/p/{period}/flexible",
                     "/jobs/{job_id}/collation/sign",
                     "/jobs/{job_id}/collation/revoke"}, f"表单 POST 清单变了：{sorted(posts)}"


def test_JSON接口都有登录保护():
    """app.py 里除 /api/status 外的 /api 端点首行应检查登录。"""
    src = (SERVER / "app.py").read_text(encoding="utf-8")
    blocks = re.split(r"\n@app\.", src)
    unguarded = []
    for b in blocks:
        m = re.match(r'(get|post)\("(/api/[^"]+)"\)', b)
        if not m:
            continue
        path = m.group(2)
        if path in ("/api/status", "/api/docs"):
            continue
        if "current_user(request)" not in b:
            unguarded.append(path)
    assert not unguarded, f"这些 /api 端点没有登录检查：{unguarded}"


def test_SSE端点存在且是GET():
    paths = [p for _, p in _routes()]
    assert "/api/jobs/{job_id}/events" in paths


def test_首页与控制台分家():
    """`/` 是对勘本（报告是主角），控制台在 `/run`。
    这条曾经踩过：验收脚本打 `/` 取「最近任务」表，一条都匹配不上。"""
    paths = [p for _, p in _routes()]
    assert "/" in paths and "/run" in paths


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
    不回源。改完 `collation.js`、服务器 curl 验过是新文件，页面上照样是旧样子，
    看起来像「功能没做」，得按 Ctrl+F5 才见效——评审现场不能靠这个。
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

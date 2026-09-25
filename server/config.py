# -*- coding: utf-8 -*-
"""文衡演示站配置：路径 + 环境变量（自带 .env 解析，不依赖第三方）。"""
import os
import pathlib
import sys

SERVER_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SERVER_DIR.parent


def _load_dotenv():
    env_file = SERVER_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

INPUT_DIR = ROOT / "input"
OUT_DIR = ROOT / "out"
JOBS_DIR = OUT_DIR / "_jobs"
PIPELINE = ROOT / "src" / "run_pipeline.py"
MASTER = ROOT / "master" / "学科信息参考母版_2026第5期.docx"

PYTHON = os.environ.get("WENHENG_PYTHON") or sys.executable

DEMO_USER = os.environ.get("WENHENG_USER", "demo")
DEMO_PASS = os.environ.get("WENHENG_PASS", "wenheng@2026")
SECRET = os.environ.get("WENHENG_SECRET", "wenheng-demo-secret-change-me")
PUBLIC_URL = os.environ.get("WENHENG_PUBLIC_URL", "")
REFERENCE_DOCX = os.environ.get("WENHENG_REFERENCE_DOCX", "")
SHOW_HINT = os.environ.get("WENHENG_SHOW_HINT", "") == "1"

GUEST_USER = os.environ.get("WENHENG_GUEST_USER", "guest")
GUEST_PASS = os.environ.get("WENHENG_GUEST_PASS", "guest@2026")

#: 登录页是否显示「以游客身份浏览」入口。**默认显示**（演示要一眼看得见）；
#: 不想公开只读入口就设 `WENHENG_SHOW_GUEST=0`。
#: 入口是纯表单 POST（不依赖 JS），凭据以隐藏字段写在页面里——游客只读，这是演示需要；
#: 公网部署时游客口令照样该改（见 server/deploy/部署执行清单.md §4.3）。
SHOW_GUEST = os.environ.get("WENHENG_SHOW_GUEST", "1") == "1"

PALETTE = {"primary": "#B8422C", "deep": "#8A2A18", "lift": "#D65A38"}


#: 老站下线（ADR-0002 阶段 2）的 302 映射表：老路由 -> 新工作区地址。
#: 单一事实源：路由（server/app.py）与测试（tests/test_stack_contract.py）都读它。
#: 值里的 `{period}` 由调用方按上下文填：
#: 期次页直接取路由参数；`/jobs/*` 先查任务的期次再填。
#: 实例期次名可带后缀（如 202605_复现），转发时用原样字符串（quote），不做归一化。
LEGACY_REDIRECTS = {
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
    # 2026-09-24：老预测页已被新预测台（/app/?view=forecast）取代（前端确认）。
    "/forecast": "/app/?view=forecast",
    # 2026-09-24 第二轮：P2 两页迁完（前端走查通过）——运行档案 → 档案视图、
    # 灵活报告 → 分析台（灵活报告是其中一块）。任务档案同落档案视图（自动挂该期任务）。
    "/p/{period}/archive": "/app/?view=archive&period={period}",
    "/p/{period}/flexible": "/app/?view=analysis&period={period}",
    "/jobs/{job_id}/archive": "/app/?view=archive&period={period}",
}

#: 已下线（302 已生效）的条目——随每个页面下线追加。
#: e2e 只对这份清单逐条验收；未列入的条目仍在过渡期（保留原页）。
LEGACY_LIVE = (
    "/",
    "/run",
    "/p/{period}",
    "/p/{period}/redslots",
    "/p/{period}/charts",
    "/p/{period}/trace",
    "/jobs/{job_id}",
    "/jobs/{job_id}/collation",
    "/jobs/{job_id}/redslots",
    "/jobs/{job_id}/charts",
    "/forecast",
    "/p/{period}/archive",
    "/p/{period}/flexible",
    "/jobs/{job_id}/archive",
)

#: 过渡期保留页：2026-09-24 第二轮后**已清空**——老站页面全部 302。
#: 保留项只剩基础设施（/api/*、下载、图、登录、探活）与离线快照，见 ADR-0002 §决定 2。
LEGACY_KEEP_PAGES = ()


def role_of(username):
    """用户名 -> 角色。admin 管工作台；guest 只看陈列馆的封面、目录和名词解释。"""
    if username == DEMO_USER:
        return "admin"
    return "guest"


# ---- Agent 层接入（2026-09-15）--------------------------------------------
# 把 src/ 放进 sys.path，演示站才能直接用 agent 层的状态机与步骤表。
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent import states as agent_states                        # noqa: E402
from agent.flow import STEPS as _FLOW_STEPS                     # noqa: E402

#: 主干步骤表**唯一来源是 `src/agent/flow.py`**。前端五步进度与后端编排必须同源，
#: 各存一份必然漂移（`tests/test_agent_flow.py` 有一致性断言守着这条）。
STEPS = [{"id": s["id"], "label": s["label"], "desc": s["desc"]} for s in _FLOW_STEPS]

#: 任务状态（10 态）与中文名，同样以 agent.states 为唯一来源
STATES = agent_states.STATES
STATUS_LABELS = agent_states.LABELS

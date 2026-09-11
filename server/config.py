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

STEPS = [
    {"id": "parse", "label": "解析台账", "desc": "22 个工作表归一化 + 机器断言"},
    {"id": "compute", "label": "计算大表与概述", "desc": "22 学科 × 11 列 + 概述数字事实"},
    {"id": "forecast", "label": "预测回测", "desc": "InCites + 历史差值校准（MAPE < 5%）"},
    {"id": "charts", "label": "图表渲染", "desc": "16 学科 × 6 图 + 概览图"},
    {"id": "docx", "label": "母版替换", "desc": "红色件原地替换 → 报告初稿 + 红件清单"},
]

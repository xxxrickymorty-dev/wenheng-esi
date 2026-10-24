# -*- coding: utf-8 -*-
"""AI 问数 MCP server（stdio，零第三方依赖）——外部 AI 客户端的查询面。

把问数库（out/_aidata/aiqa.sqlite）以 MCP（Model Context Protocol）工具的
形式暴露给任意支持 stdio MCP 的客户端（Claude Desktop / CodeBuddy / 其他 Agent）：

    tools/list → 三个工具：
      aiqa_meta        问数库元信息（期次/指标白名单/学科名单）
      aiqa_ask         自然语言问数（规则规划 → 白名单参数化 SQL → 答案 + 图表数据）
      aiqa_sql         受控 SQL（**只读** SELECT；列名/表名白名单 + 只读连接 +
                       LIMIT 强制；拒绝一切写语句与 PRAGMA）

红线（与 src/aiqa_engine 同源）：
- 只读：连接以 mode=ro 打开；aiqa_sql 再过语句白名单（仅 SELECT）；
- 值只从一条缝进来：工具返回 JSON 文本，数值全部来自库，模型不做计算。

接入（客户端 JSON，Windows 路径按本机改）：
    {
      "mcpServers": {
        "wenheng-aiqa": {
          "command": "uv",
          "args": ["run", "python", "server/mcp_aiqa.py"],
          "cwd": "C:/Users/admin/code/ai/wenheng-esi"
        }
      }
    }

协议：JSON-RPC 2.0 over stdio（Content-Length 头的旧式 framing 不用——
现行 MCP stdio 传输是**一行一消息**的 newline-delimited JSON）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import aiqa_db                                                # noqa: E402
from aiqa_engine import (execute, plan, render_text,      # noqa: E402
                           suggest_chart, to_chart_data)

#: aiqa_sql 允许查询的表白名单（qa_log 含用户问题文本，也可查）。
_SQL_TABLES = frozenset({
    "facts", "dim_discipline", "dim_metric", "dim_period",
    "report_table2", "report_overview", "qa_log", "meta",
})
_SQL_COLS = frozenset({
    "discipline", "discipline_cn", "ord", "metric", "metric_cn", "better",
    "period", "label", "filled", "source", "value", "key", "rank_cn_change",
    "papers", "cnci", "total_cites", "thr_1pct", "thr_1pct_gap",
    "thr_1permille", "permille_rank", "top_papers", "prox_change",
    "id", "ts", "user", "question", "specs", "plan_origin", "n_rows",
    "elapsed_ms", "answer_text", "chart_kind", "schema_version",
    "built_at", "mirror_sha256", "n_facts", "n_table2", "n_overview",
    "content_sha256", "path",
})
_FORBIDDEN = re.compile(
    r"\b(attach|detach|pragma|vacuum|reindex|replace\s+into|insert|update|"
    r"delete|drop|alter|create|grant|revoke)\b", re.IGNORECASE)
_MAX_ROWS = 200


# ---------------------------------------------------------------- 工具实现

def tool_meta() -> dict:
    con = aiqa_db.connect_ro(REPO)
    try:
        m = aiqa_db.meta(REPO)
        return {
            "period": m.get("period", ""),
            "built_at": m.get("built_at", ""),
            "n_facts": int(m.get("n_facts", "0") or 0),
            "disciplines": aiqa_db.view_disciplines(con),
            "metrics": aiqa_db.view_metrics(con),
            "periods": aiqa_db.view_periods(con),
        }
    finally:
        con.close()


def tool_ask(question: str) -> dict:
    q = str(question or "").strip()
    if not q:
        return {"error": "问题不能为空"}
    con = aiqa_db.connect_ro(REPO)
    try:
        p = plan(q, con)
        result = execute(con, p["specs"])
        chart = suggest_chart(con, p["specs"], result)
        return {
            "question": q,
            "plan": p,
            "answer": render_text(con, q, result),
            "chart": chart,
            "chart_data": to_chart_data(con, chart, result),
        }
    finally:
        con.close()


def tool_sql(sql: str) -> dict:
    s = str(sql or "").strip().rstrip(";")
    if not s:
        return {"error": "SQL 不能为空"}
    if not s.lower().lstrip("( ").startswith("select"):
        return {"error": "只允许只读 SELECT 语句",
                "hint": "写操作、PRAGMA、DDL 一律拒绝"}
    if _FORBIDDEN.search(s):
        return {"error": "语句里出现了禁止的关键字（写操作/PRAGMA/ATTACH 等）"}
    if ";" in s:
        return {"error": "一次只允许一条语句"}
    # 标识符白名单：抽出来的表名/列名必须都在名单内
    idents = {i.lower() for i in re.findall(r"\b([A-Za-z_]\w*)\b", s)
              if i.lower() not in _SQL_KEYWORDS}
    unknown = {i for i in idents if i not in _SQL_TABLES and i not in _SQL_COLS}
    if unknown:
        return {"error": f"未知表/列：{sorted(unknown)}",
                "hint": f"可用表：{sorted(_SQL_TABLES)}"}
    if not re.search(r"\blimit\b", s, re.IGNORECASE):
        s += f" LIMIT {_MAX_ROWS}"
    con = aiqa_db.connect_ro(REPO)
    try:
        cur = con.execute(s)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchmany(_MAX_ROWS + 1)]
        truncated = len(rows) > _MAX_ROWS
        return {"columns": cols, "rows": rows[:_MAX_ROWS],
                "n": len(rows[:_MAX_ROWS]), "truncated": truncated}
    except Exception as e:                                     # noqa: BLE001
        return {"error": f"SQL 执行失败：{e}"}
    finally:
        con.close()


_SQL_KEYWORDS = frozenset({
    "select", "from", "where", "group", "by", "order", "having", "limit",
    "offset", "as", "and", "or", "not", "in", "is", "null", "like", "between",
    "join", "left", "right", "inner", "outer", "on", "asc", "desc", "distinct",
    "case", "when", "then", "else", "end", "cast", "count", "sum", "avg",
    "min", "max", "round", "abs", "ifnull", "coalesce", "length", "substr",
    "upper", "lower", "escape", "exists", "union", "all", "values", "with",
})


# ---------------------------------------------------------------- MCP 框架

TOOLS = [
    {
        "name": "aiqa_meta",
        "description": ("文衡问数库元信息：当前期次、指标白名单（中文名）、"
                        "22 个学科名单、期次轴。问数前先看它。"),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "aiqa_ask",
        "description": ("自然语言问数：问「化学的总被引趋势」「202607 论文数前 5 名」"
                        "这类问题，返回人话答案 + ECharts 就绪的图表数据"
                        "（categories/series）。推荐入口。"),
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string",
                                        "description": "自然语言问题（中文）"}},
            "required": ["question"],
        },
    },
    {
        "name": "aiqa_sql",
        "description": ("受控只读 SQL：仅 SELECT，表/列白名单，自动补 LIMIT。"
                        "表：facts（学科×期次×指标事实）、report_table2（当期大表）、"
                        "report_overview（概述事实）、dim_*（维度）、qa_log（问数留痕）。"),
        "inputSchema": {
            "type": "object",
            "properties": {"sql": {"type": "string",
                                   "description": "只读 SELECT 语句"}},
            "required": ["sql"],
        },
    },
]


def dispatch(name: str, args: dict):
    if name == "aiqa_meta":
        return tool_meta()
    if name == "aiqa_ask":
        return tool_ask(str(args.get("question") or ""))
    if name == "aiqa_sql":
        return tool_sql(str(args.get("sql") or ""))
    raise ValueError(f"未知工具：{name}")


def handle(req: dict) -> dict:
    method = req.get("method", "")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "wenheng-aiqa", "version": "1.0.0"},
        }}
    if method == "notifications/initialized":
        return None                                    # 通知无需响应
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = (req.get("params") or {}).get("name", "")
        args = (req.get("params") or {}).get("args") or \
            (req.get("params") or {}).get("arguments") or {}
        try:
            data = dispatch(name, args)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(data, ensure_ascii=False)}],
                "isError": bool(data.get("error")) if isinstance(data, dict) else False,
            }}
        except Exception as e:                                 # noqa: BLE001
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"工具执行失败：{e}"}],
                "isError": True}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": f"未知方法：{method}"}}
    return None


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle(req)
        except Exception as e:                                 # noqa: BLE001
            if req.get("id") is not None:
                resp = {"jsonrpc": "2.0", "id": req.get("id"), "error": {
                    "code": -32603, "message": str(e)}}
            else:
                resp = None
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""本地小模型层（可选增强）：仅做"文字润色/起草"，绝不接触数字。

机制（数字防护盾）：
  1. 段落中的数字全部替换为 [[n]] 占位符（protect）
  2. 本地模型只拿到"含占位符的文本"，只允许润色
  3. 校验器：占位符必须全部保留且仅一次；不得出现任何其它数字
  4. 任一校验失败 → 自动回退原文（数据零风险）

运行依赖（本地、离线，无外部 API）：
  - Ollama 服务：https://ollama.com  （已装则 `ollama serve`）
  - 模型示例：ollama pull qwen2.5:3b-instruct  （3B 低配首选；有 GPU/内存充足可 7b/14b）

用法：
  python src\\local_llm.py check                 # 检查服务与模型
  python src\\local_llm.py polish "文本…"         # 单段试润色
  python src\\local_llm.py draft out\\202607      # 对本期句骨架批量润色 → draft_texts.json
"""
import json
import pathlib
import re
import sys
import urllib.request

OLLAMA = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b-instruct"
NUM = re.compile(r"\d+(?:\.\d+)?")
MARK = re.compile(r"\[\[(\d+)\]\]")

PROMPT = """你是中文公文写作助手。任务：在不改变事实含义的前提下，把下面的段落润色得更通顺、更符合中文报告语体。

严格规则：
1. [[n]] 是数字占位标记，必须原样保留，每个必须出现且只出现一次，可微调其所在语句位置，但不得改写标记本身；
2. 严禁新增、删除或修改任何其它数字、百分号；
3. 不要添加评论、标题或解释，只输出润色后的整段文字。

原文：
{text}
"""


def check():
    """返回 (ok, models|错误信息)。"""
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3) as r:
            tags = json.load(r)
        return True, [m.get("name") for m in tags.get("models", [])]
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def generate(prompt, model=DEFAULT_MODEL, temperature=0.2, timeout=600):
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": temperature},
    }).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r).get("response", "").strip()


def protect(text):
    """数字 → [[n]]，返回 (受保护文本, 映射表)。"""
    mapping = {}

    def repl(m):
        k = str(len(mapping) + 1)
        mapping[k] = m.group(0)
        return f"[[{k}]]"

    return NUM.sub(repl, text), mapping


def restore(text, mapping):
    return re.sub(r"\[\[(\d+)\]\]", lambda m: mapping.get(m.group(1), m.group(0)), text)


def validate(out_text, mapping):
    """占位符完备 + 无新增数字。返回 (ok, 详情)。"""
    missing = [k for k in mapping if out_text.count(f"[[{k}]]") != 1]
    stray = NUM.findall(MARK.sub("", out_text))
    ok = (not missing) and (not stray)
    return ok, {"missing": missing, "stray": stray}


def polish(text, model=DEFAULT_MODEL):
    """润色一段（含数字）。返回 (最终文本, 说明 dict)。失败自动回退原文。"""
    protected, mapping = protect(text)
    try:
        out = generate(PROMPT.format(text=protected), model=model)
    except Exception as e:  # noqa: BLE001
        return text, {"mode": "fallback", "reason": f"调用失败: {e}"}
    ok, detail = validate(out, mapping)
    if not ok:
        return text, {"mode": "fallback", "reason": f"校验失败: {detail}"}
    return restore(out, mapping), {"mode": "polished", "model": model}


def draft(ledger_dir, model=DEFAULT_MODEL):
    """对本期句骨架批量润色 → out/<期次>/draft_texts.json。"""
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    import sentences  # noqa: PLC0415
    ld = pathlib.Path(ledger_dir)
    meta = json.loads((ld / "meta.json").read_text(encoding="utf-8"))
    facts = json.loads((ld / "overview_facts.json").read_text(encoding="utf-8"))
    texts = sentences.build(facts, meta["period_current"], meta["period_prev"])
    out, stats = {}, {"polished": 0, "fallback": 0}
    for key, t in texts.items():
        if key.startswith("cover"):
            out[key] = t
            continue
        new, info = polish(t, model=model)
        out[key] = new
        stats[info["mode"]] += 1
        print(f"[{info['mode']}] {key}: {info.get('reason', model)}")
    (ld / "draft_texts.json").write_text(
        json.dumps({"texts": out, "stats": stats}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {ld / 'draft_texts.json'}  {stats}")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        ok, info = check()
        if ok:
            print("Ollama 运行中。已装模型：", info or "（无，先 ollama pull）")
        else:
            print("Ollama 未运行或未安装：", info)
            print("启动：命令行执行 `ollama serve`（或启动 Ollama 桌面应用）；拉模型：`ollama pull qwen2.5:3b-instruct`")
    elif cmd == "polish":
        text = sys.argv[2] if len(sys.argv) > 2 else "本期我校工程学较5月上升33.87%。"
        out, info = polish(text)
        print(json.dumps({"out": out, "info": info}, ensure_ascii=False, indent=1))
    elif cmd == "draft":
        draft(sys.argv[2] if len(sys.argv) > 2 else "out/202607")
    else:
        print(__doc__)

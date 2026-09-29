# -*- coding: utf-8 -*-
"""Brain 端口（唯一接缝，内部）与规则适配器（SPEC §3）。

- 端口判据（D-ports）：只有「跨网络、不受控、且真实适配器 ≥2」的依赖才开端口；
  云模型满足（rule 生产 / openai 生产 / 测试替身），其余依赖（工具/台账/记录）并入内部。
- **回落＝同一端口的另一个适配器**：`RuleBrain` 是默认、演示站与一切回落的终点；
  两条路共享盾、白名单、留痕与标注，机械上不易分叉。
- `OpenAIBrain` 列后（D3，等 key）；Scripted/Failing 只进 tests。
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass


class BrainError(RuntimeError):
    """模型适配器的**可回落**失败：超时 / 连不上 / 限额 / 协议坏。

    `code` 是回落原因码（进 Answer.notice 与记录 `fallback`），默认取类名；
    云适配器用 timeout / rate_limit / http_5xx / unreachable / bad_response / egress_budget。
    """

    def __init__(self, message, *, code: str | None = None):
        super().__init__(message)
        self.code = code or type(self).__name__


@dataclass(frozen=True)
class Brief:
    """模块 → 端口。这就是「外发」的全部（最小外发，I5）：静态纪律提示 + 受保护文本
    （数字已变 [[n]] 占位）+ 只读工具规格 + 回执摘要（已占位化）。台账原值与来源映射不出模块。
    """

    ability: str
    system: str
    task: str
    step: int = 1
    max_steps: int = 1
    evidence: tuple[str, ...] = ()
    tools: tuple[dict, ...] = ()

    def egress_texts(self) -> tuple[str, ...]:
        """外发面的全部文本（供预算度量与「零数字」测试）。"""
        import json                                            # noqa: PLC0415

        out = [self.ability, self.system, self.task, *self.evidence]
        if self.tools:
            out.append(json.dumps([dict(t) for t in self.tools], ensure_ascii=False, sort_keys=True))
        return tuple(out)

    def egress_bytes(self) -> int:
        return sum(len(t.encode("utf-8")) for t in self.egress_texts())


@dataclass(frozen=True)
class Turn:
    """端口 → 模块：候选正文（含 [[n]]）或工具调用；二选一。"""

    text: str | None = None
    calls: tuple[dict, ...] = ()
    note: str = ""


class RuleBrain:
    """规则适配器：进程内、确定性、**演示站永远走它**（无 key 物理上无法外发）。

    它不做业务逻辑——只是把构建器已拼好的规则版原文原样交回（回落物先存在，D-ports O3）。
    """

    name = "rule"
    is_rule = True

    def think(self, brief: Brief) -> Turn:                     # noqa: ARG002
        return Turn(text=brief.task)


class OpenAIBrain:
    """OpenAI 兼容云适配器（生产；DeepSeek `deepseek-flash` / 百炼等同协议）。

    - key 只从构造参数（= 部署 env，见 `_config.py`）来；本模块不读环境、不落盘（SPEC §2.5）。
    - **单次尝试**：超时 / 限额 / 协议坏 → `BrainError`（带原因码），由核心回落规则版；
      不做半句模型半句规则（SPEC §2.5）。
    - 外发预算：字符上限（`max_egress_chars`），超限**不发包**直接回落（code=egress_budget），
      预算内只发占位面（Brief 构造已保证零数字）。
    - diagnose 是锚定型改写，本适配器不发工具（function calling 随 qa 落地，D2 之后）。
    """

    is_rule = False

    def __init__(self, *, base_url, model, key, timeout=30.0, max_tokens=2048,
                 max_egress_chars=6000, temperature=0.2):
        self.base_url = str(base_url).rstrip("/")
        self.model = str(model)
        self.name = f"openai:{self.model}"
        self._key = str(key)
        self.timeout = float(timeout)
        self.max_tokens = int(max_tokens)
        self.max_egress_chars = int(max_egress_chars)
        self.temperature = float(temperature)

    def think(self, brief: Brief) -> Turn:
        egress_chars = sum(len(t) for t in brief.egress_texts())
        if egress_chars > self.max_egress_chars:
            raise BrainError(
                f"外发 {egress_chars} 字符超过上限 {self.max_egress_chars}",
                code="egress_budget")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": brief.system},
                {"role": "user", "content": brief.task},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:   # noqa: S310
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            code = "rate_limit" if e.code == 429 else f"http_{e.code}"
            raise BrainError(f"HTTP {e.code}", code=code) from e
        except (TimeoutError, socket.timeout) as e:
            raise BrainError(f"超时（{self.timeout:g}s）", code="timeout") from e
        except (urllib.error.URLError, OSError) as e:
            raise BrainError(f"连不上：{e}", code="unreachable") from e
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise BrainError("响应不是合法 JSON", code="bad_response") from e
        try:
            content = data["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError) as e:
            raise BrainError("响应缺 choices/content", code="bad_response") from e
        return Turn(text=str(content or ""))

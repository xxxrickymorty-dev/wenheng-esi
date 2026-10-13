# src/_vendor —— vendored 依赖快照

> 规则：只收「体量小、上游 Alpha、接口自供」的依赖；来源/版本/许可/哈希全部留档；
> **不改 pyproject.toml / uv.lock / .venv**（快照随包走，导入即用）。

## pi_agent_core（pi-agent-core 0.1.1）

| 项 | 值 |
|---|---|
| 包名 / 版本 | `pi-agent-core` 0.1.1（PyPI） |
| 上游 | PyPI 项目页 <https://pypi.org/project/pi-agent-core/0.1.1/>；作者 Huvinesh Rajendran |
| 来源 | 是 TypeScript `@mariozechner/pi-agent-core`（pi-mono）的 Python 移植 |
| 许可 | MIT（wheel 元数据 `License-Expression: MIT`） |
| wheel | `pi_agent_core-0.1.1-py3-none-any.whl`，sha256 `f915ed1d79775ae340bac41eea2ec65089e197333e08f16c4bec5245a99c073b`（21721 字节） |
| 快照日期 | 2026-10-13（票 01 spike 选定；票 03 入库） |
| 运行时依赖 | 仅 `pydantic>=2`（主 venv 经 fastapi 已有；快照不含 httpx/anthropic 路径） |

### 文件清单与哈希（sha256）

`agent.py` / `agent_loop.py` / `types.py` 与上游 wheel **逐字节一致**（哈希已对 wheel RECORD 校验）：

| 文件 | sha256 | 上游 RECORD（urlsafe-b64） |
|---|---|---|
| `pi_agent_core/agent.py` | `3dcaf5dfc049dbd760a9f42e871eadebf5c67be6d9ce3da882301569d928d326` | `Pcr138BJ29dgqfQuhx6t6_XGe-bZzj2ogjAVadko0yY` |
| `pi_agent_core/agent_loop.py` | `707ce425ff9514372c89926610c7a117e33cc06bbab4a05cd836cc79ce29af5b` | `cHzkJf-VFDcsiZJmEMehF-M8wGu6tKBc2DbMec4pr1s` |
| `pi_agent_core/types.py` | `52cbdb2dbcb852eca3998a4e9ad8369a2dda4621f6bb9a2591c4d621a67175f9` | `UsvbLby4UuyjmYpOmtg2mi3aRiH2u5olkcTWIaZxdfk` |

### 相对上游的裁剪（唯一修改处）

- `pi_agent_core/__init__.py`：**重写**为精简版——上游无条件导入 `proxy`（依赖 httpx）与可选
  `anthropic`；本仓库只用 agent loop + types 子集（StreamFn 自供），故不导出这两个模块。
- 未拷入 `proxy.py` / `anthropic.py`（对应依赖 httpx / anthropic，不在本仓库锁定 venv 里，
  也用不到）。其余文件原样。

### MIT 许可正文

上游 wheel/sdist 元数据声明 `License-Expression: MIT` 并引用 `LICENSE`，但 wheel 与 sdist
均未随包附许可文件（已核）。按 MIT 模板补齐如下（版权人取自包元数据作者）：

```
MIT License

Copyright (c) Huvinesh Rajendran

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 更新姿势（升级快照时）

1. 临时环境拉新 wheel：`uv run --no-project --with pi-agent-core python -c "import pi_agent_core; print(pi_agent_core.__file__)"`；
2. 重拷 `agent.py` / `agent_loop.py` / `types.py`，更新本 README 的版本与哈希；
3. 重跑 `tests/test_ai_dialog_kernel.py`（Scripted 全绿即接口未破）。

# Issue tracker 约定（本仓：文件版，无外部 tracker）

> mattpocock 技能链（to-spec / to-tickets / wayfinder / code-review）的落点约定。
> 本仓**不启用** GitHub Issues（gh 虽已登录，但演示仓公开、评审不依赖外部服务）；
> 一律用**文件版**。

## 落点

| 工件 | 路径 | 入库？ |
|---|---|---|
| spec（to-spec 产物） | `docs/specs/YYYY-MM-DD-<slug>.md` | ✅ 入库（评审材料也用得上） |
| 票（to-tickets 产物） | `.scratch/<slug>/issues/<NN>-<短名>.md` | ❌ 不入库（.gitignore 已排除） |
| wayfinder 地图（若用） | `.scratch/wayfinder/<map-slug>/` | ❌ 不入库 |

## 约定

- 票文件头三行固定：`spec:`（来源文件或对话）、`blocked by:`（票号，空写 `—`）、`status: open|doing|done`。
- 依赖只写票号；**`blocked by` 全空才是可做的 frontier 票**。
- 一张票一次交付：改完 → 跑该票验收 → 提交（commit message 带票号，如 `(票 05)`）。
- code-review 找 spec 的顺序：commit 引用 → 用户给的路径 → `docs/specs/` 匹配文件名。
- 若将来改用 GitHub Issues：替换本文，并把 triage 标签约定一并记录。

## 当前生效

- **对话前门**（2026-10-10 发布）：spec `docs/specs/2026-10-10-对话前门.md`（`ready-for-agent`）／
  票集 `.scratch/duihua-qianmen/issues/`（01–06；**01 无前置**，02 与 06 可并行）
- **Agent 自主性 · 灵活产线**：spec `docs/specs/2026-10-10-agent自主性-灵活产线.md`／
  票集 `.scratch/agent-zizhu/issues/`（01 已 `done`，02–06 `open`；Critic 原型在 `prototype/critic-anchors` 分支）
- 已完结：spec `docs/specs/2026-09-28-地基与信息减负.md`／票集 `.scratch/diji-jianfu/issues/`（15 票全部 `done`）

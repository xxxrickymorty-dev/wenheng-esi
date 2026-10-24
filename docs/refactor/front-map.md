# 前端模块地图（自动生成）

> 扫描 `web/src`（82 个 ts/tsx，18254 行）。生成脚本 `tools/gen_front_map.py`。
> `依赖 api` 一列就是该文件的对外耦合面——重构时按列切，不要按文件名字母序切。

## 按 API 耦合数排序（改动风险最高的在前）

| 文件 | 行数 | 依赖 api 函数 |
|---|---:|---|
| `web/src/dialog/DialogPage.tsx` | 1004 | `req`, `getArtifacts`, `getJobProgress`, `getMe`, `getPeriods`, `getRollbackPoints`, `postJob`, `rollbackPeriod` |
| `web/src/Tools.tsx` | 242 | `getJob`, `getPeriodArtifacts`, `getPeriodDetail`, `getRollbackPoints`, `humanSize`, `rerunJob`, `rollbackPeriod` |
| `web/src/App.tsx` | 817 | `getHealth`, `getMe`, `getPeriodDetail`, `getPeriods`, `getStatus`, `postJob` |
| `web/src/hooks/useJobRun.ts` | 270 | `getJob`, `getJobProgress`, `getPeriodDetail`, `getStatus`, `jobEventsUrl` |
| `web/src/Acquire.tsx` | 713 | `getAcquisition`, `openPeriod`, `postAcquisition`, `postAcqBrowser` |
| `web/src/Panorama.tsx` | 673 | `getAcquisition`, `getArchive`, `req` |
| `web/src/Archive.tsx` | 354 | `getAcquisition`, `getArchive`, `humanSize` |
| `web/src/Report.tsx` | 493 | `getPeriodArtifacts`, `humanSize` |
| `web/src/Workbench.tsx` | 484 | `getArchive` |
| `web/src/StoryBand.tsx` | 392 | `getArchive` |
| `web/src/AiRecords.tsx` | 177 | `getAiCalls` |
| `web/src/library/data.ts` | 171 | `req` |
| `web/src/HealSandbox.tsx` | 160 | `getHealSandbox` |
| `web/src/Pick.tsx` | 132 | `getOutline` |
| `web/src/Trace.tsx` | 128 | `req` |
| `web/src/Ledger.tsx` | 120 | `req` |
| `web/src/Waterfall.tsx` | 117 | `getJobProgress` |
| `web/src/MigrateSandbox.tsx` | 91 | `getMigrateSandbox` |

## 无 API 耦合（纯展示 / 纯样式 / 工具）

| 文件 | 行数 |
|---|---:|
| `web/src/library/scene/libraryRuntime.ts` | 1751 |
| `web/src/library/scene/LibraryScene.tsx` | 1376 |
| `web/src/library/Reader.tsx` | 723 |
| `web/src/Review.tsx` | 643 |
| `web/src/Forecast.tsx` | 576 |
| `web/src/api.ts` | 503 |
| `web/src/Flexible.tsx` | 407 |
| `web/src/library/scene/coverTexture.ts` | 343 |
| `web/src/library/LibraryHome.tsx` | 265 |
| `web/src/library/scene/libraryLights.ts` | 252 |
| `web/src/library/ShelfPage.tsx` | 239 |
| `web/src/library/scene/architecture.ts` | 236 |
| `web/src/Reading.tsx` | 222 |
| `web/src/lib/runMachine.ts` | 214 |
| `web/src/library/library-audio.ts` | 196 |
| `web/src/api-forecast.ts` | 192 |
| `web/src/wb.ts` | 178 |
| `web/src/wb.test.ts` | 159 |
| `web/src/api-flexible.ts` | 151 |
| `web/src/lib/status.ts` | 147 |
| `web/src/lib/runMachine.test.ts` | 145 |
| `web/src/RedList.tsx` | 142 |
| `web/src/library/LibraryExperience.tsx` | 141 |
| `web/src/api-dialog.ts` | 129 |
| `web/src/lib/archiveStory.test.ts` | 125 |
| `web/src/api-workbench.ts` | 112 |
| `web/src/lib/archiveStory.ts` | 108 |
| `web/src/lib/status.test.ts` | 106 |
| `web/src/library/scene/libraryCamera.ts` | 105 |
| `web/src/Charts.tsx` | 96 |
| `web/src/lib/forecast.test.ts` | 91 |
| `web/src/library/types.ts` | 88 |
| `web/src/lib/taskview.test.ts` | 87 |
| `web/src/lib/taskview.ts` | 80 |
| `web/src/icons.tsx` | 77 |
| `web/src/lib/dialog.test.ts` | 75 |
| `web/src/lib/dialog.ts` | 73 |
| `web/src/api-collation.ts` | 69 |
| `web/src/lib/forecast.ts` | 67 |
| `web/src/lib/period.ts` | 67 |
| `web/src/library/scene/ShelfScene.tsx` | 65 |
| `web/src/lib/labels.ts` | 63 |
| `web/src/NumberedText.tsx` | 60 |
| `web/src/lib/motion.ts` | 59 |
| `web/src/api-report.ts` | 58 |
| `web/src/ConfirmButton.tsx` | 55 |
| `web/src/lib/period.test.ts` | 53 |
| `web/src/lib/UserChip.tsx` | 50 |
| `web/src/lib/banned.test.ts` | 47 |
| `web/src/lib/labels.test.ts` | 45 |
| `web/src/api-sign.ts` | 42 |
| `web/src/lib/run.test.ts` | 42 |
| `web/src/lib/stateDb.test.ts` | 41 |
| `web/src/lib/repro.test.ts` | 40 |
| `web/src/lib/stateDb.ts` | 38 |
| `web/src/lib/repro.ts` | 35 |
| `web/src/lib/banned.ts` | 32 |
| `web/src/lib/run.ts` | 30 |
| `web/src/lib/terms.ts` | 30 |
| `web/src/Info.tsx` | 19 |
| `web/src/dialog/main.tsx` | 18 |
| `web/src/library/main.tsx` | 17 |
| `web/src/main.tsx` | 11 |
| `web/src/Analysis.tsx` | 10 |

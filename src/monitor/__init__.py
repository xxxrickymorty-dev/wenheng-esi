# -*- coding: utf-8 -*-
"""监测版（第三条产线）：ESI-only 全校学科站位报告。

对外入口：`report.generate(中文名)` → 出单文件 HTML（最简版）；
`report.latest_period()` / `report.load_cache()` / `report.build_cache()` 供服务端取数。
契约见工作区仓库① `评审文档/38-监测版包契约-ESIonly（20261031）.md`（2026-10-31 升级为评审分册）；核验 CLI 见 `doctor.py`。
"""

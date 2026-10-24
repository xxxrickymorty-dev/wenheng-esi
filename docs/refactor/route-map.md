# 后端路由清单（自动生成）

> 来源 `server/app.py`（3021 行，91 个路由）。
> 生成脚本 `tools/gen_route_map.py`。**不要手改本文件**，改 app.py 后重跑。
> `行号区间` 是该处理函数的大致位置——排查时只读这一段，不要读全文。

| # | 方法 | 路径 | 处理函数 | 行号区间 | 行数 |
|---:|---|---|---|---|---:|
| 1 | GET | `/login` | `login_page` | 263–270 | 8 |
| 2 | POST | `/login` | `do_login` | 271–303 | 33 |
| 3 | GET | `/logout` | `logout` | 304–344 | 41 |
| 4 | GET | `/` | `home` | 345–356 | 12 |
| 5 | GET | `/run` | `run_page` | 357–364 | 8 |
| 6 | GET | `/forecast` | `forecast_page` | 365–374 | 10 |
| 7 | GET | `/p/{period}` | `period_collation` | 375–390 | 16 |
| 8 | GET | `/p/{period}/redslots` | `period_redslots` | 391–402 | 12 |
| 9 | GET | `/p/{period}/trace` | `period_trace` | 403–428 | 26 |
| 10 | GET | `/p/{period}/charts` | `period_charts` | 429–497 | 69 |
| 11 | GET | `/p/{period}/flexible` | `period_flexible` | 498–516 | 19 |
| 12 | GET | `/p/{period}/flexible/chart/{intent}/{name}` | `period_flexible_chart` | 517–530 | 14 |
| 13 | GET | `/p/{period}/flexible/{intent}/report.html` | `period_flexible_report` | 531–555 | 25 |
| 14 | GET | `/p/{period}/flexible/{intent}/report.docx` | `period_flexible_report_docx` | 556–586 | 31 |
| 15 | GET | `/p/{period}/archive` | `period_archive` | 587–603 | 17 |
| 16 | GET | `/p/{period}/chart/{rel:path}` | `period_chart` | 604–621 | 18 |
| 17 | GET | `/p/{period}/download/{key}` | `period_download` | 622–634 | 13 |
| 18 | GET | `/jobs/{job_id}` | `job_page` | 635–640 | 6 |
| 19 | GET | `/jobs/{job_id}/redslots` | `redslots_page` | 641–653 | 13 |
| 20 | GET | `/jobs/{job_id}/charts` | `charts_page` | 654–666 | 13 |
| 21 | GET | `/jobs/{job_id}/archive` | `job_archive` | 667–680 | 14 |
| 22 | GET | `/jobs/{job_id}/collation` | `collation_page` | 681–694 | 14 |
| 23 | GET | `/api/jobs/{job_id}/approval` | `api_approval` | 695–706 | 12 |
| 24 | GET | `/api/jobs/{job_id}/progress` | `api_job_progress` | 707–739 | 33 |
| 25 | GET | `/healthz` | `healthz` | 740–773 | 34 |
| 26 | GET | `/api/status` | `api_status` | 774–836 | 63 |
| 27 | GET | `/api/periods` | `api_periods` | 837–856 | 20 |
| 28 | GET | `/api/me` | `api_me` | 857–866 | 10 |
| 29 | GET | `/api/periods/{period}` | `api_period_detail` | 867–973 | 107 |
| 30 | GET | `/api/periods/{period}/acquisition` | `api_period_acquisition` | 974–1156 | 183 |
| 31 | POST | `/api/acquisition/browser` | `api_acq_browser` | 1157–1215 | 59 |
| 32 | POST | `/api/periods/{period}/acquisition/start` | `api_acq_start` | 1216–1225 | 10 |
| 33 | POST | `/api/periods/{period}/acquisition/open` | `api_acq_open` | 1226–1247 | 22 |
| 34 | POST | `/api/periods/{period}/acquisition/retry` | `api_acq_retry` | 1248–1262 | 15 |
| 35 | POST | `/api/periods/{period}/acquisition/copy` | `api_acq_copy` | 1263–1269 | 7 |
| 36 | POST | `/api/periods/{period}/acquisition/merge` | `api_acq_merge` | 1270–1291 | 22 |
| 37 | POST | `/api/periods/{period}/acquisition/preflight` | `api_acq_preflight` | 1292–1306 | 15 |
| 38 | POST | `/api/periods/{period}/acquisition/stop` | `api_acq_stop` | 1307–1336 | 30 |
| 39 | GET | `/api/periods/{period}/acquisition/datapack` | `api_acq_datapack` | 1337–1386 | 50 |
| 40 | GET | `/api/periods/{period}/artifacts` | `api_period_artifacts` | 1387–1400 | 14 |
| 41 | GET | `/api/periods/{period}/download/{key}` | `api_period_download` | 1401–1424 | 24 |
| 42 | POST | `/api/periods/{period}/sign` | `api_period_sign_json` | 1425–1450 | 26 |
| 43 | GET | `/api/periods/{period}/forecast-choice` | `api_forecast_choice_get` | 1451–1480 | 30 |
| 44 | GET/POST | `/api/periods/{period}/forecast-choice` | `api_forecast_choice` | 1481–1513 | 33 |
| 45 | POST | `/api/periods/{period}/revoke` | `api_period_revoke_json` | 1514–1528 | 15 |
| 46 | POST | `/api/periods/{period}/fill` | `api_period_fill_json` | 1529–1555 | 27 |
| 47 | POST | `/api/periods/{period}/flag` | `api_period_flag_json` | 1556–1574 | 19 |
| 48 | POST | `/api/periods/{period}/rebuild` | `api_period_rebuild_json` | 1575–1654 | 80 |
| 49 | GET | `/api/periods/{period}/facts` | `api_period_facts` | 1655–1679 | 25 |
| 50 | GET | `/api/periods/{period}/water` | `api_period_water` | 1680–1693 | 14 |
| 51 | GET | `/api/sandbox/heal` | `api_sandbox_heal` | 1694–1711 | 18 |
| 52 | GET | `/api/sandbox/migrate` | `api_sandbox_migrate` | 1712–1725 | 14 |
| 53 | GET | `/api/periods/{period}/workbench` | `api_period_workbench` | 1726–1739 | 14 |
| 54 | GET | `/api/periods/{period}/report-preview` | `api_period_report_preview` | 1740–1757 | 18 |
| 55 | GET | `/api/periods/{period}/report-image/{rid}` | `api_period_report_image` | 1758–1806 | 49 |
| 56 | GET | `/api/periods/{period}/archive` | `api_period_archive` | 1807–1846 | 40 |
| 57 | GET | `/api/periods/{period}/trace` | `api_period_trace` | 1847–1890 | 44 |
| 58 | GET | `/api/periods/{period}/redslots` | `api_period_redslots` | 1891–1915 | 25 |
| 59 | GET | `/api/periods/{period}/outline` | `api_period_outline` | 1916–1988 | 73 |
| 60 | GET | `/api/periods/{period}/collation` | `api_period_collation` | 1989–2018 | 30 |
| 61 | GET | `/api/periods/{period}/charts` | `api_period_charts_json` | 2019–2057 | 39 |
| 62 | GET | `/api/ledger/sheets` | `api_ledger_sheets` | 2058–2100 | 43 |
| 63 | POST | `/api/analyze` | `api_analyze` | 2101–2123 | 23 |
| 64 | POST | `/api/periods/{period}/review-advice` | `api_period_review_advice` | 2124–2140 | 17 |
| 65 | GET | `/api/ai/capabilities` | `api_ai_capabilities` | 2141–2150 | 10 |
| 66 | GET | `/api/periods/{period}/ai-calls` | `api_period_ai_calls` | 2151–2200 | 50 |
| 67 | POST | `/api/ai/switch` | `api_ai_switch` | 2201–2223 | 23 |
| 68 | POST | `/api/dialog/turn` | `api_dialog_turn` | 2224–2375 | 152 |
| 69 | POST | `/api/dialog/turn/stream` | `api_dialog_turn_stream` | 2376–2432 | 57 |
| 70 | GET | `/api/dialog/session/{session_id}` | `api_dialog_session` | 2433–2451 | 19 |
| 71 | GET | `/api/dialog/sessions` | `api_dialog_sessions` | 2452–2464 | 13 |
| 72 | POST | `/api/dialog/session/{session_id}/drop` | `api_dialog_session_drop` | 2465–2482 | 18 |
| 73 | GET | `/api/dialog/home` | `api_dialog_home` | 2483–2503 | 21 |
| 74 | GET | `/api/forecast/board` | `api_forecast_board` | 2504–2516 | 13 |
| 75 | GET | `/api/periods/{period}/flexible` | `api_period_flexible` | 2517–2546 | 30 |
| 76 | POST | `/api/periods/{period}/flexible` | `api_period_flexible_generate` | 2547–2602 | 56 |
| 77 | POST | `/api/periods/{period}/flexible/stream` | `api_period_flexible_stream` | 2603–2655 | 53 |
| 78 | POST | `/api/periods/{period}/flexible/stop` | `api_period_flexible_stop` | 2656–2673 | 18 |
| 79 | POST | `/api/periods/{period}/flexible/polish` | `api_period_flexible_polish` | 2674–2713 | 40 |
| 80 | GET | `/api/forecast/meta` | `api_forecast_meta` | 2714–2719 | 6 |
| 81 | POST | `/api/forecast/run` | `api_forecast_run` | 2720–2733 | 14 |
| 82 | POST | `/api/jobs` | `api_create_job` | 2734–2780 | 47 |
| 83 | GET | `/api/jobs/{job_id}` | `api_job` | 2781–2792 | 12 |
| 84 | GET | `/api/jobs/{job_id}/artifacts` | `api_artifacts` | 2793–2803 | 11 |
| 85 | GET | `/api/jobs/{job_id}/download/{key}` | `api_job_download` | 2804–2815 | 12 |
| 86 | POST | `/api/jobs/{job_id}/rerun` | `api_rerun_job` | 2816–2862 | 47 |
| 87 | GET | `/api/periods/{period}/rollback-points` | `api_rollback_points` | 2863–2873 | 11 |
| 88 | POST | `/api/periods/{period}/rollback` | `api_rollback` | 2874–2944 | 71 |
| 89 | GET | `/api/jobs/{job_id}/events` | `api_events` | 2945–2991 | 47 |
| 90 | GET | `/jobs/{job_id}/download/{key}` | `download` | 2992–3010 | 19 |
| 91 | GET | `/qr.png` | `qr` | 3011–3020 | 10 |

## 分组计数

| 前缀 | 路由数 |
|---|---:|
| `/api/periods` | 40 |
| `/p/{period}/*` | 11 |
| `/api/jobs` | 8 |
| `/api/dialog` | 6 |
| `/api/forecast` | 3 |
| `/login` | 2 |
| `/api/sandbox` | 2 |
| `/api/ai` | 2 |
| `/logout` | 1 |
| `/` | 1 |
| `/run` | 1 |
| `/forecast` | 1 |
| `/jobs/{job_id}` | 1 |
| `/jobs/{job_id}/redslots` | 1 |
| `/jobs/{job_id}/charts` | 1 |
| `/jobs/{job_id}/archive` | 1 |
| `/jobs/{job_id}/collation` | 1 |
| `/healthz` | 1 |
| `/api/status` | 1 |
| `/api/me` | 1 |
| `/api/acquisition` | 1 |
| `/api/ledger` | 1 |
| `/api/analyze` | 1 |
| `/jobs/{job_id}/download/{key}` | 1 |
| `/qr.png` | 1 |

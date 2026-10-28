# 后端路由清单（自动生成）

> 来源 `server/app.py`（3039 行，92 个路由）。
> 生成脚本 `tools/gen_route_map.py`。**不要手改本文件**，改 app.py 后重跑。
> `行号区间` 是该处理函数的大致位置——排查时只读这一段，不要读全文。

| # | 方法 | 路径 | 处理函数 | 行号区间 | 行数 |
|---:|---|---|---|---|---:|
| 1 | GET | `/login` | `login_page` | 264–271 | 8 |
| 2 | POST | `/login` | `do_login` | 272–304 | 33 |
| 3 | GET | `/logout` | `logout` | 305–345 | 41 |
| 4 | GET | `/` | `home` | 346–357 | 12 |
| 5 | GET | `/run` | `run_page` | 358–365 | 8 |
| 6 | GET | `/forecast` | `forecast_page` | 366–375 | 10 |
| 7 | GET | `/p/{period}` | `period_collation` | 376–391 | 16 |
| 8 | GET | `/p/{period}/redslots` | `period_redslots` | 392–403 | 12 |
| 9 | GET | `/p/{period}/trace` | `period_trace` | 404–429 | 26 |
| 10 | GET | `/p/{period}/charts` | `period_charts` | 430–498 | 69 |
| 11 | GET | `/p/{period}/flexible` | `period_flexible` | 499–517 | 19 |
| 12 | GET | `/p/{period}/flexible/chart/{intent}/{name}` | `period_flexible_chart` | 518–531 | 14 |
| 13 | GET | `/p/{period}/flexible/{intent}/report.html` | `period_flexible_report` | 532–556 | 25 |
| 14 | GET | `/p/{period}/flexible/{intent}/report.docx` | `period_flexible_report_docx` | 557–587 | 31 |
| 15 | GET | `/p/{period}/archive` | `period_archive` | 588–604 | 17 |
| 16 | GET | `/p/{period}/chart/{rel:path}` | `period_chart` | 605–622 | 18 |
| 17 | GET | `/p/{period}/download/{key}` | `period_download` | 623–635 | 13 |
| 18 | GET | `/jobs/{job_id}` | `job_page` | 636–641 | 6 |
| 19 | GET | `/jobs/{job_id}/redslots` | `redslots_page` | 642–654 | 13 |
| 20 | GET | `/jobs/{job_id}/charts` | `charts_page` | 655–667 | 13 |
| 21 | GET | `/jobs/{job_id}/archive` | `job_archive` | 668–681 | 14 |
| 22 | GET | `/jobs/{job_id}/collation` | `collation_page` | 682–695 | 14 |
| 23 | GET | `/api/jobs/{job_id}/approval` | `api_approval` | 696–707 | 12 |
| 24 | GET | `/api/jobs/{job_id}/progress` | `api_job_progress` | 708–740 | 33 |
| 25 | GET | `/healthz` | `healthz` | 741–774 | 34 |
| 26 | GET | `/api/status` | `api_status` | 775–837 | 63 |
| 27 | GET | `/api/periods` | `api_periods` | 838–857 | 20 |
| 28 | GET | `/api/me` | `api_me` | 858–867 | 10 |
| 29 | GET | `/api/periods/{period}` | `api_period_detail` | 868–974 | 107 |
| 30 | GET | `/api/periods/{period}/acquisition` | `api_period_acquisition` | 975–1157 | 183 |
| 31 | POST | `/api/acquisition/browser` | `api_acq_browser` | 1158–1216 | 59 |
| 32 | POST | `/api/periods/{period}/acquisition/start` | `api_acq_start` | 1217–1226 | 10 |
| 33 | POST | `/api/periods/{period}/acquisition/open` | `api_acq_open` | 1227–1248 | 22 |
| 34 | POST | `/api/periods/{period}/acquisition/retry` | `api_acq_retry` | 1249–1263 | 15 |
| 35 | POST | `/api/periods/{period}/acquisition/copy` | `api_acq_copy` | 1264–1270 | 7 |
| 36 | POST | `/api/periods/{period}/acquisition/merge` | `api_acq_merge` | 1271–1292 | 22 |
| 37 | POST | `/api/periods/{period}/acquisition/preflight` | `api_acq_preflight` | 1293–1307 | 15 |
| 38 | POST | `/api/periods/{period}/acquisition/stop` | `api_acq_stop` | 1308–1337 | 30 |
| 39 | GET | `/api/periods/{period}/acquisition/datapack` | `api_acq_datapack` | 1338–1387 | 50 |
| 40 | GET | `/api/periods/{period}/artifacts` | `api_period_artifacts` | 1388–1401 | 14 |
| 41 | GET | `/api/periods/{period}/download/{key}` | `api_period_download` | 1402–1425 | 24 |
| 42 | POST | `/api/periods/{period}/sign` | `api_period_sign_json` | 1426–1451 | 26 |
| 43 | GET | `/api/periods/{period}/forecast-choice` | `api_forecast_choice_get` | 1452–1481 | 30 |
| 44 | GET/POST | `/api/periods/{period}/forecast-choice` | `api_forecast_choice` | 1482–1514 | 33 |
| 45 | POST | `/api/periods/{period}/revoke` | `api_period_revoke_json` | 1515–1529 | 15 |
| 46 | POST | `/api/periods/{period}/fill` | `api_period_fill_json` | 1530–1556 | 27 |
| 47 | POST | `/api/periods/{period}/flag` | `api_period_flag_json` | 1557–1575 | 19 |
| 48 | POST | `/api/periods/{period}/rebuild` | `api_period_rebuild_json` | 1576–1655 | 80 |
| 49 | GET | `/api/periods/{period}/facts` | `api_period_facts` | 1656–1680 | 25 |
| 50 | GET | `/api/periods/{period}/water` | `api_period_water` | 1681–1694 | 14 |
| 51 | GET | `/api/sandbox/heal` | `api_sandbox_heal` | 1695–1712 | 18 |
| 52 | GET | `/api/sandbox/migrate` | `api_sandbox_migrate` | 1713–1726 | 14 |
| 53 | GET | `/api/periods/{period}/workbench` | `api_period_workbench` | 1727–1740 | 14 |
| 54 | GET | `/api/periods/{period}/report-preview` | `api_period_report_preview` | 1741–1758 | 18 |
| 55 | GET | `/api/periods/{period}/report-image/{rid}` | `api_period_report_image` | 1759–1807 | 49 |
| 56 | GET | `/api/periods/{period}/archive` | `api_period_archive` | 1808–1847 | 40 |
| 57 | GET | `/api/periods/{period}/trace` | `api_period_trace` | 1848–1891 | 44 |
| 58 | GET | `/api/periods/{period}/redslots` | `api_period_redslots` | 1892–1916 | 25 |
| 59 | GET | `/api/periods/{period}/outline` | `api_period_outline` | 1917–1989 | 73 |
| 60 | GET | `/api/periods/{period}/collation` | `api_period_collation` | 1990–2019 | 30 |
| 61 | GET | `/api/periods/{period}/charts` | `api_period_charts_json` | 2020–2036 | 17 |
| 62 | GET | `/api/periods/{period}/charts-data` | `api_period_charts_data` | 2037–2075 | 39 |
| 63 | GET | `/api/ledger/sheets` | `api_ledger_sheets` | 2076–2118 | 43 |
| 64 | POST | `/api/analyze` | `api_analyze` | 2119–2141 | 23 |
| 65 | POST | `/api/periods/{period}/review-advice` | `api_period_review_advice` | 2142–2158 | 17 |
| 66 | GET | `/api/ai/capabilities` | `api_ai_capabilities` | 2159–2168 | 10 |
| 67 | GET | `/api/periods/{period}/ai-calls` | `api_period_ai_calls` | 2169–2218 | 50 |
| 68 | POST | `/api/ai/switch` | `api_ai_switch` | 2219–2241 | 23 |
| 69 | POST | `/api/dialog/turn` | `api_dialog_turn` | 2242–2393 | 152 |
| 70 | POST | `/api/dialog/turn/stream` | `api_dialog_turn_stream` | 2394–2450 | 57 |
| 71 | GET | `/api/dialog/session/{session_id}` | `api_dialog_session` | 2451–2469 | 19 |
| 72 | GET | `/api/dialog/sessions` | `api_dialog_sessions` | 2470–2482 | 13 |
| 73 | POST | `/api/dialog/session/{session_id}/drop` | `api_dialog_session_drop` | 2483–2500 | 18 |
| 74 | GET | `/api/dialog/home` | `api_dialog_home` | 2501–2521 | 21 |
| 75 | GET | `/api/forecast/board` | `api_forecast_board` | 2522–2534 | 13 |
| 76 | GET | `/api/periods/{period}/flexible` | `api_period_flexible` | 2535–2564 | 30 |
| 77 | POST | `/api/periods/{period}/flexible` | `api_period_flexible_generate` | 2565–2620 | 56 |
| 78 | POST | `/api/periods/{period}/flexible/stream` | `api_period_flexible_stream` | 2621–2673 | 53 |
| 79 | POST | `/api/periods/{period}/flexible/stop` | `api_period_flexible_stop` | 2674–2691 | 18 |
| 80 | POST | `/api/periods/{period}/flexible/polish` | `api_period_flexible_polish` | 2692–2731 | 40 |
| 81 | GET | `/api/forecast/meta` | `api_forecast_meta` | 2732–2737 | 6 |
| 82 | POST | `/api/forecast/run` | `api_forecast_run` | 2738–2751 | 14 |
| 83 | POST | `/api/jobs` | `api_create_job` | 2752–2798 | 47 |
| 84 | GET | `/api/jobs/{job_id}` | `api_job` | 2799–2810 | 12 |
| 85 | GET | `/api/jobs/{job_id}/artifacts` | `api_artifacts` | 2811–2821 | 11 |
| 86 | GET | `/api/jobs/{job_id}/download/{key}` | `api_job_download` | 2822–2833 | 12 |
| 87 | POST | `/api/jobs/{job_id}/rerun` | `api_rerun_job` | 2834–2880 | 47 |
| 88 | GET | `/api/periods/{period}/rollback-points` | `api_rollback_points` | 2881–2891 | 11 |
| 89 | POST | `/api/periods/{period}/rollback` | `api_rollback` | 2892–2962 | 71 |
| 90 | GET | `/api/jobs/{job_id}/events` | `api_events` | 2963–3009 | 47 |
| 91 | GET | `/jobs/{job_id}/download/{key}` | `download` | 3010–3028 | 19 |
| 92 | GET | `/qr.png` | `qr` | 3029–3038 | 10 |

## 分组计数

| 前缀 | 路由数 |
|---|---:|
| `/api/periods` | 41 |
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

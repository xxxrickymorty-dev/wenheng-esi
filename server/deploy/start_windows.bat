@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist server\.env copy server\.env.example server\.env >nul
uv run python -m uvicorn server.app:app --host 0.0.0.0 --port 8080
pause

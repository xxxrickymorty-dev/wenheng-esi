@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  文衡 · 学科信息参考 一键出报告
echo  输入：input 目录下最新一期的 监测表.xlsx
echo ============================================
echo.
.venv\Scripts\python.exe src\run_latest.py
echo.
echo 完成。报告在 out 目录下对应期次的文件夹里。
pause

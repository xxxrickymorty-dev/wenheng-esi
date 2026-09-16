@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  Wenheng / Xueke Xinxi Cankao : report run
echo  [OFFLINE FALLBACK] daily entry is the dashboard
echo  input: newest ledger table under input\ folder
echo ============================================
echo.

rem Keep this file ASCII-only. cmd mis-parses non-ASCII batch text when the
rem console codepage is not UTF-8. Chinese output comes from the job log.
rem %RANDOM% suffix (not for /f) so cmd never re-reads this file mid-run.
set "JOBDIR=out\_jobs\bat_%RANDOM%%RANDOM%"
if not exist "%JOBDIR%" mkdir "%JOBDIR%"
set "LOG=%JOBDIR%\console.log"

echo [%date% %time%] fallback run started > "%LOG%"
echo running ... log: %LOG%
.venv\Scripts\python.exe src\run_latest.py >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo [FAIL] exit code %RC% -- no report produced, do NOT treat as done
  echo log: %LOG%
  echo.
  pause
  exit /b %RC%
)

echo [OK] report produced under out\ folder
echo log: %LOG%
echo.
pause
exit /b 0

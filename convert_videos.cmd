@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
where py >nul 2>nul
if not errorlevel 1 goto run_py
where python >nul 2>nul
if not errorlevel 1 goto run_python
echo [ERROR] Install Python 3.11 or later and add it to PATH. 1>&2
exit /b 2

:run_py
py -3 "%~dp0convert_videos.py" --input "%~dp0video" %*
exit /b %errorlevel%

:run_python
python "%~dp0convert_videos.py" --input "%~dp0video" %*
exit /b %errorlevel%

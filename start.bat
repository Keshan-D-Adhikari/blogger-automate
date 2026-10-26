@echo off
REM Penny Wise Finds dashboard - double-click to start
cd /d "%~dp0"

if not exist "ui\dist\index.html" (
  echo Building the dashboard for the first time...
  pushd ui
  call npm install --no-audit --no-fund
  call npm run build
  popd
)

echo.
echo  Penny Wise Finds dashboard: http://127.0.0.1:5050
echo  Close this window to stop the dashboard.
echo.
start "" http://127.0.0.1:5050
python -W ignore server.py
pause

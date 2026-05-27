@echo off
cd /d %~dp0
echo Starting tax-assistant server...
echo Browser will open in 3 seconds.
echo Press Ctrl+C to stop.
echo.
start /B powershell -Command "Start-Sleep 3; Start-Process 'http://127.0.0.1:4000'"
python -m uvicorn main:app --host 127.0.0.1 --port 4000 --reload
pause

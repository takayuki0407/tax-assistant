@echo off
chcp 65001 > nul
cd /d %~dp0
echo 税法アシスタントを起動しています...
echo 3秒後にブラウザが開きます
echo 終了するには Ctrl+C を押してください
echo.

:: 3秒後にブラウザを開く（バックグラウンド）
start /B powershell -Command "Start-Sleep 3; Start-Process 'http://127.0.0.1:4000'"

:: サーバー起動（フォアグラウンド）
python -m uvicorn main:app --host 127.0.0.1 --port 4000 --reload
pause

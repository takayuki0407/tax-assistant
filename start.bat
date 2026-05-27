@echo off
chcp 65001 > nul
echo 税法アシスタントを起動しています...
echo ブラウザで http://127.0.0.1:4000 を開いてください
echo 終了するには Ctrl+C を押してください
echo.
python -m uvicorn main:app --host 127.0.0.1 --port 4000 --reload
pause

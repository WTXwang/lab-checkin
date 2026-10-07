@echo off
chcp 65001 >nul
title 实验课签到系统
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3 并勾选 "Add to PATH"
    pause
    exit /b 1
)

echo 正在启动实验课签到系统...
echo 启动后，访问地址会显示在下方。
echo.
python -m uvicorn app:app --host 0.0.0.0 --port 8000

echo.
echo 系统已停止。
pause

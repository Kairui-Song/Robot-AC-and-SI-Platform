@echo off
cd /d "%~dp0"
if exist "启动LingLong自检系统.exe" (
  "启动LingLong自检系统.exe"
) else if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" portable_launcher.py
) else (
  echo 未找到可执行程序或项目虚拟环境。
  pause
)

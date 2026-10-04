@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo [ERROR] venv\Scripts\python.exe not found.
  pause
  exit /b 1
)

echo Building LingLong portable web program...
"venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "LingLongWeb.spec"
if errorlevel 1 (
  echo.
  echo Build failed.
  pause
  exit /b 1
)

if exist "dist\LingLong网页程序.zip" del /q "dist\LingLong网页程序.zip"
copy /y "给使用者的说明.txt" "dist\LingLong网页程序\给使用者的说明.txt" >nul
copy /y "左臂EtherCAT部署说明.md" "dist\LingLong网页程序\左臂EtherCAT部署说明.md" >nul
if not exist "dist\LingLong网页程序\主控部署文件" mkdir "dist\LingLong网页程序\主控部署文件"
copy /y "controller\ethercat_left_arm_test.py" "dist\LingLong网页程序\主控部署文件\ethercat_left_arm_test.py" >nul
copy /y "controller\install_left_arm_service.sh" "dist\LingLong网页程序\主控部署文件\install_left_arm_service.sh" >nul
copy /y "controller\control_benchmark.py" "dist\LingLong网页程序\主控部署文件\control_benchmark.py" >nul
copy /y "controller\je_single_motor_test_v2.cpp" "dist\LingLong网页程序\主控部署文件\je_single_motor_test_v2.cpp" >nul
copy /y "controller\install_je_single_motor_test_v2.sh" "dist\LingLong网页程序\主控部署文件\install_je_single_motor_test_v2.sh" >nul
powershell -NoProfile -Command "Compress-Archive -LiteralPath 'dist\LingLong网页程序' -DestinationPath 'dist\LingLong网页程序.zip' -CompressionLevel Optimal"

echo.
echo Build complete:
echo   dist\LingLong网页程序
echo   dist\LingLong网页程序.zip
pause

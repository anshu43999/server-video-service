@echo off
setlocal
chcp 65001 >nul

cd /d E:\aiyolo\server-video-service

set "YOLO_EXE=%CD%\.venv\Scripts\yolo.exe"
set "MODEL=%CD%\models\yolo11n.pt"
set "DATA=D:\BaiduNetdiskDownload\安全帽工装5类-yolo-clean\data.yaml"
set "OUTPUT=D:\BaiduNetdiskDownload\training-runs"

if not exist "%YOLO_EXE%" (
    echo [ERROR] YOLO virtual environment executable not found:
    echo         %YOLO_EXE%
    pause
    exit /b 1
)

if not exist "%MODEL%" (
    echo [ERROR] Base model not found:
    echo         %MODEL%
    pause
    exit /b 1
)

if not exist "%DATA%" (
    echo [ERROR] Dataset configuration not found:
    echo         %DATA%
    pause
    exit /b 1
)

if not exist "%OUTPUT%" mkdir "%OUTPUT%"

echo [INFO] Starting CPU training...
echo [INFO] Dataset: %DATA%
echo [INFO] Output:  %OUTPUT%\helmet-workwear-v1

"%YOLO_EXE%" detect train ^
    model="%MODEL%" ^
    data="%DATA%" ^
    epochs=100 ^
    imgsz=640 ^
    batch=8 ^
    device=cpu ^
    workers=0 ^
    project="%OUTPUT%" ^
    name=helmet-workwear-v1

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Training failed with exit code %EXIT_CODE%.
) else (
    echo [INFO] Training completed.
    echo [INFO] Best model: %OUTPUT%\helmet-workwear-v1\weights\best.pt
)

pause
exit /b %EXIT_CODE%

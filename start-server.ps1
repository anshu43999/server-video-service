[CmdletBinding()]
param(
    [int]$Port = 8080,
    [switch]$InstallYolo,
    [switch]$NoInstall,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

function Write-Step([string]$Message) {
    Write-Host "[server-video-service] $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host "[server-video-service] ERROR: $Message" -ForegroundColor Red
    exit 1
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    Fail "未找到 Python。请安装 Python 3.11+，并确保 python 已加入 PATH。"
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($NoInstall) {
        Fail "项目虚拟环境不存在：$venvPython。去掉 -NoInstall 后脚本会自动创建并安装依赖。"
    }
    Write-Step "创建 Python 虚拟环境"
    & $pythonCommand.Source -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "创建虚拟环境失败。" }
}

$dependencyMarker = Join-Path $projectRoot ".venv\.server-video-service-deps"
$dependenciesReady = $false
if (Test-Path -LiteralPath $dependencyMarker) {
    & $venvPython -c "import fastapi, cv2, pydantic_settings, sqlalchemy, alembic, psycopg; assert int(cv2.__version__.split('.')[0]) < 5, f'unsupported OpenCV {cv2.__version__}'" 2>$null
    $dependenciesReady = $LASTEXITCODE -eq 0
}
if (-not $dependenciesReady) {
    if ($NoInstall) {
        Fail "基础依赖尚未安装。去掉 -NoInstall 后脚本会自动安装 requirements.txt。"
    }
    Write-Step "安装基础依赖"
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "基础依赖安装失败。请检查网络或手动执行 pip install -r requirements.txt。" }
    & $venvPython -c "import cv2; assert int(cv2.__version__.split('.')[0]) < 5" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Step "修复 OpenCV 版本（YOLO 视频解码要求 4.x）"
        & $venvPython -m pip install "opencv-python>=4.10,<5"
        if ($LASTEXITCODE -ne 0) { Fail "OpenCV 4.x 安装失败。" }
    }
    New-Item -ItemType File -Force -Path $dependencyMarker | Out-Null
}

if ($InstallYolo) {
    Write-Step "安装 YOLO 依赖"
    & $venvPython -m pip install -r requirements-yolo.txt
    if ($LASTEXITCODE -ne 0) { Fail "YOLO 依赖安装失败。" }
    & $venvPython -c "import cv2; assert int(cv2.__version__.split('.')[0]) < 5, f'YOLO installed unsupported OpenCV {cv2.__version__}'"
    if ($LASTEXITCODE -ne 0) { Fail "OpenCV 必须保持 4.x；请按 requirements-yolo.txt 修复依赖版本。" }
}

if (-not (Test-Path -LiteralPath ".env") -and (Test-Path -LiteralPath ".env.example")) {
    Write-Step "未发现 .env，使用环境变量和代码默认值启动"
}

$modelPath = $env:YOLO_MODEL_PATH
if (-not $modelPath -and (Test-Path -LiteralPath ".env")) {
    $envLine = Select-String -LiteralPath ".env" -Pattern '^YOLO_MODEL_PATH=(.*)$' -SimpleMatch:$false | Select-Object -First 1
    if ($envLine) { $modelPath = $envLine.Matches[0].Groups[1].Value.Trim() }
}
if ($modelPath -and -not (Test-Path -LiteralPath $modelPath)) {
    Write-Host "[server-video-service] WARNING: YOLO_MODEL_PATH 不存在，PC 可看原画面预览，YOLO 分析尚未就绪。" -ForegroundColor Yellow
}
if (-not $modelPath) {
    Write-Host "[server-video-service] INFO: 未配置 YOLO_MODEL_PATH，PC 可看原画面预览；YOLO 分析尚未就绪。" -ForegroundColor Yellow
}

Write-Step "启动管理页面：http://localhost:$Port/admin/"
Write-Step "Swagger API：http://localhost:$Port/docs"
Write-Step "PC 同源预览及 YOLO 分析可用；不启动媒体分发进程"
Write-Step "按 Ctrl+C 停止服务"

if ($Reload) {
    & $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
} else {
    & $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port $Port
}
exit $LASTEXITCODE

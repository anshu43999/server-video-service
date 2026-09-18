param(
    [int]$Port = 8080,
    [switch]$InstallYolo,
    [switch]$NoInstall,
    [switch]$Reload,
    [switch]$WithMediaMtx,
    [string]$MediaPublicHost = "127.0.0.1",
    [string]$MediaBindAddress = "127.0.0.1",
    [int]$MediaRtspPort = 19554,
    [int]$MediaHlsPort = 18888,
    [int]$MediaWhepPort = 18889,
    [int]$MediaWebRtcUdpPort = 18189,
    [int]$MediaApiPort = 19997
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

function Assert-PortAvailable([int]$Value, [string]$Name, [switch]$Udp) {
    if ($Value -lt 1 -or $Value -gt 65535) {
        Fail "$Name 端口必须在 1 到 65535 之间。"
    }
    if ($Udp) {
        $listener = Get-NetUDPEndpoint -LocalPort $Value -ErrorAction SilentlyContinue
    } else {
        $listener = Get-NetTCPConnection -LocalPort $Value -State Listen -ErrorAction SilentlyContinue
    }
    if ($listener) {
        Fail "$Name 端口 $Value 已被占用，请指定其他端口。"
    }
}

function Stop-ManagedProcess([System.Diagnostics.Process]$Process) {
    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(3000) | Out-Null
    }
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
    Write-Host "[server-video-service] WARNING: YOLO_MODEL_PATH 不存在，开启 YOLO 时将降级输出原始画面。" -ForegroundColor Yellow
}
if (-not $modelPath) {
    Write-Host "[server-video-service] INFO: 未配置 YOLO_MODEL_PATH，当前可使用原始视频流；YOLO 分析尚未就绪。" -ForegroundColor Yellow
}

$mediaProcess = $null
$mediaConfigPath = $null
$mediaLogPath = $null
$mediaErrorLogPath = $null
$savedMediaEnvironment = @{}
$mediaEnvironmentNames = @(
    "MEDIAMTX_ENABLED",
    "MEDIAMTX_RTSP_URL",
    "MEDIAMTX_API_URL",
    "MEDIAMTX_WHEP_URL",
    "MEDIAMTX_LLHLS_URL",
    "MEDIAMTX_FFMPEG_PATH",
    "MEDIAMTX_VIDEO_ENCODER"
)

try {
    if ($WithMediaMtx) {
        if ([string]::IsNullOrWhiteSpace($MediaPublicHost) -or
            $MediaPublicHost -notmatch '^[A-Za-z0-9.-]+$' -or
            $MediaPublicHost.Contains('..')) {
            Fail "MediaPublicHost 必须是有效的 IPv4 地址或 DNS 主机名。"
        }
        $parsedBindAddress = $null
        if (-not [System.Net.IPAddress]::TryParse($MediaBindAddress, [ref]$parsedBindAddress)) {
            Fail "MediaBindAddress 必须是有效的 IP 地址。"
        }
        $allPorts = @($Port, $MediaRtspPort, $MediaHlsPort, $MediaWhepPort, $MediaWebRtcUdpPort, $MediaApiPort)
        if (($allPorts | Sort-Object -Unique).Count -ne $allPorts.Count) {
            Fail "后端与 MediaMTX 端口必须互不相同。"
        }
        Assert-PortAvailable $MediaRtspPort "MediaMTX RTSP"
        Assert-PortAvailable $MediaHlsPort "MediaMTX LL-HLS"
        Assert-PortAvailable $MediaWhepPort "MediaMTX WHEP"
        Assert-PortAvailable $MediaApiPort "MediaMTX API"
        Assert-PortAvailable $MediaWebRtcUdpPort "MediaMTX WebRTC UDP" -Udp

        $workspaceRoot = Split-Path -Parent $projectRoot
        $rtspToolRoot = Join-Path $workspaceRoot "tools\rtsp"
        $mediaMtxPath = Join-Path $rtspToolRoot "mediamtx\1.20.1\mediamtx.exe"
        $ffmpegPath = Join-Path $rtspToolRoot "ffmpeg\9.0.1\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe"
        if (-not (Test-Path -LiteralPath $mediaMtxPath)) { Fail "未找到 MediaMTX：$mediaMtxPath" }
        if (-not (Test-Path -LiteralPath $ffmpegPath)) { Fail "未找到 FFmpeg：$ffmpegPath" }

        $runtimeName = "server-video-service-mediamtx-$PID"
        $mediaConfigPath = Join-Path ([System.IO.Path]::GetTempPath()) "$runtimeName.yml"
        $mediaLogPath = Join-Path ([System.IO.Path]::GetTempPath()) "$runtimeName.log"
        $mediaErrorLogPath = Join-Path ([System.IO.Path]::GetTempPath()) "$runtimeName.error.log"
        $mediaConfig = @"
logLevel: info
logDestinations: [stdout]
api: true
apiAddress: 127.0.0.1:$MediaApiPort
metrics: false
pprof: false
playback: false
rtsp: true
rtspTransports: [tcp]
rtspAddress: 127.0.0.1:$MediaRtspPort
rtmp: false
hls: true
hlsAddress: ${MediaBindAddress}:$MediaHlsPort
hlsVariant: lowLatency
hlsSegmentCount: 7
hlsSegmentDuration: 1s
hlsPartDuration: 200ms
webrtc: true
webrtcAddress: ${MediaBindAddress}:$MediaWhepPort
webrtcLocalUDPAddress: ${MediaBindAddress}:$MediaWebRtcUdpPort
webrtcAdditionalHosts: [$MediaPublicHost]
srt: false
moq: false
paths:
  all_others: {}
"@
        [System.IO.File]::WriteAllText($mediaConfigPath, $mediaConfig, [System.Text.UTF8Encoding]::new($false))

        $mediaProcess = Start-Process `
            -WindowStyle Hidden `
            -FilePath $mediaMtxPath `
            -ArgumentList @($mediaConfigPath) `
            -RedirectStandardOutput $mediaLogPath `
            -RedirectStandardError $mediaErrorLogPath `
            -PassThru
        Start-Sleep -Seconds 1
        if ($mediaProcess.HasExited) {
            Fail "MediaMTX 启动失败，请查看日志：$mediaLogPath"
        }

        foreach ($name in $mediaEnvironmentNames) {
            $savedMediaEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, "Process")
        }
        $env:MEDIAMTX_ENABLED = "true"
        $env:MEDIAMTX_RTSP_URL = "rtsp://127.0.0.1:$MediaRtspPort"
        $env:MEDIAMTX_API_URL = "http://127.0.0.1:$MediaApiPort"
        $env:MEDIAMTX_WHEP_URL = "http://${MediaPublicHost}:$MediaWhepPort"
        $env:MEDIAMTX_LLHLS_URL = "http://${MediaPublicHost}:$MediaHlsPort"
        $env:MEDIAMTX_FFMPEG_PATH = $ffmpegPath
        $env:MEDIAMTX_VIDEO_ENCODER = "auto"

        Write-Step "MediaMTX 已启动：RTSP $MediaRtspPort / LL-HLS $MediaHlsPort / WHEP $MediaWhepPort / 对外主机 $MediaPublicHost"
    }

    Write-Step "启动管理页面：http://localhost:$Port/admin/"
    Write-Step "Swagger API：http://localhost:$Port/docs"
    Write-Step "按 Ctrl+C 停止服务"

    if ($Reload) {
        & $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
    } else {
        & $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port $Port
    }
    $serverExitCode = $LASTEXITCODE
} finally {
    Stop-ManagedProcess $mediaProcess
    foreach ($name in $mediaEnvironmentNames) {
        [System.Environment]::SetEnvironmentVariable($name, $savedMediaEnvironment[$name], "Process")
    }
    if ($mediaConfigPath) { Remove-Item -LiteralPath $mediaConfigPath -Force -ErrorAction SilentlyContinue }
    if ($WithMediaMtx) { Write-Step "MediaMTX 已停止；本次日志：$mediaLogPath" }
}
exit $serverExitCode

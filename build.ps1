# 78HAM Desktop Build Script
# Usage: .\build.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SpecFile = Join-Path $ProjectDir "78HAM.spec"
$DistDir = Join-Path $ProjectDir "dist"
$BuildDir = Join-Path $ProjectDir "build"
$AppName = "78HAM"
$Version = "2.1.0"
$ZipName = "${AppName}_v${Version}.zip"

Write-Host ""
Write-Host "  78HAM Desktop Build" -ForegroundColor Cyan
Write-Host "  Version: $Version" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "[1/5] Checking environment..." -ForegroundColor Yellow

# 自动查找 Python（优先 PATH，其次常见安装路径）
$PythonExe = $null
$PythonPaths = @(
    "python",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Python310\python.exe"
)
foreach ($p in $PythonPaths) {
    try {
        $ver = & $p --version 2>&1
        if ($ver -match "Python \d") {
            $PythonExe = $p
            $pyVer = $ver
            break
        }
    } catch {}
}
if (-not $PythonExe) {
    Write-Host "  Error: Python not found" -ForegroundColor Red
    Write-Host "  Searched: PATH, AppData\Local\Programs\Python\" -ForegroundColor Red
    exit 1
}
Write-Host "  $pyVer ($PythonExe)" -ForegroundColor Green

# Check PyInstaller
try {
    $piVer = & $PythonExe -c "import PyInstaller; print(PyInstaller.__version__)" 2>&1
    Write-Host "  PyInstaller $piVer" -ForegroundColor Green
} catch {
    Write-Host "  Error: PyInstaller not found" -ForegroundColor Red
    Write-Host "  Run: $PythonExe -m pip install pyinstaller" -ForegroundColor Red
    exit 1
}

# 2. Clean
Write-Host "[2/4] Cleaning..." -ForegroundColor Yellow
if (Test-Path $BuildDir) {
    Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue
}
$distAppDir = Join-Path $DistDir $AppName
if (Test-Path $distAppDir) {
    Remove-Item -Recurse -Force $distAppDir -ErrorAction SilentlyContinue
}
Write-Host "  Done" -ForegroundColor Green

# 3. Build
Write-Host "[3/4] Building..." -ForegroundColor Yellow
Set-Location $ProjectDir
& $PythonExe -m PyInstaller --clean $SpecFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "  Done" -ForegroundColor Green

# 4. Copy config template
Write-Host "[4/5] Copying config template..." -ForegroundColor Yellow
$configTemplate = @"
# 78HAM 配置文件
servers:
  - name: "示例服务器"
    host: ""
    port: 60050
    password: ""

device:
  callsign: "N0CALL"
  ssid: 1
  dmr_id: "123456"
  password: ""

audio:
  codec: "g711"
  sample_rate: 8000

network:
  heartbeat_interval: 2
  buffer_size: 4096

location:
  auto_report: true
  report_interval: 120
  default_lat: 0.0
  default_lng: 0.0
"@
$configPath = Join-Path $distAppDir "config.yaml"
[System.IO.File]::WriteAllText($configPath, $configTemplate, [System.Text.UTF8Encoding]::new($false))
Write-Host "  Done" -ForegroundColor Green

# 5. Package
Write-Host "[5/5] Packaging..." -ForegroundColor Yellow
Start-Sleep -Seconds 2  # 等待 PyInstaller 释放文件锁
$zipPath = Join-Path $DistDir $ZipName
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}
Set-Location $DistDir
Compress-Archive -Path $AppName -DestinationPath $ZipName -Force

$appSize = [math]::Round((Get-ChildItem $AppName -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
$zipSize = [math]::Round((Get-Item $ZipName).Length / 1MB, 1)

Write-Host ""
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "  App size : ${appSize} MB" -ForegroundColor White
Write-Host "  Zip size : ${zipSize} MB" -ForegroundColor White
Write-Host "  Output   : dist\$AppName\" -ForegroundColor White
Write-Host "  Package  : dist\$ZipName" -ForegroundColor White
Write-Host ""

Set-Location $ProjectDir

# 78HAM Client One-Click Build Script
# Usage: .\build.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SpecFile = Join-Path $ProjectDir "78HAM_Client_Preview.spec"
$ConfigFile = Join-Path $ProjectDir "config.yaml"
$DistDir = Join-Path $ProjectDir "dist"
$BuildDir = Join-Path $ProjectDir "build"
$AppName = "78HAM_Client_Preview"
$ZipName = "${AppName}_v1.4.3.zip"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  78HAM Client Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Activate conda env
Write-Host "[1/5] Activating build environment..." -ForegroundColor Yellow
conda activate nrllink_3.10
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: cannot activate conda env nrllink_3.10" -ForegroundColor Red
    exit 1
}
Write-Host "  env: nrllink_3.10 $(python --version)" -ForegroundColor Green

# 2. Clean old outputs
Write-Host "[2/5] Cleaning old build outputs..." -ForegroundColor Yellow
if (Test-Path $BuildDir) {
    Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue
}
$distAppDir = Join-Path $DistDir $AppName
if (Test-Path $distAppDir) {
    Remove-Item -Recurse -Force $distAppDir -ErrorAction SilentlyContinue
}
Write-Host "  clean done" -ForegroundColor Green

# 3. PyInstaller build
Write-Host "[3/5] Building with PyInstaller..." -ForegroundColor Yellow
Set-Location $ProjectDir
pyinstaller --clean $SpecFile
Write-Host "  build done" -ForegroundColor Green

# 4. Copy config.yaml
Write-Host "[4/5] Copying config.yaml..." -ForegroundColor Yellow
Copy-Item $ConfigFile $distAppDir -Force
Write-Host "  config.yaml copied" -ForegroundColor Green

# 5. Create zip
Write-Host "[5/5] Creating zip package..." -ForegroundColor Yellow
Set-Location $DistDir
Compress-Archive -Path $AppName -DestinationPath $ZipName -Force
$zipSize = [math]::Round((Get-Item $ZipName).Length / 1MB, 1)
$appSize = [math]::Round((Get-ChildItem $AppName -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1)

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Uncompressed : ${appSize} MB" -ForegroundColor White
Write-Host "  Zip          : ${zipSize} MB" -ForegroundColor White
Write-Host "  Output       : dist\$AppName\" -ForegroundColor White
Write-Host "               : dist\$ZipName" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan

Set-Location $ProjectDir

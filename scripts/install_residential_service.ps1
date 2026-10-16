# scripts/install_residential_service.ps1
# Installs and starts the Residential SOCKS5 Proxy as an automatic Windows Service via NSSM.

$ErrorActionPreference = "Stop"

# 1. Self-elevation to Administrator if running unprivileged
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Meminta hak Administrator untuk mendaftarkan Windows Service..." -ForegroundColor Yellow
    $scriptPath = $MyInvocation.MyCommand.Path
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" -Wait
    exit
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " KOMDIGI BOT - RESIDENTIAL SOCKS5 PROXY WINDOWS SERVICE" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 2. Determine paths
$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = (Get-Command python.exe).Source
}

# Locate nssm.exe
$nssmExe = $null
$nssmCmd = Get-Command nssm.exe -ErrorAction SilentlyContinue
if ($nssmCmd) {
    $nssmExe = $nssmCmd.Source
}
if (-not $nssmExe) {
    $wingetPkg = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "nssm.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($wingetPkg) {
        $nssmExe = $wingetPkg.FullName
    }
}

if (-not $nssmExe) {
    Write-Error "nssm.exe tidak ditemukan. Harap pastikan NSSM terpasang melalui winget install --id NSSM.NSSM."
    exit 1
}

$serviceName = "KomdigiResidentialProxy"
$displayName = "Komdigi Bot - Residential SOCKS5 Proxy"
$description = "Residential SOCKS5 Proxy Daemon for KOMDIGI Bot Hybrid Worker (Port 1080)"
$scriptTarget = Join-Path $repoRoot "start_residential_proxy.py"
$logDir = Join-Path $repoRoot "outputs\logs"
$stdoutLog = Join-Path $logDir "residential_service.log"
$stderrLog = Join-Path $logDir "residential_service_err.log"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

Write-Host "[1/5] Menghentikan service lama jika ada..." -ForegroundColor Gray
& $nssmExe stop $serviceName 2>$null | Out-Null
& $nssmExe remove $serviceName confirm 2>$null | Out-Null

Write-Host "[2/5] Mendaftarkan service baru '$serviceName'..." -ForegroundColor Gray
$appArgs = "`"$scriptTarget`" --host 0.0.0.0 --port 1080"
& $nssmExe install $serviceName $pythonExe $appArgs
& $nssmExe set $serviceName AppDirectory $repoRoot
& $nssmExe set $serviceName DisplayName $displayName
& $nssmExe set $serviceName Description $description
& $nssmExe set $serviceName Start SERVICE_AUTO_START

Write-Host "[3/5] Mengonfigurasi rotasi log dan restart otomatis..." -ForegroundColor Gray
& $nssmExe set $serviceName AppStdout $stdoutLog
& $nssmExe set $serviceName AppStderr $stderrLog
& $nssmExe set $serviceName AppRotateFiles 1
& $nssmExe set $serviceName AppRotateBytes 10485760
& $nssmExe set $serviceName AppRestartDelay 5000

Write-Host "[4/5] Menjalankan service..." -ForegroundColor Gray
& $nssmExe start $serviceName

Start-Sleep -Seconds 2

Write-Host "[5/5] Memeriksa status service..." -ForegroundColor Gray
$svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host ""
    Write-Host "[SUCCESS] Service '$serviceName' BERHASIL dipasang dan AKTIF RUNNING!" -ForegroundColor Green
    Write-Host "Status: $($svc.Status)" -ForegroundColor Green
    Write-Host "Proxy siap digunakan di: socks5://0.0.0.0:1080 (Tailscale IP: socks5://100.118.42.78:1080)" -ForegroundColor Green
    Write-Host "Log file: $stdoutLog" -ForegroundColor Gray
} else {
    Write-Host ""
    Write-Host "[WARNING] Service terpasang dengan status: $($svc.Status)" -ForegroundColor Yellow
    Write-Host "Periksa log error di: $stderrLog" -ForegroundColor Yellow
}

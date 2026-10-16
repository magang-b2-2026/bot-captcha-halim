# scripts/uninstall_residential_service.ps1
# Stops and removes the Residential SOCKS5 Proxy Windows Service.

$ErrorActionPreference = "Stop"

# Self-elevation to Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Meminta hak Administrator untuk mencabut Windows Service..." -ForegroundColor Yellow
    $scriptPath = $MyInvocation.MyCommand.Path
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" -Wait
    exit
}

$serviceName = "KomdigiResidentialProxy"

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

if ($nssmExe) {
    & $nssmExe stop $serviceName 2>$null | Out-Null
    & $nssmExe remove $serviceName confirm 2>$null | Out-Null
} else {
    Stop-Service -Name $serviceName -ErrorAction SilentlyContinue
    sc.exe delete $serviceName
}

Write-Host "[SUCCESS] Service '$serviceName' berhasil dicabut." -ForegroundColor Green

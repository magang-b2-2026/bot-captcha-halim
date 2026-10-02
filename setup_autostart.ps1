# setup_autostart.ps1
# Jalankan sebagai Administrator untuk daftarkan auto-start
# Klik kanan > "Run as Administrator"

$ProjectDir = "C:\Coding\Komdigi"
$TaskName   = "KomdigiBot-Service"

$action  = New-ScheduledTaskAction `
    -Execute "$ProjectDir\run_service.bat" `
    -WorkingDirectory $ProjectDir

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -StartWhenAvailable $true

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -RunLevel Highest `
    -LogonType Interactive

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force `
    -Description "komdigi-bot captcha solving service 24/7"

Write-Host "Auto-start registered! Service akan jalan otomatis saat Windows boot." -ForegroundColor Green
Write-Host "Jalankan sekarang dengan: Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Cyan

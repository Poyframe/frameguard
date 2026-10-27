<#
.SYNOPSIS
    Prueba rápida del Frameguard.exe COMPILADO (dist\Frameguard), con datos aislados.
    Arranca el motor, carga un .blend de prueba y abre la ventana 3 veces (normal, menú hamburguesa y panel
    de detalles), cambiando el tamaño. Falla si la ventana no se conecta al motor o si ui.log tiene errores.
.PARAMETER Blend
    .blend de prueba (que no sea de producción).
#>
param([Parameter(Mandatory)][string]$Blend, [string]$OutDir = "$env:TEMP\frameguard_smoke")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$exe = Join-Path $root "dist\Frameguard\Frameguard.exe"
$port = 47877
New-Item -ItemType Directory -Force $OutDir | Out-Null
$home_ = Join-Path $OutDir ("home_" + (Get-Date -Format "HHmmss"))
$env:FRAMEGUARD_HOME = $home_
$env:FRAMEGUARD_DRY_POWER = "1"
$env:FRAMEGUARD_GITHUB_API = "http://127.0.0.1:9/sin-red"  # nunca el GitHub real
$engine = [Diagnostics.Process]::Start($exe, "--engine --port $port")
$ok = $true
try {
    for ($i = 0; $i -lt 50; $i++) { try { Invoke-RestMethod "http://127.0.0.1:$port/api/ping" | Out-Null; break } catch { Start-Sleep -Milliseconds 300 } }
    $body = @{ cmd = "add"; paths = @($Blend) } | ConvertTo-Json
    Invoke-RestMethod "http://127.0.0.1:$port/api/cmd" -Method Post -Body $body -ContentType "application/json" | Out-Null
    $env:FRAMEGUARD_SCREENSHOT_DELAY = "5000"
    foreach ($case in @("normal", "menu", "panel")) {
        $env:FRAMEGUARD_SCREENSHOT = Join-Path $OutDir "smoke_$case.png"
        $env:FRAMEGUARD_SCREENSHOT_DRAWER = $(if ($case -eq "menu") { "1" } else { "" })
        $env:FRAMEGUARD_SCREENSHOT_POPUP = $(if ($case -eq "panel") { "1" } else { "" })
        $ui = [Diagnostics.Process]::Start($exe, "--port $port")
        if (-not $ui.WaitForExit(30000)) { $ui.Kill(); $ok = $false; Write-Host "FALLO [$case]: la ventana no terminó" }
        $res = Get-Content "$($env:FRAMEGUARD_SCREENSHOT).json" -Raw | ConvertFrom-Json
        $good = $res.connected -and $res.rows -ge 1 -and ($case -ne "menu" -or $res.drawer) -and ($case -ne "panel" -or $res.popup)
        Write-Host ("{0} [{1}] conectada={2} filas={3} menú={4} panel={5} código={6}" -f $(if ($good) { "OK   " } else { "FALLO" }), $case, $res.connected, $res.rows, $res.drawer, $res.popup, $ui.ExitCode)
        if (-not $good -or $ui.ExitCode -ne 0) { $ok = $false }
    }
    # El nivel ERROR exacto (como tools\pruebas\comun.py): una línea INFO puede citar un «WinError» de Windows
    $errs = Select-String -Path (Join-Path $home_ "ui.log") -Pattern " ERROR |Traceback" -CaseSensitive -ErrorAction SilentlyContinue
    if ($errs) { $ok = $false; Write-Host "FALLO: errores en ui.log:"; $errs | ForEach-Object { "   " + $_.Line } } else { Write-Host "OK    ui.log sin errores" }
} finally {
    try { Invoke-RestMethod "http://127.0.0.1:$port/api/cmd" -Method Post -Body '{"cmd":"quit"}' -ContentType "application/json" | Out-Null } catch {}
}
if ($ok) { Write-Host "PRUEBA SUPERADA" -ForegroundColor Green; exit 0 } else { Write-Host "PRUEBA FALLIDA" -ForegroundColor Red; exit 1 }

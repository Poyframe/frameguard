<#
.SYNOPSIS
    Compila Frameguard: icono -> Frameguard.exe (PyInstaller) -> instalador (Inno Setup).
.DESCRIPTION
    Resultado: dist\installer\Frameguard-Setup-<versión>.exe
    La versión se toma de frameguard\__init__.py (__version__). Para publicar una actualización:
      1. Subir __version__ (p. ej. 0.1.0 -> 0.2.0).
      2. Ejecutar este script.
      3. Copiar el instalador (y opcionalmente Frameguard-<versión>-novedades.txt) a la carpeta de
         actualizaciones configurada en Ajustes. Los PC que la vean mostrarán el aviso.
.PARAMETER SkipPyInstaller
    Reutiliza dist\Frameguard sin recompilar (solo rehace el instalador).
#>
param([switch]$SkipPyInstaller)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$ver = (Select-String -Path (Join-Path $root "frameguard\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Frameguard $ver" -ForegroundColor Cyan

& $py (Join-Path $root "tools\check_names.py")
if ($LASTEXITCODE) { throw "Hay nombres sin definir en el código: corrígelos antes de compilar" }
& $py (Join-Path $root "tools\check_i18n.py")
if ($LASTEXITCODE) { throw "Faltan traducciones al inglés (tools\check_i18n.py): complétalas antes de compilar" }
& $py (Join-Path $root "tools\make_icon.py")
if (-not $SkipPyInstaller) {
    Push-Location $root
    try { & $py -m PyInstaller --noconfirm --clean frameguard.spec; if ($LASTEXITCODE) { throw "PyInstaller falló" } }
    finally { Pop-Location }
}
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "No se encontró Inno Setup 6 (ISCC.exe)" }
& $iscc "/DAppVersion=$ver" (Join-Path $root "installer\frameguard.iss")
if ($LASTEXITCODE) { throw "Inno Setup falló" }
$out = Join-Path $root "dist\installer\Frameguard-Setup-$ver.exe"
Write-Host ("Instalador: {0}  ({1:N1} MB)" -f $out, ((Get-Item $out).Length / 1MB)) -ForegroundColor Green

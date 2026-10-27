<#
.SYNOPSIS
    Compila Frameguard: icono -> Frameguard.exe (PyInstaller) -> instalador (Inno Setup).
.DESCRIPTION
    Resultado: dist\installer\Frameguard-Setup-<versión>.exe
    La versión se toma de frameguard\__init__.py (__version__). Para publicar una actualización:
      1. Subir __version__ (p. ej. 0.1.0 -> 0.2.0).
      2. Ejecutar este script.
      3. Crear la release v<versión> en GitHub con el instalador adjunto (notas en inglés, «---», en español):
         todas las Frameguard 0.2.0 o posteriores con internet mostrarán el aviso.
      4. Opcional: copiar el instalador (y Frameguard-<versión>-novedades.txt) a la carpeta de actualizaciones
         configurada en Ajustes. Los PC que la vean mostrarán el aviso (la carpeta manda si tiene esa versión).
.PARAMETER SkipPyInstaller
    Reutiliza dist\Frameguard sin recompilar (solo rehace el instalador).
.PARAMETER SinGitHub
    Edición interna para los PC de un estudio: el .exe se compila SIN el módulo de GitHub (no tiene ningún código
    que se conecte a GitHub) y solo se actualiza desde la carpeta de la red. El instalador sale en
    dist\installer-interna\ (mismo nombre de archivo, para que la carpeta de actualizaciones lo reconozca).
#>
param([switch]$SkipPyInstaller, [switch]$SinGitHub)
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
if ($SinGitHub) { Write-Host "Edición interna: sin GitHub" -ForegroundColor Yellow }
if (-not $SkipPyInstaller) {
    Push-Location $root
    if ($SinGitHub) { $env:FRAMEGUARD_SIN_GITHUB_BUILD = "1" } else { Remove-Item Env:FRAMEGUARD_SIN_GITHUB_BUILD -ErrorAction SilentlyContinue }
    try { & $py -m PyInstaller --noconfirm --clean frameguard.spec; if ($LASTEXITCODE) { throw "PyInstaller falló" } }
    finally { Pop-Location; Remove-Item Env:FRAMEGUARD_SIN_GITHUB_BUILD -ErrorAction SilentlyContinue }
}
# Comprobación: el módulo de GitHub está en la edición pública y NO está en la interna
$listing = & (Join-Path $root ".venv\Scripts\pyi-archive_viewer.exe") --list --recursive (Join-Path $root "dist\Frameguard\Frameguard.exe") 2>&1 | Out-String
$hasGitHub = $listing -match "frameguard\.github_updates"
if ($SinGitHub -and $hasGitHub) { throw "La edición interna contiene el módulo de GitHub: no se publica" }
if (-not $SinGitHub -and -not $hasGitHub) { throw "La edición pública no contiene el módulo de GitHub" }
Write-Host ("Módulo de GitHub en el .exe: {0}" -f $(if ($hasGitHub) { "sí" } else { "no" }))
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "No se encontró Inno Setup 6 (ISCC.exe)" }
$outDir = Join-Path $root $(if ($SinGitHub) { "dist\installer-interna" } else { "dist\installer" })
& $iscc "/DAppVersion=$ver" "/O$outDir" (Join-Path $root "installer\frameguard.iss")
if ($LASTEXITCODE) { throw "Inno Setup falló" }
$out = Join-Path $outDir "Frameguard-Setup-$ver.exe"
Write-Host ("Instalador: {0}  ({1:N1} MB)" -f $out, ((Get-Item $out).Length / 1MB)) -ForegroundColor Green

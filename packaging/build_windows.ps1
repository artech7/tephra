# Build Tephra.exe and an installer. Run on Windows in PowerShell.
#
#   .\packaging\build_windows.ps1
#   $env:SIGN_PFX="cert.pfx"; $env:SIGN_PASS="..."; .\packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$Version = if ($env:VERSION) { $env:VERSION } else { "1.0.0" }

Write-Host "==> deps"
# A venv, not the system python -- a disposable build environment, kept
# deliberately separate from run.py's own .venv\ (which doesn't carry
# PyInstaller and shouldn't).
$Venv = Join-Path $PWD ".venv-build"
if (-not (Test-Path $Venv)) { python -m venv $Venv }
$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install -q --upgrade pip
& $Py -m pip install -q -r requirements-desktop.txt

Write-Host "==> freeze"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $Py -m PyInstaller tephra.spec --noconfirm --log-level WARN
if (-not (Test-Path "dist\Tephra\Tephra.exe")) { throw "freeze produced no exe" }

if ($env:SIGN_PFX) {
  Write-Host "==> sign binaries"
  # Sign before packaging, or the installer bundles unsigned executables.
  $st = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe |
        Where-Object { $_.FullName -match 'x64' } | Select-Object -First 1
  & $st.FullName sign /f $env:SIGN_PFX /p $env:SIGN_PASS `
      /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "dist\Tephra\Tephra.exe"
} else {
  Write-Host "==> skipping signing (SIGN_PFX unset)"
  Write-Host "    SmartScreen will warn on other machines until this build"
  Write-Host "    earns reputation or you sign it. Users click More info > Run anyway."
}

Write-Host "==> installer"
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 not found. winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$Version" "packaging\tephra.iss"

if ($env:SIGN_PFX) {
  $st = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe |
        Where-Object { $_.FullName -match 'x64' } | Select-Object -First 1
  & $st.FullName sign /f $env:SIGN_PFX /p $env:SIGN_PASS `
      /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
      "dist\Tephra-$Version-windows-x64-setup.exe"
}

Write-Host "==> done"
Get-ChildItem dist\*.exe | Select-Object Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}}

# Builds the installer:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
#   1. the program as a folder with its .exe   (PyInstaller -> dist\Stage Display Controller)
#   2. one installer .exe                       (Inno Setup  -> dist\installer\StageDisplayController-Setup-<version>.exe)
# Needs: pip install pyinstaller, and Inno Setup 6 (winget install JRSoftware.InnoSetup).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# the version, from config.py
$version = (Select-String -Path "config.py" -Pattern '^VERSION = "([0-9.]+)"').Matches[0].Groups[1].Value
$parts = ($version.Split(".") + @("0", "0", "0"))[0..3] -join ", "
$info = Get-Content "installer\version_info.txt" -Raw
$info = $info -replace "filevers=\([0-9, ]+\)", "filevers=($parts)" -replace "prodvers=\([0-9, ]+\)", "prodvers=($parts)"
$info = $info -replace "'FileVersion', '[0-9.]+'", "'FileVersion', '$version'" -replace "'ProductVersion', '[0-9.]+'", "'ProductVersion', '$version'"
[IO.File]::WriteAllText("$root\installer\version_info.txt", $info, (New-Object Text.UTF8Encoding $false))
Write-Host "Stage Display Controller $version"

# from here on the tools write their progress to stderr: with "Stop", Windows PowerShell
# would take that for a failure once the output is redirected - their exit codes say instead
$ErrorActionPreference = "Continue"

# 1. the program
python -m PyInstaller --noconfirm --clean --distpath "$root\dist" --workpath "$root\build" "installer\stage_display.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# 1b. the built program checks itself (its own settings and files, no stage window, no sound)
$report = "$root\build\selftest.json"
Remove-Item $report -ErrorAction SilentlyContinue
$test = Start-Process -FilePath "$root\dist\Stage Display Controller\Stage Display Controller.exe" `
    -ArgumentList "--selftest", "`"$report`"" -PassThru -Wait
$result = Get-Content $report -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($c in $result.checks) { Write-Host ("  {0}  {1}  {2}" -f $(if ($c.ok) { "ok  " } else { "FAIL" }), $c.check, $c.detail) }
if (-not $result.ok) { throw "The built program failed its self-test (exit $($test.ExitCode)) - no installer made." }

# 2. the installer
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 is not installed (winget install JRSoftware.InnoSetup)" }
& $iscc "/DAppVersion=$version" "installer\StageDisplay.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem "$root\dist\installer" | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB) } }

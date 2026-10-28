# Publishes a new version - every installed copy then finds it and updates itself:
#   powershell -ExecutionPolicy Bypass -File installer\release.ps1
# Before: VERSION in config.py raised, a "## <version> — <date> · <title>" section at the top
# of CHANGELOG.md, everything committed on main. It builds the installer (build.ps1: the
# self-test must pass), tags the version, pushes, and makes the GitHub release with the
# installer and the changelog's words. Needs: gh (winget install GitHub.cli), signed in.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (Select-String -Path "config.py" -Pattern '^VERSION = "([0-9.]+)"').Matches[0].Groups[1].Value
$tag = "v$version"
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { throw "gh is not installed (winget install GitHub.cli), or not on PATH" }
if (git status --porcelain) { throw "Commit everything first - the release is made from what is committed." }
if ((git branch --show-current) -ne "main") { throw "Releases are made from main." }
if (git tag --list $tag) { throw "$tag exists already - raise VERSION in config.py." }

# the changelog's section for this version: its title, and its words for the release
$log = Get-Content "CHANGELOG.md" -Encoding utf8
$start = ($log | Select-String -Pattern "^## $([regex]::Escape($version)) ").LineNumber
if (-not $start) { throw "CHANGELOG.md has no '## $version ...' section." }
$end = ($log[$start..($log.Count - 1)] | Select-String -Pattern "^## " | Select-Object -First 1).LineNumber
$body = if ($end) { $log[$start..($start + $end - 2)] } else { $log[$start..($log.Count - 1)] }
$title = ($log[$start - 1] -split "·", 2)[-1].Trim()
$notes = Join-Path $env:TEMP "sdc-release-$version.md"
$text = (($body -join "`n").Trim() + "`n`n## Install`n`nDownload **StageDisplayController-Setup-$version.exe** below and run it " +
         "(Windows 10 / 11, 64-bit, no administrator needed). An installed copy finds this version by itself " +
         "(*Settings → Updates*) and puts it in when the program is closed. Windows may say *`"Windows protected your PC`"* " +
         "(the installer is not code-signed): choose **More info → Run anyway**.`n")
[IO.File]::WriteAllText($notes, $text, (New-Object Text.UTF8Encoding $false))

# the installer (it stops here if the built program fails its self-test)
& "$PSScriptRoot\build.ps1"
$setup = "$root\dist\installer\StageDisplayController-Setup-$version.exe"
if (-not (Test-Path $setup)) { throw "No installer: $setup" }

git tag -a $tag -m "Stage Display Controller $version"
git push origin main $tag
if ($LASTEXITCODE -ne 0) { throw "git push failed" }
& $gh release create $tag $setup --title "Stage Display Controller $version — $title" --notes-file $notes --latest
if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }
Write-Host "Published $tag - installed copies find it within six hours, or at once with Settings → Updates → Check now."

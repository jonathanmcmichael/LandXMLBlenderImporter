# Rebuilds the LandXML TIN Importer extension and installs/enables it in
# Blender. Checks the standard blender.org install first, then the Microsoft
# Store execution alias.
#
# Usage (from repo root or anywhere): pwsh scripts/install_extension.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$blenderCandidates = @(
    "$env:ProgramFiles\Blender Foundation\Blender 5.2\blender.exe",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\blender-launcher.exe"
)
$blenderExecutable = $blenderCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $blenderExecutable) {
    throw "Blender was not found in the standard website or Microsoft Store locations. Add its executable path to `$blenderCandidates."
}

Get-ChildItem "$repoRoot\landxml_tin_importer-*.zip" -ErrorAction SilentlyContinue | Remove-Item -Force

Push-Location $repoRoot
try {
    Write-Host "Validating extension..."
    & $blenderExecutable --command extension validate landxml_importer

    Write-Host "Building extension..."
    & $blenderExecutable --command extension build --source-dir landxml_importer
    # The Microsoft Store alias may return control before Blender finishes.
    Start-Sleep -Seconds 3

    $zip = Get-ChildItem "$repoRoot\landxml_tin_importer-*.zip" -ErrorAction SilentlyContinue
    if (-not $zip) {
        throw "Build did not produce a landxml_tin_importer-*.zip."
    }

    Write-Host "Installing and enabling in Blender..."
    & $blenderExecutable -b --python "$PSScriptRoot\install_extension.py"
    Start-Sleep -Seconds 3

    Write-Host "Done. Restart Blender (or disable/re-enable the extension in Preferences) to pick up the change."
} finally {
    Pop-Location
}

# Fetches wheels, rebuilds the LandXML TIN Importer extension, and installs/enables it in
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

function Invoke-Blender {
    & $blenderExecutable @args
    if ($LASTEXITCODE) {
        throw "Blender exited with code $LASTEXITCODE (arguments: $args)."
    }
}

Push-Location $repoRoot
try {
    Write-Host "Fetching wheels..."
    Invoke-Blender -b --factory-startup --python-exit-code 1 --python "$PSScriptRoot\fetch_wheels.py"

    Write-Host "Validating extension..."
    Invoke-Blender --command extension validate landxml_importer

    Write-Host "Building extension..."
    Invoke-Blender --command extension build --source-dir landxml_importer --split-platforms
    # The Microsoft Store alias may return control before Blender finishes.
    Start-Sleep -Seconds 3

    $zip = Get-ChildItem "$repoRoot\landxml_tin_importer-*.zip" -ErrorAction SilentlyContinue
    if (-not $zip) {
        throw "Build did not produce any landxml_tin_importer-*.zip files."
    }

    Write-Host "Installing and enabling in Blender..."
    Invoke-Blender -b --python-exit-code 1 --python "$PSScriptRoot\install_extension.py"
    Start-Sleep -Seconds 3

    Write-Host "Done. Restart Blender (or disable/re-enable the extension in Preferences) to pick up the change."
} finally {
    Pop-Location
}

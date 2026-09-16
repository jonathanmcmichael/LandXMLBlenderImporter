# Rebuilds the LandXML TIN Importer extension and installs/enables it in
# Blender. Assumes the Microsoft Store install of Blender (the standard
# blender.exe path is ACL-protected and can't be run directly; the Store
# execution alias is the supported entry point). If Blender is installed
# a different way, change $blenderAlias below.
#
# Usage (from repo root or anywhere): pwsh scripts/install_extension.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$blenderAlias = "$env:LOCALAPPDATA\Microsoft\WindowsApps\blender-launcher.exe"

if (-not (Test-Path $blenderAlias)) {
    throw "Blender launcher alias not found at $blenderAlias -- edit `$blenderAlias in this script if Blender is installed elsewhere."
}

Get-ChildItem "$repoRoot\landxml_tin_importer-*.zip" -ErrorAction SilentlyContinue | Remove-Item -Force

Push-Location $repoRoot
try {
    Write-Host "Building extension..."
    & $blenderAlias --command extension build --source-dir landxml_importer
    # The Microsoft Store execution alias returns control before the actual
    # Blender process finishes, so give it a moment before checking output.
    Start-Sleep -Seconds 3

    $zip = Get-ChildItem "$repoRoot\landxml_tin_importer-*.zip" -ErrorAction SilentlyContinue
    if (-not $zip) {
        throw "Build did not produce a landxml_tin_importer-*.zip -- run 'blender --command extension validate --source-dir landxml_importer' to see why."
    }

    Write-Host "Installing and enabling in Blender..."
    & $blenderAlias -b --python "$PSScriptRoot\install_extension.py"
    Start-Sleep -Seconds 3

    Write-Host "Done. Restart Blender (or disable/re-enable the extension in Preferences) to pick up the change."
} finally {
    Pop-Location
}

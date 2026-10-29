# Links the plugin package into the QGIS 4 default profile (directory junction).
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repo "geophysics_workbench"
$pluginsDir = Join-Path $env:APPDATA "QGIS\QGIS4\profiles\default\python\plugins"
$link = Join-Path $pluginsDir "geophysics_workbench"

New-Item -ItemType Directory -Force -Path $pluginsDir | Out-Null
if (Test-Path $link) {
    $item = Get-Item $link -Force
    if ($item.LinkType -eq "Junction") {
        Write-Host "Junction already exists: $link"
        exit 0
    }
    throw "$link exists and is not a junction; remove it manually."
}
New-Item -ItemType Junction -Path $link -Target $source | Out-Null
Write-Host "Created junction $link -> $source"

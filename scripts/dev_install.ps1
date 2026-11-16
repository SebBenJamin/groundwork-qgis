# Links the plugin package into the QGIS 4 default profile (directory junction).
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repo "groundwork_geophysics"
$pluginsDir = Join-Path $env:APPDATA "QGIS\QGIS4\profiles\default\python\plugins"
$link = Join-Path $pluginsDir "groundwork_geophysics"

New-Item -ItemType Directory -Force -Path $pluginsDir | Out-Null
if (Get-Item $link -Force -ErrorAction SilentlyContinue) {
    $item = Get-Item $link -Force
    if ($item.LinkType -eq "Junction") {
        if ($item.Target -contains $source -and (Test-Path $source)) {
            Write-Host "Junction already exists: $link"
            exit 0
        }
        Write-Host "Replacing stale junction (was -> $($item.Target))"
        (Get-Item $link -Force).Delete()
    } else {
        throw "$link exists and is not a junction; remove it manually."
    }
}
New-Item -ItemType Junction -Path $link -Target $source | Out-Null
Write-Host "Created junction $link -> $source"

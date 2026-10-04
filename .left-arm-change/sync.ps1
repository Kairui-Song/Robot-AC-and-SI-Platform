$ErrorActionPreference = 'Stop'
$stageRoot = 'C:\Users\Administrator\Desktop\linglong_1025_2'
$actualRoot = 'D:\Desktop\linglong_1025_2'
$manifest = Get-Content -LiteralPath (Join-Path $stageRoot '.left-arm-change\manifest.json') -Raw | ConvertFrom-Json
# Verify every original before any mutation, avoiding overwriting intervening work.
foreach ($entry in $manifest) {
    $target = [IO.Path]::GetFullPath((Join-Path $actualRoot $entry.path))
    if (-not $target.StartsWith($actualRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Target outside project' }
    $source = Join-Path $stageRoot $entry.path
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $entry.after) { throw "Staging changed: $($entry.path)" }
    $current = if (Test-Path -LiteralPath $target) { (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash } else { $null }
    if ($current -ne $entry.before) { throw "Original changed since review: $($entry.path)" }
}
foreach ($entry in $manifest) {
    $target = Join-Path $actualRoot $entry.path
    if (Test-Path -LiteralPath $target) {
        $backup = Join-Path $stageRoot ('.left-arm-change\before\' + $entry.path)
        New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
        Copy-Item -LiteralPath $target -Destination $backup
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $stageRoot $entry.path) -Destination $target
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry.after) { throw "Copy verification failed: $($entry.path)" }
}
Write-Output "Synced and hash-verified $($manifest.Count) files to $actualRoot; originals backed up in the C-drive workspace."

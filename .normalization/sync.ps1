$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\Administrator\Desktop\linglong_1025_2'
$stage = Join-Path $workspace '.normalization\project'
$actual = 'D:\Desktop\linglong_1025_2'
$entries = Get-Content -LiteralPath (Join-Path $workspace '.normalization\manifest.json') -Raw | ConvertFrom-Json
foreach ($entry in $entries) {
    $target = [IO.Path]::GetFullPath((Join-Path $actual $entry.path))
    if (-not $target.StartsWith($actual + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid target' }
    $before = if (Test-Path -LiteralPath $target) { (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash } else { $null }
    if ($before -ne $entry.before) { throw "Original changed: $($entry.path)" }
    if ((Get-FileHash -LiteralPath (Join-Path $stage $entry.path) -Algorithm SHA256).Hash -ne $entry.after) { throw 'Staging changed' }
}
foreach ($entry in $entries) {
    $target = Join-Path $actual $entry.path
    if (Test-Path -LiteralPath $target) {
        $backup = Join-Path $workspace ('.normalization\before\' + $entry.path)
        New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
        Copy-Item -LiteralPath $target -Destination $backup
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $stage $entry.path) -Destination $target
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry.after) { throw 'Copy verification failed' }
}
Write-Output "Updated $($entries.Count) documentation/template files in $actual. No control source or runtime configuration changed."

$ErrorActionPreference = 'Stop'
$stageRoot = 'C:\Users\Administrator\Desktop\linglong_1025_2\.multi-joint'
$projectRoot = 'D:\Desktop\linglong_1025_2'
$entries = Get-Content -LiteralPath "$stageRoot\manifest.json" -Raw | ConvertFrom-Json
foreach ($entry in $entries) {
    $target = [IO.Path]::GetFullPath((Join-Path $projectRoot $entry.relative))
    if (-not $target.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Target escapes project' }
    if (Test-Path -LiteralPath $target) {
        if ((Get-FileHash -LiteralPath $target).Hash -ne $entry.before) { throw "Concurrent change: $target" }
    } elseif ($null -ne $entry.before) { throw "Missing original: $target" }
    if ((Get-FileHash -LiteralPath (Join-Path "$stageRoot\project" $entry.relative)).Hash -ne $entry.after) { throw 'Stage hash changed' }
}
foreach ($entry in $entries) {
    $target = Join-Path $projectRoot $entry.relative
    if (Test-Path -LiteralPath $target) {
        $backup = Join-Path "$stageRoot\before" $entry.relative
        New-Item -ItemType Directory -Force -Path (Split-Path $backup) | Out-Null
        Copy-Item -LiteralPath $target -Destination $backup
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Copy-Item -LiteralPath (Join-Path "$stageRoot\project" $entry.relative) -Destination $target
    if ((Get-FileHash -LiteralPath $target).Hash -ne $entry.after) { throw "Hash mismatch: $target" }
}
Write-Output "Synced and hash-verified $($entries.Count) files; originals backed up in $stageRoot\before"

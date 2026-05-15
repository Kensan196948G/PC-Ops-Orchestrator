<#
.SYNOPSIS
    Regenerate agent/manifest.json with current SHA-256 hashes (Issue #188 part 2).
.DESCRIPTION
    Walks agent/ for the entry script, collectors, and the scheduled-task
    registrar, computes SHA-256 of each, and writes agent/manifest.json. Run
    this whenever agent/*.ps1 changes. CI may invoke it before signing the
    release artifact; locally, developers regenerate after editing.
.NOTES
    The manifest is intentionally checked into git so production installs ship
    with a known-good baseline. Forgetting to regenerate causes a self-check
    failure that blocks Agent startup — that is the intended fail-closed signal.
#>

[CmdletBinding()]
param(
    [string]$AgentDir = (Join-Path $PSScriptRoot ".." | ForEach-Object { Join-Path $_ "agent" })
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $AgentDir)) {
    throw "Agent directory not found: $AgentDir"
}

$AgentDir = (Resolve-Path $AgentDir).Path

# Files included in the integrity manifest. Order is preserved in JSON output
# for deterministic diffs.
$tracked = @(
    "PCOpsAgent.ps1",
    "Register-AgentTask.ps1",
    "collectors/Get-HardwareInfo.ps1",
    "collectors/Get-SoftwareInfo.ps1",
    "collectors/Get-NetworkInfo.ps1"
)

$files = [ordered]@{}
foreach ($rel in $tracked) {
    $abs = Join-Path $AgentDir $rel
    if (-not (Test-Path $abs)) {
        throw "Tracked file missing: $rel (looked for $abs)"
    }
    $hash = (Get-FileHash -Path $abs -Algorithm SHA256).Hash.ToLowerInvariant()
    $files[$rel] = $hash
}

$manifest = [ordered]@{
    "_comment" = "SHA-256 manifest for Agent self-check (Issue #188 part 2). Regenerate via tools/Update-AgentManifest.ps1 when agent files change."
    "version"  = "1.0.0"
    "algorithm" = "SHA-256"
    "files"    = $files
}

$out = Join-Path $AgentDir "manifest.json"
$json = $manifest | ConvertTo-Json -Depth 5
# ConvertTo-Json omits the trailing newline; add one for clean diffs.
Set-Content -Path $out -Value ($json + "`n") -Encoding UTF8 -NoNewline

Write-Host "manifest.json updated:"
foreach ($k in $files.Keys) {
    Write-Host ("  {0,-44} {1}" -f $k, $files[$k])
}

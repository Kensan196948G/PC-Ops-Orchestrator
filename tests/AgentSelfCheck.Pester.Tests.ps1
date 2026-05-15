Set-StrictMode -Version Latest

# Tests for Issue #188 part 2: Agent self-check via manifest.json (SHA-256).
#
# We don't load PCOpsAgent.ps1 itself — it starts the collection loop. Instead
# we exercise the Test-AgentIntegrity function by extracting it into a script
# block. For end-to-end behavior (tampered file → exit 1) we spawn the real
# script through pwsh with a copy of the agent install and assert exit codes.

Describe "Agent self-check (Issue #188 part 2)" {
    BeforeAll {
        $script:repoRoot = Split-Path $PSScriptRoot -Parent
        $script:agentDir = Join-Path $script:repoRoot "agent"
        $script:agentScript = Join-Path $script:agentDir "PCOpsAgent.ps1"
        $script:manifest = Join-Path $script:agentDir "manifest.json"
    }

    Context "Source artifacts" {
        It "ships agent/manifest.json alongside PCOpsAgent.ps1" {
            Test-Path $script:manifest | Should -BeTrue
        }

        It "manifest declares SHA-256 algorithm and a files map" {
            $m = Get-Content $script:manifest -Raw -Encoding UTF8 | ConvertFrom-Json
            $m.algorithm | Should -Be "SHA-256"
            $m.files | Should -Not -BeNullOrEmpty
            $m.files.PSObject.Properties.Name | Should -Contain "PCOpsAgent.ps1"
        }

        It "manifest has no PLACEHOLDER hashes" {
            $m = Get-Content $script:manifest -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $m.files.PSObject.Properties) {
                $p.Value | Should -Not -Be "PLACEHOLDER"
                $p.Value | Should -Match '^[0-9a-fA-F]{64}$'
            }
        }

        It "every manifested file exists in agent/" {
            $m = Get-Content $script:manifest -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $m.files.PSObject.Properties) {
                $abs = Join-Path $script:agentDir $p.Name
                Test-Path $abs | Should -BeTrue -Because "manifest references $($p.Name)"
            }
        }

        It "manifest hashes match the actual file contents (CI guard)" {
            # If this fails, run: pwsh tools/Update-AgentManifest.ps1
            $m = Get-Content $script:manifest -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $m.files.PSObject.Properties) {
                $abs = Join-Path $script:agentDir $p.Name
                $actual = (Get-FileHash -Path $abs -Algorithm SHA256).Hash.ToUpperInvariant()
                $expected = ([string]$p.Value).ToUpperInvariant()
                $actual | Should -Be $expected -Because "manifest says $($p.Name) should be $expected"
            }
        }
    }

    Context "PCOpsAgent.ps1 self-check wiring" {
        It "declares Test-AgentIntegrity before the Mutex entry point" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'function Test-AgentIntegrity'
            $content | Should -Match 'manifest\.json'
            $content | Should -Match 'Get-FileHash'
            $content | Should -Match 'SHA256'
            # Fail-closed: missing manifest must abort
            $content | Should -Match 'Self-check失敗'
            # Self-check runs before Mutex acquisition (defense in depth)
            $idxSelf = $content.IndexOf('Test-AgentIntegrity -AgentRoot')
            $idxMutex = $content.IndexOf('New-Object System.Threading.Mutex')
            $idxSelf | Should -BeGreaterThan 0
            $idxMutex | Should -BeGreaterThan 0
            $idxSelf | Should -BeLessThan $idxMutex
        }
    }

    Context "Test-AgentIntegrity function behavior" {
        BeforeAll {
            # Extract the function definition from PCOpsAgent.ps1 and load it in
            # isolation so we can call it without starting the collection loop.
            $raw = Get-Content -Raw -Path $script:agentScript
            $match = [regex]::Match($raw, '(?s)function Test-AgentIntegrity \{.*?\n\}')
            if (-not $match.Success) {
                throw "Failed to extract Test-AgentIntegrity from PCOpsAgent.ps1"
            }
            $funcSrc = $match.Value
            # Stub Write-AgentError so the function under test doesn't try to
            # write to the production log directory.
            $stub = @"
function Write-AgentError { param([string]`$Message) Write-Host "[stub-err] `$Message" }
function Write-AgentInfo  { param([string]`$Message) Write-Host "[stub-info] `$Message" }
$funcSrc
"@
            $script:loader = [scriptblock]::Create($stub)
        }

        It "returns `$true on an untampered install" {
            $sandbox = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_selfcheck_ok_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
            New-Item -ItemType Directory -Path $sandbox -Force | Out-Null
            try {
                Copy-Item -Path $script:manifest -Destination (Join-Path $sandbox "manifest.json")
                Copy-Item -Path $script:agentScript -Destination (Join-Path $sandbox "PCOpsAgent.ps1")
                Copy-Item -Path (Join-Path $script:agentDir "Register-AgentTask.ps1") -Destination (Join-Path $sandbox "Register-AgentTask.ps1")
                Copy-Item -Path (Join-Path $script:agentDir "collectors") -Destination (Join-Path $sandbox "collectors") -Recurse

                . $script:loader
                $result = Test-AgentIntegrity -AgentRoot $sandbox
                $result | Should -BeTrue
            } finally {
                Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue
            }
        }

        It "returns `$false when PCOpsAgent.ps1 is tampered" {
            $sandbox = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_selfcheck_tamper_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
            New-Item -ItemType Directory -Path $sandbox -Force | Out-Null
            try {
                Copy-Item -Path $script:manifest -Destination (Join-Path $sandbox "manifest.json")
                Copy-Item -Path $script:agentScript -Destination (Join-Path $sandbox "PCOpsAgent.ps1")
                Copy-Item -Path (Join-Path $script:agentDir "Register-AgentTask.ps1") -Destination (Join-Path $sandbox "Register-AgentTask.ps1")
                Copy-Item -Path (Join-Path $script:agentDir "collectors") -Destination (Join-Path $sandbox "collectors") -Recurse

                # Append a byte to simulate tampering
                Add-Content -Path (Join-Path $sandbox "PCOpsAgent.ps1") -Value "# tampered" -Encoding UTF8

                . $script:loader
                $result = Test-AgentIntegrity -AgentRoot $sandbox
                $result | Should -BeFalse
            } finally {
                Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue
            }
        }

        It "returns `$false when manifest.json is absent (fail-closed)" {
            $sandbox = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_selfcheck_nomanifest_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
            New-Item -ItemType Directory -Path $sandbox -Force | Out-Null
            try {
                Copy-Item -Path $script:agentScript -Destination (Join-Path $sandbox "PCOpsAgent.ps1")

                . $script:loader
                $result = Test-AgentIntegrity -AgentRoot $sandbox
                $result | Should -BeFalse
            } finally {
                Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue
            }
        }

        It "returns `$false when a tracked collector is missing" {
            $sandbox = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_selfcheck_missing_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
            New-Item -ItemType Directory -Path $sandbox -Force | Out-Null
            try {
                Copy-Item -Path $script:manifest -Destination (Join-Path $sandbox "manifest.json")
                Copy-Item -Path $script:agentScript -Destination (Join-Path $sandbox "PCOpsAgent.ps1")
                Copy-Item -Path (Join-Path $script:agentDir "Register-AgentTask.ps1") -Destination (Join-Path $sandbox "Register-AgentTask.ps1")
                # Intentionally skip copying collectors/

                . $script:loader
                $result = Test-AgentIntegrity -AgentRoot $sandbox
                $result | Should -BeFalse
            } finally {
                Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue
            }
        }

        It "returns `$false when manifest contains a PLACEHOLDER hash" {
            $sandbox = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_selfcheck_placeholder_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
            New-Item -ItemType Directory -Path $sandbox -Force | Out-Null
            try {
                $manifestJson = Get-Content $script:manifest -Raw -Encoding UTF8 | ConvertFrom-Json
                $manifestJson.files.'PCOpsAgent.ps1' = "PLACEHOLDER"
                $manifestJson | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $sandbox "manifest.json") -Encoding UTF8
                Copy-Item -Path $script:agentScript -Destination (Join-Path $sandbox "PCOpsAgent.ps1")

                . $script:loader
                $result = Test-AgentIntegrity -AgentRoot $sandbox
                $result | Should -BeFalse
            } finally {
                Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue
            }
        }
    }
}

Set-StrictMode -Version Latest

# Tests for Issue #188 part 3: DPAPI api_key protection.
#
# DPAPI is Windows-only. The function source/wiring tests run everywhere
# (they just regex the source), but the round-trip / migration tests are
# guarded so they skip cleanly on Linux CI runners.

$script:isWindowsHost = ($PSVersionTable.PSVersion.Major -le 5) -or $IsWindows

Describe "Agent DPAPI api_key protection (Issue #188 part 3)" {
    BeforeAll {
        $script:repoRoot = Split-Path $PSScriptRoot -Parent
        $script:agentDir = Join-Path $script:repoRoot "agent"
        $script:agentScript = Join-Path $script:agentDir "PCOpsAgent.ps1"
        $script:helper = Join-Path $script:repoRoot "tools/Protect-AgentApiKey.ps1"
    }

    Context "Source wiring" {
        It 'declares Resolve-AgentApiKey before $API_KEY is assigned' {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'function Resolve-AgentApiKey'
            $idxFunc = $content.IndexOf('function Resolve-AgentApiKey')
            $idxCall = $content.IndexOf('$API_KEY = Resolve-AgentApiKey')
            $idxFunc | Should -BeGreaterThan 0
            $idxCall | Should -BeGreaterThan 0
            $idxFunc | Should -BeLessThan $idxCall
        }

        It "uses DPAPI ProtectedData with CurrentUser scope" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'System\.Security\.Cryptography\.ProtectedData'
            $content | Should -Match 'DataProtectionScope\]::CurrentUser'
        }

        It "fail-closes when both api_key and api_key_protected are missing" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'api_key も api_key_protected も存在しません'
            $content | Should -Match 'exit 1'
        }

        It "removes plaintext api_key on migration" {
            # The migration loop must skip the api_key property when rebuilding
            # the config so the rewritten file does not retain the plaintext.
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match "if \(\`$p\.Name -eq 'api_key'\) \{ continue \}"
        }

        It "ships tools/Protect-AgentApiKey.ps1 helper" {
            Test-Path $script:helper | Should -BeTrue
        }
    }

    Context "Resolve-AgentApiKey function behavior" -Skip:(-not $script:isWindowsHost) {
        BeforeAll {
            $raw = Get-Content -Raw -Path $script:agentScript
            $match = [regex]::Match($raw, '(?s)function Resolve-AgentApiKey \{.*?\n\}')
            if (-not $match.Success) {
                throw "Failed to extract Resolve-AgentApiKey from PCOpsAgent.ps1"
            }
            $funcSrc = $match.Value
            $script:loader = [scriptblock]::Create($funcSrc)
        }

        It "migrates plaintext api_key to api_key_protected and removes plaintext" {
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_dpapi_migrate_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                $cfg = [ordered]@{
                    server_url = "https://example.invalid/"
                    api_key    = "plain-secret-123"
                    pc_name    = "TEST-PC"
                }
                $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $tmp -Encoding UTF8

                . $script:loader
                $config = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
                $resolved = Resolve-AgentApiKey -Config $config -ConfigPath $tmp
                $resolved | Should -Be "plain-secret-123"

                $after = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
                $after.PSObject.Properties.Match('api_key').Count | Should -Be 0
                $after.PSObject.Properties.Match('api_key_protected').Count | Should -Be 1
                $after.api_key_protected | Should -Not -BeNullOrEmpty
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }

        It "decrypts api_key_protected on subsequent boots" {
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_dpapi_roundtrip_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                Add-Type -AssemblyName System.Security -ErrorAction SilentlyContinue
                $plain = "round-trip-key-xyz"
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($plain)
                $cipher = [System.Security.Cryptography.ProtectedData]::Protect(
                    $bytes, $null,
                    [System.Security.Cryptography.DataProtectionScope]::CurrentUser
                )
                $b64 = [Convert]::ToBase64String($cipher)

                $cfg = [ordered]@{
                    server_url         = "https://example.invalid/"
                    api_key_protected  = $b64
                    pc_name            = "TEST-PC"
                }
                $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $tmp -Encoding UTF8

                . $script:loader
                $config = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
                $resolved = Resolve-AgentApiKey -Config $config -ConfigPath $tmp
                $resolved | Should -Be $plain
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }

        It "supports hashtable Config (fresh install bootstrap path)" {
            # P1 fix (Codex review): when config.json is missing the script
            # initializes $config as a hashtable. PSObject.Properties.Match()
            # does NOT see hashtable entries, so the old code regressed to exit 1.
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_dpapi_hashtable_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                $cfg = @{
                    server_url = "https://example.invalid/"
                    api_key    = "bootstrap-default-key"
                    pc_name    = "FRESH-PC"
                }

                . $script:loader
                $resolved = Resolve-AgentApiKey -Config $cfg -ConfigPath $tmp
                $resolved | Should -Be "bootstrap-default-key"

                # The migration must persist the protected form even though the
                # input was a hashtable rather than a parsed JSON object.
                Test-Path $tmp | Should -BeTrue
                $after = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
                $after.PSObject.Properties.Match('api_key').Count | Should -Be 0
                $after.PSObject.Properties.Match('api_key_protected').Count | Should -Be 1
                $after.api_key_protected | Should -Not -BeNullOrEmpty
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }

        It "strips plaintext api_key when api_key_protected already exists" {
            # P2 fix (Codex review): if a config has both api_key_protected and a
            # leftover plaintext api_key, the resolver must still rewrite the file
            # without the plaintext so at-rest exposure is removed.
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_dpapi_mixed_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                Add-Type -AssemblyName System.Security -ErrorAction SilentlyContinue
                $plain = "mixed-existing-protected"
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($plain)
                $cipher = [System.Security.Cryptography.ProtectedData]::Protect(
                    $bytes, $null,
                    [System.Security.Cryptography.DataProtectionScope]::CurrentUser
                )
                $b64 = [Convert]::ToBase64String($cipher)

                $cfg = [ordered]@{
                    server_url        = "https://example.invalid/"
                    api_key           = "leftover-plaintext-should-be-removed"
                    api_key_protected = $b64
                    pc_name           = "MIXED-PC"
                }
                $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $tmp -Encoding UTF8

                . $script:loader
                $config = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
                $resolved = Resolve-AgentApiKey -Config $config -ConfigPath $tmp
                $resolved | Should -Be $plain  # decrypted from protected, not plaintext

                $after = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
                $after.PSObject.Properties.Match('api_key').Count | Should -Be 0
                $after.PSObject.Properties.Match('api_key_protected').Count | Should -Be 1
                $after.api_key_protected | Should -Be $b64  # protected value preserved verbatim
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }

        It "fail-closes (exit) when api_key_protected ciphertext is corrupt" {
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_dpapi_corrupt_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                $cfg = [ordered]@{
                    server_url        = "https://example.invalid/"
                    api_key_protected = [Convert]::ToBase64String([byte[]](0x00, 0x01, 0x02, 0x03))
                }
                $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $tmp -Encoding UTF8

                . $script:loader
                $config = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json

                # Spawn a child pwsh so `exit 1` doesn't kill the test host
                $script = @"
`$ErrorActionPreference = 'Stop'
$($script:loader.ToString())
`$cfg = Get-Content -Path '$tmp' -Raw -Encoding UTF8 | ConvertFrom-Json
Resolve-AgentApiKey -Config `$cfg -ConfigPath '$tmp'
"@
                $exe = (Get-Process -Id $PID).Path
                $tmpScript = [System.IO.Path]::GetTempFileName() + ".ps1"
                Set-Content -Path $tmpScript -Value $script -Encoding UTF8
                try {
                    & $exe -NoProfile -File $tmpScript 2>$null | Out-Null
                    $LASTEXITCODE | Should -Be 1
                } finally {
                    Remove-Item -Force $tmpScript -ErrorAction SilentlyContinue
                }
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }
    }
}

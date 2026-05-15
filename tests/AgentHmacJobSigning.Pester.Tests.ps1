Set-StrictMode -Version Latest

# Tests for Issue #188 part 4: HMAC-SHA256 pending_tasks signing.
#
# Server signs the /api/collect response's pending_tasks with a per-PC key
# (HMAC-SHA256 over canonical JSON). The agent verifies the signature before
# executing any task, and persists a newly-issued key via DPAPI.
#
# Source-wiring assertions (regex on PCOpsAgent.ps1) run everywhere.
# Round-trip / round-trip-via-DPAPI tests are guarded so Linux CI skips them
# cleanly. Canonical-JSON parity is validated against a known Python output.

$script:isWindowsHost = ($PSVersionTable.PSVersion.Major -le 5) -or $IsWindows

Describe "Agent HMAC pending_tasks signing (Issue #188 part 4)" {
    BeforeAll {
        $script:repoRoot = Split-Path $PSScriptRoot -Parent
        $script:agentDir = Join-Path $script:repoRoot "agent"
        $script:agentScript = Join-Path $script:agentDir "PCOpsAgent.ps1"
    }

    Context "Source wiring" {
        It "declares all four HMAC helpers" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'function Resolve-AgentSigningKey'
            $content | Should -Match 'function Save-AgentSigningKey'
            $content | Should -Match 'function ConvertTo-CanonicalJson'
            $content | Should -Match 'function Test-PendingTasksSignature'
        }

        It 'assigns $SIGNING_KEY after the helpers are defined' {
            $content = Get-Content -Raw -Path $script:agentScript
            $idxFunc = $content.IndexOf('function Resolve-AgentSigningKey')
            $idxCall = $content.IndexOf('$SIGNING_KEY = Resolve-AgentSigningKey')
            $idxFunc | Should -BeGreaterThan 0
            $idxCall | Should -BeGreaterThan 0
            $idxFunc | Should -BeLessThan $idxCall
        }

        It "uses HMACSHA256 from System.Security.Cryptography" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'System\.Security\.Cryptography\.HMACSHA256'
        }

        It "protects the signing key with DPAPI CurrentUser scope" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'System\.Security\.Cryptography\.ProtectedData'
            $content | Should -Match 'DataProtectionScope\]::CurrentUser'
        }

        It "uses constant-time hex comparison (accumulated XOR)" {
            $content = Get-Content -Raw -Path $script:agentScript
            # The XOR accumulation loop is the timing-safe primitive.
            $content | Should -Match '\$diff = \$diff -bor'
            $content | Should -Match '-bxor'
            $content | Should -Match 'BitConverter\]::ToString'
            $content | Should -Match 'ToLowerInvariant'
        }

        It "sorts dict/PSObject keys alphabetically for canonical JSON" {
            $content = Get-Content -Raw -Path $script:agentScript
            # Both branches must sort: IDictionary keys and PSObject properties.
            $content | Should -Match '@\(\$Value\.Keys\) \| Sort-Object'
            $content | Should -Match '@\(\$Value\.PSObject\.Properties\) \| Sort-Object Name'
        }

        It "fail-closes pending_tasks when signing key is missing" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match '署名鍵未設定のまま pending_tasks を受信'
        }

        It "fail-closes pending_tasks when signature is missing" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'pending_tasks_sig が欠落'
        }

        It "fail-closes pending_tasks when HMAC verification fails" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'HMAC 検証失敗'
        }

        It "Save-AgentSigningKey strips both plaintext and old protected key" {
            $content = Get-Content -Raw -Path $script:agentScript
            # The migration loops must skip both names in both hashtable and PSObject branches.
            $content | Should -Match "if \(\`$p -eq 'agent_signing_key'\) \{ continue \}"
            $content | Should -Match "if \(\`$p -eq 'agent_signing_key_protected'\) \{ continue \}"
            $content | Should -Match "if \(\`$p\.Name -eq 'agent_signing_key'\) \{ continue \}"
            $content | Should -Match "if \(\`$p\.Name -eq 'agent_signing_key_protected'\) \{ continue \}"
        }

        It 'Resolve-AgentSigningKey returns $null (not exit 1) when key is absent' {
            $content = Get-Content -Raw -Path $script:agentScript
            # The function MUST NOT fail-closed on missing key — a fresh agent has none.
            # Only corrupt ciphertext is fail-closed.
            $content | Should -Match 'agent_signing_key_protected の復号に失敗'
        }
    }

    Context "ConvertTo-CanonicalJson behavior" {
        BeforeAll {
            $raw = Get-Content -Raw -Path $script:agentScript
            $match = [regex]::Match($raw, '(?s)function ConvertTo-CanonicalJson \{.*?\n\}')
            if (-not $match.Success) {
                throw "Failed to extract ConvertTo-CanonicalJson from PCOpsAgent.ps1"
            }
            $script:canonicalSrc = $match.Value
            $script:canonicalLoader = [scriptblock]::Create($script:canonicalSrc)
        }

        It "produces compact separators with no spaces" {
            . $script:canonicalLoader
            $obj = [ordered]@{ a = 1; b = 2 }
            $out = ConvertTo-CanonicalJson -Value $obj
            # No literal space character anywhere in the output.
            $out.Contains(' ') | Should -BeFalse
            $out.Contains("`t") | Should -BeFalse
            $out.Contains("`n") | Should -BeFalse
        }

        It "sorts dictionary keys alphabetically" {
            . $script:canonicalLoader
            $obj = [ordered]@{ zebra = 1; apple = 2; mango = 3 }
            $out = ConvertTo-CanonicalJson -Value $obj
            $out | Should -Be '{"apple":2,"mango":3,"zebra":1}'
        }

        It "matches Python json.dumps(sort_keys=True, separators=(',', ':')) for a representative task list" {
            . $script:canonicalLoader
            # Mirrors what the server signs: a list of task dicts with mixed types.
            $tasks = @(
                [ordered]@{ id = 1; task_type = 'collect'; command = 'Get-PCInfo'; parameters = $null },
                [ordered]@{ id = 2; task_type = 'restart'; command = 'Restart-Service'; parameters = [ordered]@{ name = 'spooler' } }
            )
            $out = ConvertTo-CanonicalJson -Value $tasks
            # Computed via:
            #   python -c "import json; print(json.dumps([{'id':1,'task_type':'collect','command':'Get-PCInfo','parameters':None},{'id':2,'task_type':'restart','command':'Restart-Service','parameters':{'name':'spooler'}}],sort_keys=True,separators=(',',':')))"
            $expected = '[{"command":"Get-PCInfo","id":1,"parameters":null,"task_type":"collect"},{"command":"Restart-Service","id":2,"parameters":{"name":"spooler"},"task_type":"restart"}]'
            $out | Should -Be $expected
        }

        It "handles empty array" {
            . $script:canonicalLoader
            $out = ConvertTo-CanonicalJson -Value @()
            $out | Should -Be '[]'
        }

        It "handles null" {
            . $script:canonicalLoader
            $out = ConvertTo-CanonicalJson -Value $null
            $out | Should -Be 'null'
        }

        It "handles booleans" {
            . $script:canonicalLoader
            (ConvertTo-CanonicalJson -Value $true) | Should -Be 'true'
            (ConvertTo-CanonicalJson -Value $false) | Should -Be 'false'
        }
    }

    Context "Test-PendingTasksSignature behavior" -Skip:(-not $script:isWindowsHost) {
        BeforeAll {
            $raw = Get-Content -Raw -Path $script:agentScript
            # Load BOTH helpers — Test-PendingTasksSignature depends on ConvertTo-CanonicalJson.
            $canonicalMatch = [regex]::Match($raw, '(?s)function ConvertTo-CanonicalJson \{.*?\n\}')
            $verifyMatch = [regex]::Match($raw, '(?s)function Test-PendingTasksSignature \{.*?\n\}')
            if (-not ($canonicalMatch.Success -and $verifyMatch.Success)) {
                throw "Failed to extract HMAC helpers from PCOpsAgent.ps1"
            }
            $script:verifyLoader = [scriptblock]::Create(
                $canonicalMatch.Value + "`n`n" + $verifyMatch.Value
            )
        }

        It 'returns $true for a server-equivalent HMAC of pending_tasks' {
            . $script:verifyLoader
            $key = 'unit-test-signing-key-do-not-use-in-prod'
            $tasks = @(
                [ordered]@{ id = 10; task_type = 'collect'; command = 'X'; parameters = $null }
            )
            # Build the canonical bytes the same way the function does, then sign separately.
            $canonical = ConvertTo-CanonicalJson -Value $tasks
            $keyBytes = [System.Text.Encoding]::UTF8.GetBytes($key)
            $msgBytes = [System.Text.Encoding]::UTF8.GetBytes($canonical)
            $h = [System.Security.Cryptography.HMACSHA256]::new($keyBytes)
            try { $sig = $h.ComputeHash($msgBytes) } finally { $h.Dispose() }
            $hex = [BitConverter]::ToString($sig).Replace('-', '').ToLowerInvariant()

            Test-PendingTasksSignature -SigningKey $key -Tasks $tasks -ExpectedHex $hex | Should -BeTrue
        }

        It "is case-insensitive on the expected hex (uppercase input still verifies)" {
            . $script:verifyLoader
            $key = 'case-insensitive-key'
            $tasks = @([ordered]@{ id = 1; task_type = 't' })
            $canonical = ConvertTo-CanonicalJson -Value $tasks
            $keyBytes = [System.Text.Encoding]::UTF8.GetBytes($key)
            $msgBytes = [System.Text.Encoding]::UTF8.GetBytes($canonical)
            $h = [System.Security.Cryptography.HMACSHA256]::new($keyBytes)
            try { $sig = $h.ComputeHash($msgBytes) } finally { $h.Dispose() }
            $hexUpper = [BitConverter]::ToString($sig).Replace('-', '').ToUpperInvariant()

            Test-PendingTasksSignature -SigningKey $key -Tasks $tasks -ExpectedHex $hexUpper | Should -BeTrue
        }

        It 'returns $false when one task is tampered' {
            . $script:verifyLoader
            $key = 'tamper-test-key'
            $original = @([ordered]@{ id = 1; task_type = 'collect' })
            $canonical = ConvertTo-CanonicalJson -Value $original
            $keyBytes = [System.Text.Encoding]::UTF8.GetBytes($key)
            $msgBytes = [System.Text.Encoding]::UTF8.GetBytes($canonical)
            $h = [System.Security.Cryptography.HMACSHA256]::new($keyBytes)
            try { $sig = $h.ComputeHash($msgBytes) } finally { $h.Dispose() }
            $hex = [BitConverter]::ToString($sig).Replace('-', '').ToLowerInvariant()

            $tampered = @(
                [ordered]@{ id = 1; task_type = 'collect' },
                [ordered]@{ id = 999; task_type = 'evil' }
            )
            Test-PendingTasksSignature -SigningKey $key -Tasks $tampered -ExpectedHex $hex | Should -BeFalse
        }

        It 'returns $false when expected hex is empty or whitespace' {
            . $script:verifyLoader
            $tasks = @([ordered]@{ id = 1 })
            Test-PendingTasksSignature -SigningKey 'k' -Tasks $tasks -ExpectedHex '' | Should -BeFalse
            Test-PendingTasksSignature -SigningKey 'k' -Tasks $tasks -ExpectedHex '   ' | Should -BeFalse
        }

        It 'returns $false when hex length differs (wrong-size signature)' {
            . $script:verifyLoader
            $tasks = @([ordered]@{ id = 1 })
            # 32 hex chars instead of 64 — never matches an SHA-256 output.
            Test-PendingTasksSignature -SigningKey 'k' -Tasks $tasks -ExpectedHex ('a' * 32) | Should -BeFalse
        }

        It 'returns $false when a single hex character differs' {
            . $script:verifyLoader
            $key = 'one-char-flip-key'
            $tasks = @([ordered]@{ id = 7; task_type = 'noop' })
            $canonical = ConvertTo-CanonicalJson -Value $tasks
            $keyBytes = [System.Text.Encoding]::UTF8.GetBytes($key)
            $msgBytes = [System.Text.Encoding]::UTF8.GetBytes($canonical)
            $h = [System.Security.Cryptography.HMACSHA256]::new($keyBytes)
            try { $sig = $h.ComputeHash($msgBytes) } finally { $h.Dispose() }
            $hex = [BitConverter]::ToString($sig).Replace('-', '').ToLowerInvariant()

            # Flip the first hex char to a different value (deterministic mapping).
            $firstChar = $hex[0]
            $flipped = if ($firstChar -eq '0') { '1' } else { '0' }
            $bad = $flipped + $hex.Substring(1)

            Test-PendingTasksSignature -SigningKey $key -Tasks $tasks -ExpectedHex $bad | Should -BeFalse
        }
    }

    Context "Resolve-AgentSigningKey / Save-AgentSigningKey DPAPI round-trip" -Skip:(-not $script:isWindowsHost) {
        BeforeAll {
            $raw = Get-Content -Raw -Path $script:agentScript
            $resolveMatch = [regex]::Match($raw, '(?s)function Resolve-AgentSigningKey \{.*?\n\}')
            $saveMatch = [regex]::Match($raw, '(?s)function Save-AgentSigningKey \{.*?\n\}')
            if (-not ($resolveMatch.Success -and $saveMatch.Success)) {
                throw "Failed to extract DPAPI helpers from PCOpsAgent.ps1"
            }
            $script:dpapiLoader = [scriptblock]::Create(
                $resolveMatch.Value + "`n`n" + $saveMatch.Value
            )
        }

        It 'returns $null when neither plaintext nor protected key is present (fresh agent)' {
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_hmac_fresh_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                $cfg = [ordered]@{
                    server_url = "https://example.invalid/"
                    api_key    = "irrelevant-for-this-test"
                    pc_name    = "FRESH-PC"
                }
                $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $tmp -Encoding UTF8

                . $script:dpapiLoader
                $config = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
                $resolved = Resolve-AgentSigningKey -Config $config -ConfigPath $tmp
                # Critical: a fresh agent without a server-issued key must get $null,
                # NOT exit 1 — the next /api/collect call returns the key.
                $resolved | Should -BeNullOrEmpty
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }

        It "Save-AgentSigningKey encrypts and Resolve decrypts to the same plaintext" {
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_hmac_save_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                $cfg = [ordered]@{
                    server_url = "https://example.invalid/"
                    pc_name    = "TEST-PC"
                }
                $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $tmp -Encoding UTF8

                . $script:dpapiLoader
                $plain = "server-issued-key-abc-XYZ-1234567890"
                Save-AgentSigningKey -PlainKey $plain -ConfigPath $tmp

                $after = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
                $after.PSObject.Properties.Match('agent_signing_key').Count | Should -Be 0
                $after.PSObject.Properties.Match('agent_signing_key_protected').Count | Should -Be 1

                $resolved = Resolve-AgentSigningKey -Config $after -ConfigPath $tmp
                $resolved | Should -Be $plain
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }

        It "Save-AgentSigningKey strips leftover plaintext agent_signing_key" {
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_hmac_strip_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                $cfg = [ordered]@{
                    server_url         = "https://example.invalid/"
                    agent_signing_key  = "leftover-plaintext-to-purge"
                    pc_name            = "MIXED-PC"
                }
                $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $tmp -Encoding UTF8

                . $script:dpapiLoader
                Save-AgentSigningKey -PlainKey "new-protected-key" -ConfigPath $tmp

                $after = Get-Content -Path $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
                $after.PSObject.Properties.Match('agent_signing_key').Count | Should -Be 0
                $after.PSObject.Properties.Match('agent_signing_key_protected').Count | Should -Be 1
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }

        It "fail-closes (exit 1) when agent_signing_key_protected ciphertext is corrupt" {
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_hmac_corrupt_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                $cfg = [ordered]@{
                    server_url                  = "https://example.invalid/"
                    agent_signing_key_protected = [Convert]::ToBase64String([byte[]](0x00, 0x01, 0x02, 0x03))
                }
                $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $tmp -Encoding UTF8

                . $script:dpapiLoader

                # Spawn a child pwsh so `exit 1` doesn't kill the test host.
                $script = @"
`$ErrorActionPreference = 'Stop'
$($script:dpapiLoader.ToString())
`$cfg = Get-Content -Path '$tmp' -Raw -Encoding UTF8 | ConvertFrom-Json
Resolve-AgentSigningKey -Config `$cfg -ConfigPath '$tmp'
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

        It "supports hashtable Config (fresh install bootstrap path)" {
            # Mirrors the PR #199 P1 fix: when config.json is missing the script
            # initializes $config as a hashtable. PSObject.Properties.Match() does
            # NOT see hashtable entries, so the resolver must handle both shapes.
            . $script:dpapiLoader
            $cfg = @{
                server_url = "https://example.invalid/"
                pc_name    = "HASHTABLE-PC"
            }
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_hmac_hash_" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
            try {
                $resolved = Resolve-AgentSigningKey -Config $cfg -ConfigPath $tmp
                $resolved | Should -BeNullOrEmpty
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }
    }
}

Set-StrictMode -Version Latest

# Tests for Issue #186: SQLite + AES-256 offline cache migration.
#
# Source-wiring tests (Context "Source wiring") run on all platforms via regex.
# Round-trip tests (Context "Round-trip") require Windows DPAPI + PSSQLite and
# are guarded with -Skip:(-not $script:isWindowsHost).

$script:isWindowsHost = ($PSVersionTable.PSVersion.Major -le 5) -or $IsWindows

Describe "Agent offline cache SQLite+AES-256 (Issue #186)" {
    BeforeAll {
        $script:repoRoot   = Split-Path $PSScriptRoot -Parent
        $script:agentDir   = Join-Path $script:repoRoot "agent"
        $script:agentScript  = Join-Path $script:agentDir "PCOpsAgent.ps1"
        $script:cacheModule  = Join-Path $script:agentDir "OfflineCacheDB.ps1"
    }

    # -----------------------------------------------------------------------
    Context "Source wiring — OfflineCacheDB.ps1" {
        It "ships agent/OfflineCacheDB.ps1" {
            Test-Path $script:cacheModule | Should -BeTrue
        }

        It "declares Initialize-OfflineCacheDB" {
            Get-Content -Raw -Path $script:cacheModule | Should -Match 'function Initialize-OfflineCacheDB'
        }

        It "declares New-CacheKey and Get-CacheKey" {
            $content = Get-Content -Raw -Path $script:cacheModule
            $content | Should -Match 'function New-CacheKey'
            $content | Should -Match 'function Get-CacheKey'
        }

        It "declares Protect-CachePayload and Unprotect-CachePayload" {
            $content = Get-Content -Raw -Path $script:cacheModule
            $content | Should -Match 'function Protect-CachePayload'
            $content | Should -Match 'function Unprotect-CachePayload'
        }

        It "declares Add-ToOfflineCacheDB and Read-OfflineCacheDB" {
            $content = Get-Content -Raw -Path $script:cacheModule
            $content | Should -Match 'function Add-ToOfflineCacheDB'
            $content | Should -Match 'function Read-OfflineCacheDB'
        }

        It "declares Remove-SyncedEntries and Remove-ExpiredEntries" {
            $content = Get-Content -Raw -Path $script:cacheModule
            $content | Should -Match 'function Remove-SyncedEntries'
            $content | Should -Match 'function Remove-ExpiredEntries'
        }

        It "declares Migrate-LegacyJsonCache" {
            Get-Content -Raw -Path $script:cacheModule | Should -Match 'function Migrate-LegacyJsonCache'
        }

        It "uses DPAPI ProtectedData with CurrentUser scope" {
            $content = Get-Content -Raw -Path $script:cacheModule
            $content | Should -Match 'System\.Security\.Cryptography\.ProtectedData'
            $content | Should -Match 'DataProtectionScope\]::CurrentUser'
        }

        It "uses AES-256 CBC mode" {
            $content = Get-Content -Raw -Path $script:cacheModule
            $content | Should -Match 'KeySize\s*=\s*256'
            $content | Should -Match 'CipherMode\]::CBC'
        }

        It "uses HMAC-SHA256 for authentication" {
            Get-Content -Raw -Path $script:cacheModule | Should -Match 'HMACSHA256'
        }

        It "defines 30-day TTL constant" {
            Get-Content -Raw -Path $script:cacheModule | Should -Match 'CACHE_TTL_DAYS\s*=\s*30'
        }
    }

    # -----------------------------------------------------------------------
    Context "Source wiring — PCOpsAgent.ps1 integration" {
        It "dot-sources OfflineCacheDB.ps1" {
            Get-Content -Raw -Path $script:agentScript | Should -Match '\.\s+\$offlineCacheModule'
        }

        It "sets OFFLINE_CACHE_DB under ProgramData" {
            $content = Get-Content -Raw -Path $script:agentScript
            $content | Should -Match 'OFFLINE_CACHE_DB'
            $content | Should -Match 'ProgramData'
        }

        It "calls _EnsureCacheDB in Add-ToOfflineCache" {
            $content = Get-Content -Raw -Path $script:agentScript
            $idxAdd = $content.IndexOf('function Add-ToOfflineCache')
            $idxEnsure = $content.IndexOf('_EnsureCacheDB', $idxAdd)
            $idxAdd | Should -BeGreaterThan 0
            $idxEnsure | Should -BeGreaterThan $idxAdd
        }

        It "calls Remove-ExpiredEntries in _EnsureCacheDB" {
            $content = Get-Content -Raw -Path $script:agentScript
            $idxEnsure = $content.IndexOf('function _EnsureCacheDB')
            $idxExpired = $content.IndexOf('Remove-ExpiredEntries', $idxEnsure)
            $idxEnsure | Should -BeGreaterThan 0
            $idxExpired | Should -BeGreaterThan $idxEnsure
        }

        It "references LEGACY_CACHE_FILE for migration" {
            Get-Content -Raw -Path $script:agentScript | Should -Match 'LEGACY_CACHE_FILE'
        }
    }

    # -----------------------------------------------------------------------
    Context "Encrypt/Decrypt round-trip" -Skip:(-not $script:isWindowsHost) {
        BeforeAll {
            . $script:cacheModule
        }

        It "Protect-CachePayload / Unprotect-CachePayload round-trip" {
            $aesKey  = [byte[]]::new(32); $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
            $hmacKey = [byte[]]::new(32)
            $rng.GetBytes($aesKey); $rng.GetBytes($hmacKey); $rng.Dispose()

            $plain = '{"pc_name":"TEST","cpu_usage":42}'
            $blob  = Protect-CachePayload  -Plaintext $plain -AesKey $aesKey -HmacKey $hmacKey
            $back  = Unprotect-CachePayload -Base64Blob $blob  -AesKey $aesKey -HmacKey $hmacKey
            $back | Should -Be $plain
        }

        It "Protect-CachePayload produces different ciphertext each call (IV randomness)" {
            $aesKey  = [byte[]]::new(32); $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
            $hmacKey = [byte[]]::new(32)
            $rng.GetBytes($aesKey); $rng.GetBytes($hmacKey); $rng.Dispose()

            $plain = "same plaintext"
            $b1 = Protect-CachePayload -Plaintext $plain -AesKey $aesKey -HmacKey $hmacKey
            $b2 = Protect-CachePayload -Plaintext $plain -AesKey $aesKey -HmacKey $hmacKey
            $b1 | Should -Not -Be $b2
        }

        It "Unprotect-CachePayload throws on tampered ciphertext" {
            $aesKey  = [byte[]]::new(32); $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
            $hmacKey = [byte[]]::new(32)
            $rng.GetBytes($aesKey); $rng.GetBytes($hmacKey); $rng.Dispose()

            $blob   = Protect-CachePayload -Plaintext "hello" -AesKey $aesKey -HmacKey $hmacKey
            $raw    = [Convert]::FromBase64String($blob)
            $raw[0] = $raw[0] -bxor 0xFF  # flip first byte
            $tampered = [Convert]::ToBase64String($raw)
            { Unprotect-CachePayload -Base64Blob $tampered -AesKey $aesKey -HmacKey $hmacKey } | Should -Throw
        }
    }

    # -----------------------------------------------------------------------
    Context "DPAPI key management" -Skip:(-not $script:isWindowsHost) {
        BeforeAll {
            . $script:cacheModule
        }

        It "New-CacheKey creates a protected key file" {
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_key_" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".bin")
            try {
                $keys = New-CacheKey -KeyPath $tmp
                Test-Path $tmp | Should -BeTrue
                $keys.AesKey  | Should -HaveCount 32
                $keys.HmacKey | Should -HaveCount 32
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }

        It "Get-CacheKey round-trips the same key bytes" {
            $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_key_rt_" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".bin")
            try {
                $created = New-CacheKey -KeyPath $tmp
                $loaded  = Get-CacheKey  -KeyPath $tmp
                [Convert]::ToBase64String($created.AesKey)  | Should -Be ([Convert]::ToBase64String($loaded.AesKey))
                [Convert]::ToBase64String($created.HmacKey) | Should -Be ([Convert]::ToBase64String($loaded.HmacKey))
            } finally {
                Remove-Item -Force $tmp -ErrorAction SilentlyContinue
            }
        }
    }

    # -----------------------------------------------------------------------
    Context "SQLite CRUD round-trip" -Skip:(-not $script:isWindowsHost) {
        BeforeAll {
            # PSSQLite must be available on the test host
            if (-not (Get-Module -ListAvailable -Name PSSQLite)) {
                Install-Module PSSQLite -Scope CurrentUser -Force -SkipPublisherCheck -ErrorAction SilentlyContinue
            }
            Import-Module PSSQLite -ErrorAction SilentlyContinue

            . $script:cacheModule

            $script:tmpDb  = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_cache_" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".db")
            $script:tmpKey = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_key_"   + [guid]::NewGuid().ToString("N").Substring(0,8) + ".bin")
        }

        AfterAll {
            Remove-Item -Force $script:tmpDb  -ErrorAction SilentlyContinue
            Remove-Item -Force $script:tmpKey -ErrorAction SilentlyContinue
        }

        It "Initialize-OfflineCacheDB creates the DB file" {
            Initialize-OfflineCacheDB -DbPath $script:tmpDb
            Test-Path $script:tmpDb | Should -BeTrue
        }

        It "Add-ToOfflineCacheDB inserts an encrypted entry" {
            $entry = @{ pc_name = "TEST-PC"; cpu_usage = 55; collected_at = "2026-01-01T00:00:00Z" }
            Add-ToOfflineCacheDB -DbPath $script:tmpDb -KeyPath $script:tmpKey -Entry $entry
            $cnt = (Invoke-SqliteQuery -DataSource $script:tmpDb -Query "SELECT COUNT(*) AS c FROM offline_cache").c
            $cnt | Should -Be 1
        }

        It "payload column stores a Base64 blob (not plain JSON)" {
            $raw = (Invoke-SqliteQuery -DataSource $script:tmpDb -Query "SELECT payload FROM offline_cache LIMIT 1").payload
            # Should not contain plain JSON keys directly
            $raw | Should -Not -Match '"pc_name"'
        }

        It "Read-OfflineCacheDB decrypts and returns the entry" {
            $entries = @(Read-OfflineCacheDB -DbPath $script:tmpDb -KeyPath $script:tmpKey)
            $entries | Should -HaveCount 1
            $entries[0].pc_name | Should -Be "TEST-PC"
            $entries[0].cpu_usage | Should -Be 55
        }

        It "Remove-SyncedEntries deletes by id" {
            $entries = @(Read-OfflineCacheDB -DbPath $script:tmpDb -KeyPath $script:tmpKey)
            $ids = @($entries | ForEach-Object { [int]$_._cache_id })
            Remove-SyncedEntries -DbPath $script:tmpDb -Ids $ids
            $cnt = (Invoke-SqliteQuery -DataSource $script:tmpDb -Query "SELECT COUNT(*) AS c FROM offline_cache").c
            $cnt | Should -Be 0
        }

        It "Remove-ExpiredEntries deletes entries older than 30 days" {
            $old = @{ pc_name = "OLD-PC"; cpu_usage = 10; collected_at = "2020-01-01T00:00:00Z" }
            Add-ToOfflineCacheDB -DbPath $script:tmpDb -KeyPath $script:tmpKey -Entry $old
            Remove-ExpiredEntries -DbPath $script:tmpDb
            $cnt = (Invoke-SqliteQuery -DataSource $script:tmpDb -Query "SELECT COUNT(*) AS c FROM offline_cache").c
            $cnt | Should -Be 0
        }
    }

    # -----------------------------------------------------------------------
    Context "Legacy JSON migration" -Skip:(-not $script:isWindowsHost) {
        BeforeAll {
            if (-not (Get-Module -ListAvailable -Name PSSQLite)) {
                Install-Module PSSQLite -Scope CurrentUser -Force -SkipPublisherCheck -ErrorAction SilentlyContinue
            }
            Import-Module PSSQLite -ErrorAction SilentlyContinue
            . $script:cacheModule
        }

        It "Migrate-LegacyJsonCache moves entries from JSON to SQLite and removes JSON file" {
            $tmpJson = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_legacy_" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".json")
            $tmpDb   = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_mig_"    + [guid]::NewGuid().ToString("N").Substring(0,8) + ".db")
            $tmpKey  = Join-Path ([System.IO.Path]::GetTempPath()) ("pcops_migkey_" + [guid]::NewGuid().ToString("N").Substring(0,8) + ".bin")
            try {
                @(
                    @{ pc_name = "OLD-PC1"; cpu_usage = 10; collected_at = "2026-01-01T00:00:00Z" },
                    @{ pc_name = "OLD-PC2"; cpu_usage = 20; collected_at = "2026-01-02T00:00:00Z" }
                ) | ConvertTo-Json -Depth 5 | Set-Content -Path $tmpJson -Encoding UTF8

                Initialize-OfflineCacheDB -DbPath $tmpDb
                Migrate-LegacyJsonCache -JsonPath $tmpJson -DbPath $tmpDb -KeyPath $tmpKey

                Test-Path $tmpJson | Should -BeFalse
                $entries = @(Read-OfflineCacheDB -DbPath $tmpDb -KeyPath $tmpKey)
                $entries | Should -HaveCount 2
                ($entries | Where-Object { $_.pc_name -eq "OLD-PC1" }) | Should -Not -BeNullOrEmpty
            } finally {
                Remove-Item -Force $tmpJson, $tmpDb, $tmpKey -ErrorAction SilentlyContinue
            }
        }
    }
}

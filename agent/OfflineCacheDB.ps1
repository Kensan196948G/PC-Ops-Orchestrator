# Agent offline cache: SQLite + AES-256-CBC + HMAC-SHA256
# Key protected by Windows DPAPI (CurrentUser scope).
# Requires: PSSQLite module (Install-Module PSSQLite)

Set-StrictMode -Version Latest

$script:CACHE_TTL_DAYS = 30

# ---------------------------------------------------------------------------
# Key management (DPAPI-protected AES-256 key)
# ---------------------------------------------------------------------------

function New-CacheKey {
    <#
    .SYNOPSIS
    Generates a new AES-256 key and HMAC key, protects with DPAPI, saves to $KeyPath.
    Returns $null on non-Windows (DPAPI unavailable).
    #>
    param([string]$KeyPath)

    Add-Type -AssemblyName System.Security -ErrorAction SilentlyContinue

    $aesKey  = [byte[]]::new(32)  # AES-256
    $hmacKey = [byte[]]::new(32)  # HMAC-SHA256
    $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    $rng.GetBytes($aesKey)
    $rng.GetBytes($hmacKey)
    $rng.Dispose()

    $combined = $aesKey + $hmacKey  # 64 bytes total
    $protected = [System.Security.Cryptography.ProtectedData]::Protect(
        $combined, $null,
        [System.Security.Cryptography.DataProtectionScope]::CurrentUser
    )

    $dir = Split-Path $KeyPath -Parent
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllBytes($KeyPath, $protected)
    return [PSCustomObject]@{ AesKey = $aesKey; HmacKey = $hmacKey }
}

function Get-CacheKey {
    <#
    .SYNOPSIS
    Loads DPAPI-protected key from $KeyPath. Creates new key if missing.
    Returns $null on non-Windows.
    #>
    param([string]$KeyPath)

    Add-Type -AssemblyName System.Security -ErrorAction SilentlyContinue

    if (-not (Test-Path $KeyPath)) {
        return New-CacheKey -KeyPath $KeyPath
    }

    try {
        $protected = [System.IO.File]::ReadAllBytes($KeyPath)
        $combined = [System.Security.Cryptography.ProtectedData]::Unprotect(
            $protected, $null,
            [System.Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        return [PSCustomObject]@{
            AesKey  = $combined[0..31]
            HmacKey = $combined[32..63]
        }
    } catch {
        throw "キャッシュ鍵の復号に失敗しました: $_"
    }
}

# ---------------------------------------------------------------------------
# AES-256-CBC + HMAC-SHA256 encrypt / decrypt
# ---------------------------------------------------------------------------

function Protect-CachePayload {
    <#
    .SYNOPSIS
    Encrypts $Plaintext (string) with AES-256-CBC and authenticates with HMAC-SHA256.
    Returns Base64 string: IV(16) + CipherText + HMAC(32)
    #>
    param(
        [string]$Plaintext,
        [byte[]]$AesKey,
        [byte[]]$HmacKey
    )

    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.KeySize = 256
    $aes.BlockSize = 128
    $aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
    $aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
    $aes.Key = $AesKey
    $aes.GenerateIV()
    $iv = $aes.IV

    $plaintextBytes = [System.Text.Encoding]::UTF8.GetBytes($Plaintext)
    $encryptor = $aes.CreateEncryptor()
    $cipherBytes = $encryptor.TransformFinalBlock($plaintextBytes, 0, $plaintextBytes.Length)
    $encryptor.Dispose()
    $aes.Dispose()

    $ivPlusCipher = $iv + $cipherBytes

    $hmac = [System.Security.Cryptography.HMACSHA256]::new($HmacKey)
    $tag = $hmac.ComputeHash($ivPlusCipher)
    $hmac.Dispose()

    return [Convert]::ToBase64String($ivPlusCipher + $tag)
}

function Unprotect-CachePayload {
    <#
    .SYNOPSIS
    Decrypts Base64 blob produced by Protect-CachePayload.
    Throws on HMAC mismatch (tamper detection).
    #>
    param(
        [string]$Base64Blob,
        [byte[]]$AesKey,
        [byte[]]$HmacKey
    )

    $raw = [Convert]::FromBase64String($Base64Blob)
    if ($raw.Length -lt (16 + 32 + 1)) {
        throw "暗号化データが短すぎます"
    }

    $tagOffset = $raw.Length - 32
    $ivPlusCipher = $raw[0..($tagOffset - 1)]
    $storedTag = $raw[$tagOffset..($raw.Length - 1)]

    $hmac = [System.Security.Cryptography.HMACSHA256]::new($HmacKey)
    $computedTag = $hmac.ComputeHash($ivPlusCipher)
    $hmac.Dispose()

    # Constant-time HMAC comparison
    $ok = $true
    for ($i = 0; $i -lt 32; $i++) {
        if ($storedTag[$i] -ne $computedTag[$i]) { $ok = $false }
    }
    if (-not $ok) { throw "HMACの検証に失敗しました（データが改ざんされています）" }

    $iv = $ivPlusCipher[0..15]
    $cipherBytes = $ivPlusCipher[16..($ivPlusCipher.Length - 1)]

    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.KeySize = 256
    $aes.BlockSize = 128
    $aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
    $aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
    $aes.Key = $AesKey
    $aes.IV = $iv

    $decryptor = $aes.CreateDecryptor()
    $plainBytes = $decryptor.TransformFinalBlock($cipherBytes, 0, $cipherBytes.Length)
    $decryptor.Dispose()
    $aes.Dispose()

    return [System.Text.Encoding]::UTF8.GetString($plainBytes)
}

# ---------------------------------------------------------------------------
# SQLite schema helpers
# ---------------------------------------------------------------------------

function Initialize-OfflineCacheDB {
    <#
    .SYNOPSIS
    Creates the SQLite DB and schema at $DbPath if not present.
    Requires PSSQLite module.
    #>
    param([string]$DbPath)

    $dir = Split-Path $DbPath -Parent
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    $createSql = @"
CREATE TABLE IF NOT EXISTS offline_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT    NOT NULL,
    payload      BLOB    NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_collected_at ON offline_cache (collected_at);
"@
    Invoke-SqliteQuery -DataSource $DbPath -Query $createSql
}

# ---------------------------------------------------------------------------
# Public CRUD
# ---------------------------------------------------------------------------

function Add-ToOfflineCacheDB {
    <#
    .SYNOPSIS
    Encrypts $Entry (hashtable) and inserts into the SQLite cache.
    #>
    param(
        [string]$DbPath,
        [string]$KeyPath,
        [hashtable]$Entry
    )

    $keys = Get-CacheKey -KeyPath $KeyPath
    $json = $Entry | ConvertTo-Json -Depth 10 -Compress
    $blob = Protect-CachePayload -Plaintext $json -AesKey $keys.AesKey -HmacKey $keys.HmacKey
    $collectedAt = if ($Entry.ContainsKey('collected_at')) { $Entry['collected_at'] } else {
        (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    }

    $sql = "INSERT INTO offline_cache (collected_at, payload, attempts) VALUES (@at, @payload, 0)"
    Invoke-SqliteQuery -DataSource $DbPath -Query $sql -SqlParameters @{
        at      = $collectedAt
        payload = $blob
    }
}

function Read-OfflineCacheDB {
    <#
    .SYNOPSIS
    Returns all cached entries as an array of hashtables (decrypted).
    Rows that fail decryption are skipped with a warning.
    #>
    param(
        [string]$DbPath,
        [string]$KeyPath
    )

    if (-not (Test-Path $DbPath)) { return @() }

    $keys = Get-CacheKey -KeyPath $KeyPath
    $rows = Invoke-SqliteQuery -DataSource $DbPath -Query "SELECT id, payload FROM offline_cache ORDER BY id"
    $results = @()
    foreach ($row in $rows) {
        try {
            $json = Unprotect-CachePayload -Base64Blob $row.payload -AesKey $keys.AesKey -HmacKey $keys.HmacKey
            $obj  = $json | ConvertFrom-Json
            $ht   = @{ _cache_id = $row.id }
            $obj.PSObject.Properties | ForEach-Object { $ht[$_.Name] = $_.Value }
            $results += $ht
        } catch {
            Write-Warning "キャッシュ行 id=$($row.id) の復号をスキップ: $_"
        }
    }
    return $results
}

function Remove-SyncedEntries {
    <#
    .SYNOPSIS
    Removes rows by $Ids array after successful server sync.
    #>
    param(
        [string]$DbPath,
        [int[]]$Ids
    )

    if (-not $Ids -or $Ids.Count -eq 0) { return }
    $placeholders = ($Ids | ForEach-Object { "?" }) -join ","
    Invoke-SqliteQuery -DataSource $DbPath -Query "DELETE FROM offline_cache WHERE id IN ($placeholders)" -SqlParameters $Ids
}

function Remove-ExpiredEntries {
    <#
    .SYNOPSIS
    Deletes entries older than $script:CACHE_TTL_DAYS (default 30 days).
    #>
    param([string]$DbPath)

    if (-not (Test-Path $DbPath)) { return }
    $cutoff = (Get-Date).ToUniversalTime().AddDays(-$script:CACHE_TTL_DAYS).ToString("yyyy-MM-ddTHH:mm:ssZ")
    Invoke-SqliteQuery -DataSource $DbPath -Query "DELETE FROM offline_cache WHERE collected_at < @cutoff" -SqlParameters @{ cutoff = $cutoff }
}

function Migrate-LegacyJsonCache {
    <#
    .SYNOPSIS
    Migrates entries from the legacy JSON cache file into the new SQLite DB.
    Deletes the JSON file on success.
    #>
    param(
        [string]$JsonPath,
        [string]$DbPath,
        [string]$KeyPath
    )

    if (-not (Test-Path $JsonPath)) { return }

    try {
        $raw = Get-Content -Path $JsonPath -Raw -Encoding UTF8
        $entries = $raw | ConvertFrom-Json
    } catch {
        Write-Warning "レガシーキャッシュの読み込み失敗、移行をスキップ: $_"
        return
    }

    if ($null -eq $entries) { return }
    $list = @($entries)
    foreach ($e in $list) {
        $ht = @{}
        $e.PSObject.Properties | ForEach-Object { $ht[$_.Name] = $_.Value }
        try {
            Add-ToOfflineCacheDB -DbPath $DbPath -KeyPath $KeyPath -Entry $ht
        } catch {
            Write-Warning "エントリの移行失敗: $_"
        }
    }

    Remove-Item -Path $JsonPath -Force -ErrorAction SilentlyContinue
    Write-Host "[OfflineCacheDB] レガシーJSON ($($list.Count) 件) を SQLite に移行しました"
}

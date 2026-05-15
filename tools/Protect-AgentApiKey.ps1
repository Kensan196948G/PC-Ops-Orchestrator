<#
.SYNOPSIS
    Encrypt an Agent api_key with DPAPI (CurrentUser scope) for pre-deployment.
.DESCRIPTION
    Installers want to ship config.json without a plaintext api_key. This helper
    accepts plaintext (-PlainText, -ConfigPath, or stdin), encrypts via DPAPI
    under the current Windows user account, and emits base64 ciphertext suitable
    for the api_key_protected field. When -ConfigPath is provided, the script
    rewrites the config in place, removing the plaintext api_key field.

    Must run on the SAME Windows user account that will execute PCOpsAgent.ps1.
    DPAPI CurrentUser ciphertext cannot be decrypted by a different user.
.PARAMETER PlainText
    Plaintext API key. Use - (single dash) to read from stdin.
.PARAMETER ConfigPath
    Optional config.json path. When set, the script reads api_key from the file,
    encrypts it, writes api_key_protected back, and removes api_key.
.EXAMPLE
    pwsh tools/Protect-AgentApiKey.ps1 -PlainText "sk_live_xxx"
    # → prints base64 ciphertext to stdout

.EXAMPLE
    pwsh tools/Protect-AgentApiKey.ps1 -ConfigPath "C:\PCOpsAgent\config.json"
    # → migrates the file in place

.NOTES
    Issue #188 part 3. Mirrors the logic in agent/PCOpsAgent.ps1::Resolve-AgentApiKey
    so installer output round-trips correctly with the Agent runtime.
#>

[CmdletBinding(DefaultParameterSetName = "Inline")]
param(
    [Parameter(ParameterSetName = "Inline", Position = 0)]
    [string]$PlainText,

    [Parameter(ParameterSetName = "Config", Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"

if (-not ($IsWindows -or $PSVersionTable.PSVersion.Major -le 5)) {
    Write-Error "DPAPI は Windows 専用です。Windows 上で実行してください。"
    exit 1
}

if ($PSVersionTable.PSVersion.Major -le 5) {
    try { Add-Type -AssemblyName System.Security -ErrorAction Stop } catch {}
}

function Protect-Plaintext {
    param([Parameter(Mandatory = $true)][string]$Plain)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Plain)
    $cipher = [System.Security.Cryptography.ProtectedData]::Protect(
        $bytes, $null,
        [System.Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    return [Convert]::ToBase64String($cipher)
}

if ($PSCmdlet.ParameterSetName -eq "Config") {
    if (-not (Test-Path $ConfigPath)) {
        Write-Error "config.json が見つかりません: $ConfigPath"
        exit 1
    }
    $config = Get-Content -Path $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $hasPlain = $config.PSObject.Properties.Match('api_key').Count -gt 0 `
        -and -not [string]::IsNullOrWhiteSpace($config.api_key)
    if (-not $hasPlain) {
        Write-Error "config.json に平文 api_key がありません (migrate 不要)"
        exit 1
    }
    $b64 = Protect-Plaintext -Plain ([string]$config.api_key)

    $migrated = [ordered]@{}
    foreach ($p in $config.PSObject.Properties) {
        if ($p.Name -eq 'api_key') { continue }
        $migrated[$p.Name] = $p.Value
    }
    $migrated['api_key_protected'] = $b64

    $migrated | ConvertTo-Json -Depth 10 |
        Set-Content -Path $ConfigPath -Encoding UTF8
    Write-Host "migrated: api_key -> api_key_protected (length=$($b64.Length))"
    return
}

if ([string]::IsNullOrEmpty($PlainText) -or $PlainText -eq '-') {
    $PlainText = [Console]::In.ReadToEnd().Trim()
}

if ([string]::IsNullOrWhiteSpace($PlainText)) {
    Write-Error "PlainText が空です。-PlainText か -ConfigPath を指定してください。"
    exit 1
}

$b64 = Protect-Plaintext -Plain $PlainText
Write-Output $b64

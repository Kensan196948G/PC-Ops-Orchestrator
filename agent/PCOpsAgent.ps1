<#
.SYNOPSIS
    PC-Ops Orchestrator Agent - 情報収集・タスク実行エージェント
.DESCRIPTION
    HTTPS(443)のみを使用してサーバーと通信。
    情報収集（センサー）とタスク実行（指示取得）を行う。
    変更操作は行わず、サーバーからの指示に従う。
.NOTES
    Version: 1.0.0
    Author: PC-Ops Team
#>

param(
    [string]$ConfigPath = ""
)

#requires -Version 5.1

# === 設定 ===
$AGENT_VERSION = "1.0.0"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $ConfigPath -or -not (Test-Path $ConfigPath)) {
    $ConfigPath = Join-Path $SCRIPT_DIR "config.json"
}

$config = @{}
if (Test-Path $ConfigPath) {
    try {
        $config = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Error "設定ファイルの読み込みに失敗: $_"
        exit 1
    }
} else {
    $config = @{
        server_url = "https://localhost:5000"
        api_key = "default-agent-key"
        pc_name = ""
        collection_interval_minutes = 5
        log_level = "INFO"
        proxy = ""
        retry_count = 3
        retry_delay_seconds = 10
    }
}

# === TLS enforcement (Issue #187) ===
# Spec: ssl_verify must always be true. The config key is removed; any value left
# in legacy config.json is intentionally ignored so a tampered config cannot
# downgrade TLS. ServerCertificateValidationCallback is never overridden.
try {
    [System.Net.ServicePointManager]::SecurityProtocol = (
        [System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls13
    )
} catch {
    # PS 5.1 / older .NET fallback: Tls13 enum may be absent
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
}

$SERVER_URL = $config.server_url.TrimEnd('/')

# === DPAPI api_key protection (Issue #188 part 3) ===
# config.json は CurrentUser スコープの DPAPI で暗号化された api_key_protected
# (base64 ciphertext) を優先する。後方互換のため平文 api_key も受け付けるが、
# 起動時に必ず暗号化して config.json を書き直し、平文フィールドは削除する。
# どちらも欠落していた場合は fail-closed で exit 1。
#
# Why:
#   - 共有ホストで Agent ユーザに read 権限を持つ攻撃者が config.json を覗いても
#     Bearer Token をそのまま入手できない。DPAPI/CurrentUser は同じユーザー
#     アカウントでしか復号できないため、別ユーザーへの横展開を遮断する。
#   - 平文の自動移行を必須化することで、配布時に installer がうっかり平文を
#     残したまま運用に乗ってもインシデント化前に修復される。
function Resolve-AgentApiKey {
    param(
        [Parameter(Mandatory = $true)] $Config,
        [Parameter(Mandatory = $true)] [string]$ConfigPath
    )

    # PS 5.1 では System.Security を明示ロード（PS 7 の .NET 7+ はビルトイン）
    if ($PSVersionTable.PSVersion.Major -le 5) {
        try { Add-Type -AssemblyName System.Security -ErrorAction Stop } catch {}
    }

    $hasProtected = $Config.PSObject.Properties.Match('api_key_protected').Count -gt 0 `
        -and -not [string]::IsNullOrWhiteSpace($Config.api_key_protected)
    $hasPlain = $Config.PSObject.Properties.Match('api_key').Count -gt 0 `
        -and -not [string]::IsNullOrWhiteSpace($Config.api_key)

    if ($hasProtected) {
        try {
            $cipherBytes = [Convert]::FromBase64String($Config.api_key_protected)
            $plainBytes = [System.Security.Cryptography.ProtectedData]::Unprotect(
                $cipherBytes, $null,
                [System.Security.Cryptography.DataProtectionScope]::CurrentUser
            )
            return [System.Text.Encoding]::UTF8.GetString($plainBytes)
        } catch {
            Write-Error "api_key_protected の復号に失敗 (DPAPI scope=CurrentUser): $_"
            exit 1
        }
    }

    if ($hasPlain) {
        Write-Warning "config.json に平文 api_key を検出。DPAPI で暗号化して書き直します。"
        try {
            $plain = [string]$Config.api_key
            $plainBytes = [System.Text.Encoding]::UTF8.GetBytes($plain)
            $cipherBytes = [System.Security.Cryptography.ProtectedData]::Protect(
                $plainBytes, $null,
                [System.Security.Cryptography.DataProtectionScope]::CurrentUser
            )
            $b64 = [Convert]::ToBase64String($cipherBytes)
        } catch {
            Write-Error "api_key の DPAPI 暗号化に失敗: $_"
            exit 1
        }

        # config.json を再構築 (api_key を削除し api_key_protected を追加)
        $migrated = [ordered]@{}
        foreach ($p in $Config.PSObject.Properties) {
            if ($p.Name -eq 'api_key') { continue }
            $migrated[$p.Name] = $p.Value
        }
        $migrated['api_key_protected'] = $b64

        try {
            $migrated | ConvertTo-Json -Depth 10 |
                Set-Content -Path $ConfigPath -Encoding UTF8
        } catch {
            Write-Error "config.json への migrate 書き込みに失敗: $_"
            exit 1
        }
        return $plain
    }

    Write-Error "config.json に api_key も api_key_protected も存在しません。"
    exit 1
}

$API_KEY = Resolve-AgentApiKey -Config $config -ConfigPath $ConfigPath

$COLLECT_INTERVAL = [math]::Max(1, [int]$config.collection_interval_minutes)
$RETRY_COUNT = [int]$config.retry_count
$RETRY_DELAY = [int]$config.retry_delay_seconds
$LOG_LEVEL = $config.log_level
$PROXY = $config.proxy

$LOG_DIR = Join-Path $SCRIPT_DIR "logs"
if (-not (Test-Path $LOG_DIR)) {
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
}

# === Phase A-2 (#175): dot-source collector modules ===
# Missing collector files are reported (not silently skipped) so a corrupt
# deployment surfaces immediately instead of degrading collection coverage
# without warning.
$COLLECTORS_DIR = Join-Path $SCRIPT_DIR "collectors"
foreach ($mod in @("Get-HardwareInfo.ps1", "Get-SoftwareInfo.ps1", "Get-NetworkInfo.ps1")) {
    $modPath = Join-Path $COLLECTORS_DIR $mod
    if (Test-Path $modPath) {
        try {
            . $modPath
        } catch {
            Write-Warning "Collector module load failed: ${mod}: $_"
        }
    } else {
        Write-Warning "Collector module not found: $modPath — agent will run with reduced coverage"
    }
}

$CACHE_DIR = Join-Path $SCRIPT_DIR "cache"
if (-not (Test-Path $CACHE_DIR)) {
    New-Item -ItemType Directory -Path $CACHE_DIR -Force | Out-Null
}
$OFFLINE_CACHE_FILE = Join-Path $CACHE_DIR "offline_cache.json"
$MAX_CACHE_ENTRIES = 2016  # 7 days * 24 h * 12 (5-min interval)

# Resolved early so the Mutex name and the main loop see the same identity even
# if config.json is reloaded later. Renaming pc_name in config.json starts a
# fresh single-instance slot, which is the documented behavior.
$PC_NAME = if ($config.pc_name) { $config.pc_name } else { $env:COMPUTERNAME }

# === ログ関数 ===
function Write-AgentLog {
    param([string]$Message, [string]$Level = "INFO")
    $time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine = "$time [$Level] $Message"
    $logFile = Join-Path $LOG_DIR ("agent_" + (Get-Date -Format "yyyyMMdd") + ".log")

    Add-Content -Path $logFile -Value $logLine -Encoding UTF8
    if ($Level -eq "ERROR" -or $Level -eq "WARN") {
        Write-Host $logLine -ForegroundColor Yellow
    }
}

function Write-AgentError {
    param([string]$Message)
    Write-AgentLog -Message $Message -Level "ERROR"
}

function Write-AgentInfo {
    param([string]$Message)
    if ($LOG_LEVEL -in "INFO", "DEBUG") {
        Write-AgentLog -Message $Message -Level "INFO"
    }
}

function Write-AgentDebug {
    param([string]$Message)
    if ($LOG_LEVEL -eq "DEBUG") {
        Write-AgentLog -Message $Message -Level "DEBUG"
    }
}

# === VPN / Connection Detection ===
function Get-ConnectionType {
    # Check FortiClient SSL-VPN adapter
    try {
        $vpnAdapter = Get-NetAdapter -ErrorAction SilentlyContinue |
            Where-Object { $_.InterfaceDescription -match "FortiSSL|Fortinet SSL" -or $_.Name -match "fortissl|FortiSSL" }
        if ($vpnAdapter -and $vpnAdapter.Status -eq "Up") {
            return "SSL-VPN"
        }
    } catch {}

    # Fallback: check FortiClient process + any VPN adapter is up
    try {
        $fcProc = Get-Process -Name "FortiClient", "FortiTray", "FortiSSLVPN" -ErrorAction SilentlyContinue
        if ($fcProc) {
            $vpnIface = Get-NetIPInterface -ErrorAction SilentlyContinue |
                Where-Object { $_.InterfaceAlias -match "VPN|vpn|Tunnel|tunnel" -and $_.ConnectionState -eq "Connected" }
            if ($vpnIface) {
                return "SSL-VPN"
            }
        }
    } catch {}

    return "LAN"
}

# === Server Reachability ===
function Test-ServerReachable {
    try {
        $uri = [System.Uri]$SERVER_URL
        $params = @{
            Uri = "$SERVER_URL/api/health"
            Method = "GET"
            Headers = @{ "Authorization" = "Bearer $API_KEY" }
            UseBasicParsing = $true
            TimeoutSec = 10
        }
        if ($PROXY) { $params["Proxy"] = $PROXY }
        $r = Invoke-RestMethod @params
        return $true
    } catch {
        return $false
    }
}

# === Offline Cache ===
function Read-OfflineCache {
    if (-not (Test-Path $OFFLINE_CACHE_FILE)) {
        return @()
    }
    try {
        $raw = Get-Content $OFFLINE_CACHE_FILE -Raw -Encoding UTF8
        return ConvertFrom-Json $raw
    } catch {
        Write-AgentError "オフラインキャッシュ読み込み失敗: $_"
        return @()
    }
}

function Write-OfflineCache {
    param([array]$Entries)
    try {
        # Keep only last MAX_CACHE_ENTRIES to prevent unbounded growth
        if ($Entries.Count -gt $MAX_CACHE_ENTRIES) {
            $Entries = $Entries | Select-Object -Last $MAX_CACHE_ENTRIES
        }
        $Entries | ConvertTo-Json -Depth 10 -Compress | Set-Content -Path $OFFLINE_CACHE_FILE -Encoding UTF8
    } catch {
        Write-AgentError "オフラインキャッシュ書き込み失敗: $_"
    }
}

function Add-ToOfflineCache {
    param([hashtable]$Entry)
    $cache = @(Read-OfflineCache)
    $cache += $Entry
    Write-OfflineCache -Entries $cache
    Write-AgentInfo "オフラインキャッシュ追加: 合計 $($cache.Count) 件"
}

function Sync-OfflineCache {
    param([string]$PcName)
    $cache = @(Read-OfflineCache)
    if ($cache.Count -eq 0) {
        return
    }

    Write-AgentInfo "オフラインキャッシュ同期開始: $($cache.Count) 件"
    $body = @{
        pc_name = $PcName
        offline_cache = $cache
    }
    $response = Invoke-AgentRequest -Method "POST" -Endpoint "/api/collect/sync" -Body $body
    if ($response) {
        Write-AgentInfo "同期完了: inserted=$($response.inserted) skipped=$($response.skipped)"
        Remove-Item -Path $OFFLINE_CACHE_FILE -Force -ErrorAction SilentlyContinue
    } else {
        Write-AgentError "オフラインキャッシュ同期失敗、次回リトライ"
    }
}

# === HTTP Helper ===
function Invoke-AgentRequest {
    param(
        [string]$Method,
        [string]$Endpoint,
        [object]$Body = $null
    )
    $url = "$SERVER_URL$Endpoint"
    $params = @{
        Uri = $url
        Method = $Method
        Headers = @{
            "Authorization" = "Bearer $API_KEY"
            "Content-Type" = "application/json"
        }
        UseBasicParsing = $true
    }

    if ($PROXY) {
        $params["Proxy"] = $PROXY
    }

    if ($Body) {
        $jsonBody = $Body | ConvertTo-Json -Depth 10 -Compress
        $params["Body"] = $jsonBody
    }

    $lastError = $null
    for ($i = 0; $i -lt $RETRY_COUNT; $i++) {
        try {
            if ($i -gt 0) {
                Write-AgentInfo "リトライ $i/$RETRY_COUNT..."
                Start-Sleep -Seconds $RETRY_DELAY
            }
            $response = Invoke-RestMethod @params
            return $response
        } catch {
            $lastError = $_
            Write-AgentDebug "HTTP ${Method}:${Endpoint} 失敗 ($($_.Exception.Message))"
        }
    }

    Write-AgentError "通信失敗: $Method $Endpoint ($($lastError.Exception.Message))"
    return $null
}

# === 情報収集 ===
function Get-PCSystemInfo {
    $info = @{
        pc_name = ""
        domain = ""
        os_version = ""
        os_architecture = ""
        cpu_name = ""
        cpu_cores = 0
        cpu_logical_processors = 0
        memory_total_gb = 0
        memory_available_gb = 0
        disk_total_gb = 0
        disk_free_gb = 0
        ip_address = ""
        mac_address = ""
        agent_version = $AGENT_VERSION
        cpu_usage = $null
        uptime_days = $null
        pending_reboot = $false
        windows_update_pending = $false
    }

    try {
        $cs = Get-CimInstance Win32_ComputerSystem
        $info.pc_name = $env:COMPUTERNAME
        $info.domain = $cs.Domain
        $info.cpu_name = ($cs | Select-Object -ExpandProperty Name)
        $info.cpu_logical_processors = $cs.NumberOfLogicalProcessors
        $info.cpu_cores = $cs.NumberOfProcessors

        $os = Get-CimInstance Win32_OperatingSystem
        $info.os_version = $os.Caption
        $info.os_architecture = $os.OSArchitecture
        $info.memory_total_gb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
        $info.memory_available_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)

        $disk = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Where-Object { $_.DeviceID -eq $env:SystemDrive }
        if ($disk) {
            $info.disk_total_gb = [math]::Round($disk.Size / 1GB, 1)
            $info.disk_free_gb = [math]::Round($disk.FreeSpace / 1GB, 1)
        }

        $uptime = (Get-Date) - $os.LastBootUpTime
        $info.uptime_days = [math]::Round($uptime.TotalDays, 1)
    } catch {
        Write-AgentError "システム情報取得失敗: $_"
    }

    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
            $_.InterfaceAlias -notlike "*Loopback*" -and $_.PrefixOrigin -ne "Wellknown"
        } | Select-Object -First 1)
        if ($ip) {
            $info.ip_address = $ip.IPAddress
        }
    } catch {}

    try {
        $mac = (Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | Select-Object -First 1)
        if ($mac) {
            $info.mac_address = $mac.MacAddress
        }
    } catch {}

    try {
        $cpuPerf = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average
        if ($cpuPerf.Average -ge 0) {
            $info.cpu_usage = [math]::Round($cpuPerf.Average, 1)
        }
    } catch {}

    try {
        $reboot = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update" -Name RebootRequired -ErrorAction SilentlyContinue
        if ($reboot) { $info.pending_reboot = $true }

        $reboot2 = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update" -Name RebootPending -ErrorAction SilentlyContinue
        if ($reboot2) { $info.pending_reboot = $true }
    } catch {}

    try {
        $wuau = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update" -Name AUState -ErrorAction SilentlyContinue
        if ($wuau -and $wuau.AUState -eq 2) {
            $info.windows_update_pending = $true
        }
    } catch {}

    return $info
}

function Get-PCSoftwareList {
    try {
        $software = Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" |
            Where-Object { $_.DisplayName -and $_.DisplayName.Trim() } |
            Select-Object @{N="name";E={$_.DisplayName}},
                         @{N="version";E={$_.DisplayVersion}},
                         @{N="publisher";E={$_.Publisher}},
                         @{N="install_date";E={if ($_.InstallDate) { try { [datetime]::ParseExact($_.InstallDate, "yyyyMMdd", $null).ToString("yyyy-MM-dd") } catch { $null } } }}

        $software32 = Get-ItemProperty "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -and $_.DisplayName.Trim() } |
            Select-Object @{N="name";E={$_.DisplayName}},
                         @{N="version";E={$_.DisplayVersion}},
                         @{N="publisher";E={$_.Publisher}},
                         @{N="install_date";E={if ($_.InstallDate) { try { [datetime]::ParseExact($_.InstallDate, "yyyyMMdd", $null).ToString("yyyy-MM-dd") } catch { $null } } }}

        return @($software) + @($software32) | Sort-Object name -Unique
    } catch {
        Write-AgentError "ソフトウェア一覧取得失敗: $_"
        return @()
    }
}

function Get-PCWindowsUpdates {
    try {
        $session = New-Object -ComObject Microsoft.Update.Session
        $searcher = $session.CreateUpdateSearcher()
        $history = $searcher.QueryHistory(0, $searcher.GetTotalHistoryCount())

        $updates = $history | ForEach-Object {
            $title = $_.Title
            $kbMatch = [regex]::Match($title, 'KB\d+')
            $kbId = if ($kbMatch.Success) { $kbMatch.Value } else { $null }

            $date = $null
            try { $date = $_.Date.ToString("yyyy-MM-ddTHH:mm:ss") } catch {}

            return @{
                kb_id = $kbId
                title = $title
                severity = $_.Categories | Where-Object { $_.Name -match "Update" } | Select-Object -First 1 -ExpandProperty Name
                installed = $_.ResultCode -eq 2
                installed_at = $date
            }
        }

        return @($updates) | Select-Object -First 200
    } catch {
        Write-AgentDebug "Windows Update履歴取得失敗: $_"
        return @()
    }
}

function Get-PCEventLogs {
    param(
        [string[]]$LogNames = @("System", "Application"),
        [int]$MaxEvents = 50,
        [string]$MinLevel = "Error"
    )
    try {
        $logs = @()
        foreach ($logName in $LogNames) {
            try {
                $events = Get-WinEvent -LogName $logName -MaxEvents $MaxEvents -ErrorAction SilentlyContinue |
                    Where-Object { $_.LevelDisplayName -eq $MinLevel -or $_.LevelDisplayName -eq "Warning" } |
                    Select-Object -First ([math]::Floor($MaxEvents / $LogNames.Count)) |
                    ForEach-Object {
                        @{
                            log_type = $logName
                            event_id = $_.Id
                            level = $_.LevelDisplayName
                            source = $_.ProviderName
                            message = $_.Message.Substring(0, [math]::Min(500, $_.Message.Length))
                            generated_at = $_.TimeCreated.ToString("yyyy-MM-ddTHH:mm:ss")
                        }
                    }
                $logs += $events
            } catch {}
        }
        return $logs | Select-Object -First $MaxEvents
    } catch {
        return @()
    }
}

# === タスク実行 ===
function Invoke-AssignedTask {
    param(
        [int]$TaskId,
        [string]$TaskType,
        [string]$Command,
        [string]$Parameters
    )
    Write-AgentInfo "タスク実行開始: ID=$TaskId Type=$TaskType"

    $result = @{}
    $errorMsg = $null
    $status = "completed"

    try {
        switch ($TaskType) {
            "cleanup" {
                $result = Invoke-CleanupTask -Parameters $Parameters
            }
            "update" {
                $result = Invoke-UpdateTask -Parameters $Parameters
            }
            "diagnose" {
                $result = Invoke-DiagnoseTask -Parameters $Parameters
            }
            "custom" {
                if ($Command) {
                    Write-AgentInfo "カスタムコマンド実行: $Command"
                    $output = Invoke-Expression $Command 2>&1
                    $result = @{ output = "$output" }
                }
            }
            default {
                $status = "failed"
                $errorMsg = "不明なタスク種別: $TaskType"
            }
        }
    } catch {
        $status = "failed"
        $errorMsg = $_.Exception.Message
        Write-AgentError "タスク実行失敗: $errorMsg"
    }

    $body = @{
        task_id = $TaskId
        status = $status
        result = $result
        error_message = $errorMsg
    }

    $response = Invoke-AgentRequest -Method "POST" -Endpoint "/api/result" -Body $body
    if ($response) {
        Write-AgentInfo "タスク結果送信完了: ID=$TaskId Status=$status"
    }
}

function Invoke-CleanupTask {
    param([string]$Parameters)
    Write-AgentInfo "クリーンアップタスク実行"
    return @{ message = "Cleanup completed"; action = "cleanup" }
}

function Invoke-UpdateTask {
    param([string]$Parameters)
    Write-AgentInfo "更新タスク実行"
    return @{ message = "Update check completed"; action = "update" }
}

function Invoke-DiagnoseTask {
    param([string]$Parameters)
    Write-AgentInfo "診断タスク実行"
    return @{ message = "Diagnosis completed"; action = "diagnose" }
}

# === メインループ ===
function Start-AgentLoop {
    Write-AgentInfo "Agent起動: v$AGENT_VERSION"

    $pcName = $PC_NAME
    Write-AgentInfo "PC Name: $pcName, Server: $SERVER_URL"

    while ($true) {
        try {
            Write-AgentInfo "=== 情報収集開始 ==="

            # Detect connection type before collecting
            $connectionType = Get-ConnectionType
            Write-AgentDebug "接続種別: $connectionType"

            $systemInfo = Get-PCSystemInfo
            $systemInfo.pc_name = $pcName
            $systemInfo.connection_type = $connectionType
            $systemInfo.last_boot_time = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).LastBootUpTime.ToString("yyyy-MM-ddTHH:mm:ss")
            Write-AgentDebug "システム情報取得完了"

            # Phase A-2 (#175): augment payload with hardware block / network array / os_build flat key.
            # Old servers ignore unknown keys; new servers (routes/collect.py) ingest them.
            # Collector failures are logged at WARN (not DEBUG) so operators can
            # see when hardware/NIC coverage silently drops in production logs.
            try {
                if (Get-Command Get-HardwareInfo -ErrorAction SilentlyContinue) {
                    $hardware = Get-HardwareInfo
                    if ($hardware) {
                        $systemInfo.hardware = $hardware
                        if ($hardware.os_build) { $systemInfo.os_build = $hardware.os_build }
                    }
                }
            } catch {
                Write-AgentLog -Message "Get-HardwareInfo 失敗: $_" -Level "WARN"
            }
            try {
                if (Get-Command Get-NetworkInfo -ErrorAction SilentlyContinue) {
                    $nics = Get-NetworkInfo
                    if ($nics) { $systemInfo.network = @($nics) }
                }
            } catch {
                Write-AgentLog -Message "Get-NetworkInfo 失敗: $_" -Level "WARN"
            }

            # Check server reachability
            if (-not (Test-ServerReachable)) {
                Write-AgentInfo "サーバー未到達 ($connectionType) — キャッシュに保存"
                $cacheEntry = $systemInfo.Clone()
                $cacheEntry.collected_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
                Add-ToOfflineCache -Entry $cacheEntry
                Write-AgentInfo "=== オフラインキャッシュ保存完了 ==="
                Start-Sleep -Seconds ($COLLECT_INTERVAL * 60)
                continue
            }

            # Server reachable — sync pending offline cache first
            Sync-OfflineCache -PcName $pcName

            $response = Invoke-AgentRequest -Method "POST" -Endpoint "/api/collect" -Body $systemInfo
            if (-not $response) {
                Write-AgentError "情報送信失敗 — オフラインキャッシュに追加"
                $cacheEntry = $systemInfo.Clone()
                $cacheEntry.collected_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
                Add-ToOfflineCache -Entry $cacheEntry
                Start-Sleep -Seconds ($COLLECT_INTERVAL * 60)
                continue
            }

            Write-AgentInfo "情報送信成功: PC_ID=$($response.pc_id) Score=$($response.health_score) Status=$($response.status)"

            if ($response.pending_tasks -and $response.pending_tasks.Count -gt 0) {
                Write-AgentInfo "保留中のタスク: $($response.pending_tasks.Count)件"
                foreach ($task in $response.pending_tasks) {
                    Invoke-AssignedTask -TaskId $task.id -TaskType $task.task_type -Command $task.command -Parameters $task.parameters
                }
            } else {
                Write-AgentDebug "保留タスクなし"
            }

            $sendDetail = $false
            if ($sendDetail) {
                $software = Get-PCSoftwareList
                $updates = Get-PCWindowsUpdates
                $events = Get-PCEventLogs

                $detailBody = @{
                    pc_name = $pcName
                    software = $software
                    windows_updates = $updates
                    event_logs = $events
                }
                Invoke-AgentRequest -Method "POST" -Endpoint "/api/collect/detail" -Body $detailBody | Out-Null
                Write-AgentInfo "詳細情報送信完了"
            }

            Write-AgentInfo "=== 情報収集完了 ==="

        } catch {
            Write-AgentError "収集ループエラー: $_"
        }

        Write-AgentInfo "次の収集まで ${COLLECT_INTERVAL}分待機..."
        Start-Sleep -Seconds ($COLLECT_INTERVAL * 60)
    }
}

# === Self-check (Issue #188 part 2) ===
# Verify the integrity of the Agent install before acquiring the single-instance
# Mutex. A manifest.json shipped alongside PCOpsAgent.ps1 carries SHA-256 hashes
# of every file the Agent loads (the entry script + collectors + scheduled-task
# registrar). Mismatch or missing manifest is fail-closed: the Agent refuses to
# start so a tampered binary cannot collect data or fetch tasks.
#
# This runs *before* the Mutex so a tampered second instance is rejected at the
# earliest point. The manifest path is fixed alongside SCRIPT_DIR; an attacker
# who can rewrite manifest.json can also rewrite the script itself, so this is a
# tamper-evidence layer (not anti-tamper). Combined with later DPAPI api_key
# protection (#188 part 3) and HMAC job signing (#188 part 4), it raises the bar
# for an attacker swapping files on disk.
function Test-AgentIntegrity {
    param([string]$AgentRoot)

    $manifestPath = Join-Path $AgentRoot "manifest.json"
    if (-not (Test-Path $manifestPath)) {
        Write-AgentError "Self-check失敗: manifest.json が見つかりません: $manifestPath"
        return $false
    }

    try {
        $manifest = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-AgentError "Self-check失敗: manifest.json 解析エラー: $_"
        return $false
    }

    if (-not $manifest.files) {
        Write-AgentError "Self-check失敗: manifest.json に files セクションがありません"
        return $false
    }

    if ($manifest.algorithm -and $manifest.algorithm -ne "SHA-256") {
        Write-AgentError "Self-check失敗: 未対応のアルゴリズム: $($manifest.algorithm)"
        return $false
    }

    foreach ($prop in $manifest.files.PSObject.Properties) {
        $relPath = $prop.Name
        $expected = $prop.Value
        if ([string]::IsNullOrWhiteSpace($expected) -or $expected -eq "PLACEHOLDER") {
            Write-AgentError "Self-check失敗: $relPath のハッシュが未定義 (PLACEHOLDER)"
            return $false
        }
        $absPath = Join-Path $AgentRoot $relPath
        if (-not (Test-Path $absPath)) {
            Write-AgentError "Self-check失敗: ファイル欠落: $relPath"
            return $false
        }
        try {
            $actual = (Get-FileHash -Path $absPath -Algorithm SHA256 -ErrorAction Stop).Hash
        } catch {
            Write-AgentError "Self-check失敗: ${relPath} のハッシュ計算エラー: $_"
            return $false
        }
        if ($actual.ToUpperInvariant() -ne $expected.ToUpperInvariant()) {
            Write-AgentError "Self-check失敗: ${relPath} 改竄検知 expected=$expected actual=$actual"
            return $false
        }
    }
    return $true
}

if (-not (Test-AgentIntegrity -AgentRoot $SCRIPT_DIR)) {
    Write-AgentError "Agent 自己検証に失敗したため起動を中止します。manifest.json と配布物を確認してください。"
    exit 1
}
Write-AgentInfo "Self-check成功: manifest 一致を確認"

# === エントリーポイント ===
# Single-instance enforcement (Issue #188 part 1).
# A machine-wide named Mutex prevents a second PCOpsAgent process on the same
# install dir from racing the first one on collect / cache / pending-task
# execution. The lock key is derived from $SCRIPT_DIR (the Agent install path)
# rather than $PC_NAME — pc_name is user-editable and may legitimately contain
# '\' (e.g. "DOMAIN\PC01"), which is reserved by Windows as the Global\ namespace
# separator and would throw at New-Object Mutex. SHA-256 of the install path
# truncated to 16 hex chars yields a stable, sanitized identifier; two distinct
# Agent installs on the same host (testing scenario) still get separate locks.
$pathBytes = [System.Text.Encoding]::UTF8.GetBytes($SCRIPT_DIR.ToLowerInvariant())
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $installFingerprint = [System.BitConverter]::ToString($sha.ComputeHash($pathBytes)).Replace("-", "").Substring(0, 16)
} finally {
    $sha.Dispose()
}
$mutexName = "Global\PCOpsAgent_$installFingerprint"
$mutexAcquired = $false
$agentMutex = $null
try {
    $agentMutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$mutexAcquired)
    if (-not $mutexAcquired) {
        Write-AgentError "別のAgentインスタンスが既に起動中: $mutexName"
        exit 1
    }
    Write-AgentInfo "Single-instance Mutex取得: $mutexName"

    try {
        Start-AgentLoop
    } catch {
        Write-AgentError "Agent致命的エラー: $_"
        exit 1
    }
} finally {
    if ($agentMutex) {
        if ($mutexAcquired) {
            try { $agentMutex.ReleaseMutex() } catch { }
        }
        $agentMutex.Dispose()
    }
}

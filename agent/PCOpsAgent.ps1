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
        ssl_verify = $true
        retry_count = 3
        retry_delay_seconds = 10
    }
}

$SERVER_URL = $config.server_url.TrimEnd('/')
$API_KEY = $config.api_key
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
$COLLECTORS_DIR = Join-Path $SCRIPT_DIR "collectors"
foreach ($mod in @("Get-HardwareInfo.ps1", "Get-SoftwareInfo.ps1", "Get-NetworkInfo.ps1")) {
    $modPath = Join-Path $COLLECTORS_DIR $mod
    if (Test-Path $modPath) {
        . $modPath
    }
}

$CACHE_DIR = Join-Path $SCRIPT_DIR "cache"
if (-not (Test-Path $CACHE_DIR)) {
    New-Item -ItemType Directory -Path $CACHE_DIR -Force | Out-Null
}
$OFFLINE_CACHE_FILE = Join-Path $CACHE_DIR "offline_cache.json"
$MAX_CACHE_ENTRIES = 2016  # 7 days * 24 h * 12 (5-min interval)

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
        if (-not $config.ssl_verify) {
            [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        }
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

    if (-not $config.ssl_verify) {
        if (-not ([System.Net.ServicePointManager]::ServerCertificateValidationCallback)) {
            [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        }
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

    $pcName = if ($config.pc_name) { $config.pc_name } else { $env:COMPUTERNAME }
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
            try {
                if (Get-Command Get-HardwareInfo -ErrorAction SilentlyContinue) {
                    $hardware = Get-HardwareInfo
                    if ($hardware) {
                        $systemInfo.hardware = $hardware
                        if ($hardware.os_build) { $systemInfo.os_build = $hardware.os_build }
                    }
                }
            } catch {
                Write-AgentDebug "Get-HardwareInfo 失敗: $_"
            }
            try {
                if (Get-Command Get-NetworkInfo -ErrorAction SilentlyContinue) {
                    $nics = Get-NetworkInfo
                    if ($nics) { $systemInfo.network = @($nics) }
                }
            } catch {
                Write-AgentDebug "Get-NetworkInfo 失敗: $_"
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

# === エントリーポイント ===
try {
    Start-AgentLoop
} catch {
    Write-AgentError "Agent致命的エラー: $_"
    exit 1
}

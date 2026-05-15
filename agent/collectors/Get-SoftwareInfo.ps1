<#
.SYNOPSIS
    Software information collector (Phase A-2 / Issue #175).
.DESCRIPTION
    Returns installed programs (HKLM 32/64-bit Uninstall keys) plus Windows
    Update history. The structure is compatible with /api/collect/detail's
    `software` and `windows_updates` arrays.
#>

#requires -Version 5.1

function Get-InstalledPrograms {
    [CmdletBinding()]
    param(
        [int]$MaxItems = 500
    )

    $paths = @(
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )

    $results = @()
    foreach ($path in $paths) {
        try {
            $items = Get-ItemProperty $path -ErrorAction SilentlyContinue |
                Where-Object { $_.DisplayName -and $_.DisplayName.Trim() }
            foreach ($it in $items) {
                $installDate = $null
                if ($it.InstallDate) {
                    try {
                        $installDate = [datetime]::ParseExact($it.InstallDate, "yyyyMMdd", $null).ToString("yyyy-MM-dd")
                    } catch {
                        $installDate = $null
                    }
                }
                $results += @{
                    name         = $it.DisplayName
                    version      = $it.DisplayVersion
                    publisher    = $it.Publisher
                    install_date = $installDate
                }
            }
        } catch {
            Write-Verbose "Uninstall キー読み込み失敗 ($path): $_"
        }
    }

    return @($results | Sort-Object name -Unique | Select-Object -First $MaxItems)
}

function Get-WindowsUpdateHistory {
    [CmdletBinding()]
    param(
        [int]$MaxItems = 200
    )

    try {
        $session  = New-Object -ComObject Microsoft.Update.Session
        $searcher = $session.CreateUpdateSearcher()
        $total    = $searcher.GetTotalHistoryCount()
        if ($total -le 0) {
            return @()
        }
        $history = $searcher.QueryHistory(0, [math]::Min($total, $MaxItems))

        $updates = @()
        foreach ($entry in $history) {
            $title = $entry.Title
            $kbMatch = [regex]::Match($title, 'KB\d+')
            $kbId    = if ($kbMatch.Success) { $kbMatch.Value } else { $null }

            $date = $null
            try { $date = $entry.Date.ToString("yyyy-MM-ddTHH:mm:ss") } catch {}

            $severity = $null
            try {
                $category = $entry.Categories |
                    Where-Object { $_.Name -match "Update" } |
                    Select-Object -First 1
                if ($category) { $severity = $category.Name }
            } catch {}

            $updates += @{
                kb_id        = $kbId
                title        = $title
                severity     = $severity
                installed    = ($entry.ResultCode -eq 2)
                installed_at = $date
            }
        }
        return @($updates)
    } catch {
        Write-Verbose "Windows Update 履歴取得失敗: $_"
        return @()
    }
}

function Get-PendingWindowsUpdate {
    [CmdletBinding()]
    param()

    $status = @{
        pending_reboot          = $false
        windows_update_pending  = $false
    }

    try {
        $kbRoot = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update"
        foreach ($name in @("RebootRequired", "RebootPending")) {
            try {
                $val = Get-ItemProperty $kbRoot -Name $name -ErrorAction Stop
                if ($val) { $status.pending_reboot = $true }
            } catch {}
        }
        try {
            $au = Get-ItemProperty $kbRoot -Name AUState -ErrorAction Stop
            if ($au -and $au.AUState -eq 2) {
                $status.windows_update_pending = $true
            }
        } catch {}
    } catch {
        Write-Verbose "Windows Update 状態取得失敗: $_"
    }

    return $status
}

function Get-SoftwareInfo {
    [CmdletBinding()]
    param(
        [int]$MaxPrograms = 500,
        [int]$MaxUpdates  = 200
    )
    return @{
        software        = Get-InstalledPrograms -MaxItems $MaxPrograms
        windows_updates = Get-WindowsUpdateHistory -MaxItems $MaxUpdates
        update_status   = Get-PendingWindowsUpdate
    }
}

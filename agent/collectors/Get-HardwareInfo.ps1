<#
.SYNOPSIS
    Hardware information collector (Phase A-2 / Issue #175).
.DESCRIPTION
    Collects CPU / RAM / Disk / Manufacturer / Model details plus the Windows
    build number (os_build) introduced in Phase A-1.

    Returned hashtable is suitable for inclusion under the `hardware` key of
    the /api/collect payload while remaining compatible with the legacy v1
    flat dictionary.
#>

#requires -Version 5.1

function Get-HardwareInfo {
    [CmdletBinding()]
    param()

    $hw = @{
        manufacturer            = $null
        model                   = $null
        serial_number           = $null
        bios_version            = $null
        bios_release_date       = $null
        os_build                = $null
        cpu_name                = $null
        cpu_cores               = $null
        cpu_logical_processors  = $null
        cpu_max_clock_mhz       = $null
        memory_total_gb         = $null
        memory_available_gb     = $null
        disks                   = @()
    }

    try {
        $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
        $hw.manufacturer = $cs.Manufacturer
        $hw.model        = $cs.Model
        if ($cs.TotalPhysicalMemory) {
            $hw.memory_total_gb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
        }
    } catch {
        Write-Verbose "Win32_ComputerSystem 取得失敗: $_"
    }

    try {
        $bios = Get-CimInstance Win32_BIOS -ErrorAction Stop
        $hw.serial_number     = $bios.SerialNumber
        $hw.bios_version      = ($bios.SMBIOSBIOSVersion, $bios.Version | Where-Object { $_ } | Select-Object -First 1)
        if ($bios.ReleaseDate) {
            try {
                $hw.bios_release_date = ([Management.ManagementDateTimeConverter]::ToDateTime($bios.ReleaseDate)).ToString("yyyy-MM-dd")
            } catch {
                $hw.bios_release_date = $null
            }
        }
    } catch {
        Write-Verbose "Win32_BIOS 取得失敗: $_"
    }

    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        if ($os.FreePhysicalMemory) {
            $hw.memory_available_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        }
        if ($os.BuildNumber) {
            $ubr = $null
            try {
                $ubr = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -Name UBR -ErrorAction Stop).UBR
            } catch { $ubr = $null }
            if ($ubr) {
                $hw.os_build = "{0}.{1}" -f $os.BuildNumber, $ubr
            } else {
                $hw.os_build = "$($os.BuildNumber)"
            }
        }
    } catch {
        Write-Verbose "Win32_OperatingSystem 取得失敗: $_"
    }

    try {
        $procs = @(Get-CimInstance Win32_Processor -ErrorAction Stop)
        if ($procs.Count -gt 0) {
            $hw.cpu_name              = $procs[0].Name
            $hw.cpu_max_clock_mhz     = $procs[0].MaxClockSpeed
            $hw.cpu_cores             = ($procs | Measure-Object -Property NumberOfCores -Sum).Sum
            $hw.cpu_logical_processors= ($procs | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        }
    } catch {
        Write-Verbose "Win32_Processor 取得失敗: $_"
    }

    try {
        $disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction Stop
        foreach ($d in $disks) {
            $hw.disks += @{
                drive_letter = $d.DeviceID
                file_system  = $d.FileSystem
                total_gb     = if ($d.Size) { [math]::Round($d.Size / 1GB, 1) } else { $null }
                free_gb      = if ($d.FreeSpace) { [math]::Round($d.FreeSpace / 1GB, 1) } else { $null }
                volume_name  = $d.VolumeName
            }
        }
    } catch {
        Write-Verbose "Win32_LogicalDisk 取得失敗: $_"
    }

    return $hw
}

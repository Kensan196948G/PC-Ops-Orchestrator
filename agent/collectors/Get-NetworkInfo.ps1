<#
.SYNOPSIS
    Network interface collector (Phase A-2 / Issue #175).
.DESCRIPTION
    Enumerates all active NICs (Status=Up) and returns one entry per interface
    with IP / MAC / DNS / gateway / link-speed. Structure matches the
    NetworkInterface model (server/models.py) so /api/collect can upsert rows
    directly under the `network` payload key.
#>

#requires -Version 5.1

function Get-NetworkInfo {
    [CmdletBinding()]
    param()

    $results = @()

    try {
        $adapters = @(Get-NetAdapter -ErrorAction Stop | Where-Object { $_.Status -eq "Up" })
    } catch {
        Write-Verbose "Get-NetAdapter 失敗: $_"
        return $results
    }

    foreach ($adapter in $adapters) {
        $entry = @{
            interface_name  = $adapter.Name
            description     = $adapter.InterfaceDescription
            mac_address     = $adapter.MacAddress
            ip_address      = $null
            ipv6_address    = $null
            subnet_mask     = $null
            gateway         = $null
            dns_servers     = $null
            link_speed_mbps = $null
            is_active       = $true
        }

        try {
            if ($adapter.LinkSpeed) {
                $speed = $adapter.LinkSpeed
                $mbps = $null
                if ($speed -is [string]) {
                    if ($speed -match '([\d\.]+)\s*Gbps') {
                        $mbps = [int]([double]$Matches[1] * 1000)
                    } elseif ($speed -match '([\d\.]+)\s*Mbps') {
                        $mbps = [int]([double]$Matches[1])
                    }
                } else {
                    $mbps = [int]([double]$speed / 1e6)
                }
                # 0 indicates "unknown" from the driver; persist as null
                # so dashboards do not display a misleading 0 Mbps link.
                if ($mbps -and $mbps -gt 0) {
                    $entry.link_speed_mbps = $mbps
                }
            }
        } catch {}

        try {
            $ip4 = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Where-Object { $_.PrefixOrigin -ne "WellKnown" } |
                Select-Object -First 1
            if ($ip4) {
                $entry.ip_address  = $ip4.IPAddress
                $entry.subnet_mask = (ConvertTo-SubnetMask -PrefixLength $ip4.PrefixLength)
            }
        } catch {}

        try {
            $ip6 = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv6 -ErrorAction SilentlyContinue |
                Where-Object { $_.PrefixOrigin -ne "WellKnown" -and $_.IPAddress -notlike 'fe80*' } |
                Select-Object -First 1
            if ($ip6) { $entry.ipv6_address = $ip6.IPAddress }
        } catch {}

        try {
            $route = Get-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
                Sort-Object -Property RouteMetric |
                Select-Object -First 1
            if ($route) { $entry.gateway = $route.NextHop }
        } catch {}

        try {
            $dns = Get-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue
            if ($dns -and $dns.ServerAddresses) {
                $entry.dns_servers = ($dns.ServerAddresses -join ",")
            }
        } catch {}

        $results += $entry
    }

    return $results
}

function ConvertTo-SubnetMask {
    [CmdletBinding()]
    param([int]$PrefixLength)

    if ($PrefixLength -lt 0 -or $PrefixLength -gt 32) {
        return $null
    }
    $bits = ('1' * $PrefixLength).PadRight(32, '0')
    $octets = @()
    for ($i = 0; $i -lt 4; $i++) {
        $octets += [Convert]::ToInt32($bits.Substring($i * 8, 8), 2)
    }
    return ($octets -join ".")
}

"""WinRM-based remote PC data collection service (Phase I-2, Issue #304).

Connects to a Windows endpoint via WinRM and runs PowerShell scripts to
collect the same payload format used by the local Windows agent, enabling
agentless management of Windows PCs.

Environment variables
---------------------
WINRM_USER          Login user (e.g. .\\mirai-user or DOMAIN\\user)
WINRM_PASSWORD      Login password
WINRM_PORT          WinRM port (default 5985)
WINRM_TRANSPORT     Authentication transport (default ntlm; basic/kerberos/certificate)
WINRM_SSL           Use HTTPS (true/false, default false)
WINRM_SSL_INSECURE  Skip TLS certificate verification when SSL is enabled.
                    DANGER: exposes connections to MITM attacks.
                    Only set to "true" for local dev/lab environments where
                    you own all network paths between server and target PC.
                    Production deployments should use WINRM_CA_BUNDLE instead.
WINRM_CA_BUNDLE     Path to a CA certificate file (PEM) for verifying the
                    remote endpoint's TLS certificate. Use this for internal
                    CAs or self-signed certs instead of disabling verification.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# PowerShell script that collects basic system information as JSON.
_PS_SYSINFO = r"""
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$memTotal = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
$memFree = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$diskTotal = if ($disk) { [math]::Round($disk.Size / 1GB, 2) } else { $null }
$diskFree = if ($disk) { [math]::Round($disk.FreeSpace / 1GB, 2) } else { $null }
$lastBoot = $os.LastBootUpTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$result = @{
    pc_name    = $env:COMPUTERNAME
    domain     = $env:USERDOMAIN
    os_version = $os.Caption
    os_build   = $os.BuildNumber
    os_architecture = $os.OSArchitecture
    cpu_name   = $cpu.Name
    cpu_cores  = [int]$cpu.NumberOfCores
    cpu_logical_processors = [int]$cpu.NumberOfLogicalProcessors
    memory_total_gb     = $memTotal
    memory_available_gb = $memFree
    disk_total_gb  = $diskTotal
    disk_free_gb   = $diskFree
    last_boot_time = $lastBoot
    uptime_days    = [math]::Round(((Get-Date).ToUniversalTime() - $os.LastBootUpTime.ToUniversalTime()).TotalDays, 2)
    pending_reboot = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')
}
$result | ConvertTo-Json -Compress
"""

# PowerShell script that lists installed software.
_PS_SOFTWARE = r"""
$ErrorActionPreference = 'SilentlyContinue'
$paths = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$sw = Get-ItemProperty $paths |
    Where-Object { $_.DisplayName } |
    Select-Object DisplayName,DisplayVersion,Publisher,InstallDate |
    ForEach-Object {
        $date = $null
        if ($_.InstallDate -match '^\d{8}$') {
            $date = '{0}-{1}-{2}' -f $_.InstallDate.Substring(0,4), $_.InstallDate.Substring(4,2), $_.InstallDate.Substring(6,2)
        }
        @{
            name         = $_.DisplayName
            version      = $_.DisplayVersion
            publisher    = $_.Publisher
            install_date = $date
        }
    }
$sw | ConvertTo-Json -Compress
"""

# PowerShell script that lists installed Windows updates (hotfixes).
_PS_UPDATES = r"""
$ErrorActionPreference = 'SilentlyContinue'
$hf = Get-HotFix | Select-Object HotFixID,Description,InstalledOn | ForEach-Object {
    $dt = $null
    if ($_.InstalledOn) {
        $dt = $_.InstalledOn.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
    @{
        kb_id        = $_.HotFixID
        title        = $_.Description
        installed    = $true
        installed_at = $dt
    }
}
$hf | ConvertTo-Json -Compress
"""


def _winrm_config():
    """Return WinRM connection parameters from environment variables."""
    user = os.environ.get("WINRM_USER", "")
    password = os.environ.get("WINRM_PASSWORD", "")
    port = int(os.environ.get("WINRM_PORT", "5985"))
    transport = os.environ.get("WINRM_TRANSPORT", "ntlm")
    use_ssl = os.environ.get("WINRM_SSL", "false").lower() in ("1", "true", "yes")
    # Require an explicit opt-in to skip TLS verification; default is always validate.
    allow_insecure = os.environ.get("WINRM_SSL_INSECURE", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    ca_bundle = os.environ.get("WINRM_CA_BUNDLE") or None
    return user, password, port, transport, use_ssl, allow_insecure, ca_bundle


def is_winrm_configured() -> bool:
    """Return True if WINRM_USER and WINRM_PASSWORD are set."""
    user, password, *_ = _winrm_config()
    return bool(user and password)


def _cert_validation(use_ssl: bool, allow_insecure: bool) -> str:
    """Return the pywinrm server_cert_validation value.

    SSL disabled → "validate" is unused but pywinrm still requires a value;
    we pass "validate" to keep the safest default.
    SSL enabled  → always validate unless WINRM_SSL_INSECURE=true.
    """
    if not use_ssl:
        return "validate"
    return "ignore" if allow_insecure else "validate"


def collect_remote(target: str) -> dict:
    """Connect to *target* via WinRM and return a collected-data dict.

    Parameters
    ----------
    target:
        Hostname or IP address of the Windows PC to collect from.

    Returns
    -------
    dict
        Collected data payload compatible with the /api/collect JSON format.

    Raises
    ------
    EnvironmentError
        If WINRM_USER or WINRM_PASSWORD is not configured.
    RuntimeError
        If the WinRM connection or script execution fails.
    """
    try:
        import winrm  # lazy import — optional dependency
    except ImportError as exc:
        raise RuntimeError(
            "pywinrm is not installed. Add 'pywinrm>=0.4.3' to requirements.txt."
        ) from exc

    user, password, port, transport, use_ssl, allow_insecure, ca_bundle = (
        _winrm_config()
    )
    if not user or not password:
        raise EnvironmentError(
            "WINRM_USER and WINRM_PASSWORD must be set to use remote collection."
        )

    cert_validation = _cert_validation(use_ssl, allow_insecure)
    scheme = "https" if use_ssl else "http"
    if use_ssl and allow_insecure:
        logger.warning(
            "WinRM TLS certificate verification is DISABLED for %s "
            "(WINRM_SSL_INSECURE=true). This is unsafe outside dev/lab environments.",
            target,
        )
    logger.info(
        "WinRM connecting to %s://%s:%d (transport=%s, cert_validation=%s)",
        scheme,
        target,
        port,
        transport,
        cert_validation,
    )

    session_kwargs: dict = {
        "target": target,
        "auth": (user, password),
        "transport": transport,
        "server_cert_validation": cert_validation,
        "port": port,
    }
    if ca_bundle:
        session_kwargs["ca_trust_path"] = ca_bundle

    session = winrm.Session(**session_kwargs)

    def _run_ps(script: str) -> str:
        result = session.run_ps(script)
        if result.status_code != 0:
            stderr = result.std_err.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"PowerShell error (exit {result.status_code}): {stderr}"
            )
        return result.std_out.decode("utf-8", errors="replace").strip()

    # Collect system info
    try:
        raw_sys = _run_ps(_PS_SYSINFO)
        sysinfo = json.loads(raw_sys) if raw_sys else {}
    except Exception as exc:
        raise RuntimeError(
            f"Failed to collect system info from {target}: {exc}"
        ) from exc

    # Collect software list (non-fatal on failure)
    software = []
    try:
        raw_sw = _run_ps(_PS_SOFTWARE)
        if raw_sw:
            parsed = json.loads(raw_sw)
            software = parsed if isinstance(parsed, list) else [parsed]
    except Exception as exc:
        logger.warning("Software collection failed for %s: %s", target, exc)

    # Collect Windows updates (non-fatal on failure)
    updates = []
    try:
        raw_up = _run_ps(_PS_UPDATES)
        if raw_up:
            parsed = json.loads(raw_up)
            updates = parsed if isinstance(parsed, list) else [parsed]
    except Exception as exc:
        logger.warning("Windows updates collection failed for %s: %s", target, exc)

    payload = dict(sysinfo)
    payload["software"] = software
    payload["windows_updates"] = updates
    # Mark collection source as server-side remote pull
    payload["collection_source"] = "winrm"
    payload.setdefault("ip_address", target)

    logger.info(
        "WinRM collection complete for %s: sw=%d updates=%d",
        target,
        len(software),
        len(updates),
    )
    return payload

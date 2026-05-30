"""Seed realistic demo data into every WebUI-facing table.

Purpose
-------
The production DB ships with only the ``admin`` user, so every sidebar page
renders empty. This script populates all major tables with a coherent,
realistic Japanese-context dataset so each page shows individual detail
content, and dashboard charts / rankings / counts have a meaningful
distribution.

Usage
-----
    cd server
    DATABASE_URL="sqlite:////tmp/seed_demo_test.db" python seed_demo.py
    # re-run is safe (idempotent skip)
    python seed_demo.py --force   # wipe existing demo data, then re-seed

Safety
------
* Production guard: refuses to run if the target SQLite DB looks like the real
  ``instance/pc_ops.db`` (or a non-throwaway DB). Set ``DATABASE_URL`` to a
  ``/tmp`` SQLite path, or pass ``--allow-prod`` to override intentionally.
* Idempotent: if >= ``_SEED_THRESHOLD`` PCs already exist, it skips unless
  ``--force`` is given.
* The ``admin`` user (and any existing users) are never touched; demo
  operator/viewer users are added only if missing.
* ``--force`` deletes demo rows from content tables but preserves all users
  and system settings.
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone

# Ensure local imports work whether run as `python seed_demo.py` from server/
# or via an absolute path.
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402
from auth import hash_password  # noqa: E402
from extensions import db  # noqa: E402
from models import (  # noqa: E402
    Alert,
    AlertRule,
    AppResponseLog,
    ApiKey,
    BackupJob,
    BootTimeLog,
    Certificate,
    CollectionPolicy,
    DiskHealth,
    EventLog,
    Inquiry,
    JobExecution,
    JobTemplate,
    KnownIssue,
    License,
    NetworkInterface,
    NetworkPingLog,
    NotificationChannel,
    NotificationLog,
    OperationLog,
    PC,
    PCGroup,
    ScheduledTask,
    Software,
    StabilityScore,
    SystemSetting,
    SystemSnapshot,
    Task,
    User,
    UptimeLog,
    WindowsUpdate,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
random.seed(42)

_SEED_THRESHOLD = 5  # if >= this many PCs exist, treat DB as already seeded
NOW = datetime.now(timezone.utc)

# Production DB filename. The app's default SQLite URI is the *relative*
# ``sqlite:///pc_ops.db``, which Flask-SQLAlchemy resolves under ``instance/``.
# Running this seeder without DATABASE_URL would therefore hit the real prod DB,
# so we refuse unless the target is clearly a throwaway (e.g. /tmp) or the
# operator passes --allow-prod explicitly.
_PROD_DB_BASENAME = "pc_ops.db"


def _resolve_db_path(app):
    """Return the on-disk path of the SQLite DB the app is bound to, or None."""
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite:"):
        return None  # non-SQLite (e.g. postgres) — guard handled separately
    # Strip the sqlite:/// (or sqlite:////) scheme to get the filesystem path.
    path = uri.split("sqlite:///")[-1]
    if path == ":memory:" or path == "":
        return None
    if not os.path.isabs(path):
        # Flask resolves relative SQLite paths under the instance folder.
        path = os.path.join(app.instance_path, path)
    return os.path.abspath(path)


def _guard_not_production(app, allow_prod):
    """Abort if we're about to write to the real production DB."""
    if allow_prod:
        return
    db_path = _resolve_db_path(app)

    # Non-SQLite without explicit DATABASE_URL would be the prod postgres default.
    if db_path is None and "DATABASE_URL" not in os.environ:
        raise SystemExit(
            "REFUSING to seed: no DATABASE_URL set and target is not an explicit "
            "throwaway SQLite DB. Pass --allow-prod to override (NOT recommended)."
        )

    if db_path is None:
        return  # explicit non-SQLite DATABASE_URL — operator's responsibility

    # The classic foot-gun: relative default landing in instance/pc_ops.db.
    is_prod_basename = os.path.basename(db_path) == _PROD_DB_BASENAME
    in_tmp = db_path.startswith("/tmp/") or "/tmp/" in db_path
    if is_prod_basename and not in_tmp:
        raise SystemExit(
            f"REFUSING to seed: target DB looks like production ({db_path}).\n"
            f"Set DATABASE_URL to a throwaway DB, e.g.\n"
            f'  DATABASE_URL="sqlite:////tmp/seed_demo.db" python seed_demo.py\n'
            f"or pass --allow-prod to override (NOT recommended)."
        )


def _ago(days=0, hours=0, minutes=0):
    """Return a tz-aware UTC datetime in the past."""
    return NOW - timedelta(days=days, hours=hours, minutes=minutes)


def _rand_past(min_days=0, max_days=90):
    """Random tz-aware datetime between min_days and max_days ago."""
    total_minutes = random.randint(min_days * 24 * 60, max_days * 24 * 60)
    return NOW - timedelta(minutes=total_minutes)


# --------------------------------------------------------------------------- #
# Static demo vocabulary (Japanese context)
# --------------------------------------------------------------------------- #
_DEPARTMENTS = [
    ("営業部", "Sales"),
    ("情報システム部", "IT"),
    ("経理部", "Finance"),
    ("人事部", "HR"),
    ("開発部", "Dev"),
    ("総務部", "GA"),
]

_OWNER_NAMES = [
    "田中 太郎",
    "佐藤 花子",
    "鈴木 一郎",
    "高橋 美咲",
    "渡辺 健",
    "伊藤 由美",
    "山本 大輔",
    "中村 さくら",
    "小林 翔",
    "加藤 恵",
    "吉田 拓也",
    "山田 七海",
    "佐々木 亮",
    "松本 彩",
    "井上 直樹",
    "木村 麻衣",
    "林 浩二",
    "斎藤 千夏",
    "清水 隆",
    "森 advice",  # replaced below if odd; kept simple ascii fallback avoided
]
# Keep owner names clean (drop the placeholder above defensively).
_OWNER_NAMES = [n for n in _OWNER_NAMES if "advice" not in n]

_OS_VERSIONS = [
    ("Windows 11 Pro", "22631", "x64"),
    ("Windows 11 Pro", "22621", "x64"),
    ("Windows 11 Enterprise", "22631", "x64"),
    ("Windows 10 Pro", "19045", "x64"),
    ("Windows 10 Pro", "19044", "x64"),
    ("Windows 10 Enterprise", "19045", "x64"),
]

_CPU_NAMES = [
    ("Intel Core i5-1240P", 12, 16),
    ("Intel Core i7-1260P", 12, 16),
    ("Intel Core i5-10500", 6, 12),
    ("Intel Core i7-10700", 8, 16),
    ("AMD Ryzen 5 PRO 5650U", 6, 12),
    ("AMD Ryzen 7 PRO 5850U", 8, 16),
]

_SOFTWARE_CATALOG = [
    ("Microsoft 365 Apps for enterprise", "16.0.17126.20132", "Microsoft Corporation"),
    ("Google Chrome", "124.0.6367.91", "Google LLC"),
    ("Microsoft Edge", "124.0.2478.67", "Microsoft Corporation"),
    ("Mozilla Firefox", "125.0.3", "Mozilla"),
    ("Adobe Acrobat Reader DC", "24.001.20629", "Adobe Inc."),
    ("7-Zip", "23.01", "Igor Pavlov"),
    ("Zoom Workplace", "6.0.2", "Zoom Video Communications, Inc."),
    ("Microsoft Teams", "24074.2701.2911", "Microsoft Corporation"),
    ("Slack", "4.37.101", "Slack Technologies"),
    ("Notepad++", "8.6.7", "Notepad++ Team"),
    ("VLC media player", "3.0.20", "VideoLAN"),
    ("PowerShell 7", "7.4.2", "Microsoft Corporation"),
    ("Git", "2.45.0", "The Git Development Community"),
    ("TeraTerm", "5.2", "TeraTerm Project"),
    ("Visual Studio Code", "1.89.0", "Microsoft Corporation"),
    ("Sophos Endpoint Agent", "2024.1.2", "Sophos Ltd."),
    ("ウイルスバスター Corp.", "14.0", "Trend Micro"),
    ("筆まめ", "33", "ソースネクスト"),
]

_KB_CATALOG = [
    ("KB5037771", "2024-05 累積更新プログラム (Windows 11)", "Important"),
    ("KB5037768", "2024-05 累積更新プログラム (Windows 10)", "Important"),
    ("KB5037591", ".NET Framework セキュリティ更新", "Critical"),
    ("KB5036980", "2024-04 累積更新プログラム", "Important"),
    ("KB5034441", "回復環境 (WinRE) 更新", "Moderate"),
    ("KB890830", "悪意のあるソフトウェアの削除ツール", "Low"),
    ("KB5037853", "Microsoft Defender 定義更新", "Critical"),
    ("KB5035853", "サーボスタック更新プログラム", "Moderate"),
]

# (event_id, level, source, message, category) for EventLog
_EVENT_CATALOG = [
    (
        1001,
        "Critical",
        "Microsoft-Windows-WER-SystemErrorReporting",
        "コンピューターは正しくシャットダウンされませんでした (BugCheck 0x0000007e)",
        "crash",
    ),
    (
        41,
        "Critical",
        "Microsoft-Windows-Kernel-Power",
        "システムが正常にシャットダウンせずに再起動しました",
        "power",
    ),
    (
        6008,
        "Error",
        "EventLog",
        "前回のシステムのシャットダウンは予期されていません",
        "power",
    ),
    (
        7,
        "Error",
        "disk",
        "デバイス \\Device\\Harddisk0 に不良ブロックがあります",
        "disk",
    ),
    (51, "Warning", "disk", "ページング操作中にエラーが検出されました", "disk"),
    (153, "Warning", "disk", "IO 操作が再試行されました", "disk"),
    (
        1000,
        "Error",
        "Application Error",
        "障害が発生しているアプリケーション EXCEL.EXE",
        "app",
    ),
    (
        1002,
        "Warning",
        "Application Hang",
        "プログラム OUTLOOK.EXE が応答を停止しました",
        "app",
    ),
    (
        7034,
        "Error",
        "Service Control Manager",
        "Print Spooler サービスが予期せず終了しました",
        "service",
    ),
    (
        7000,
        "Error",
        "Service Control Manager",
        "サービスは起動できませんでした",
        "service",
    ),
    (
        10016,
        "Warning",
        "DistributedCOM",
        "アプリケーション固有のアクセス許可の設定",
        "other",
    ),
    (
        1,
        "Information",
        "Microsoft-Windows-Time-Service",
        "時刻同期が完了しました",
        "other",
    ),
    (6005, "Information", "EventLog", "イベントログサービスが開始されました", "other"),
]

_APP_NAMES = [
    "Microsoft Excel",
    "Outlook",
    "社内ポータル",
    "勤怠システム",
    "Chrome",
    "Teams",
]
_PING_TARGETS = {
    "ping": ["8.8.8.8", "192.168.1.1", "fileserver01"],
    "dns": ["dns01.corp.local", "8.8.8.8"],
    "vpn": ["vpn.corp.example.jp"],
    "wifi": ["CORP-WLAN-5G", "CORP-WLAN-2G"],
}

_TASK_TYPES = ["cleanup", "update", "diagnostic", "custom"]
_TASK_COMMANDS = {
    "cleanup": "Clear-DiskTempFiles -Drive C:",
    "update": "Install-WindowsUpdate -AcceptAll",
    "diagnostic": "Get-SystemDiagnostics -Full",
    "custom": "Invoke-CustomScript -Name HealthCheck",
}


# --------------------------------------------------------------------------- #
# Force-clear (preserve users + settings)
# --------------------------------------------------------------------------- #
def _wipe_demo_data():
    """Delete content rows in FK-safe order. Users and SystemSetting preserved."""
    # Order matters: children before parents.
    for model in (
        NotificationLog,
        UptimeLog,
        JobExecution,
        StabilityScore,
        DiskHealth,
        BootTimeLog,
        NetworkPingLog,
        AppResponseLog,
        SystemSnapshot,
        Software,
        WindowsUpdate,
        EventLog,
        NetworkInterface,
        Alert,
        Task,
        ScheduledTask,
        Inquiry,
        AlertRule,
        JobTemplate,
        CollectionPolicy,
        OperationLog,
        Certificate,
        License,
        BackupJob,
        ApiKey,
        NotificationChannel,
        KnownIssue,
    ):
        db.session.query(model).delete()
    db.session.commit()
    # PCGroup membership (association table) + groups + PCs last.
    for grp in PCGroup.query.all():
        grp.pcs = []
    db.session.commit()
    db.session.query(PCGroup).delete()
    db.session.query(PC).delete()
    db.session.commit()


# --------------------------------------------------------------------------- #
# Seeders
# --------------------------------------------------------------------------- #
def seed_users():
    """Add demo operator/viewer users (admin untouched)."""
    added = 0
    demo_users = [
        ("operator", "operator"),
        ("viewer", "viewer"),
    ]
    for username, role in demo_users:
        if not User.query.filter_by(username=username).first():
            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password("Demo-Pass123!"),
                    role=role,
                    is_active=True,
                    last_login=_rand_past(0, 5),
                    created_at=_rand_past(120, 150),
                )
            )
            added += 1
    db.session.commit()
    return added


def seed_pc_groups():
    groups = []
    for jp, _en in _DEPARTMENTS[:6]:
        g = PCGroup(
            name=f"{jp}",
            description=f"{jp} 配下の管理対象 PC グループ",
            created_by="admin",
            created_at=_rand_past(120, 180),
        )
        db.session.add(g)
        groups.append(g)
    db.session.commit()
    return groups


def seed_pcs(groups):
    """Create 18 PCs with a deliberate status/health distribution."""
    pcs = []
    # Distribution: healthy x9, warning x4, critical x3, unknown x2 = 18
    status_plan = ["healthy"] * 9 + ["warning"] * 4 + ["critical"] * 3 + ["unknown"] * 2
    random.shuffle(status_plan)

    for i, status in enumerate(status_plan, start=1):
        os_version, os_build, arch = random.choice(_OS_VERSIONS)
        cpu_name, cores, logical = random.choice(_CPU_NAMES)
        mem_total = random.choice([8.0, 16.0, 32.0])
        disk_total = random.choice([256.0, 512.0, 1024.0])

        # Health/last_seen tuned to status so dashboard buckets are meaningful.
        if status == "healthy":
            health = round(random.uniform(82, 99), 1)
            stability = round(random.uniform(85, 100), 1)
            mem_avail = round(mem_total * random.uniform(0.35, 0.7), 1)
            disk_free = round(disk_total * random.uniform(0.3, 0.7), 1)
            last_seen = _ago(minutes=random.randint(1, 4))  # online
        elif status == "warning":
            health = round(random.uniform(55, 78), 1)
            stability = round(random.uniform(55, 80), 1)
            mem_avail = round(mem_total * random.uniform(0.12, 0.25), 1)
            disk_free = round(disk_total * random.uniform(0.08, 0.15), 1)
            last_seen = _ago(hours=random.randint(2, 10))  # stale
        elif status == "critical":
            health = round(random.uniform(20, 50), 1)
            stability = round(random.uniform(20, 50), 1)
            mem_avail = round(mem_total * random.uniform(0.03, 0.09), 1)
            disk_free = round(disk_total * random.uniform(0.02, 0.06), 1)
            last_seen = _ago(hours=random.randint(12, 40))  # offline-ish
        else:  # unknown
            health = round(random.uniform(0, 30), 1)
            stability = round(random.uniform(40, 70), 1)
            mem_avail = round(mem_total * random.uniform(0.2, 0.5), 1)
            disk_free = round(disk_total * random.uniform(0.2, 0.5), 1)
            last_seen = _ago(days=random.randint(3, 20))  # long offline

        dept_jp = random.choice(_DEPARTMENTS)[0]
        deploy_year = random.randint(2019, 2025)
        asset_number = f"{deploy_year}{random.randint(1, 9):02d}{i:03d}M"
        connection_type = random.choice(["LAN", "LAN", "LAN", "SSL-VPN", "SSL-VPN"])
        asset_source = random.choice(
            ["agent", "agent", "agent", "agent", "ledger", "winrm"]
        )
        ip_lan = f"192.168.{random.randint(1, 6)}.{random.randint(10, 240)}"
        ip_wifi = f"10.20.{random.randint(1, 6)}.{random.randint(10, 240)}"
        mac_wired = ":".join(f"{random.randint(0, 255):02X}" for _ in range(6))
        mac_wireless = ":".join(f"{random.randint(0, 255):02X}" for _ in range(6))
        owner = random.choice(_OWNER_NAMES)

        pc = PC(
            pc_name=f"PC-EMP-{i:03d}",
            domain="corp.local",
            os_version=os_version,
            os_build=os_build,
            os_architecture=arch,
            cpu_name=cpu_name,
            cpu_cores=cores,
            cpu_logical_processors=logical,
            memory_total_gb=mem_total,
            memory_available_gb=mem_avail,
            disk_total_gb=disk_total,
            disk_free_gb=disk_free,
            ip_address=ip_lan,
            mac_address=mac_wired,
            last_seen=last_seen,
            status=status,
            health_score=health,
            agent_version="2.3.1",
            connection_type=connection_type,
            offline_pending_count=(
                random.randint(0, 8) if connection_type == "SSL-VPN" else 0
            ),
            stability_score=stability,
            last_stability_calc_at=_rand_past(0, 2),
            # CMDB ledger (Phase I-1)
            asset_number=asset_number,
            owner_name=f"{owner}（CIM）",
            employee_id=f"MK{random.randint(100, 9999):04d}",
            deploy_year=deploy_year,
            ad_cn=owner.replace(" ", ""),
            ad_sam=f"u{random.randint(1000, 9999)}",
            ad_dn=f"CN={owner.replace(' ', '')},OU={dept_jp},DC=corp,DC=local",
            ip_lan=ip_lan,
            ip_wifi=ip_wifi,
            mac_wired=mac_wired,
            mac_wireless=mac_wireless,
            asset_source=asset_source,
            ledger_synced_at=(_rand_past(0, 10) if asset_source == "ledger" else None),
            created_at=_rand_past(120, 180),
        )
        db.session.add(pc)
        pcs.append(pc)

    db.session.commit()

    # Assign each PC to 1-2 groups.
    for pc in pcs:
        for grp in random.sample(groups, k=random.randint(1, 2)):
            grp.pcs.append(pc)
    db.session.commit()
    return pcs


def seed_network_interfaces(pcs):
    count = 0
    for pc in pcs:
        # Always an Ethernet; ~half also Wi-Fi.
        ifaces = [
            (
                "Ethernet",
                "Intel(R) Ethernet Connection I219-LM",
                pc.mac_wired,
                pc.ip_lan,
                1000,
            )
        ]
        if random.random() < 0.6:
            ifaces.append(
                (
                    "Wi-Fi",
                    "Intel(R) Wi-Fi 6 AX201 160MHz",
                    pc.mac_wireless,
                    pc.ip_wifi,
                    867,
                )
            )
        for name, desc, mac, ip, speed in ifaces:
            db.session.add(
                NetworkInterface(
                    pc_id=pc.id,
                    interface_name=name,
                    description=desc,
                    mac_address=mac,
                    ip_address=ip,
                    ipv6_address=f"fe80::{random.randint(1, 9999):x}",
                    subnet_mask="255.255.255.0",
                    gateway=ip.rsplit(".", 1)[0] + ".1",
                    dns_servers="192.168.1.10, 8.8.8.8",
                    link_speed_mbps=speed,
                    is_active=True,
                    collected_at=_rand_past(0, 1),
                )
            )
            count += 1
    db.session.commit()
    return count


def seed_snapshots(pcs):
    count = 0
    for pc in pcs:
        for d in range(random.randint(4, 8)):
            db.session.add(
                SystemSnapshot(
                    pc_id=pc.id,
                    collected_at=_ago(days=d, hours=random.randint(0, 12)),
                    cpu_usage=round(random.uniform(5, 95), 1),
                    memory_available_gb=round(
                        (pc.memory_total_gb or 16) * random.uniform(0.1, 0.7),
                        1,
                    ),
                    disk_free_gb=round(
                        (pc.disk_total_gb or 512) * random.uniform(0.05, 0.7),
                        1,
                    ),
                    uptime_days=round(random.uniform(0.2, 30), 1),
                    pending_reboot=random.random() < 0.2,
                    windows_update_pending=random.random() < 0.3,
                    last_boot_time=_ago(days=random.randint(0, 14)),
                )
            )
            count += 1
    db.session.commit()
    return count


def seed_software(pcs):
    count = 0
    for pc in pcs:
        catalog = random.sample(
            _SOFTWARE_CATALOG, k=random.randint(6, len(_SOFTWARE_CATALOG))
        )
        for name, version, publisher in catalog:
            db.session.add(
                Software(
                    pc_id=pc.id,
                    name=name,
                    version=version,
                    publisher=publisher,
                    install_date=_rand_past(30, 700),
                    collected_at=_rand_past(0, 2),
                )
            )
            count += 1
    db.session.commit()
    return count


def seed_windows_updates(pcs):
    count = 0
    for pc in pcs:
        catalog = random.sample(_KB_CATALOG, k=random.randint(3, len(_KB_CATALOG)))
        for kb_id, title, severity in catalog:
            installed = random.random() < 0.7
            installed_at = _rand_past(1, 60) if installed else None
            reboot_at = (
                installed_at + timedelta(minutes=random.randint(3, 30))
                if installed and random.random() < 0.5
                else None
            )
            db.session.add(
                WindowsUpdate(
                    pc_id=pc.id,
                    kb_id=kb_id,
                    title=title,
                    severity=severity,
                    installed=installed,
                    installed_at=installed_at,
                    reboot_at=reboot_at,
                    collected_at=_rand_past(0, 2),
                )
            )
            count += 1
    db.session.commit()
    return count


def seed_event_logs(pcs):
    count = 0
    for pc in pcs:
        # critical/warning PCs get more (and worse) events.
        if pc.status in ("critical", "unknown"):
            n = random.randint(12, 20)
            pool = _EVENT_CATALOG  # full pool incl. crash/disk
        elif pc.status == "warning":
            n = random.randint(7, 14)
            pool = _EVENT_CATALOG
        else:
            n = random.randint(5, 9)
            pool = _EVENT_CATALOG[-4:]  # mostly informational
        for _ in range(n):
            event_id, level, source, message, category = random.choice(pool)
            log_type = (
                "System"
                if category in ("power", "disk", "service", "crash")
                else "Application"
            )
            db.session.add(
                EventLog(
                    pc_id=pc.id,
                    log_type=log_type,
                    event_id=event_id,
                    level=level,
                    source=source,
                    message=message,
                    category=category,
                    generated_at=_rand_past(0, 30),
                    collected_at=_rand_past(0, 1),
                )
            )
            count += 1
    db.session.commit()
    return count


def seed_boot_logs(pcs):
    count = 0
    for pc in pcs:
        base = random.randint(20, 50)
        for d in range(random.randint(3, 7)):
            # critical PCs boot slower
            extra = random.randint(40, 120) if pc.status == "critical" else 0
            db.session.add(
                BootTimeLog(
                    pc_id=pc.id,
                    boot_duration_seconds=base + extra + random.randint(-5, 20),
                    boot_timestamp=_ago(days=d, hours=random.randint(0, 8)),
                    collected_at=_rand_past(0, 1),
                )
            )
            count += 1
    db.session.commit()
    return count


def seed_ping_logs(pcs):
    count = 0
    for pc in pcs:
        for _ in range(random.randint(4, 9)):
            check_type = random.choice(list(_PING_TARGETS.keys()))
            target = random.choice(_PING_TARGETS[check_type])
            ok = random.random() < (0.5 if pc.status == "critical" else 0.85)
            status = "ok" if ok else random.choice(["timeout", "error", "unreachable"])
            latency = random.randint(1, 60) if ok else None
            db.session.add(
                NetworkPingLog(
                    pc_id=pc.id,
                    check_type=check_type,
                    target=target,
                    status=status,
                    latency_ms=latency,
                    checked_at=_rand_past(0, 7),
                )
            )
            count += 1
    db.session.commit()
    return count


def seed_app_response_logs(pcs):
    count = 0
    for pc in pcs:
        for _ in range(random.randint(4, 8)):
            app_name = random.choice(_APP_NAMES)
            threshold = random.choice([500, 1000, 2000, 3000])
            rt = random.randint(80, 6000)
            db.session.add(
                AppResponseLog(
                    pc_id=pc.id,
                    app_name=app_name,
                    response_time_ms=rt,
                    threshold_ms=threshold,
                    is_slow=rt > threshold,
                    recorded_at=_rand_past(0, 14),
                )
            )
            count += 1
    db.session.commit()
    return count


def seed_uptime_logs(pcs):
    """Dense online/offline time-series so uptime % is meaningful per PC."""
    count = 0
    for pc in pcs:
        # one sample every ~3h for 30 days -> ~240 samples
        cur = _ago(days=30)
        # baseline online probability tied to status
        p_online = {
            "healthy": 0.99,
            "warning": 0.93,
            "critical": 0.70,
            "unknown": 0.40,
        }.get(pc.status, 0.9)
        while cur < NOW:
            status = "online" if random.random() < p_online else "offline"
            db.session.add(UptimeLog(pc_id=pc.id, status=status, recorded_at=cur))
            count += 1
            cur += timedelta(hours=3, minutes=random.randint(-20, 20))
    db.session.commit()
    return count


def seed_stability_scores(pcs):
    count = 0
    for pc in pcs:
        # a few historical points + one current
        for d in (14, 7, 0):
            deductions = []
            if pc.status in ("warning", "critical", "unknown"):
                deductions = [
                    {
                        "reason": "BugCheck (BSOD)",
                        "event_id": 1001,
                        "count": random.randint(1, 3),
                        "points": 30,
                    },
                    {
                        "reason": "Disk Error (Bad Block)",
                        "event_id": 7,
                        "count": random.randint(1, 2),
                        "points": 20,
                    },
                ]
            db.session.add(
                StabilityScore(
                    pc_id=pc.id,
                    score=pc.stability_score
                    if d == 0
                    else round(random.uniform(40, 100), 1),
                    deductions=json.dumps(deductions, ensure_ascii=False)
                    if deductions
                    else None,
                    analysis_days=7,
                    calculated_at=_ago(days=d),
                )
            )
            count += 1
    db.session.commit()
    return count


def seed_disk_health(pcs):
    count = 0
    disk_events = [
        (7, "disk", "不良ブロックを検出しました", "critical"),
        (51, "disk", "ページング中のエラー", "warning"),
        (153, "disk", "IO 再試行が発生", "warning"),
        (55, "Ntfs", "ファイルシステム構造の破損", "critical"),
    ]
    for pc in pcs:
        # only some PCs have disk issues
        if pc.status in ("critical", "warning") and random.random() < 0.7:
            for _ in range(random.randint(1, 3)):
                event_id, source, message, severity = random.choice(disk_events)
                db.session.add(
                    DiskHealth(
                        pc_id=pc.id,
                        event_id=event_id,
                        source=source,
                        message=message,
                        disk_label=random.choice(["C:", "D:", "PhysicalDrive0"]),
                        severity=severity,
                        generated_at=_rand_past(0, 30),
                        collected_at=_rand_past(0, 1),
                    )
                )
                count += 1
    db.session.commit()
    return count


def seed_tasks(pcs):
    count = 0
    # 30 tasks across statuses
    status_plan = (
        ["completed"] * 16 + ["failed"] * 5 + ["pending"] * 6 + ["running"] * 3
    )
    random.shuffle(status_plan)
    for status in status_plan:
        pc = random.choice(pcs)
        task_type = random.choice(_TASK_TYPES)
        created = _rand_past(0, 25)
        started = (
            created + timedelta(minutes=random.randint(1, 30))
            if status in ("completed", "failed", "running")
            else None
        )
        completed = (
            (started or created) + timedelta(minutes=random.randint(1, 60))
            if status in ("completed", "failed")
            else None
        )
        # bias some completions to "today" so dashboard "completed today" > 0
        if status == "completed" and random.random() < 0.4:
            completed = _ago(hours=random.randint(0, 12))
            created = completed - timedelta(hours=1)
            started = completed - timedelta(minutes=30)
        db.session.add(
            Task(
                pc_id=pc.id,
                task_type=task_type,
                command=_TASK_COMMANDS[task_type],
                parameters=json.dumps({"timeout": 300}),
                status=status,
                priority=random.randint(0, 3),
                created_by=random.choice(["admin", "operator", "system"]),
                created_at=created,
                started_at=started,
                completed_at=completed,
                result=("正常終了" if status == "completed" else None),
                error_message=(
                    "リモート接続に失敗しました (WinRM timeout)"
                    if status == "failed"
                    else None
                ),
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_scheduled_tasks(pcs):
    count = 0
    plans = [
        ("夜間ディスククリーンアップ", "cleanup", "daily", None, "02:00", None, None),
        ("週次 Windows Update", "update", "weekly", None, None, 6, "03:00"),
        ("定期診断", "diagnostic", "interval", 360, None, None, None),
        ("月初インベントリ収集", "custom", "daily", None, "07:30", None, None),
        ("VPN 接続ヘルスチェック", "diagnostic", "interval", 120, None, None, None),
        ("ログローテーション", "custom", "weekly", None, None, 0, "01:00"),
    ]
    for name, ttype, stype, interval, daily, wday, wtime in plans:
        target_pc = random.choice(pcs) if random.random() < 0.3 else None
        last_status = random.choice(["success", "success", "failed", None])
        db.session.add(
            ScheduledTask(
                name=name,
                description=f"{name} の自動実行ジョブ",
                task_type=ttype,
                command=_TASK_COMMANDS.get(ttype, "Invoke-Job"),
                parameters="{}",
                pc_id=target_pc.id if target_pc else None,
                target_type="pc" if target_pc else "all",
                schedule_type=stype,
                interval_minutes=interval,
                daily_time=daily,
                weekly_day=wday,
                weekly_time=wtime,
                is_enabled=random.random() < 0.85,
                last_run_at=_rand_past(0, 7),
                next_run_at=NOW + timedelta(hours=random.randint(1, 48)),
                run_count=random.randint(0, 200),
                last_status=last_status,
                created_by="admin",
                created_at=_rand_past(60, 150),
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_job_templates_and_executions(pcs):
    templates = [
        ("ディスククリーンアップ", "maintenance", "low", False, "Cleanmgr /sagerun:1"),
        (
            "プリンタスプーラ再起動",
            "maintenance",
            "low",
            False,
            "Restart-Service Spooler",
        ),
        ("グループポリシー更新", "config", "medium", False, "gpupdate /force"),
        ("リモート再起動", "power", "high", True, "Restart-Computer -Force"),
        (
            "セキュリティスキャン",
            "security",
            "medium",
            True,
            "Start-MpScan -ScanType FullScan",
        ),
    ]
    tobjs = []
    for name, category, risk, approval, script in templates:
        t = JobTemplate(
            name=name,
            description=f"{name} を実行する PowerShell テンプレート",
            category=category,
            script_body=script,
            parameters_schema=json.dumps({"type": "object", "properties": {}}),
            risk_level=risk,
            requires_approval=approval,
            is_enabled=True,
            created_by="admin",
            created_at=_rand_past(60, 150),
        )
        db.session.add(t)
        tobjs.append(t)
    db.session.commit()

    exec_count = 0
    statuses = [
        "completed",
        "completed",
        "failed",
        "pending",
        "running",
        "pending_approval",
        "cancelled",
    ]
    for _ in range(18):
        t = random.choice(tobjs)
        pc = random.choice(pcs)
        status = random.choice(statuses)
        created = _rand_past(0, 20)
        executed = (
            created + timedelta(minutes=random.randint(1, 20))
            if status in ("completed", "failed", "running")
            else None
        )
        completed = (
            executed + timedelta(minutes=random.randint(1, 30))
            if status in ("completed", "failed") and executed
            else None
        )
        approved_by = (
            "admin"
            if t.requires_approval and status not in ("pending_approval",)
            else None
        )
        db.session.add(
            JobExecution(
                template_id=t.id,
                pc_id=pc.id,
                status=status,
                parameters=json.dumps({}),
                result_output=("Success" if status == "completed" else None),
                result_exit_code=(
                    0 if status == "completed" else (1 if status == "failed" else None)
                ),
                requested_by=random.choice(["admin", "operator"]),
                approved_by=approved_by,
                approved_at=created if approved_by else None,
                executed_at=executed,
                completed_at=completed,
                created_at=created,
            )
        )
        exec_count += 1
    db.session.commit()
    return len(tobjs), exec_count


def seed_alert_rules():
    rules = [
        ("CPU 高使用率", "cpu", "gt", 90.0, "warning"),
        ("メモリ枯渇", "memory", "gt", 90.0, "critical"),
        ("ディスク空き不足", "disk", "lt", 10.0, "critical"),
        ("PC オフライン検知", "offline", "gte", 30.0, "warning"),
        ("ディスク空き警告", "disk", "lt", 20.0, "warning"),
        ("CPU 警告", "cpu", "gt", 75.0, "warning"),
    ]
    objs = []
    for name, metric, op, threshold, severity in rules:
        r = AlertRule(
            name=name,
            metric=metric,
            operator=op,
            threshold=threshold,
            severity=severity,
            notify_email="it-ops@corp.example.jp",
            notify_slack_webhook="https://hooks.slack.com/services/T000/B000/demo",
            channel_type=random.choice(["slack", "email", None]),
            is_enabled=random.random() < 0.85,
            created_by="admin",
            created_at=_rand_past(60, 150),
        )
        db.session.add(r)
        objs.append(r)
    db.session.commit()
    return objs


def seed_alerts(pcs, rules):
    count = 0
    alert_specs = [
        ("cpu_high", "warning", "CPU 使用率が 90% を超えています"),
        ("memory_high", "critical", "メモリ使用率が危険水準です"),
        ("disk_low", "critical", "ディスク空き容量が 10% を下回りました"),
        ("offline", "warning", "PC が 30 分以上応答していません"),
        ("disk_warn", "warning", "ディスク空き容量が 20% を下回りました"),
        ("stability_low", "critical", "安定性スコアが大幅に低下しました"),
        ("update_pending", "info", "未適用の重要更新があります"),
    ]
    seq = 0
    for _ in range(24):
        pc = random.choice(pcs)
        alert_type, severity, message = random.choice(alert_specs)
        rule = random.choice(rules) if random.random() < 0.7 else None
        resolved = random.random() < 0.45
        created = _rand_past(0, 30)
        acknowledged = resolved or random.random() < 0.3
        seq += 1
        db.session.add(
            Alert(
                pc_id=pc.id,
                alert_rule_id=rule.id if rule else None,
                alert_type=alert_type,
                severity=severity,
                message=f"[{pc.pc_name}] {message}",
                # unique per row to satisfy (source_key, resolved) constraint
                source_key=f"{alert_type}:{pc.id}:{seq}",
                acknowledged=acknowledged,
                acknowledged_by="operator" if acknowledged else None,
                acknowledged_at=created + timedelta(minutes=10)
                if acknowledged
                else None,
                resolved=resolved,
                resolved_at=created + timedelta(hours=random.randint(1, 24))
                if resolved
                else None,
                created_at=created,
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_notification_channels():
    channels = [
        ("IT運用 Slack", "slack", "https://hooks.slack.com/services/T000/B001/itops"),
        ("インフラ Teams", "teams", "https://outlook.office.com/webhook/demo-teams"),
        ("管理者メール", "email", "it-admin@corp.example.jp"),
        ("汎用 Webhook", "webhook", "https://ops.corp.example.jp/hooks/alert"),
    ]
    objs = []
    for name, ctype, target in channels:
        c = NotificationChannel(
            name=name,
            channel_type=ctype,
            target=target,
            is_active=random.random() < 0.85,
            created_at=_rand_past(60, 150),
        )
        db.session.add(c)
        objs.append(c)
    db.session.commit()
    return objs


def seed_notification_logs(alerts, rules):
    count = 0
    channels = ["slack", "teams", "email", "generic_webhook"]
    alert_list = Alert.query.all()
    for _ in range(30):
        alert = random.choice(alert_list) if alert_list else None
        rule = random.choice(rules) if rules and random.random() < 0.7 else None
        channel = random.choice(channels)
        status = random.choice(["sent", "sent", "sent", "failed", "skipped"])
        msg = {
            "sent": "通知を送信しました",
            "failed": "送信に失敗しました (HTTP 500)",
            "skipped": "チャンネル無効のためスキップ",
        }[status]
        db.session.add(
            NotificationLog(
                alert_id=alert.id if alert else None,
                rule_id=rule.id if rule else None,
                channel=channel,
                status=status,
                message=msg,
                sent_at=_rand_past(0, 30),
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_certificates():
    from datetime import date

    today = date.today()
    specs = [
        ("社内ポータル SSL", "portal.corp.example.jp", "DigiCert", "server", 40),
        ("VPN ゲートウェイ証明書", "vpn.corp.example.jp", "GlobalSign", "server", 12),
        ("メールサーバ証明書", "mail.corp.example.jp", "Let's Encrypt", "server", 5),
        ("社内 CA ルート", "corp-root-ca", "Internal CA", "code", 800),
        ("ワイルドカード証明書", "*.corp.example.jp", "DigiCert", "server", -3),
        (
            "クライアント認証証明書",
            "client.corp.example.jp",
            "Internal CA",
            "client",
            180,
        ),
        ("コード署名証明書", "codesign.corp.example.jp", "Sectigo", "code", -15),
        ("テスト環境証明書", "test.corp.example.jp", "Let's Encrypt", "server", 25),
    ]
    count = 0
    for name, domain, issuer, ctype, days_left in specs:
        db.session.add(
            Certificate(
                name=name,
                domain=domain,
                issuer=issuer,
                cert_type=ctype,
                issued_at=today - timedelta(days=365),
                expires_at=today + timedelta(days=days_left),
                auto_renew=random.random() < 0.6,
                notes=("期限切れ間近" if 0 <= days_left <= 30 else None),
                created_at=_rand_past(60, 150),
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_licenses():
    from datetime import date

    today = date.today()
    specs = [
        ("Microsoft 365 E3", "Microsoft", "subscription", 250, 2700, 200),
        ("Windows 11 Enterprise", "Microsoft", "volume", 250, 8000, 400),
        ("Adobe Acrobat Pro", "Adobe", "subscription", 30, 1980, 90),
        ("Zoom ライセンス", "Zoom", "subscription", 50, 2000, 30),
        ("ウイルスバスター Corp.", "Trend Micro", "subscription", 250, 1200, 150),
        ("Slack Business+", "Salesforce", "subscription", 120, 1600, 60),
        ("筆まめ Select", "ソースネクスト", "perpetual", 20, 5000, None),
        ("Visual Studio Pro", "Microsoft", "subscription", 15, 6500, -10),
        ("AutoCAD LT", "Autodesk", "subscription", 8, 60000, 220),
        ("TeraTerm Pro サポート", "Vendor", "subscription", 5, 3000, 45),
    ]
    count = 0
    for product, vendor, ltype, seats, unit, days_left in specs:
        db.session.add(
            License(
                product_name=product,
                vendor=vendor,
                license_type=ltype,
                seat_count=seats,
                unit_price=unit,
                expires_at=(
                    today + timedelta(days=days_left) if days_left is not None else None
                ),
                notes=(
                    "更新要確認" if days_left is not None and days_left < 60 else None
                ),
                created_at=_rand_past(60, 150),
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_backup_jobs():
    count = 0
    for d in range(10):
        status = random.choice(["success", "success", "success", "failed", "running"])
        size = random.randint(50_000_000, 500_000_000) if status != "running" else None
        duration = random.randint(20, 600) if status != "running" else None
        started = _ago(days=d, hours=2)
        finished = (
            started + timedelta(seconds=duration)
            if duration and status != "running"
            else None
        )
        db.session.add(
            BackupJob(
                backup_type=random.choice(["full", "incremental"]),
                target="DB + config",
                status=status,
                size_bytes=size,
                duration_seconds=duration,
                storage_path=f"/var/backups/pc-ops/backup-{started:%Y%m%d}.tar.gz",
                notes=("ストレージ書き込みエラー" if status == "failed" else None),
                started_at=started,
                finished_at=finished,
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_known_issues():
    specs = [
        (
            "KB5037771 適用後に印刷ができない",
            "KB5037771",
            [372],
            "印刷ジョブがスプーラでスタックする",
            "スプーラ再起動またはドライバ再インストール",
            "Windows 11 22H2/23H2",
            ["VersaPro", "Latitude"],
            "high",
        ),
        (
            "Kernel-Power 41 による突然の再起動",
            None,
            [41, 6008],
            "高負荷時に突然再起動する",
            "電源プラン見直し・BIOS 更新",
            "Windows 10/11",
            ["ThinkPad"],
            "critical",
        ),
        (
            "Outlook 検索インデックスが壊れる",
            "KB5036980",
            [1002],
            "検索結果が表示されない",
            "検索インデックスの再構築",
            "Windows 10 22H2",
            [],
            "medium",
        ),
        (
            "ディスク 7 イベント多発による性能低下",
            None,
            [7, 51],
            "I/O が遅くなる",
            "SMART 確認・HDD/SSD 交換",
            "全 OS",
            ["HP EliteDesk"],
            "high",
        ),
        (
            "WinRE 更新失敗 (0x80070643)",
            "KB5034441",
            [],
            "更新が繰り返し失敗",
            "回復パーティション拡張",
            "Windows 10/11",
            [],
            "medium",
        ),
        (
            "Teams が起動時に応答しない",
            None,
            [1002, 1000],
            "起動直後フリーズ",
            "キャッシュクリア",
            "Windows 11",
            [],
            "low",
        ),
    ]
    count = 0
    for title, kb, eids, sym, res, os_aff, models_aff, sev in specs:
        db.session.add(
            KnownIssue(
                title=title,
                kb_id=kb,
                event_ids=json.dumps(eids) if eids else None,
                symptoms=sym,
                resolution=res,
                affected_os=os_aff,
                affected_models=json.dumps(models_aff, ensure_ascii=False)
                if models_aff
                else None,
                severity=sev,
                is_active=True,
                source=random.choice(["internal", "internal", "rss"]),
                external_id=None,
                created_at=_rand_past(30, 150),
            )
        )
        count += 1
    db.session.commit()
    return KnownIssue.query.all(), count


def seed_inquiries(pcs, known_issues):
    specs = [
        ("PC の動作が遅い", "起動に5分以上かかります"),
        ("印刷ができない", "プリンタにジョブが残り続けます"),
        ("VPN に接続できない", "在宅勤務で社内システムに繋がりません"),
        ("Excel が頻繁に落ちる", "大きなファイルを開くとクラッシュします"),
        ("Windows Update が終わらない", "更新が80%で止まります"),
        ("メールの検索ができない", "Outlook の検索が空になります"),
        ("画面がブルースクリーンになる", "作業中に突然再起動します"),
        ("無線LANが切れる", "Wi-Fi が頻繁に切断されます"),
    ]
    statuses = ["open", "open", "in_progress", "resolved", "resolved"]
    count = 0
    for subject, symptom in specs:
        pc = random.choice(pcs) if random.random() < 0.8 else None
        ki = (
            random.choice(known_issues)
            if known_issues and random.random() < 0.5
            else None
        )
        status = random.choice(statuses)
        created = _rand_past(0, 40)
        resolved_at = (
            created + timedelta(days=random.randint(1, 5))
            if status == "resolved"
            else None
        )
        db.session.add(
            Inquiry(
                pc_id=pc.id if pc else None,
                inquired_by=random.choice(_OWNER_NAMES),
                subject=subject,
                symptom=symptom,
                status=status,
                known_issue_id=ki.id if ki else None,
                response=(
                    "対応済み。再発時は再度ご連絡ください。"
                    if status == "resolved"
                    else None
                ),
                created_at=created,
                resolved_at=resolved_at,
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_operation_logs(pcs):
    count = 0
    actions = [
        ("login", "auth", "ユーザーがログインしました"),
        ("logout", "auth", "ユーザーがログアウトしました"),
        ("create_task", "task", "タスクを作成しました"),
        ("update_pc", "pc", "PC 情報を更新しました"),
        ("resolve_alert", "alert", "アラートを解決しました"),
        ("create_alert_rule", "alert_rule", "アラートルールを作成しました"),
        ("run_backup", "backup", "バックアップを実行しました"),
        ("update_settings", "settings", "システム設定を変更しました"),
        ("create_user", "user", "ユーザーを作成しました"),
        ("export_csv", "report", "CSV をエクスポートしました"),
    ]
    for _ in range(40):
        action, target_kind, details = random.choice(actions)
        target = random.choice(pcs).pc_name if target_kind == "pc" else target_kind
        db.session.add(
            OperationLog(
                action=action,
                target=target,
                details=details,
                ip_address=f"192.168.{random.randint(1, 6)}.{random.randint(2, 254)}",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                created_by=random.choice(["admin", "operator", "viewer"]),
                created_at=_rand_past(0, 30),
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_collection_policies(groups):
    count = 0
    # global defaults
    for metric in CollectionPolicy.METRIC_TYPES:
        db.session.add(
            CollectionPolicy(
                group_id=None,
                metric_type=metric,
                frequency_minutes=random.choice([30, 60, 120, 360]),
                is_enabled=True,
                created_at=_rand_past(60, 150),
            )
        )
        count += 1
    # a couple of per-group overrides
    for grp in random.sample(groups, k=min(2, len(groups))):
        metric = random.choice(CollectionPolicy.METRIC_TYPES)
        db.session.add(
            CollectionPolicy(
                group_id=grp.id,
                metric_type=metric,
                frequency_minutes=15,
                is_enabled=True,
                created_at=_rand_past(30, 100),
            )
        )
        count += 1
    db.session.commit()
    return count


def seed_api_keys():
    count = 0
    specs = ["Agent 収集キー", "監視連携キー", "レポート連携キー"]
    for name in specs:
        key, _raw = ApiKey.generate(name)
        key.is_active = random.random() < 0.85
        key.last_used_at = _rand_past(0, 10)
        key.created_at = _rand_past(60, 150)
        db.session.add(key)
        count += 1
    db.session.commit()
    return count


def seed_system_settings():
    """Add a few demo settings only if missing (don't clobber prod settings)."""
    count = 0
    defaults = {
        "offline_threshold_minutes": "30",
        "data_retention_days": "90",
        "alert_email_enabled": "true",
        "company_name": "サンプル株式会社",
    }
    for key, value in defaults.items():
        if not SystemSetting.query.get(key):
            db.session.add(SystemSetting(key=key, value=value))
            count += 1
    db.session.commit()
    return count


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(force=False, allow_prod=False):
    app = create_app()
    _guard_not_production(app, allow_prod)
    summary = {}
    with app.app_context():
        db.create_all()

        existing_pcs = PC.query.count()
        if existing_pcs >= _SEED_THRESHOLD and not force:
            print(
                f"seeded already: {existing_pcs} PCs present "
                f"(>= {_SEED_THRESHOLD}). Use --force to re-seed."
            )
            return

        if force and existing_pcs > 0:
            print("--force: wiping existing demo data (users/settings preserved)...")
            _wipe_demo_data()

        summary["users (demo)"] = seed_users()
        groups = seed_pc_groups()
        summary["pc_groups"] = len(groups)
        pcs = seed_pcs(groups)
        summary["pcs"] = len(pcs)
        summary["network_interfaces"] = seed_network_interfaces(pcs)
        summary["system_snapshots"] = seed_snapshots(pcs)
        summary["software"] = seed_software(pcs)
        summary["windows_updates"] = seed_windows_updates(pcs)
        summary["event_logs"] = seed_event_logs(pcs)
        summary["boot_time_logs"] = seed_boot_logs(pcs)
        summary["network_ping_logs"] = seed_ping_logs(pcs)
        summary["app_response_logs"] = seed_app_response_logs(pcs)
        summary["uptime_logs"] = seed_uptime_logs(pcs)
        summary["stability_scores"] = seed_stability_scores(pcs)
        summary["disk_health"] = seed_disk_health(pcs)
        summary["tasks"] = seed_tasks(pcs)
        summary["scheduled_tasks"] = seed_scheduled_tasks(pcs)
        n_templates, n_execs = seed_job_templates_and_executions(pcs)
        summary["job_templates"] = n_templates
        summary["job_executions"] = n_execs
        rules = seed_alert_rules()
        summary["alert_rules"] = len(rules)
        summary["alerts"] = seed_alerts(pcs, rules)
        channels = seed_notification_channels()
        summary["notification_channels"] = len(channels)
        summary["notification_logs"] = seed_notification_logs(None, rules)
        summary["certificates"] = seed_certificates()
        summary["licenses"] = seed_licenses()
        summary["backup_jobs"] = seed_backup_jobs()
        known_issues, n_known = seed_known_issues()
        summary["known_issues"] = n_known
        summary["inquiries"] = seed_inquiries(pcs, known_issues)
        summary["operation_logs"] = seed_operation_logs(pcs)
        summary["collection_policies"] = seed_collection_policies(groups)
        summary["api_keys"] = seed_api_keys()
        summary["system_settings (demo)"] = seed_system_settings()

    # --- summary ---
    print("\n=== Demo data seeded ===")
    width = max(len(k) for k in summary)
    for key in summary:
        print(f"  {key.ljust(width)} : {summary[key]}")
    print(f"  {'TOTAL rows'.ljust(width)} : {sum(summary.values())}")
    print("========================\n")


def main():
    parser = argparse.ArgumentParser(description="Seed realistic demo data.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing demo data (users/settings kept) and re-seed.",
    )
    parser.add_argument(
        "--allow-prod",
        action="store_true",
        help=(
            "Override the production-DB safety guard. Only use when you really "
            "intend to seed the configured (non-throwaway) database."
        ),
    )
    args = parser.parse_args()
    run(force=args.force, allow_prod=args.allow_prod)


if __name__ == "__main__":
    main()

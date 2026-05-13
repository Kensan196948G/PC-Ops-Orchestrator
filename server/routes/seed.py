"""Demo data seeding endpoint — admin only, not for production use."""

import json
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify

from auth import admin_required
from extensions import db
from models import (
    Alert,
    AlertRule,
    BackupJob,
    Certificate,
    License,
    NotificationChannel,
    OperationLog,
    PC,
    PCGroup,
    ScheduledTask,
    Software,
    SystemSnapshot,
    Task,
    WindowsUpdate,
)

seed_bp = Blueprint("seed", __name__)


@seed_bp.route("/admin/seed-demo", methods=["POST"])
@admin_required
def seed_demo():
    """Populate comprehensive demo data for all pages."""
    _now = datetime.now(timezone.utc)
    added = {
        "pcs": 0,
        "groups": 0,
        "tasks": 0,
        "alerts": 0,
        "alert_rules": 0,
        "scheduled_tasks": 0,
        "operation_logs": 0,
        "software": 0,
        "windows_updates": 0,
        "notification_channels": 0,
        "certificates": 0,
        "licenses": 0,
    }

    # ── PCs ────────────────────────────────────────────────────────────
    _pc_defs = [
        {
            "pc_name": "DESKTOP-PC001",
            "domain": "corp.example.com",
            "os_version": "Windows 11 Pro 23H2",
            "os_architecture": "64-bit",
            "cpu_name": "Intel Core i7-1365U",
            "cpu_cores": 10,
            "memory_total_gb": 16.0,
            "memory_available_gb": 9.2,
            "disk_total_gb": 512.0,
            "disk_free_gb": 280.0,
            "ip_address": "192.168.1.101",
            "mac_address": "AA:BB:CC:11:22:01",
            "status": "online",
            "health_score": 95.0,
            "agent_version": "1.2.3",
            "snap_cpu": 12.5,
            "last_seen": _now - timedelta(seconds=30),
        },
        {
            "pc_name": "DESKTOP-PC002",
            "domain": "corp.example.com",
            "os_version": "Windows 11 Pro 23H2",
            "os_architecture": "64-bit",
            "cpu_name": "AMD Ryzen 7 7700X",
            "cpu_cores": 8,
            "memory_total_gb": 32.0,
            "memory_available_gb": 18.4,
            "disk_total_gb": 1024.0,
            "disk_free_gb": 650.0,
            "ip_address": "192.168.1.102",
            "mac_address": "AA:BB:CC:11:22:02",
            "status": "online",
            "health_score": 88.0,
            "agent_version": "1.2.3",
            "snap_cpu": 35.8,
            "last_seen": _now - timedelta(seconds=60),
        },
        {
            "pc_name": "LAPTOP-DEV003",
            "domain": "corp.example.com",
            "os_version": "Windows 11 Pro 22H2",
            "os_architecture": "64-bit",
            "cpu_name": "Intel Core i5-1235U",
            "cpu_cores": 10,
            "memory_total_gb": 16.0,
            "memory_available_gb": 4.1,
            "disk_total_gb": 256.0,
            "disk_free_gb": 42.0,
            "ip_address": "192.168.1.110",
            "mac_address": "AA:BB:CC:11:22:03",
            "status": "warning",
            "health_score": 62.0,
            "agent_version": "1.2.1",
            "snap_cpu": 78.3,
            "last_seen": _now - timedelta(seconds=120),
        },
        {
            "pc_name": "SERVER-FILESVR01",
            "domain": "corp.example.com",
            "os_version": "Windows Server 2022",
            "os_architecture": "64-bit",
            "cpu_name": "Intel Xeon E-2378G",
            "cpu_cores": 8,
            "memory_total_gb": 64.0,
            "memory_available_gb": 42.0,
            "disk_total_gb": 4096.0,
            "disk_free_gb": 2100.0,
            "ip_address": "192.168.1.200",
            "mac_address": "AA:BB:CC:11:22:10",
            "status": "online",
            "health_score": 97.0,
            "agent_version": "1.2.3",
            "snap_cpu": 5.2,
            "last_seen": _now - timedelta(seconds=45),
        },
        {
            "pc_name": "DESKTOP-PC005",
            "domain": "corp.example.com",
            "os_version": "Windows 10 Pro 22H2",
            "os_architecture": "64-bit",
            "cpu_name": "Intel Core i3-10100",
            "cpu_cores": 4,
            "memory_total_gb": 8.0,
            "memory_available_gb": 1.2,
            "disk_total_gb": 256.0,
            "disk_free_gb": 15.0,
            "ip_address": "192.168.1.105",
            "mac_address": "AA:BB:CC:11:22:05",
            "status": "offline",
            "health_score": 30.0,
            "agent_version": "1.1.9",
            "snap_cpu": None,
            "last_seen": _now - timedelta(hours=6),
        },
        {
            "pc_name": "LAPTOP-MGR006",
            "domain": "corp.example.com",
            "os_version": "Windows 11 Enterprise 23H2",
            "os_architecture": "64-bit",
            "cpu_name": "Intel Core i7-1260P",
            "cpu_cores": 12,
            "memory_total_gb": 32.0,
            "memory_available_gb": 20.1,
            "disk_total_gb": 512.0,
            "disk_free_gb": 310.0,
            "ip_address": "192.168.1.106",
            "mac_address": "AA:BB:CC:11:22:06",
            "status": "online",
            "health_score": 91.0,
            "agent_version": "1.2.3",
            "snap_cpu": 18.4,
            "last_seen": _now - timedelta(seconds=90),
        },
        {
            "pc_name": "SERVER-DC01",
            "domain": "corp.example.com",
            "os_version": "Windows Server 2022",
            "os_architecture": "64-bit",
            "cpu_name": "Intel Xeon E-2386G",
            "cpu_cores": 12,
            "memory_total_gb": 64.0,
            "memory_available_gb": 50.0,
            "disk_total_gb": 2048.0,
            "disk_free_gb": 1800.0,
            "ip_address": "192.168.1.201",
            "mac_address": "AA:BB:CC:11:22:11",
            "status": "online",
            "health_score": 99.0,
            "agent_version": "1.2.3",
            "snap_cpu": 3.1,
            "last_seen": _now - timedelta(seconds=20),
        },
        {
            "pc_name": "DESKTOP-SALES007",
            "domain": "corp.example.com",
            "os_version": "Windows 11 Pro 23H2",
            "os_architecture": "64-bit",
            "cpu_name": "AMD Ryzen 5 7600",
            "cpu_cores": 6,
            "memory_total_gb": 16.0,
            "memory_available_gb": 10.5,
            "disk_total_gb": 512.0,
            "disk_free_gb": 220.0,
            "ip_address": "192.168.1.107",
            "mac_address": "AA:BB:CC:11:22:07",
            "status": "online",
            "health_score": 84.0,
            "agent_version": "1.2.2",
            "snap_cpu": 25.0,
            "last_seen": _now - timedelta(seconds=180),
        },
    ]

    pc_map = {}  # pc_name → PC object
    for p in _pc_defs:
        existing = PC.query.filter_by(pc_name=p["pc_name"]).first()
        if existing:
            pc_map[p["pc_name"]] = existing
            continue
        new_pc = PC(
            pc_name=p["pc_name"],
            domain=p.get("domain"),
            os_version=p.get("os_version"),
            os_architecture=p.get("os_architecture"),
            cpu_name=p.get("cpu_name"),
            cpu_cores=p.get("cpu_cores"),
            memory_total_gb=p.get("memory_total_gb"),
            memory_available_gb=p.get("memory_available_gb"),
            disk_total_gb=p.get("disk_total_gb"),
            disk_free_gb=p.get("disk_free_gb"),
            ip_address=p.get("ip_address"),
            mac_address=p.get("mac_address"),
            status=p.get("status", "unknown"),
            health_score=p.get("health_score", 0.0),
            agent_version=p.get("agent_version"),
            last_seen=p.get("last_seen"),
            created_at=_now,
        )
        db.session.add(new_pc)
        db.session.flush()
        if p.get("snap_cpu") is not None:
            db.session.add(
                SystemSnapshot(
                    pc_id=new_pc.id,
                    cpu_usage=p["snap_cpu"],
                    memory_available_gb=p.get("memory_available_gb"),
                    disk_free_gb=p.get("disk_free_gb"),
                    collected_at=p.get("last_seen", _now),
                )
            )
        pc_map[p["pc_name"]] = new_pc
        added["pcs"] += 1

    db.session.flush()

    # ── Software (for PC detail page) ─────────────────────────────────
    _sw_common = [
        ("Microsoft 365 Apps", "16.0.17628", "Microsoft Corporation"),
        ("Google Chrome", "124.0.6367.207", "Google LLC"),
        ("7-Zip 23.01 (x64)", "23.01", "Igor Pavlov"),
        ("Zoom", "5.17.11", "Zoom Video Communications, Inc."),
        ("Visual Studio Code", "1.89.1", "Microsoft Corporation"),
        ("Slack", "4.38.125", "Slack Technologies"),
        ("Adobe Acrobat Reader DC", "24.001.20604", "Adobe Inc."),
    ]
    for pc_name, pc_obj in pc_map.items():
        if not Software.query.filter_by(pc_id=pc_obj.id).first():
            for sw_name, sw_ver, sw_pub in _sw_common:
                db.session.add(
                    Software(
                        pc_id=pc_obj.id,
                        name=sw_name,
                        version=sw_ver,
                        publisher=sw_pub,
                        collected_at=_now,
                    )
                )
                added["software"] += 1

    # ── Windows Updates (for PC detail page) ──────────────────────────
    _updates = [
        (
            "KB5035853",
            "2024-03 x64 向け累積更新プログラム",
            "Critical",
            True,
            _now - timedelta(days=10),
        ),
        (
            "KB5034441",
            "2024-01 WinRE 更新プログラム",
            "Important",
            True,
            _now - timedelta(days=40),
        ),
        ("KB5036893", "2024-04 .NET Framework 累積更新", "Moderate", False, None),
        ("KB5037771", "2024-05 セキュリティ品質ロールアップ", "Critical", False, None),
        (
            "KB5035951",
            "Microsoft Defender ウイルス対策定義",
            "Moderate",
            True,
            _now - timedelta(days=2),
        ),
    ]
    for pc_name, pc_obj in list(pc_map.items())[:4]:
        if not WindowsUpdate.query.filter_by(pc_id=pc_obj.id).first():
            for kb_id, title, sev, installed, inst_at in _updates:
                db.session.add(
                    WindowsUpdate(
                        pc_id=pc_obj.id,
                        kb_id=kb_id,
                        title=title,
                        severity=sev,
                        installed=installed,
                        installed_at=inst_at,
                        collected_at=_now,
                    )
                )
                added["windows_updates"] += 1

    db.session.flush()

    # ── PC Groups ─────────────────────────────────────────────────────
    _group_defs = [
        {
            "name": "営業部PC",
            "description": "営業部門所属のデスクトップ・ノートPC",
            "members": ["DESKTOP-PC001", "DESKTOP-SALES007", "LAPTOP-MGR006"],
        },
        {
            "name": "開発環境",
            "description": "開発者向けワークステーションおよびサーバー",
            "members": ["LAPTOP-DEV003", "DESKTOP-PC002", "SERVER-DC01"],
        },
        {
            "name": "サーバーグループ",
            "description": "ファイルサーバー・DCなどインフラ機器",
            "members": ["SERVER-FILESVR01", "SERVER-DC01"],
        },
        {
            "name": "要注意PC",
            "description": "健全性スコアが低いまたはオフラインのPC",
            "members": ["LAPTOP-DEV003", "DESKTOP-PC005"],
        },
    ]
    for gd in _group_defs:
        if not PCGroup.query.filter_by(name=gd["name"]).first():
            grp = PCGroup(
                name=gd["name"],
                description=gd["description"],
                created_by="admin",
                created_at=_now,
            )
            db.session.add(grp)
            db.session.flush()
            for pname in gd["members"]:
                pc_obj = pc_map.get(pname)
                if pc_obj:
                    grp.pcs.append(pc_obj)
            added["groups"] += 1

    db.session.flush()

    # ── Alert Rules ───────────────────────────────────────────────────
    _rule_defs = [
        {
            "name": "CPU使用率 高負荷",
            "metric": "cpu",
            "operator": "gt",
            "threshold": 90.0,
            "severity": "warning",
            "notify_email": "ops@corp.example.com",
        },
        {
            "name": "CPU使用率 危険",
            "metric": "cpu",
            "operator": "gt",
            "threshold": 98.0,
            "severity": "critical",
            "notify_slack_webhook": "https://hooks.slack.com/services/T00000000/B00000000/xxxx",
        },
        {
            "name": "メモリ使用率 高",
            "metric": "memory",
            "operator": "gt",
            "threshold": 85.0,
            "severity": "warning",
            "notify_email": "ops@corp.example.com",
        },
        {
            "name": "ディスク残量 不足",
            "metric": "disk",
            "operator": "lt",
            "threshold": 10.0,
            "severity": "critical",
            "notify_email": "ops@corp.example.com",
            "notify_slack_webhook": "https://hooks.slack.com/services/T00000000/B00000000/xxxx",
        },
        {
            "name": "PC オフライン検知",
            "metric": "offline",
            "operator": "gt",
            "threshold": None,
            "severity": "critical",
            "notify_email": "ops@corp.example.com",
        },
        {
            "name": "健全性スコア 低下",
            "metric": "health_score",
            "operator": "lt",
            "threshold": 50.0,
            "severity": "warning",
            "notify_email": "ops@corp.example.com",
        },
    ]
    for rd in _rule_defs:
        if not AlertRule.query.filter_by(name=rd["name"]).first():
            db.session.add(
                AlertRule(
                    name=rd["name"],
                    metric=rd["metric"],
                    operator=rd["operator"],
                    threshold=rd.get("threshold"),
                    severity=rd["severity"],
                    notify_email=rd.get("notify_email"),
                    notify_slack_webhook=rd.get("notify_slack_webhook"),
                    is_enabled=True,
                    created_by="admin",
                    created_at=_now,
                )
            )
            added["alert_rules"] += 1

    db.session.flush()

    # ── Alerts ────────────────────────────────────────────────────────
    _alert_defs = [
        {
            "pc": "LAPTOP-DEV003",
            "alert_type": "high_cpu",
            "severity": "critical",
            "message": "CPU使用率が 78.3% に達しました（閾値: 70%）",
            "source_key": "seed-alert-001",
            "resolved": False,
        },
        {
            "pc": "DESKTOP-PC005",
            "alert_type": "offline",
            "severity": "critical",
            "message": "PCが 6時間以上オフラインです",
            "source_key": "seed-alert-002",
            "resolved": False,
        },
        {
            "pc": "LAPTOP-DEV003",
            "alert_type": "low_disk",
            "severity": "critical",
            "message": "Cドライブの空き容量が 42GB (16%) に低下しました",
            "source_key": "seed-alert-003",
            "resolved": False,
        },
        {
            "pc": "DESKTOP-PC005",
            "alert_type": "high_memory",
            "severity": "warning",
            "message": "メモリ使用率が 85% を超えました",
            "source_key": "seed-alert-004",
            "resolved": False,
        },
        {
            "pc": "DESKTOP-PC002",
            "alert_type": "high_cpu",
            "severity": "warning",
            "message": "CPU使用率が 35.8% が継続しています（通常の2倍）",
            "source_key": "seed-alert-005",
            "resolved": False,
        },
        {
            "pc": "SERVER-FILESVR01",
            "alert_type": "windows_update",
            "severity": "medium",
            "message": "未適用のセキュリティ更新プログラムが 2件あります",
            "source_key": "seed-alert-006",
            "resolved": False,
            "acknowledged": True,
            "acknowledged_by": "admin",
        },
        {
            "pc": "DESKTOP-PC001",
            "alert_type": "high_cpu",
            "severity": "warning",
            "message": "CPU使用率が一時的に 92% に達しました",
            "source_key": "seed-alert-007",
            "resolved": True,
            "resolved_at": _now - timedelta(hours=2),
        },
        {
            "pc": "DESKTOP-SALES007",
            "alert_type": "offline",
            "severity": "critical",
            "message": "PCが 3時間オフラインでした",
            "source_key": "seed-alert-008",
            "resolved": True,
            "resolved_at": _now - timedelta(hours=5),
        },
        {
            "pc": "LAPTOP-MGR006",
            "alert_type": "low_disk",
            "severity": "warning",
            "message": "Dドライブの空き容量が 15% を下回りました",
            "source_key": "seed-alert-009",
            "resolved": False,
        },
        {
            "pc": "SERVER-DC01",
            "alert_type": "windows_update",
            "severity": "low",
            "message": "推奨更新プログラムが利用可能です（KB5035853）",
            "source_key": "seed-alert-010",
            "resolved": False,
        },
        {
            "pc": "DESKTOP-PC002",
            "alert_type": "health_score",
            "severity": "warning",
            "message": "健全性スコアが 88 に低下しました（前回: 94）",
            "source_key": "seed-alert-011",
            "resolved": True,
            "resolved_at": _now - timedelta(hours=12),
        },
        {
            "pc": None,
            "alert_type": "agent_version",
            "severity": "low",
            "message": "Agent v1.1.9 はサポート終了予定です。v1.2.x へ更新してください",
            "source_key": "seed-alert-012",
            "resolved": False,
        },
    ]
    for ad in _alert_defs:
        if Alert.query.filter_by(source_key=ad["source_key"]).first():
            continue
        pc_obj = pc_map.get(ad.get("pc")) if ad.get("pc") else None
        alert = Alert(
            pc_id=pc_obj.id if pc_obj else None,
            alert_type=ad["alert_type"],
            severity=ad["severity"],
            message=ad["message"],
            source_key=ad["source_key"],
            resolved=ad.get("resolved", False),
            acknowledged=ad.get("acknowledged", False),
            acknowledged_by=ad.get("acknowledged_by"),
            acknowledged_at=_now - timedelta(hours=1)
            if ad.get("acknowledged_by")
            else None,
            resolved_at=ad.get("resolved_at"),
            created_at=_now - timedelta(hours=1 if ad.get("resolved") else 0),
        )
        db.session.add(alert)
        added["alerts"] += 1

    db.session.flush()

    # ── Tasks ─────────────────────────────────────────────────────────
    _task_defs = [
        {
            "pc": "DESKTOP-PC001",
            "task_type": "windows_update",
            "status": "completed",
            "created_by": "admin",
            "result": "KB5035853 を正常にインストールしました",
            "delta_created": timedelta(hours=3),
            "delta_started": timedelta(hours=3),
            "delta_done": timedelta(hours=2, minutes=30),
        },
        {
            "pc": "DESKTOP-PC002",
            "task_type": "disk_cleanup",
            "status": "completed",
            "created_by": "admin",
            "result": "4.2GB の一時ファイルを削除しました",
            "delta_created": timedelta(hours=5),
            "delta_started": timedelta(hours=5),
            "delta_done": timedelta(hours=4, minutes=45),
        },
        {
            "pc": "LAPTOP-DEV003",
            "task_type": "windows_update",
            "status": "failed",
            "created_by": "admin",
            "error_message": "更新の適用中にエラーが発生しました: 0x80070005 アクセスが拒否されました",
            "delta_created": timedelta(hours=2),
            "delta_started": timedelta(hours=2),
            "delta_done": timedelta(hours=1, minutes=50),
        },
        {
            "pc": "SERVER-FILESVR01",
            "task_type": "powershell",
            "status": "completed",
            "created_by": "sysadmin",
            "command": "Get-EventLog -LogName System -Newest 100 | Export-Csv C:\\logs\\events.csv",
            "result": "イベントログを正常にエクスポートしました",
            "delta_created": timedelta(hours=6),
            "delta_started": timedelta(hours=6),
            "delta_done": timedelta(hours=5, minutes=55),
        },
        {
            "pc": "DESKTOP-SALES007",
            "task_type": "software",
            "status": "running",
            "created_by": "admin",
            "result": None,
            "delta_created": timedelta(minutes=10),
            "delta_started": timedelta(minutes=8),
            "delta_done": None,
        },
        {
            "pc": "LAPTOP-MGR006",
            "task_type": "disk_cleanup",
            "status": "pending",
            "created_by": "admin",
            "result": None,
            "delta_created": timedelta(minutes=2),
            "delta_started": None,
            "delta_done": None,
        },
        {
            "pc": "DESKTOP-PC001",
            "task_type": "powershell",
            "status": "completed",
            "created_by": "developer",
            "command": "Restart-Service -Name Spooler",
            "result": "Spooler サービスを正常に再起動しました",
            "delta_created": timedelta(days=1),
            "delta_started": timedelta(days=1),
            "delta_done": timedelta(hours=23, minutes=58),
        },
        {
            "pc": None,
            "task_type": "windows_update",
            "status": "completed",
            "created_by": "system",
            "result": "全8台に対してWindows Update スキャンを実行しました",
            "delta_created": timedelta(days=2),
            "delta_started": timedelta(days=2),
            "delta_done": timedelta(days=1, hours=22),
        },
        {
            "pc": "SERVER-DC01",
            "task_type": "powershell",
            "status": "pending",
            "created_by": "admin",
            "command": "Invoke-GPUpdate -Force",
            "result": None,
            "delta_created": timedelta(minutes=5),
            "delta_started": None,
            "delta_done": None,
        },
        {
            "pc": "DESKTOP-PC005",
            "task_type": "disk_cleanup",
            "status": "cancelled",
            "created_by": "admin",
            "result": None,
            "delta_created": timedelta(hours=8),
            "delta_started": None,
            "delta_done": None,
        },
        {
            "pc": "LAPTOP-DEV003",
            "task_type": "software",
            "status": "completed",
            "created_by": "sysadmin",
            "result": "Visual Studio Code v1.89.1 を正常にインストールしました",
            "delta_created": timedelta(days=3),
            "delta_started": timedelta(days=3),
            "delta_done": timedelta(days=2, hours=23, minutes=30),
        },
        {
            "pc": "DESKTOP-PC002",
            "task_type": "restart",
            "status": "completed",
            "created_by": "admin",
            "result": "PCを正常に再起動しました（メンテナンス完了）",
            "delta_created": timedelta(days=4),
            "delta_started": timedelta(days=4),
            "delta_done": timedelta(days=3, hours=23, minutes=50),
        },
    ]
    for td in _task_defs:
        pc_obj = pc_map.get(td.get("pc")) if td.get("pc") else None
        task = Task(
            pc_id=pc_obj.id if pc_obj else None,
            task_type=td["task_type"],
            command=td.get("command"),
            status=td["status"],
            created_by=td["created_by"],
            result=td.get("result"),
            error_message=td.get("error_message"),
            created_at=_now - td["delta_created"],
            started_at=(_now - td["delta_started"])
            if td.get("delta_started")
            else None,
            completed_at=(_now - td["delta_done"]) if td.get("delta_done") else None,
        )
        db.session.add(task)
        added["tasks"] += 1

    db.session.flush()

    # ── Scheduled Tasks ───────────────────────────────────────────────
    _st_defs = [
        {
            "name": "毎日 Windows Update チェック",
            "description": "全PCに対してWindows Updateの適用状況を確認し、不足があれば通知",
            "task_type": "windows_update",
            "schedule_type": "daily",
            "daily_time": "03:00",
            "is_enabled": True,
            "target_type": "all",
            "run_count": 42,
            "last_status": "completed",
            "last_run_at": _now - timedelta(hours=6),
            "next_run_at": _now + timedelta(hours=18),
        },
        {
            "name": "週次 ディスククリーンアップ",
            "description": "毎週日曜日に一時ファイル・ゴミ箱を自動削除",
            "task_type": "disk_cleanup",
            "schedule_type": "weekly",
            "weekly_day": 6,
            "weekly_time": "02:00",
            "is_enabled": True,
            "target_type": "all",
            "run_count": 8,
            "last_status": "completed",
            "last_run_at": _now - timedelta(days=3),
            "next_run_at": _now + timedelta(days=4),
        },
        {
            "name": "開発PC ソフトウェアインベントリ",
            "description": "開発環境グループのPCのインストール済みソフトウェアを収集",
            "task_type": "powershell",
            "command": "Get-InstalledSoftware | ConvertTo-Json | Out-File C:\\inventory.json",
            "schedule_type": "interval",
            "interval_minutes": 360,
            "is_enabled": True,
            "target_type": "all",
            "run_count": 120,
            "last_status": "completed",
            "last_run_at": _now - timedelta(hours=1),
            "next_run_at": _now + timedelta(hours=5),
        },
        {
            "name": "サーバー イベントログ収集",
            "description": "サーバーグループのWindowsイベントログをエクスポート",
            "task_type": "powershell",
            "command": "Get-EventLog -LogName System,Application -Newest 500 | Export-Csv C:\\logs\\events.csv",
            "schedule_type": "daily",
            "daily_time": "00:30",
            "is_enabled": True,
            "target_type": "pc",
            "run_count": 30,
            "last_status": "completed",
            "last_run_at": _now - timedelta(hours=10),
            "next_run_at": _now + timedelta(hours=14),
        },
        {
            "name": "月次 セキュリティパッチ適用",
            "description": "Critical・Importantに分類された更新プログラムを月次で強制適用",
            "task_type": "windows_update",
            "schedule_type": "interval",
            "interval_minutes": 43200,
            "is_enabled": False,
            "target_type": "all",
            "run_count": 3,
            "last_status": "failed",
            "last_run_at": _now - timedelta(days=30),
            "next_run_at": None,
        },
    ]
    for sd in _st_defs:
        if not ScheduledTask.query.filter_by(name=sd["name"]).first():
            db.session.add(
                ScheduledTask(
                    name=sd["name"],
                    description=sd.get("description"),
                    task_type=sd["task_type"],
                    command=sd.get("command"),
                    parameters=json.dumps({}),
                    target_type=sd.get("target_type", "all"),
                    schedule_type=sd["schedule_type"],
                    interval_minutes=sd.get("interval_minutes"),
                    daily_time=sd.get("daily_time"),
                    weekly_day=sd.get("weekly_day"),
                    weekly_time=sd.get("weekly_time"),
                    is_enabled=sd.get("is_enabled", True),
                    run_count=sd.get("run_count", 0),
                    last_status=sd.get("last_status"),
                    last_run_at=sd.get("last_run_at"),
                    next_run_at=sd.get("next_run_at"),
                    created_by="admin",
                    created_at=_now - timedelta(days=30),
                )
            )
            added["scheduled_tasks"] += 1

    db.session.flush()

    # ── Audit / Operation Logs ────────────────────────────────────────
    _log_defs = [
        {
            "action": "user_login",
            "target": "admin",
            "details": "管理者がログインしました",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(minutes=5),
        },
        {
            "action": "task_create",
            "target": "DESKTOP-PC001 / windows_update",
            "details": "Windows Update タスクを作成しました",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(hours=1),
        },
        {
            "action": "alert_acknowledge",
            "target": "Alert#6 / SERVER-FILESVR01",
            "details": "アラートを確認済みにしました",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(hours=2),
        },
        {
            "action": "pc_group_create",
            "target": "営業部PC",
            "details": "PCグループ「営業部PC」を作成しました (3台)",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(hours=3),
        },
        {
            "action": "alert_rule_update",
            "target": "CPU使用率 高負荷",
            "details": "閾値を 85% → 90% に変更しました",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(hours=4),
        },
        {
            "action": "task_create",
            "target": "全PC / disk_cleanup",
            "details": "全PCにディスククリーンアップタスクを一括発行しました",
            "created_by": "sysadmin",
            "ip": "192.168.1.55",
            "delta": timedelta(hours=5),
        },
        {
            "action": "user_login",
            "target": "sysadmin",
            "details": "システム管理者がログインしました",
            "created_by": "sysadmin",
            "ip": "192.168.1.55",
            "delta": timedelta(hours=6),
        },
        {
            "action": "scheduled_task_create",
            "target": "毎日 Windows Update チェック",
            "details": "スケジュールタスクを作成しました (毎日 03:00)",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(hours=8),
        },
        {
            "action": "alert_resolve",
            "target": "Alert#7 / DESKTOP-PC001",
            "details": "CPU高負荷アラートを解決済みにしました",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(hours=10),
        },
        {
            "action": "notification_channel_create",
            "target": "#pc-ops-critical (Slack)",
            "details": "Slack通知チャンネルを追加しました",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(hours=12),
        },
        {
            "action": "task_create",
            "target": "SERVER-DC01 / powershell",
            "details": "グループポリシー強制更新コマンドを実行しました",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(hours=14),
        },
        {
            "action": "certificate_create",
            "target": "pc-ops.example.com",
            "details": "TLS証明書を登録しました (Let's Encrypt, 有効期限: 2026-06-30)",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(days=1),
        },
        {
            "action": "user_logout",
            "target": "sysadmin",
            "details": "システム管理者がログアウトしました",
            "created_by": "sysadmin",
            "ip": "192.168.1.55",
            "delta": timedelta(days=1, hours=2),
        },
        {
            "action": "alert_rule_create",
            "target": "PC オフライン検知",
            "details": "オフライン検知アラートルールを作成しました",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(days=2),
        },
        {
            "action": "license_create",
            "target": "Microsoft 365 E3",
            "details": "ライセンス情報を登録しました (150席)",
            "created_by": "admin",
            "ip": "192.168.1.50",
            "delta": timedelta(days=3),
        },
    ]
    existing_log_count = OperationLog.query.count()
    if existing_log_count == 0:
        for ld in _log_defs:
            db.session.add(
                OperationLog(
                    action=ld["action"],
                    target=ld.get("target"),
                    details=ld.get("details"),
                    ip_address=ld.get("ip"),
                    created_by=ld["created_by"],
                    created_at=_now - ld["delta"],
                )
            )
            added["operation_logs"] += 1

    # ── Notification Channels ─────────────────────────────────────────
    _channels = [
        {
            "name": "#pc-ops-critical",
            "channel_type": "slack",
            "target": "https://hooks.slack.com/services/T00000000/B00000000/xxxx",
            "is_active": True,
        },
        {
            "name": "Ops Teams",
            "channel_type": "teams",
            "target": "https://example.webhook.office.com/webhookb2/xxxxxxxx",
            "is_active": True,
        },
        {
            "name": "oncall-mail",
            "channel_type": "email",
            "target": "oncall@corp.example.com",
            "is_active": True,
        },
        {
            "name": "SIEM Webhook",
            "channel_type": "webhook",
            "target": "https://siem.example.com/ingest/pc-ops",
            "is_active": True,
        },
        {
            "name": "legacy-pagerduty",
            "channel_type": "webhook",
            "target": "https://events.pagerduty.com/integration/xxxx/enqueue",
            "is_active": False,
        },
    ]
    for ch in _channels:
        if not NotificationChannel.query.filter_by(name=ch["name"]).first():
            db.session.add(
                NotificationChannel(
                    name=ch["name"],
                    channel_type=ch["channel_type"],
                    target=ch["target"],
                    is_active=ch["is_active"],
                    created_at=_now,
                )
            )
            added["notification_channels"] += 1

    # ── Certificates ──────────────────────────────────────────────────
    _certs = [
        {
            "name": "pc-ops.example.com",
            "domain": "pc-ops.example.com",
            "issuer": "Let's Encrypt R3",
            "cert_type": "server",
            "issued_at": date(2026, 4, 1),
            "expires_at": date(2026, 6, 30),
            "auto_renew": True,
        },
        {
            "name": "api.pc-ops.example.com",
            "domain": "api.pc-ops.example.com",
            "issuer": "Let's Encrypt R3",
            "cert_type": "server",
            "issued_at": date(2026, 4, 1),
            "expires_at": date(2026, 6, 30),
            "auto_renew": True,
        },
        {
            "name": "pc-ops-stg.example.com",
            "domain": "pc-ops-stg.example.com",
            "issuer": "Let's Encrypt R3",
            "cert_type": "server",
            "issued_at": date(2026, 2, 1),
            "expires_at": date(2026, 5, 30),
            "auto_renew": True,
        },
        {
            "name": "*.internal.example.com",
            "domain": "*.internal.example.com",
            "issuer": "Internal CA",
            "cert_type": "server",
            "issued_at": date(2026, 1, 15),
            "expires_at": date(2027, 1, 15),
            "auto_renew": False,
        },
        {
            "name": "agent-mtls-2026",
            "domain": "agent.internal.example.com",
            "issuer": "Internal CA",
            "cert_type": "client",
            "issued_at": date(2026, 4, 28),
            "expires_at": date(2027, 4, 28),
            "auto_renew": False,
            "notes": "Agent ↔ Server mTLS 証明書",
        },
    ]
    for c in _certs:
        if not Certificate.query.filter_by(domain=c["domain"]).first():
            db.session.add(
                Certificate(
                    name=c["name"],
                    domain=c["domain"],
                    issuer=c.get("issuer"),
                    cert_type=c.get("cert_type", "server"),
                    issued_at=c.get("issued_at"),
                    expires_at=c["expires_at"],
                    auto_renew=c.get("auto_renew", True),
                    notes=c.get("notes"),
                    created_at=_now,
                )
            )
            added["certificates"] += 1

    # ── Licenses ──────────────────────────────────────────────────────
    _licenses = [
        {
            "product_name": "Microsoft 365 E3",
            "vendor": "Microsoft",
            "license_type": "subscription",
            "seat_count": 150,
            "unit_price": 1360,
            "expires_at": date(2027, 3, 31),
        },
        {
            "product_name": "Adobe Creative Cloud (法人)",
            "vendor": "Adobe",
            "license_type": "subscription",
            "seat_count": 20,
            "unit_price": 3000,
            "expires_at": date(2027, 3, 31),
        },
        {
            "product_name": "Sophos Endpoint",
            "vendor": "Sophos",
            "license_type": "subscription",
            "seat_count": 200,
            "unit_price": 200,
            "expires_at": date(2026, 7, 15),
        },
        {
            "product_name": "JetBrains All Products",
            "vendor": "JetBrains",
            "license_type": "subscription",
            "seat_count": 10,
            "unit_price": 3000,
            "expires_at": date(2026, 8, 31),
        },
        {
            "product_name": "Slack Business+",
            "vendor": "Salesforce",
            "license_type": "subscription",
            "seat_count": 200,
            "unit_price": 300,
            "expires_at": date(2027, 2, 28),
        },
        {
            "product_name": "Visual Studio Pro",
            "vendor": "Microsoft",
            "license_type": "perpetual",
            "seat_count": 15,
            "unit_price": 0,
            "expires_at": None,
            "notes": "VL 買切 (償却済)",
        },
    ]
    for lic in _licenses:
        if not License.query.filter_by(product_name=lic["product_name"]).first():
            db.session.add(
                License(
                    product_name=lic["product_name"],
                    vendor=lic.get("vendor"),
                    license_type=lic.get("license_type", "subscription"),
                    seat_count=lic.get("seat_count"),
                    unit_price=lic.get("unit_price"),
                    expires_at=lic.get("expires_at"),
                    notes=lic.get("notes"),
                    created_at=_now,
                )
            )
            added["licenses"] += 1

    # Seed backup history (if none exist)
    added["backups"] = 0
    if BackupJob.query.count() == 0:
        _backup_seeds = [
            {"days_ago": 1, "btype": "full", "size": 2_200_000_000, "dur": 268},
            {"days_ago": 2, "btype": "incremental", "size": 156_000_000, "dur": 68},
            {"days_ago": 3, "btype": "incremental", "size": 139_000_000, "dur": 61},
            {"days_ago": 4, "btype": "incremental", "size": 148_000_000, "dur": 62},
            {"days_ago": 5, "btype": "incremental", "size": 132_000_000, "dur": 58},
            {"days_ago": 6, "btype": "incremental", "size": 119_000_000, "dur": 51},
            {"days_ago": 8, "btype": "full", "size": 2_000_000_000, "dur": 258},
        ]
        for b in _backup_seeds:
            ts = _now - timedelta(days=b["days_ago"])
            db.session.add(
                BackupJob(
                    backup_type=b["btype"],
                    target="DB + config" if b["btype"] == "full" else "DB",
                    status="success",
                    size_bytes=b["size"],
                    duration_seconds=b["dur"],
                    storage_path="s3://pc-ops-backups/",
                    started_at=ts,
                    finished_at=ts,
                )
            )
            added["backups"] += 1

    db.session.commit()
    total = sum(added.values())
    return jsonify(
        {"message": f"デモデータを {total} 件追加しました", "added": added}
    ), 201

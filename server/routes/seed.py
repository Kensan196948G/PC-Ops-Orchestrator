"""Demo data seeding endpoint — admin only, not for production use."""

from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify

from auth import admin_required
from extensions import db
from models import Certificate, License, NotificationChannel, PC, SystemSnapshot

seed_bp = Blueprint("seed", __name__)


@seed_bp.route("/admin/seed-demo", methods=["POST"])
@admin_required
def seed_demo():
    """Populate demo data for notification channels, certificates and licenses."""
    added = {"notification_channels": 0, "certificates": 0, "licenses": 0, "pcs": 0}

    # ── Notification Channels ──────────────────────────────────────────
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
            "target": "oncall@example.com",
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
                    created_at=datetime.now(timezone.utc),
                )
            )
            added["notification_channels"] += 1

    # ── Certificates ───────────────────────────────────────────────────
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
                    created_at=datetime.now(timezone.utc),
                )
            )
            added["certificates"] += 1

    # ── Licenses ────────────────────────────────────────────────────────
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
                    created_at=datetime.now(timezone.utc),
                )
            )
            added["licenses"] += 1

    # ── PCs (Agent demo) ───────────────────────────────────────────────
    _now = datetime.now(timezone.utc)
    _pcs = [
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
    ]
    for p in _pcs:
        if not PC.query.filter_by(pc_name=p["pc_name"]).first():
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
            added["pcs"] = added.get("pcs", 0) + 1

    db.session.commit()
    total = sum(added.values())
    return jsonify(
        {"message": f"デモデータを {total} 件追加しました", "added": added}
    ), 201

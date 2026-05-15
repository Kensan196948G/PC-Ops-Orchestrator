import secrets
from datetime import datetime, timezone
from extensions import db

pc_group_membership = db.Table(
    "pc_group_memberships",
    db.Column("group_id", db.Integer, db.ForeignKey("pc_groups.id"), primary_key=True),
    db.Column("pc_id", db.Integer, db.ForeignKey("pcs.id"), primary_key=True),
)


class PCGroup(db.Model):
    __tablename__ = "pc_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    created_by = db.Column(db.String(255), default="system")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    pcs = db.relationship(
        "PC", secondary=pc_group_membership, backref="groups", lazy="dynamic"
    )

    def to_dict(self, include_pcs=False, pc_count=None):
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "pc_count": pc_count if pc_count is not None else self.pcs.count(),
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_pcs:
            d["pcs"] = [
                {"id": pc.id, "pc_name": pc.pc_name, "status": pc.status}
                for pc in self.pcs
            ]
        return d

    def __repr__(self):
        return f"<PCGroup {self.name}>"


class PC(db.Model):
    __tablename__ = "pcs"

    id = db.Column(db.Integer, primary_key=True)
    pc_name = db.Column(db.String(255), unique=True, nullable=False, index=True)
    domain = db.Column(db.String(255))
    os_version = db.Column(db.String(255))
    os_architecture = db.Column(db.String(32))
    cpu_name = db.Column(db.String(255))
    cpu_cores = db.Column(db.Integer)
    cpu_logical_processors = db.Column(db.Integer)
    memory_total_gb = db.Column(db.Float)
    memory_available_gb = db.Column(db.Float)
    disk_total_gb = db.Column(db.Float)
    disk_free_gb = db.Column(db.Float)
    ip_address = db.Column(db.String(45))
    mac_address = db.Column(db.String(17))
    last_seen = db.Column(db.DateTime)
    status = db.Column(db.String(32), default="unknown")
    health_score = db.Column(db.Float, default=0.0)
    agent_version = db.Column(db.String(32))
    # VPN/offline sync fields (Issue #154)
    connection_type = db.Column(db.String(32), default="Unknown")
    offline_pending_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    snapshots = db.relationship(
        "SystemSnapshot", backref="pc", lazy="dynamic", cascade="all, delete-orphan"
    )
    software = db.relationship(
        "Software", backref="pc", lazy="dynamic", cascade="all, delete-orphan"
    )
    updates = db.relationship(
        "WindowsUpdate", backref="pc", lazy="dynamic", cascade="all, delete-orphan"
    )
    tasks = db.relationship(
        "Task", backref="pc", lazy="dynamic", cascade="all, delete-orphan"
    )
    event_logs = db.relationship(
        "EventLog", backref="pc", lazy="dynamic", cascade="all, delete-orphan"
    )
    scheduled_tasks = db.relationship(
        "ScheduledTask", backref="pc", lazy="dynamic", cascade="all, delete-orphan"
    )
    alerts = db.relationship(
        "Alert", backref="pc", lazy="dynamic", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "pc_name": self.pc_name,
            "domain": self.domain,
            "os_version": self.os_version,
            "os_architecture": self.os_architecture,
            "cpu_name": self.cpu_name,
            "cpu_cores": self.cpu_cores,
            "cpu_logical_processors": self.cpu_logical_processors,
            "memory_total_gb": self.memory_total_gb,
            "memory_available_gb": self.memory_available_gb,
            "disk_total_gb": self.disk_total_gb,
            "disk_free_gb": self.disk_free_gb,
            "ip_address": self.ip_address,
            "mac_address": self.mac_address,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "status": self.status,
            "health_score": self.health_score,
            "agent_version": self.agent_version,
            "connection_type": self.connection_type or "Unknown",
            "offline_pending_count": self.offline_pending_count or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<PC {self.pc_name}>"


class SystemSnapshot(db.Model):
    __tablename__ = "system_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    pc_id = db.Column(db.Integer, db.ForeignKey("pcs.id"), nullable=False, index=True)
    collected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    cpu_usage = db.Column(db.Float)
    memory_available_gb = db.Column(db.Float)
    disk_free_gb = db.Column(db.Float)
    uptime_days = db.Column(db.Float)
    pending_reboot = db.Column(db.Boolean, default=False)
    windows_update_pending = db.Column(db.Boolean, default=False)
    last_boot_time = db.Column(db.DateTime)

    def to_dict(self):
        return {
            "id": self.id,
            "pc_id": self.pc_id,
            "collected_at": self.collected_at.isoformat()
            if self.collected_at
            else None,
            "cpu_usage": self.cpu_usage,
            "memory_available_gb": self.memory_available_gb,
            "disk_free_gb": self.disk_free_gb,
            "uptime_days": self.uptime_days,
            "pending_reboot": self.pending_reboot,
            "windows_update_pending": self.windows_update_pending,
            "last_boot_time": self.last_boot_time.isoformat()
            if self.last_boot_time
            else None,
        }


class Software(db.Model):
    __tablename__ = "software"

    id = db.Column(db.Integer, primary_key=True)
    pc_id = db.Column(db.Integer, db.ForeignKey("pcs.id"), nullable=False, index=True)
    name = db.Column(db.String(512), nullable=False)
    version = db.Column(db.String(255))
    publisher = db.Column(db.String(255))
    install_date = db.Column(db.DateTime)
    collected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "pc_id": self.pc_id,
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "install_date": self.install_date.isoformat()
            if self.install_date
            else None,
        }


class WindowsUpdate(db.Model):
    __tablename__ = "windows_updates"

    id = db.Column(db.Integer, primary_key=True)
    pc_id = db.Column(db.Integer, db.ForeignKey("pcs.id"), nullable=False, index=True)
    kb_id = db.Column(db.String(32))
    title = db.Column(db.String(512))
    severity = db.Column(db.String(64))
    installed = db.Column(db.Boolean, default=False)
    installed_at = db.Column(db.DateTime)
    collected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "pc_id": self.pc_id,
            "kb_id": self.kb_id,
            "title": self.title,
            "severity": self.severity,
            "installed": self.installed,
            "installed_at": self.installed_at.isoformat()
            if self.installed_at
            else None,
        }


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    pc_id = db.Column(db.Integer, db.ForeignKey("pcs.id"), nullable=True, index=True)
    task_type = db.Column(db.String(64), nullable=False)
    command = db.Column(db.Text)
    parameters = db.Column(db.Text)
    status = db.Column(db.String(32), default="pending", index=True)
    priority = db.Column(db.Integer, default=0)
    created_by = db.Column(db.String(255), default="system")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    result = db.Column(db.Text)
    error_message = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id,
            "pc_id": self.pc_id,
            "task_type": self.task_type,
            "command": self.command,
            "parameters": self.parameters,
            "status": self.status,
            "priority": self.priority,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "result": self.result,
            "error_message": self.error_message,
        }

    def __repr__(self):
        return f"<Task {self.id}:{self.task_type} [{self.status}]>"


class EventLog(db.Model):
    __tablename__ = "event_logs"

    id = db.Column(db.Integer, primary_key=True)
    pc_id = db.Column(db.Integer, db.ForeignKey("pcs.id"), nullable=False, index=True)
    log_type = db.Column(db.String(64), nullable=False)
    event_id = db.Column(db.Integer)
    level = db.Column(db.String(32))
    source = db.Column(db.String(255))
    message = db.Column(db.Text)
    generated_at = db.Column(db.DateTime)
    collected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "pc_id": self.pc_id,
            "log_type": self.log_type,
            "event_id": self.event_id,
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "generated_at": self.generated_at.isoformat()
            if self.generated_at
            else None,
        }


class OperationLog(db.Model):
    __tablename__ = "operation_logs"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(255), nullable=False)
    target = db.Column(db.String(255))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(512))
    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "action": self.action,
            "target": self.target,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AlertRule(db.Model):
    __tablename__ = "alert_rules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    metric = db.Column(db.String(64), nullable=False)  # cpu/memory/disk/offline
    operator = db.Column(db.String(8), nullable=False, default="gt")  # gt/lt/gte/lte
    threshold = db.Column(db.Float, nullable=True)
    severity = db.Column(
        db.String(16), nullable=False, default="warning"
    )  # warning/critical
    notify_email = db.Column(db.Text)
    notify_slack_webhook = db.Column(db.Text)
    notify_teams_webhook = db.Column(db.Text)
    notify_webhook_url = db.Column(db.Text)
    # Preferred channel for test-notify and the Alert dispatcher when set.
    # NULL = legacy mode (use whichever notify_* columns are populated).
    channel_type = db.Column(db.String(32))
    is_enabled = db.Column(db.Boolean, default=True, index=True)
    created_by = db.Column(db.String(255), default="system")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
            "severity": self.severity,
            "notify_email": self.notify_email,
            "notify_slack_webhook": self.notify_slack_webhook,
            "notify_teams_webhook": self.notify_teams_webhook,
            "notify_webhook_url": self.notify_webhook_url,
            "channel_type": self.channel_type,
            "is_enabled": self.is_enabled,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Alert(db.Model):
    __tablename__ = "alerts"

    id = db.Column(db.Integer, primary_key=True)
    pc_id = db.Column(db.Integer, db.ForeignKey("pcs.id"), nullable=True, index=True)
    alert_type = db.Column(db.String(64), nullable=False, index=True)
    severity = db.Column(db.String(16), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    source_key = db.Column(db.String(128), nullable=False, index=True)

    acknowledged = db.Column(db.Boolean, default=False, index=True)
    acknowledged_by = db.Column(db.String(255))
    acknowledged_at = db.Column(db.DateTime)

    resolved = db.Column(db.Boolean, default=False, index=True)
    resolved_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("source_key", "resolved", name="uq_alert_source_active"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "pc_id": self.pc_id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "source_key": self.source_key,
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at.isoformat()
            if self.acknowledged_at
            else None,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ScheduledTask(db.Model):
    __tablename__ = "scheduled_tasks"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    task_type = db.Column(db.String(64), nullable=False)
    command = db.Column(db.Text)
    parameters = db.Column(db.Text, default="{}")
    pc_id = db.Column(db.Integer, db.ForeignKey("pcs.id"), nullable=True, index=True)
    target_type = db.Column(db.String(16), default="all")  # 'all' or 'pc'
    schedule_type = db.Column(
        db.String(16), nullable=False
    )  # 'interval','daily','weekly'
    interval_minutes = db.Column(db.Integer)
    daily_time = db.Column(db.String(5))  # "HH:MM"
    weekly_day = db.Column(db.Integer)  # 0=Monday ... 6=Sunday
    weekly_time = db.Column(db.String(5))  # "HH:MM"
    is_enabled = db.Column(db.Boolean, default=True, index=True)
    last_run_at = db.Column(db.DateTime)
    next_run_at = db.Column(db.DateTime, index=True)
    run_count = db.Column(db.Integer, default=0)
    last_status = db.Column(db.String(32))
    created_by = db.Column(db.String(255), default="system")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "task_type": self.task_type,
            "command": self.command,
            "parameters": self.parameters,
            "pc_id": self.pc_id,
            "pc_name": self.pc.pc_name if self.pc else None,
            "target_type": self.target_type,
            "schedule_type": self.schedule_type,
            "interval_minutes": self.interval_minutes,
            "daily_time": self.daily_time,
            "weekly_day": self.weekly_day,
            "weekly_time": self.weekly_time,
            "is_enabled": self.is_enabled,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "run_count": self.run_count,
            "last_status": self.last_status,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<ScheduledTask {self.id}:{self.name}>"


class NotificationChannel(db.Model):
    __tablename__ = "notification_channels"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    channel_type = db.Column(db.String(20), nullable=False)  # slack/teams/email/webhook
    target = db.Column(db.String(500), nullable=False)  # URL or email
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "channel_type": self.channel_type,
            "target": self.target,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<NotificationChannel {self.name}>"


class Certificate(db.Model):
    __tablename__ = "certificates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    domain = db.Column(db.String(200), nullable=False)
    issuer = db.Column(db.String(200))
    cert_type = db.Column(db.String(50), default="server")  # server/client/code
    issued_at = db.Column(db.Date)
    expires_at = db.Column(db.Date, nullable=False)
    auto_renew = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        from datetime import date

        today = date.today()
        days_left = (self.expires_at - today).days if self.expires_at else None
        return {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "issuer": self.issuer,
            "cert_type": self.cert_type,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "days_left": days_left,
            "auto_renew": self.auto_renew,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Certificate {self.name}>"


class License(db.Model):
    __tablename__ = "licenses"

    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(200), nullable=False)
    vendor = db.Column(db.String(200))
    license_type = db.Column(
        db.String(50), default="subscription"
    )  # subscription/perpetual/volume
    seat_count = db.Column(db.Integer)
    unit_price = db.Column(db.Integer)  # yen
    expires_at = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "product_name": self.product_name,
            "vendor": self.vendor,
            "license_type": self.license_type,
            "seat_count": self.seat_count,
            "unit_price": self.unit_price,
            "total_cost": (self.seat_count or 0) * (self.unit_price or 0),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<License {self.product_name}>"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(128), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(64), default="viewer")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime, nullable=True)
    failed_login_count = db.Column(db.Integer, default=0, nullable=False)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "failed_login_count": self.failed_login_count,
            "is_locked": self.is_locked,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
        }


class ApiKey(db.Model):
    __tablename__ = "api_keys"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    key_prefix = db.Column(db.String(8), nullable=False)
    key_value = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @classmethod
    def generate(cls, name: str) -> tuple["ApiKey", str]:
        raw = secrets.token_urlsafe(32)
        key = cls(name=name, key_prefix=raw[:8], key_value=raw)
        return key, raw

    def to_dict(self, include_key: bool = False) -> dict:
        d: dict = {
            "id": self.id,
            "name": self.name,
            "key_prefix": self.key_prefix,
            "is_active": self.is_active,
            "last_used_at": self.last_used_at.isoformat()
            if self.last_used_at
            else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_key:
            d["key_value"] = self.key_value
        return d

    def __repr__(self) -> str:
        return f"<ApiKey {self.name}>"


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<SystemSetting {self.key}={self.value!r}>"


class BackupJob(db.Model):
    __tablename__ = "backup_jobs"

    id = db.Column(db.Integer, primary_key=True)
    backup_type = db.Column(
        db.String(20), nullable=False, default="full"
    )  # full/incremental
    target = db.Column(db.String(100), default="DB + config")
    status = db.Column(
        db.String(20), nullable=False, default="running"
    )  # running/success/failed
    size_bytes = db.Column(db.BigInteger, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    storage_path = db.Column(db.String(500), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "backup_type": self.backup_type,
            "target": self.target,
            "status": self.status,
            "size_bytes": self.size_bytes,
            "duration_seconds": self.duration_seconds,
            "storage_path": self.storage_path,
            "notes": self.notes,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    def __repr__(self) -> str:
        return f"<BackupJob {self.id} {self.backup_type} {self.status}>"

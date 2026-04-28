from datetime import datetime, timezone
from extensions import db


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


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(128), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(64), default="operator")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

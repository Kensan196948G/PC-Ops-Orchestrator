"""Phase A-1 (#174) — DB schema extension tests.

Covers:
- PC.os_build column add
- NetworkInterface table + PC.network_interfaces relationship
- JobTemplate table (Phase B-1 skeleton)
"""

import os
import sys

import pytest
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models import PC, JobTemplate, NetworkInterface


@pytest.fixture(scope="module")
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


@pytest.fixture
def pc(app):
    with app.app_context():
        pc = PC(
            pc_name="A1-TEST-PC",
            domain="a1.local",
            os_version="Windows 11",
            os_build="22631.3447",
            os_architecture="64-bit",
        )
        db.session.add(pc)
        db.session.commit()
        pc_id = pc.id
        yield pc_id
        db.session.query(NetworkInterface).filter_by(pc_id=pc_id).delete()
        db.session.query(PC).filter_by(id=pc_id).delete()
        db.session.commit()


def test_pc_os_build_column(app, pc):
    with app.app_context():
        loaded = db.session.get(PC, pc)
        assert loaded.os_build == "22631.3447"
        d = loaded.to_dict()
        assert d["os_build"] == "22631.3447"


def test_pc_os_build_nullable(app):
    with app.app_context():
        pc = PC(pc_name="A1-NULL-OSBUILD", os_version="Windows 10")
        db.session.add(pc)
        db.session.commit()
        try:
            assert pc.os_build is None
            assert pc.to_dict()["os_build"] is None
        finally:
            db.session.delete(pc)
            db.session.commit()


def test_network_interface_create_and_to_dict(app, pc):
    with app.app_context():
        nic = NetworkInterface(
            pc_id=pc,
            interface_name="Ethernet0",
            description="Intel I219-V",
            mac_address="AA:BB:CC:DD:EE:FF",
            ip_address="192.168.1.10",
            subnet_mask="255.255.255.0",
            gateway="192.168.1.1",
            dns_servers="8.8.8.8,1.1.1.1",
            link_speed_mbps=1000,
        )
        db.session.add(nic)
        db.session.commit()

        d = nic.to_dict()
        assert d["interface_name"] == "Ethernet0"
        assert d["mac_address"] == "AA:BB:CC:DD:EE:FF"
        assert d["ip_address"] == "192.168.1.10"
        assert d["link_speed_mbps"] == 1000
        assert d["is_active"] is True


def test_network_interface_unique_per_pc(app, pc):
    with app.app_context():
        db.session.add(
            NetworkInterface(pc_id=pc, interface_name="Wi-Fi", ip_address="10.0.0.1")
        )
        db.session.commit()
        db.session.add(
            NetworkInterface(pc_id=pc, interface_name="Wi-Fi", ip_address="10.0.0.2")
        )
        try:
            with pytest.raises(IntegrityError):
                db.session.commit()
        finally:
            db.session.rollback()


def test_pc_network_interfaces_relationship(app, pc):
    with app.app_context():
        db.session.add_all(
            [
                NetworkInterface(
                    pc_id=pc, interface_name="eth0", ip_address="10.1.1.1"
                ),
                NetworkInterface(
                    pc_id=pc, interface_name="eth1", ip_address="10.1.1.2"
                ),
            ]
        )
        db.session.commit()
        loaded = db.session.get(PC, pc)
        names = sorted(n.interface_name for n in loaded.network_interfaces)
        assert names == ["eth0", "eth1"]


def test_pc_cascade_deletes_network_interfaces(app):
    with app.app_context():
        pc = PC(pc_name="A1-CASCADE-PC")
        db.session.add(pc)
        db.session.commit()
        pc_id = pc.id
        db.session.add(NetworkInterface(pc_id=pc_id, interface_name="lan0"))
        db.session.commit()
        assert db.session.query(NetworkInterface).filter_by(pc_id=pc_id).count() == 1
        db.session.delete(pc)
        db.session.commit()
        assert db.session.query(NetworkInterface).filter_by(pc_id=pc_id).count() == 0


def test_job_template_defaults(app):
    with app.app_context():
        tpl = JobTemplate(
            name="restart-service",
            description="Restart a Windows service",
            script_body="Restart-Service -Name $name",
        )
        db.session.add(tpl)
        db.session.commit()
        try:
            assert tpl.risk_level == "low"
            assert tpl.requires_approval is False
            assert tpl.is_enabled is True
            assert tpl.category == "general"
            assert tpl.created_by == "system"
            assert tpl.created_at is not None

            d = tpl.to_dict()
            assert d["name"] == "restart-service"
            assert d["risk_level"] == "low"
            assert d["requires_approval"] is False
            assert d["is_enabled"] is True
        finally:
            db.session.delete(tpl)
            db.session.commit()


def test_job_template_risk_levels(app):
    with app.app_context():
        names = []
        for level in ("low", "medium", "high"):
            t = JobTemplate(
                name=f"job-{level}",
                risk_level=level,
                requires_approval=(level != "low"),
            )
            db.session.add(t)
            names.append(t.name)
        db.session.commit()
        try:
            for level in ("low", "medium", "high"):
                t = db.session.query(JobTemplate).filter_by(name=f"job-{level}").one()
                assert t.risk_level == level
                assert t.requires_approval == (level != "low")
        finally:
            db.session.query(JobTemplate).filter(JobTemplate.name.in_(names)).delete(
                synchronize_session=False
            )
            db.session.commit()


def test_job_template_risk_level_check_constraint(app):
    with app.app_context():
        db.session.add(JobTemplate(name="invalid-risk", risk_level="critical"))
        try:
            with pytest.raises(IntegrityError):
                db.session.commit()
        finally:
            db.session.rollback()


def test_job_template_name_unique(app):
    with app.app_context():
        db.session.add(JobTemplate(name="dup-template"))
        db.session.commit()
        try:
            db.session.add(JobTemplate(name="dup-template"))
            try:
                with pytest.raises(IntegrityError):
                    db.session.commit()
            finally:
                db.session.rollback()
        finally:
            db.session.query(JobTemplate).filter_by(name="dup-template").delete()
            db.session.commit()

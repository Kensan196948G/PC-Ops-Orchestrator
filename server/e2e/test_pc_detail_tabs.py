"""Phase A-3 (#176) — pc_detail.html タブ刷新 E2E テスト.

検証項目:
- 7 タブ (概要 / HW / SW / NW / 更新 / 履歴 / タスク) のクリック切替
- aria-selected と .hidden の同期
- hash deep-link (/pcs/<id>#network) で対応タブが active
- ページ全体で console error / pageerror が出ない
"""

import uuid

import pytest


TABS = ["overview", "hardware", "software", "network", "updates", "history", "tasks"]


@pytest.fixture(scope="module")
def detail_pc_id(live_server_app):
    """Insert one PC row + supporting rows into the live_server's DB.

    Must use live_server_app (NOT a fresh create_app("testing")) — sqlite
    in-memory engines are isolated per-app, so a separate app instance would
    produce a different DB and the live_server thread would 404 on /details.
    """
    from extensions import db
    from models import PC, Software, NetworkInterface, WindowsUpdate

    with live_server_app.app_context():
        suffix = uuid.uuid4().hex[:6]
        pc = PC(
            pc_name=f"E2E-DETAIL-{suffix}",
            status="healthy",
            os_version="Windows 11",
            os_build="22631.3447",
            ip_address="10.0.0.50",
            cpu_name="Intel(R) Core(TM) i5",
            cpu_cores=4,
            memory_total_gb=16.0,
        )
        db.session.add(pc)
        db.session.commit()
        pc_id = pc.id

        db.session.add(Software(pc_id=pc_id, name="Google Chrome", version="124.0"))
        db.session.add(
            NetworkInterface(
                pc_id=pc_id,
                interface_name="Ethernet0",
                ip_address="10.0.0.50",
                link_speed_mbps=1000,
                is_active=True,
            )
        )
        db.session.add(
            WindowsUpdate(
                pc_id=pc_id, kb_id="KB5034441", title="Test Update", installed=True
            )
        )
        db.session.commit()
        return pc_id


def _is_ignorable(msg: str) -> bool:
    keywords = ["net::", "Failed to fetch", "chart error"]
    return any(k.lower() in msg.lower() for k in keywords)


def _open_detail(page, live_server, pc_id, fragment=""):
    page.goto(f"{live_server}/pcs/{pc_id}{fragment}", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=10000)


def test_pc_detail_renders_all_tab_buttons(page_with_login, live_server, detail_pc_id):
    p = page_with_login
    _open_detail(p, live_server, detail_pc_id)
    for tab in TABS:
        btn = p.locator(f'.tab-btn[data-tab="{tab}"]')
        assert btn.count() == 1, f"missing tab button: {tab}"


def test_pc_detail_overview_active_by_default(
    page_with_login, live_server, detail_pc_id
):
    p = page_with_login
    _open_detail(p, live_server, detail_pc_id)
    overview_btn = p.locator('.tab-btn[data-tab="overview"]')
    assert overview_btn.get_attribute("aria-selected") == "true"
    assert "hidden" not in (p.locator("#tab-overview").get_attribute("class") or "")


def test_pc_detail_tab_clicks_switch_panels(page_with_login, live_server, detail_pc_id):
    p = page_with_login
    _open_detail(p, live_server, detail_pc_id)
    for tab in TABS:
        p.locator(f'.tab-btn[data-tab="{tab}"]').click()
        btn = p.locator(f'.tab-btn[data-tab="{tab}"]')
        assert btn.get_attribute("aria-selected") == "true", (
            f"aria-selected not flipped for {tab}"
        )
        panel = p.locator(f"#tab-{tab}")
        panel_cls = panel.get_attribute("class") or ""
        assert "hidden" not in panel_cls, f"panel not visible for {tab}"

        # All other panels must be hidden
        for other in TABS:
            if other == tab:
                continue
            other_cls = p.locator(f"#tab-{other}").get_attribute("class") or ""
            assert "hidden" in other_cls, (
                f"panel #{other} still visible when {tab} active"
            )


def test_pc_detail_hash_deep_link_activates_tab(
    page_with_login, live_server, detail_pc_id
):
    """/pcs/<id>#network must load with the network panel active."""
    p = page_with_login
    _open_detail(p, live_server, detail_pc_id, fragment="#network")
    network_btn = p.locator('.tab-btn[data-tab="network"]')
    assert network_btn.get_attribute("aria-selected") == "true"
    overview_cls = p.locator("#tab-overview").get_attribute("class") or ""
    assert "hidden" in overview_cls
    network_cls = p.locator("#tab-network").get_attribute("class") or ""
    assert "hidden" not in network_cls


def test_pc_detail_no_pageerror(page_with_login, live_server, detail_pc_id):
    p = page_with_login
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    _open_detail(p, live_server, detail_pc_id)
    assert not errors, f"pageerror on /pcs/{detail_pc_id}: {errors}"


def test_pc_detail_no_console_errors(page_with_login, live_server, detail_pc_id):
    p = page_with_login
    console_errors = []

    def capture(msg):
        if msg.type == "error":
            console_errors.append(msg.text)

    p.on("console", capture)
    _open_detail(p, live_server, detail_pc_id)

    app_errors = [e for e in console_errors if not _is_ignorable(e)]
    assert not app_errors, f"console errors on /pcs/{detail_pc_id}: {app_errors}"


def test_pc_detail_counts_populated_from_details_endpoint(
    page_with_login, live_server, detail_pc_id
):
    """Tab counters (cnt-software / cnt-network / cnt-updates) reflect API data."""
    p = page_with_login
    _open_detail(p, live_server, detail_pc_id)
    # The consolidated /details call resolves under networkidle; counters should
    # display the seed numbers (1 sw / 1 nic / 1 update).
    assert p.locator("#cnt-software").text_content().strip() == "1"
    assert p.locator("#cnt-network").text_content().strip() == "1"
    assert p.locator("#cnt-updates").text_content().strip() == "1"

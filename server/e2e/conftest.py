"""Shared fixtures for Playwright E2E tests."""

import sys
import os
import threading

import pytest


@pytest.fixture(autouse=True)
def set_playwright_timeout(page):
    """Increase Playwright default timeout to 60s for slower CI environments."""
    page.set_default_timeout(60000)


# Ensure server/ is importable regardless of cwd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

E2E_PORT = 5099
BASE_URL = f"http://127.0.0.1:{E2E_PORT}"


@pytest.fixture(scope="session")
def live_server():
    """Start a Flask test server once for the entire E2E session."""
    from werkzeug.serving import make_server
    from app import create_app
    from extensions import db
    from auth import hash_password
    from models import User

    app = create_app("testing")

    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            db.session.add(
                User(
                    username="admin", password_hash=hash_password("admin"), role="admin"
                )
            )
        if not User.query.filter_by(username="viewer").first():
            db.session.add(
                User(
                    username="viewer",
                    password_hash=hash_password("viewer123"),
                    role="viewer",
                )
            )
        if not User.query.filter_by(username="operator").first():
            db.session.add(
                User(
                    username="operator",
                    password_hash=hash_password("operator123"),
                    role="operator",
                )
            )
        db.session.commit()

    server = make_server("127.0.0.1", E2E_PORT, app)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    yield BASE_URL

    server.shutdown()


@pytest.fixture()
def page_with_login(page, live_server):
    """Return a Playwright page already logged in as admin."""
    page.goto(f"{live_server}/login")
    page.fill("#username", "admin")
    page.fill("#password", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server}/", timeout=8000)
    return page


@pytest.fixture()
def viewer_page(page, live_server):
    """Return a Playwright page logged in as viewer role."""
    page.goto(f"{live_server}/login")
    page.fill("#username", "viewer")
    page.fill("#password", "viewer123")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server}/", timeout=8000)
    return page

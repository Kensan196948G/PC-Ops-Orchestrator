"""Pytest session fixtures for PC-Ops Orchestrator API tests."""

import json
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture(scope="session")
def token():
    from test_api import request, setup_module

    setup_module()
    r = request(
        "POST", "/api/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.data}"
    return json.loads(r.data)["token"]

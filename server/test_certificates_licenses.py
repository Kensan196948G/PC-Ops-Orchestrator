"""Comprehensive tests for certificates and licenses API endpoints.

Covers:
- routes/certificates.py: GET/POST/PUT/DELETE + validation edge cases
- routes/licenses.py: GET/POST/PUT/DELETE + CSV export + validation
"""

import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_viewer_token = None
_operator_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token, _viewer_token, _operator_token
    with app.app_context():
        db.create_all()
        for username, role, password in [
            (f"admin_cl_{_unique}", "admin", "AdminCl1!"),
            (f"viewer_cl_{_unique}", "viewer", "ViewerCl1!"),
            (f"oper_cl_{_unique}", "operator", "OperCl1!"),
        ]:
            if not User.query.filter_by(username=username).first():
                db.session.add(
                    User(
                        username=username,
                        password_hash=hash_password(password),
                        role=role,
                    )
                )
        db.session.commit()

    _admin_token = _login(f"admin_cl_{_unique}", "AdminCl1!")
    _viewer_token = _login(f"viewer_cl_{_unique}", "ViewerCl1!")
    _operator_token = _login(f"oper_cl_{_unique}", "OperCl1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


# ── Certificate: GET list ────────────────────────────────────────────


def test_certificates_list_admin():
    r = req("GET", "/api/certificates", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "certificates" in data
    assert isinstance(data["certificates"], list)


def test_certificates_list_viewer():
    r = req("GET", "/api/certificates", token=_viewer_token)
    assert r.status_code == 200


def test_certificates_list_unauthenticated():
    r = req("GET", "/api/certificates")
    assert r.status_code == 401


# ── Certificate: POST create ─────────────────────────────────────────


def test_create_certificate_success():
    payload = {
        "domain": f"example-{_unique}.com",
        "name": f"Test Cert {_unique}",
        "issuer": "Let's Encrypt",
        "cert_type": "server",
        "issued_at": "2025-01-01",
        "expires_at": "2027-01-01",
        "auto_renew": True,
        "notes": "Test certificate",
    }
    r = req("POST", "/api/certificates", token=_admin_token, data=payload)
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["certificate"]["domain"] == f"example-{_unique}.com"
    assert data["certificate"]["cert_type"] == "server"


def test_create_certificate_domain_as_name():
    """name が省略されたとき domain が name になる。"""
    payload = {
        "domain": f"noname-{_unique}.com",
        "expires_at": "2027-06-01",
    }
    r = req("POST", "/api/certificates", token=_admin_token, data=payload)
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["certificate"]["name"] == f"noname-{_unique}.com"


def test_create_certificate_client_type():
    payload = {
        "domain": f"client-{_unique}.com",
        "expires_at": "2027-01-01",
        "cert_type": "client",
    }
    r = req("POST", "/api/certificates", token=_admin_token, data=payload)
    assert r.status_code == 201


def test_create_certificate_code_type():
    payload = {
        "domain": f"code-{_unique}.com",
        "expires_at": "2027-01-01",
        "cert_type": "code",
    }
    r = req("POST", "/api/certificates", token=_admin_token, data=payload)
    assert r.status_code == 201


def test_create_certificate_missing_domain():
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={"expires_at": "2027-01-01"},
    )
    assert r.status_code == 400
    assert "domain" in json.loads(r.data)["error"]


def test_create_certificate_empty_domain():
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={"domain": "", "expires_at": "2027-01-01"},
    )
    assert r.status_code == 400


def test_create_certificate_missing_expires_at():
    r = req("POST", "/api/certificates", token=_admin_token, data={"domain": "x.com"})
    assert r.status_code == 400
    assert "expires_at" in json.loads(r.data)["error"]


def test_create_certificate_invalid_expires_at():
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={"domain": "x.com", "expires_at": "not-a-date"},
    )
    assert r.status_code == 400


def test_create_certificate_invalid_issued_at():
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={
            "domain": "x.com",
            "expires_at": "2027-01-01",
            "issued_at": "baddate",
        },
    )
    assert r.status_code == 400


def test_create_certificate_invalid_cert_type():
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={
            "domain": "x.com",
            "expires_at": "2027-01-01",
            "cert_type": "invalid_type",
        },
    )
    assert r.status_code == 400
    assert "cert_type" in json.loads(r.data)["error"]


def test_create_certificate_name_too_long():
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={
            "domain": "x.com",
            "expires_at": "2027-01-01",
            "name": "A" * 201,
        },
    )
    assert r.status_code == 400


def test_create_certificate_domain_too_long():
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={
            "domain": "A" * 201 + ".com",
            "expires_at": "2027-01-01",
        },
    )
    assert r.status_code == 400


def test_create_certificate_no_body():
    r = client.open(
        "/api/certificates",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_admin_token}",
        },
    )
    assert r.status_code == 400


def test_create_certificate_viewer_forbidden():
    r = req(
        "POST",
        "/api/certificates",
        token=_viewer_token,
        data={
            "domain": "x.com",
            "expires_at": "2027-01-01",
        },
    )
    assert r.status_code == 403


def test_create_certificate_operator_forbidden():
    r = req(
        "POST",
        "/api/certificates",
        token=_operator_token,
        data={
            "domain": "x.com",
            "expires_at": "2027-01-01",
        },
    )
    assert r.status_code == 403


# ── Certificate: PUT update ──────────────────────────────────────────


def _create_cert(suffix=""):
    payload = {
        "domain": f"update-test{suffix}-{_unique}.com",
        "expires_at": "2027-01-01",
    }
    r = req("POST", "/api/certificates", token=_admin_token, data=payload)
    return json.loads(r.data)["certificate"]["id"]


def test_update_certificate_success():
    cert_id = _create_cert("-upd")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "name": "Updated Cert",
            "issuer": "DigiCert",
            "cert_type": "client",
            "expires_at": "2028-12-31",
            "issued_at": "2026-01-01",
            "auto_renew": False,
            "notes": "Updated",
        },
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["certificate"]["name"] == "Updated Cert"
    assert data["certificate"]["cert_type"] == "client"


def test_update_certificate_domain():
    cert_id = _create_cert("-dom")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "domain": "new-domain.example.com",
        },
    )
    assert r.status_code == 200
    assert json.loads(r.data)["certificate"]["domain"] == "new-domain.example.com"


def test_update_certificate_empty_domain_rejected():
    cert_id = _create_cert("-empdom")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "domain": "",
        },
    )
    assert r.status_code == 400


def test_update_certificate_domain_too_long():
    cert_id = _create_cert("-longdom")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "domain": "A" * 201 + ".com",
        },
    )
    assert r.status_code == 400


def test_update_certificate_name_too_long():
    cert_id = _create_cert("-longname")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "name": "A" * 201,
        },
    )
    assert r.status_code == 400


def test_update_certificate_invalid_cert_type():
    cert_id = _create_cert("-badtype")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "cert_type": "unknown",
        },
    )
    assert r.status_code == 400


def test_update_certificate_invalid_expires_at():
    cert_id = _create_cert("-badexp")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "expires_at": "bad-date",
        },
    )
    assert r.status_code == 400


def test_update_certificate_empty_expires_at_rejected():
    cert_id = _create_cert("-emptyexp")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "expires_at": "",
        },
    )
    assert r.status_code == 400


def test_update_certificate_invalid_issued_at():
    cert_id = _create_cert("-badiss")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "issued_at": "not-a-date",
        },
    )
    assert r.status_code == 400


def test_update_certificate_not_found():
    r = req("PUT", "/api/certificates/999999", token=_admin_token, data={"name": "X"})
    assert r.status_code == 404


def test_update_certificate_no_body():
    cert_id = _create_cert("-nobody")
    r = client.open(
        f"/api/certificates/{cert_id}",
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_admin_token}",
        },
    )
    assert r.status_code == 400


def test_update_certificate_viewer_forbidden():
    cert_id = _create_cert("-view")
    r = req(
        "PUT", f"/api/certificates/{cert_id}", token=_viewer_token, data={"name": "X"}
    )
    assert r.status_code == 403


# ── Certificate: DELETE ──────────────────────────────────────────────


def test_delete_certificate_success():
    cert_id = _create_cert("-del")
    r = req("DELETE", f"/api/certificates/{cert_id}", token=_admin_token)
    assert r.status_code == 200
    assert "削除" in json.loads(r.data)["message"]


def test_delete_certificate_not_found():
    r = req("DELETE", "/api/certificates/999999", token=_admin_token)
    assert r.status_code == 404


def test_delete_certificate_viewer_forbidden():
    cert_id = _create_cert("-delvw")
    r = req("DELETE", f"/api/certificates/{cert_id}", token=_viewer_token)
    assert r.status_code == 403


# ── License: GET list ────────────────────────────────────────────────


def test_licenses_list_admin():
    r = req("GET", "/api/licenses", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "licenses" in data
    assert isinstance(data["licenses"], list)


def test_licenses_list_viewer():
    r = req("GET", "/api/licenses", token=_viewer_token)
    assert r.status_code == 200


def test_licenses_list_unauthenticated():
    r = req("GET", "/api/licenses")
    assert r.status_code == 401


# ── License: CSV export ──────────────────────────────────────────────


def test_licenses_export_csv_ok():
    r = req("GET", "/api/licenses/export.csv", token=_admin_token)
    assert r.status_code == 200
    ct = r.headers.get("Content-Type", "")
    assert "csv" in ct or "text" in ct


def test_licenses_export_csv_viewer():
    r = req("GET", "/api/licenses/export.csv", token=_viewer_token)
    assert r.status_code == 200


def test_licenses_export_csv_unauthenticated():
    r = req("GET", "/api/licenses/export.csv")
    assert r.status_code == 401


def test_licenses_export_csv_has_bom():
    """BOM prefix for Excel Japanese support."""
    r = req("GET", "/api/licenses/export.csv", token=_admin_token)
    assert r.status_code == 200
    raw = r.data
    assert raw[:3] == b"\xef\xbb\xbf", "BOM prefix missing"


# ── License: POST create ─────────────────────────────────────────────


def test_create_license_subscription():
    payload = {
        "product_name": f"Office 365 {_unique}",
        "vendor": "Microsoft",
        "license_type": "subscription",
        "seat_count": 50,
        "unit_price": 1200,
        "expires_at": "2027-03-31",
        "notes": "Annual subscription",
    }
    r = req("POST", "/api/licenses", token=_admin_token, data=payload)
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["license"]["product_name"] == f"Office 365 {_unique}"
    assert data["license"]["seat_count"] == 50
    assert data["license"]["total_cost"] == 50 * 1200


def test_create_license_perpetual():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": f"Adobe CC {_unique}",
            "license_type": "perpetual",
            "seat_count": 10,
            "unit_price": 50000,
        },
    )
    assert r.status_code == 201


def test_create_license_volume():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": f"Windows Vol {_unique}",
            "license_type": "volume",
        },
    )
    assert r.status_code == 201


def test_create_license_no_optional_fields():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": f"Minimal {_unique}",
        },
    )
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["license"]["total_cost"] == 0


def test_create_license_missing_product_name():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={"license_type": "subscription"},
    )
    assert r.status_code == 400
    assert "product_name" in json.loads(r.data)["error"]


def test_create_license_empty_product_name():
    r = req("POST", "/api/licenses", token=_admin_token, data={"product_name": ""})
    assert r.status_code == 400


def test_create_license_product_name_too_long():
    r = req(
        "POST", "/api/licenses", token=_admin_token, data={"product_name": "A" * 201}
    )
    assert r.status_code == 400


def test_create_license_invalid_license_type():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": "X",
            "license_type": "invalid",
        },
    )
    assert r.status_code == 400
    assert "license_type" in json.loads(r.data)["error"]


def test_create_license_invalid_seat_count_string():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": "X",
            "seat_count": "notanumber",
        },
    )
    assert r.status_code == 400


def test_create_license_negative_seat_count():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": "X",
            "seat_count": -1,
        },
    )
    assert r.status_code == 400


def test_create_license_invalid_unit_price_string():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": "X",
            "unit_price": "notanumber",
        },
    )
    assert r.status_code == 400


def test_create_license_negative_unit_price():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": "X",
            "unit_price": -100,
        },
    )
    assert r.status_code == 400


def test_create_license_invalid_expires_at():
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": "X",
            "expires_at": "not-a-date",
        },
    )
    assert r.status_code == 400


def test_create_license_no_body():
    r = client.open(
        "/api/licenses",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_admin_token}",
        },
    )
    assert r.status_code == 400


def test_create_license_viewer_forbidden():
    r = req("POST", "/api/licenses", token=_viewer_token, data={"product_name": "X"})
    assert r.status_code == 403


def test_create_license_operator_forbidden():
    r = req("POST", "/api/licenses", token=_operator_token, data={"product_name": "X"})
    assert r.status_code == 403


# ── License: PUT update ──────────────────────────────────────────────


def _create_license(suffix=""):
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": f"License-test{suffix}-{_unique}",
            "seat_count": 5,
            "unit_price": 1000,
        },
    )
    return json.loads(r.data)["license"]["id"]


def test_update_license_success():
    lic_id = _create_license("-upd")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "product_name": "Updated Product",
            "vendor": "New Vendor",
            "license_type": "perpetual",
            "seat_count": 100,
            "unit_price": 9999,
            "expires_at": "2028-12-31",
            "notes": "Updated notes",
        },
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["license"]["product_name"] == "Updated Product"
    assert data["license"]["seat_count"] == 100


def test_update_license_vendor_null():
    lic_id = _create_license("-vnull")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "vendor": "",
        },
    )
    assert r.status_code == 200
    assert json.loads(r.data)["license"]["vendor"] is None


def test_update_license_seat_count_null():
    lic_id = _create_license("-scnull")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "seat_count": None,
        },
    )
    assert r.status_code == 200
    assert json.loads(r.data)["license"]["seat_count"] is None


def test_update_license_unit_price_null():
    lic_id = _create_license("-upnull")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "unit_price": None,
        },
    )
    assert r.status_code == 200


def test_update_license_empty_product_name_rejected():
    lic_id = _create_license("-empname")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "product_name": "",
        },
    )
    assert r.status_code == 400


def test_update_license_product_name_too_long():
    lic_id = _create_license("-longname")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "product_name": "A" * 201,
        },
    )
    assert r.status_code == 400


def test_update_license_invalid_license_type():
    lic_id = _create_license("-badtype")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "license_type": "bad",
        },
    )
    assert r.status_code == 400


def test_update_license_invalid_seat_count():
    lic_id = _create_license("-badsc")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "seat_count": -5,
        },
    )
    assert r.status_code == 400


def test_update_license_invalid_seat_count_string():
    lic_id = _create_license("-strsc")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "seat_count": "bad",
        },
    )
    assert r.status_code == 400


def test_update_license_invalid_unit_price():
    lic_id = _create_license("-badup")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "unit_price": -100,
        },
    )
    assert r.status_code == 400


def test_update_license_invalid_unit_price_string():
    lic_id = _create_license("-strup")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "unit_price": "bad",
        },
    )
    assert r.status_code == 400


def test_update_license_invalid_expires_at():
    lic_id = _create_license("-badexp")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_admin_token,
        data={
            "expires_at": "not-a-date",
        },
    )
    assert r.status_code == 400


def test_update_license_not_found():
    r = req(
        "PUT", "/api/licenses/999999", token=_admin_token, data={"product_name": "X"}
    )
    assert r.status_code == 404


def test_update_license_no_body():
    lic_id = _create_license("-nobody")
    r = client.open(
        f"/api/licenses/{lic_id}",
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_admin_token}",
        },
    )
    assert r.status_code == 400


def test_update_license_viewer_forbidden():
    lic_id = _create_license("-view")
    r = req(
        "PUT",
        f"/api/licenses/{lic_id}",
        token=_viewer_token,
        data={"product_name": "X"},
    )
    assert r.status_code == 403


# ── License: DELETE ──────────────────────────────────────────────────


def test_delete_license_success():
    lic_id = _create_license("-del")
    r = req("DELETE", f"/api/licenses/{lic_id}", token=_admin_token)
    assert r.status_code == 200
    assert "削除" in json.loads(r.data)["message"]


def test_delete_license_not_found():
    r = req("DELETE", "/api/licenses/999999", token=_admin_token)
    assert r.status_code == 404


def test_delete_license_viewer_forbidden():
    lic_id = _create_license("-delvw")
    r = req("DELETE", f"/api/licenses/{lic_id}", token=_viewer_token)
    assert r.status_code == 403


def test_delete_license_operator_forbidden():
    lic_id = _create_license("-delop")
    r = req("DELETE", f"/api/licenses/{lic_id}", token=_operator_token)
    assert r.status_code == 403


# ── Certificate _parse_date: None passthrough ────────────────────────


def test_create_certificate_no_issued_at():
    """issued_at = None はそのまま通る（_parse_date None passthrough）。"""
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={
            "domain": f"noissue-{_unique}.com",
            "expires_at": "2027-01-01",
            "issued_at": None,
        },
    )
    assert r.status_code == 201
    assert json.loads(r.data)["certificate"]["issued_at"] is None


def test_update_certificate_issued_at_none():
    cert_id = _create_cert("-isnull")
    r = req(
        "PUT",
        f"/api/certificates/{cert_id}",
        token=_admin_token,
        data={
            "issued_at": None,
        },
    )
    assert r.status_code == 200


# ── CSV data integrity ────────────────────────────────────────────────


def test_licenses_csv_has_header():
    r = req("GET", "/api/licenses/export.csv", token=_admin_token)
    assert r.status_code == 200
    text = r.data.decode("utf-8-sig")
    assert "製品名" in text
    assert "ベンダー" in text
    assert "ライセンス種別" in text


def test_licenses_csv_with_data():
    """Create a license then verify it appears in the CSV."""
    product = f"CSV-Product-{_unique}"
    req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": product,
            "vendor": "TestVendor",
            "seat_count": 25,
            "unit_price": 500,
            "expires_at": "2027-12-31",
        },
    )
    r = req("GET", "/api/licenses/export.csv", token=_admin_token)
    assert r.status_code == 200
    text = r.data.decode("utf-8-sig")
    assert product in text
    assert "TestVendor" in text

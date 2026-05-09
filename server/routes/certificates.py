from datetime import date

from flask import Blueprint, jsonify, request

from auth import admin_required, log_operation, login_required
from extensions import db
from models import Certificate

certificates_bp = Blueprint("certificates", __name__, url_prefix="/api")

_VALID_CERT_TYPES = frozenset({"server", "client", "code"})


def _parse_date(value, field_name):
    """Parse an ISO date string (YYYY-MM-DD) and return a date object.

    Returns (date_obj, None) on success or (None, error_response) on failure.
    """
    if value is None:
        return None, None
    try:
        return date.fromisoformat(str(value)), None
    except ValueError:
        return None, (
            jsonify({"error": f"{field_name} は YYYY-MM-DD 形式で指定してください"}),
            400,
        )


@certificates_bp.route("/certificates", methods=["GET"])
@login_required
def list_certificates():
    certs = Certificate.query.order_by(Certificate.expires_at).all()
    return jsonify({"certificates": [c.to_dict() for c in certs]})


@certificates_bp.route("/certificates", methods=["POST"])
@admin_required
def create_certificate():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    domain = (data.get("domain") or "").strip()
    if not domain:
        return jsonify({"error": "domain は必須です"}), 400

    name = (data.get("name") or "").strip() or domain
    if len(name) > 200:
        return jsonify({"error": "name は200文字以内で指定してください"}), 400
    if len(domain) > 200:
        return jsonify({"error": "domain は200文字以内で指定してください"}), 400

    if not data.get("expires_at"):
        return jsonify({"error": "expires_at は必須です"}), 400

    expires_at, err = _parse_date(data.get("expires_at"), "expires_at")
    if err:
        return err

    issued_at, err = _parse_date(data.get("issued_at"), "issued_at")
    if err:
        return err

    cert_type = (data.get("cert_type") or "server").strip()
    if cert_type not in _VALID_CERT_TYPES:
        return jsonify(
            {
                "error": f"cert_type は {sorted(_VALID_CERT_TYPES)} のいずれかで指定してください"
            }
        ), 400

    cert = Certificate(
        name=name,
        domain=domain,
        issuer=(data.get("issuer") or "").strip() or None,
        cert_type=cert_type,
        issued_at=issued_at,
        expires_at=expires_at,
        auto_renew=bool(data.get("auto_renew", True)),
        notes=data.get("notes"),
    )
    db.session.add(cert)
    db.session.commit()

    log_operation(
        "create_certificate",
        f"cert:{cert.id}",
        f"name={cert.name} domain={cert.domain} expires={cert.expires_at}",
    )
    return jsonify(
        {"message": "証明書を作成しました", "certificate": cert.to_dict()}
    ), 201


@certificates_bp.route("/certificates/<int:cert_id>", methods=["PUT"])
@admin_required
def update_certificate(cert_id):
    cert = db.session.get(Certificate, cert_id)
    if not cert:
        return jsonify({"error": f"証明書 {cert_id} が見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    if "domain" in data:
        domain = (data["domain"] or "").strip()
        if not domain:
            return jsonify({"error": "domain は必須です"}), 400
        if len(domain) > 200:
            return jsonify({"error": "domain は200文字以内で指定してください"}), 400
        cert.domain = domain

    if "name" in data:
        name = (data["name"] or "").strip() or cert.domain
        if len(name) > 200:
            return jsonify({"error": "name は200文字以内で指定してください"}), 400
        cert.name = name

    if "issuer" in data:
        cert.issuer = (data["issuer"] or "").strip() or None

    if "cert_type" in data:
        cert_type = (data["cert_type"] or "").strip()
        if cert_type not in _VALID_CERT_TYPES:
            return jsonify(
                {
                    "error": f"cert_type は {sorted(_VALID_CERT_TYPES)} のいずれかで指定してください"
                }
            ), 400
        cert.cert_type = cert_type

    if "expires_at" in data:
        if not data["expires_at"]:
            return jsonify({"error": "expires_at は必須です"}), 400
        expires_at, err = _parse_date(data["expires_at"], "expires_at")
        if err:
            return err
        cert.expires_at = expires_at

    if "issued_at" in data:
        issued_at, err = _parse_date(data["issued_at"], "issued_at")
        if err:
            return err
        cert.issued_at = issued_at

    if "auto_renew" in data:
        cert.auto_renew = bool(data["auto_renew"])

    if "notes" in data:
        cert.notes = data["notes"]

    db.session.commit()

    log_operation(
        "update_certificate",
        f"cert:{cert_id}",
        f"name={cert.name}",
    )
    return jsonify({"message": "証明書を更新しました", "certificate": cert.to_dict()})


@certificates_bp.route("/certificates/<int:cert_id>", methods=["DELETE"])
@admin_required
def delete_certificate(cert_id):
    cert = db.session.get(Certificate, cert_id)
    if not cert:
        return jsonify({"error": f"証明書 {cert_id} が見つかりません"}), 404

    db.session.delete(cert)
    db.session.commit()

    log_operation("delete_certificate", f"cert:{cert_id}", "証明書削除")
    return jsonify({"message": "証明書を削除しました"})

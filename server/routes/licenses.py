import csv
import io
from datetime import date

from flask import Blueprint, jsonify, make_response, request

from auth import admin_required, log_operation, login_required
from extensions import db
from models import License

licenses_bp = Blueprint("licenses", __name__, url_prefix="/api")

_VALID_LICENSE_TYPES = frozenset({"subscription", "perpetual", "volume"})


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


@licenses_bp.route("/licenses/export.csv", methods=["GET"])
@login_required
def export_licenses_csv():
    licenses = License.query.order_by(License.product_name).all()

    buf = io.StringIO()
    buf.write("﻿")  # BOM for Excel (utf-8-sig)
    writer = csv.writer(buf)
    writer.writerow(
        [
            "製品名",
            "ベンダー",
            "ライセンス種別",
            "契約席数",
            "単価",
            "合計金額",
            "有効期限",
            "備考",
        ]
    )
    for lic in licenses:
        total_cost = (lic.seat_count or 0) * (lic.unit_price or 0)
        writer.writerow(
            [
                lic.product_name or "",
                lic.vendor or "",
                lic.license_type or "",
                lic.seat_count if lic.seat_count is not None else "",
                lic.unit_price if lic.unit_price is not None else "",
                total_cost,
                lic.expires_at.isoformat() if lic.expires_at else "",
                lic.notes or "",
            ]
        )

    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    response.headers["Content-Disposition"] = 'attachment; filename="licenses.csv"'
    return response


@licenses_bp.route("/licenses", methods=["GET"])
@login_required
def list_licenses():
    licenses = License.query.order_by(License.product_name).all()
    return jsonify({"licenses": [lic.to_dict() for lic in licenses]})


@licenses_bp.route("/licenses", methods=["POST"])
@admin_required
def create_license():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    product_name = (data.get("product_name") or "").strip()
    if not product_name:
        return jsonify({"error": "product_name は必須です"}), 400
    if len(product_name) > 200:
        return jsonify({"error": "product_name は200文字以内で指定してください"}), 400

    license_type = (data.get("license_type") or "subscription").strip()
    if license_type not in _VALID_LICENSE_TYPES:
        return jsonify(
            {
                "error": f"license_type は {sorted(_VALID_LICENSE_TYPES)} のいずれかで指定してください"
            }
        ), 400

    seat_count = data.get("seat_count")
    if seat_count is not None:
        try:
            seat_count = int(seat_count)
            if seat_count < 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({"error": "seat_count は0以上の整数で指定してください"}), 400

    unit_price = data.get("unit_price")
    if unit_price is not None:
        try:
            unit_price = int(unit_price)
            if unit_price < 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({"error": "unit_price は0以上の整数で指定してください"}), 400

    expires_at, err = _parse_date(data.get("expires_at"), "expires_at")
    if err:
        return err

    lic = License(
        product_name=product_name,
        vendor=(data.get("vendor") or "").strip() or None,
        license_type=license_type,
        seat_count=seat_count,
        unit_price=unit_price,
        expires_at=expires_at,
        notes=data.get("notes"),
    )
    db.session.add(lic)
    db.session.commit()

    log_operation(
        "create_license",
        f"license:{lic.id}",
        f"product={lic.product_name} type={lic.license_type}",
    )
    return jsonify(
        {"message": "ライセンスを作成しました", "license": lic.to_dict()}
    ), 201


@licenses_bp.route("/licenses/<int:license_id>", methods=["PUT"])
@admin_required
def update_license(license_id):
    lic = db.session.get(License, license_id)
    if not lic:
        return jsonify({"error": f"ライセンス {license_id} が見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    if "product_name" in data:
        product_name = (data["product_name"] or "").strip()
        if not product_name:
            return jsonify({"error": "product_name は必須です"}), 400
        if len(product_name) > 200:
            return jsonify(
                {"error": "product_name は200文字以内で指定してください"}
            ), 400
        lic.product_name = product_name

    if "vendor" in data:
        lic.vendor = (data["vendor"] or "").strip() or None

    if "license_type" in data:
        license_type = (data["license_type"] or "").strip()
        if license_type not in _VALID_LICENSE_TYPES:
            return jsonify(
                {
                    "error": f"license_type は {sorted(_VALID_LICENSE_TYPES)} のいずれかで指定してください"
                }
            ), 400
        lic.license_type = license_type

    if "seat_count" in data:
        seat_count = data["seat_count"]
        if seat_count is not None:
            try:
                seat_count = int(seat_count)
                if seat_count < 0:
                    raise ValueError
            except (ValueError, TypeError):
                return jsonify(
                    {"error": "seat_count は0以上の整数で指定してください"}
                ), 400
        lic.seat_count = seat_count

    if "unit_price" in data:
        unit_price = data["unit_price"]
        if unit_price is not None:
            try:
                unit_price = int(unit_price)
                if unit_price < 0:
                    raise ValueError
            except (ValueError, TypeError):
                return jsonify(
                    {"error": "unit_price は0以上の整数で指定してください"}
                ), 400
        lic.unit_price = unit_price

    if "expires_at" in data:
        expires_at, err = _parse_date(data["expires_at"], "expires_at")
        if err:
            return err
        lic.expires_at = expires_at

    if "notes" in data:
        lic.notes = data["notes"]

    db.session.commit()

    log_operation(
        "update_license",
        f"license:{license_id}",
        f"product={lic.product_name}",
    )
    return jsonify({"message": "ライセンスを更新しました", "license": lic.to_dict()})


@licenses_bp.route("/licenses/<int:license_id>", methods=["DELETE"])
@admin_required
def delete_license(license_id):
    lic = db.session.get(License, license_id)
    if not lic:
        return jsonify({"error": f"ライセンス {license_id} が見つかりません"}), 404

    db.session.delete(lic)
    db.session.commit()

    log_operation("delete_license", f"license:{license_id}", "ライセンス削除")
    return jsonify({"message": "ライセンスを削除しました"})

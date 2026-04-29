"""Public metrics endpoint (Prometheus text exposition format)."""

from flask import Blueprint, Response

from metrics import PROMETHEUS_CONTENT_TYPE, render_metrics

metrics_bp = Blueprint("metrics", __name__, url_prefix="/api")


@metrics_bp.route("/metrics", methods=["GET"])
def get_metrics():
    """Return current process metrics in Prometheus exposition format.

    Intentionally **unauthenticated** so a sidecar Prometheus scraper can hit
    it without an auth credential. The response only exposes aggregate
    counts and never includes user-identifying values, so this is a safe
    default for an internal-network deployment. For exposure on the public
    internet, gate the route behind your reverse proxy ACL.
    """
    body = render_metrics()
    return Response(body, mimetype=PROMETHEUS_CONTENT_TYPE)

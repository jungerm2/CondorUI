"""View blueprint — serves the multi-page application."""

from flask import Blueprint, render_template

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    """Serve the dashboard page."""
    return render_template("dashboard.html", active_page="dashboard")


@views_bp.route("/submit")
def submit_page():
    """Serve the submit page."""
    return render_template("submit.html", active_page="submit")


@views_bp.route("/templates")
def templates_page():
    """Serve the templates page."""
    return render_template("templates.html", active_page="templates")


@views_bp.route("/history")
def history_page():
    """Serve the history page."""
    return render_template("history.html", active_page="history")


@views_bp.route("/job/<int:cluster_id>")
@views_bp.route("/job/<int:cluster_id>/<int:proc_id>")
def job_details_page(cluster_id: int, proc_id: int = 0):
    """Serve the job details page."""
    return render_template("job_details.html", cluster_id=cluster_id, proc_id=proc_id, active_page="")

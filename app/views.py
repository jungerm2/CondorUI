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


@views_bp.route("/files")
def files_page():
    """Serve the input files management page."""
    return render_template("files.html", active_page="files")


@views_bp.route("/containers")
def containers_page():
    """Serve the containers management page."""
    return render_template("containers.html", active_page="containers")


@views_bp.route("/history")
def history_page():
    """Redirect to dashboard (history is now merged into the dashboard page)."""
    from flask import redirect, url_for
    return redirect(url_for("views.index"))


@views_bp.route("/job/<int:cluster_id>")
@views_bp.route("/job/<int:cluster_id>/<int:proc_id>")
def job_details_page(cluster_id: int, proc_id: int = 0):
    """Serve the job details page."""
    return render_template("job_details.html", cluster_id=cluster_id, proc_id=proc_id, active_page="")


@views_bp.route("/output-files")
def output_files_page():
    """Serve the output files management page."""
    return render_template("output_files.html", active_page="output-files")

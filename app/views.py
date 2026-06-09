"""View blueprint — serves the single-page application."""

from flask import Blueprint, render_template

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    """Serve the main SPA page."""
    return render_template("index.html")

"""Entry point for the Condor Web UI."""

import os

from app import create_app

app = create_app()


def main():
    """Run the development server."""
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    # Use threaded=True so that large file uploads don't block
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    main()

"""Entry point for the Condor Web UI."""

import faulthandler
import os
import signal
import threading

from app import create_app

app = create_app()


def main():
    """Run the development server."""
    # `kill -USR1 <pid>` dumps every thread's stack to stderr — the way to
    # see where a hung schedd query is actually blocked
    try:
        faulthandler.register(signal.SIGUSR1)
    except OSError, ValueError:  # unsupported signal (e.g. Windows)
        pass

    # First Ctrl+C still tries a graceful shutdown, but a schedd query
    # wedged inside the bindings' C code keeps its worker thread alive and
    # interpreter exit joins it forever — so arm a watchdog that
    # force-exits two seconds in no matter what.
    def _on_sigint(signum, frame):
        timer = threading.Timer(2.0, os._exit, args=(0,))
        timer.daemon = True
        timer.start()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _on_sigint)

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    # Use threaded=True so that large file uploads don't block
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    main()

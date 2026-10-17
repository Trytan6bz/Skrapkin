"""Run the web interface:  python -m skrapkin.web"""

import logging
import os

from . import create_app

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def startup_notice(host, password, in_container, sharing):
    """What to tell the user about who can reach the server, or None if there's nothing to say."""
    if host in LOOPBACK or password:
        return None
    if in_container and not sharing:
        # Listening on 0.0.0.0 inside a container is normal; docker-compose.yml publishes the port on
        # 127.0.0.1 only. Only warn when the settings suggest the app is meant to be shared.
        return "Running in a container: docker-compose.yml publishes it on this computer only."
    return ("WARNING: listening beyond this computer without SKRAPKIN_WEB_PASSWORD set. "
            "Anyone who can reach this port can read your leads and spend your Hunter credits.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host = os.environ.get("SKRAPKIN_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("SKRAPKIN_WEB_PORT", "8080"))
    notice = startup_notice(host, os.environ.get("SKRAPKIN_WEB_PASSWORD"), bool(os.environ.get("SKRAPKIN_CONTAINER")),
                            bool(os.environ.get("SKRAPKIN_ALLOWED_HOSTS")))
    app = create_app()
    if notice:
        print(notice, flush=True)
    print(f"SKrapkin web interface: http://localhost:{port}", flush=True)
    from waitress import serve
    serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()

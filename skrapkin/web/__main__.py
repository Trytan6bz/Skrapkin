"""Run the web interface:  python -m skrapkin.web"""

import os

from . import create_app


def main():
    host = os.environ.get("SKRAPKIN_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("SKRAPKIN_WEB_PORT", "8080"))
    app = create_app()
    if host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("SKRAPKIN_WEB_PASSWORD"):
        print("WARNING: listening beyond this computer without SKRAPKIN_WEB_PASSWORD set. "
              "Anyone who can reach this port can read your leads and spend your Hunter credits.", flush=True)
    print(f"SKrapkin web interface: http://localhost:{port}", flush=True)
    from waitress import serve
    serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()

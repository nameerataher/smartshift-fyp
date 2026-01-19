"""
Minimal Python web server for the SmartShift frontend.

Why this exists:
- Keeps the project "Python-based" for running the app locally.
- Serves the JS frontend (MapLibre + shadows) from Python.
- Can be extended later with real API endpoints (FastAPI/Flask).
"""
from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


class SmartShiftHandler(SimpleHTTPRequestHandler):
    """Serve files from the smartshift/ folder and redirect / to the viewer."""

    def do_GET(self) -> None:  # noqa: N802 - keep stdlib naming
        # Redirect root to the main viewer for convenience.
        if urlparse(self.path).path in ("", "/"):
            self.send_response(302)
            self.send_header("Location", "/frontend/dubai_lod1_viewer.html")
            self.end_headers()
            return
        super().do_GET()


def run_server(port: int) -> None:
    # Serve from the smartshift/ directory so /frontend and /data resolve correctly.
    root_dir = Path(__file__).resolve().parent
    handler = lambda *args, **kwargs: SmartShiftHandler(  # noqa: E731
        *args, directory=str(root_dir), **kwargs
    )
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"SmartShift server running at http://localhost:{port}/")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartShift local server")
    parser.add_argument("--port", type=int, default=8001, help="Port to serve on")
    args = parser.parse_args()
    run_server(args.port)


if __name__ == "__main__":
    main()

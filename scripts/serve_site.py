"""Tiny static file server for the generated dashboard (web/site).

Reads the port from the PORT env var (falls back to 8011) so it works under the
preview harness's auto-assigned port.
"""
import functools
import http.server
import os
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "web" / "site"
PORT = int(os.environ.get("PORT", "8011"))

Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"serving {ROOT} on :{PORT}")
    httpd.serve_forever()

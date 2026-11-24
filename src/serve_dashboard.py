"""Serve the Smart Door dashboard on the current computer."""

import argparse
import json
import io
import socket
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from supabase_events import LOCAL_CONFIG, load_local_supabase_settings

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "phone" / "dist"
STATIC_ASSETS = {
    "/app.js",
    "/app-config.js",
    "/styles.css",
    "/sw.js",
    "/manifest.webmanifest",
    "/icons/smart-door-180.png",
    "/icons/smart-door-192.png",
    "/icons/smart-door-512.png",
    "/icons/smart-door-maskable.png",
    "/vendor/supabase-2.119.2.js",
    "/vendor/supabase-LICENSE.txt",
}


def load_browser_config():
    if not LOCAL_CONFIG.is_file():
        return None

    project, key = load_local_supabase_settings()
    values = json.dumps({"project": project, "key": key})
    return f"window.smartDoorConfig = Object.freeze({values});\n".encode("utf-8")


class DashboardServer(ThreadingHTTPServer):
    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, index, browser_config, **kwargs):
        self.index = index
        self.browser_config = browser_config
        super().__init__(*args, directory=str(ASSETS), **kwargs)

    def send_head(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return self.send_content(self.index, "text/html; charset=utf-8")
        if path == "/app-config.js" and self.browser_config is not None:
            return self.send_content(self.browser_config, "text/javascript; charset=utf-8")
        if path in STATIC_ASSETS:
            return super().send_head()
        self.send_error(404)
        return None

    def send_content(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return io.BytesIO(body)


def main():
    parser = argparse.ArgumentParser(description="Serve Smart Door on localhost.")
    parser.add_argument("--port", type=int, default=8000, help="Local HTTP port (default: 8000)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")

    try:
        handler = partial(
            DashboardHandler,
            index=(ASSETS / "index.html").read_bytes(),
            browser_config=load_browser_config(),
        )
        with DashboardServer(("127.0.0.1", args.port), handler) as server:
            print(f"Smart Door dashboard ready at http://localhost:{args.port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, f"Could not start the dashboard: {error}\n")


if __name__ == "__main__":
    main()


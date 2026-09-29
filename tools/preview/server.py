"""Allowlisted local preview server. Browser SDK key only; no Kakao Local/REST calls."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parent


def sdk_key(path):
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == "KAKAO_MAP_JAVASCRIPT_KEY":
            value = value.strip()
            if value and not re.fullmatch(r"[a-fA-F0-9]{32}", value):
                raise ValueError("Invalid browser SDK key format")
            return value
    return ""


def make_handler(data_path, env_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_bytes(self, status, payload, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlsplit(self.path).path
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in files:
                name, content_type = files[path]
                return self.send_bytes(200, (STATIC / name).read_bytes(), content_type)
            if path == "/api/samples":
                if not data_path.exists():
                    return self.send_bytes(503, b'{"error":"Sample file missing. Run build_samples.py."}', "application/json")
                return self.send_bytes(200, data_path.read_bytes(), "application/json; charset=utf-8")
            if path == "/api/config":
                # Public JavaScript SDK key; REST/admin keys are never read or returned.
                data = json.dumps({"javascriptKey": sdk_key(env_path)}).encode("utf-8")
                return self.send_bytes(200, data, "application/json; charset=utf-8")
            if path == "/favicon.ico":
                return self.send_bytes(204, b"", "image/x-icon")
            return self.send_bytes(404, b"Not found", "text/plain")
    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--data-file", type=Path, default=ROOT / "data/processed/preview.json")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    sdk_key(args.env_file)  # Validate format without printing key material.
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.data_file, args.env_file))
    print(f"Saljari data preview: http://localhost:{args.port} (bind {args.host})", flush=True)
    server.serve_forever()

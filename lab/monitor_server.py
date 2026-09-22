#!/usr/bin/env python3
"""
Lab-only screenshot receiver (simulated C2 viewer).

Run on the "operator" machine inside an isolated lab network:

  python lab/monitor_server.py --host 0.0.0.0 --port 8765

The target agent POSTs PNG bytes to /upload.
Saved files land in lab/captures/ for comparison during defense experiments.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CAPTURE_DIR = Path(__file__).resolve().parent / "captures"


class UploadHandler(BaseHTTPRequestHandler):
    server_version = "LabMonitorServer/0.1"

    def do_POST(self) -> None:
        if self.path != "/upload":
            self.send_error(404, "Use POST /upload")
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        if not payload:
            self.send_error(400, "Empty body")
            return

        mode = self.headers.get("X-Capture-Mode", "live")
        agent = self.headers.get("X-Agent-Name", "unknown")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        filename = CAPTURE_DIR / f"{timestamp}_{agent}_{mode}.png"
        filename.write_bytes(payload)

        print(
            f"[received] agent={agent} mode={mode} bytes={len(payload)} file={filename.name}",
            flush=True,
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format: str, *args: object) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab monitor receiver for PNG uploads.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), UploadHandler)
    print(f"Lab monitor server listening on http://{args.host}:{args.port}", flush=True)
    print(f"Saving captures to {CAPTURE_DIR}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)


if __name__ == "__main__":
    main()

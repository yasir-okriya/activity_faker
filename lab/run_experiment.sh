#!/usr/bin/env bash
# Lab helper — run from repo root inside an isolated VM network you control.
set -euo pipefail

echo "=== Lab monitor research ==="
echo "Terminal 1 (operator machine):"
echo "  python lab/monitor_server.py --host 0.0.0.0 --port 8765"
echo
echo "Terminal 2 (target machine):"
echo "  python lab/monitor_agent.py --server http://OPERATOR_IP:8765 --mode live --interval 10"
echo
echo "Decoy-feed experiment (application layer, not OS hook):"
echo "  python lab/monitor_agent.py --server http://OPERATOR_IP:8765 --mode decoy --decoy-image lab/samples/decoy_home.png"
echo
echo "Create decoy PNG first:"
echo "  screencapture -x lab/samples/decoy_home.png   # capture wallpaper-only desktop"

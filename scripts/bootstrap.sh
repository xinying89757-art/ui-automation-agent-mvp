#!/usr/bin/env bash
# One-shot local setup: Python venv, PyYAML/openpyxl, and the pinned Playwright.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v node >/dev/null 2>&1; then
  echo "Install Node.js 22+ once, then re-run this script." >&2
  exit 1
fi
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) process.exit(1)' \
  || { echo "Node.js 22+ is required." >&2; exit 1; }
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
npm --prefix assets/playwright-runner ci
npm --prefix assets/playwright-runner exec -- playwright install chromium
echo "Ready. Run: source .venv/bin/activate"

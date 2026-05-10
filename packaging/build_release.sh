#!/usr/bin/env bash
# packaging/build_release.sh — Mac / Linux
set -euo pipefail
cd "$(dirname "$0")"
pip install -e "..[dev]"
pyinstaller --clean -y nettest.spec
echo "Built dist/nettest"

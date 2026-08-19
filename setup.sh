#!/bin/bash
# setup.sh
#
# One-time setup for SeedPrimer on a new/unfamiliar Linux machine
# (air-gapped or otherwise). Safe to run on any Linux system -- no
# network calls, no sudo required for the chmod step.
#
# Usage:
#   chmod +x setup.sh   (if this file isn't already executable)
#   ./setup.sh

set -e
cd "$(dirname "$0")"

echo "=== SeedPrimer setup ==="
echo

echo "1. Making all scripts executable..."
find . -type f \( -name "*.py" -o -name "*.sh" \) -exec chmod +x {} \;
echo "   done."
echo

echo "2. Checking dependencies (tkinter, hashlib, math, qr_encoder)..."
python3 check_dependencies.py
DEP_STATUS=$?
echo

if [ $DEP_STATUS -eq 0 ]; then
    echo "Setup complete. Run SeedPrimer with:"
    echo "  ./run_gui.sh"
else
    echo "Setup incomplete -- see remediation steps above before running the app."
fi

exit $DEP_STATUS

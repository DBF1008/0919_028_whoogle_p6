#!/bin/sh
# Runs the full Whoogle unit test suite.
#
# Usage:
#   ./test.sh              # run all unit tests
#   ./test.sh test/test_config.py   # run a specific test module
#
# Requires the project dependencies to be installed:
#   pip install -r requirements.txt
#   pip install pytest python-dateutil
#
# Set PYTHON to override the interpreter, e.g.:
#   PYTHON=/usr/bin/python3.11 ./test.sh

set -e

SCRIPT_DIR="$(CDPATH= command cd -- "$(dirname -- "$0")" && pwd -P)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-python3}"

# Point the app at the repo's static folder so tests can load settings
export APP_ROOT="$SCRIPT_DIR/app"
export STATIC_FOLDER="$APP_ROOT/static"

# Ensure the test static folder symlink exists (mirrors ./run test)
if [ ! -e "$SCRIPT_DIR/test/static" ]; then
    ln -s "$SCRIPT_DIR/app/static" "$SCRIPT_DIR/test/static"
fi

if [ "$#" -gt 0 ]; then
    "$PYTHON" -m pytest -sv "$@"
else
    "$PYTHON" -m pytest -sv test/
fi

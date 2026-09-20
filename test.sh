#!/usr/bin/env bash
# Runs the full unit test suite.
# Usage:
#   ./test.sh                 # run all unit tests
#   ./test.sh test/test_config_manager.py   # run a specific test file
#   PYTHON=/path/to/python ./test.sh        # use a specific interpreter
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if [ "$#" -gt 0 ]; then
    exec "$PYTHON" -m pytest -v "$@"
else
    exec "$PYTHON" -m pytest test/ -v
fi

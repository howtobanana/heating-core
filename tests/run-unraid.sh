#!/usr/bin/env bash
# Tests mit Home Assistant in Docker auf Unraid ausführen (der Mac hat kein passendes Python/HA).
# Aufruf: tests/run-unraid.sh [pytest-Argumente]
set -euo pipefail
cd "$(dirname "$0")/.."
ziel=/mnt/cache/appdata/dev/heating-core-test
rsync -az --delete --exclude .git --exclude data ./ "unraid-perg:$ziel/"
ssh unraid-perg "docker run --rm -v $ziel:/w -v /mnt/cache/appdata/dev/pip-cache:/root/.cache/pip -w /w python:3.14 \
  sh -c 'pip install -q -r requirements_test.txt >/dev/null 2>&1 && pytest -q $*'"

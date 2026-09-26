#!/usr/bin/env bash
#
# Run the test suite against a clean, disposable Trilium fixture.
#
# Flow: stop containers -> reset the seeded DB -> (re)build & start containers
# -> wait for MCP health -> run pytest -> stop containers -> reset the DB.
#
# The DB reset always runs with the Trilium container stopped: overwriting
# document.db while SQLite has it open corrupts the file ("malformed"). The
# final stop + reset run via an EXIT trap, so they happen even if a test fails.
#
# Any extra arguments are passed through to pytest, e.g.:
#   ./run-tests.sh                       # full suite
#   ./run-tests.sh tests/live -q         # just the live tests, quietly
#   ./run-tests.sh -k export             # a single test by keyword
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

reset_db() {
  # Restore the committed seed and drop runtime/test collateral. The Trilium
  # container MUST be stopped before calling this.
  git checkout -- trilium-data/
  rm -f trilium-data/document.db-wal trilium-data/document.db-shm
  rm -rf trilium-data/backup
}

wait_for_health() {
  local url="http://localhost:9091/health"
  echo "Waiting for MCP health at $url ..."
  for _ in $(seq 1 60); do
    if [ "$(curl -fs "$url" 2>/dev/null || true)" = "ok" ]; then
      echo "MCP is healthy."
      return 0
    fi
    sleep 1
  done
  echo "ERROR: MCP did not become healthy within 60s." >&2
  return 1
}

cleanup() {
  echo "== Teardown: stopping containers and resetting DB =="
  docker compose stop
  reset_db
}
# Always tear down (stop + reset) on exit, even if the tests fail.
trap cleanup EXIT

echo "== Stopping containers =="
docker compose stop

echo "== Resetting seeded DB to pristine =="
reset_db

echo "== Building and starting containers =="
# --build so the MCP server reflects the current source; --wait blocks until
# Trilium reports healthy.
docker compose up -d --build --wait

wait_for_health

echo "== Running tests =="
( cd app && uv run pytest "$@" )

#!/usr/bin/env bash
# local_ci.sh: GitHub Actions CI pipeline can run in one command on our local machine
set -euo pipefail

IMAGE_NAME="sample-app"
CONTAINER_NAME="sample-app-ci"
PORT="${1:-8000}"      # first argument = port; if it gets nothing then 8000
MAX_TRIES=10

log() {
  echo "[local-ci] $*"
}

cleanup() {
  log "Cleanup: removing the container"
  docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1 || true
}
trap cleanup EXIT      # irrespective of the ending of this script, clean up is imprtant

log "Step 1: Docker check"
if ! docker info > /dev/null 2>&1; then
  log "ERROR: Docker Desktop is closed"
  exit 1
fi

log "Step 2: Image build"
docker build -t "$IMAGE_NAME" ./sample_app

log "Step 3: Container start (port $PORT)"
docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1 || true   # if there is any old container remove it
docker run -d -p "$PORT:8000" --name "$CONTAINER_NAME" "$IMAGE_NAME" > /dev/null

log "Step 4: Smoke test"
for i in $(seq 1 "$MAX_TRIES"); do
  if curl --silent --fail "http://localhost:$PORT/" > /dev/null; then
    log "PASS: app replied (try $i)"
    exit 0
  fi

  RUNNING=$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")
  if [ "$RUNNING" != "true" ]; then
    log "Container crashed (try $i), no point of waiting more"
    break
  fi

  log "Try $i/$MAX_TRIES: app is not yeady yet, wait for 2 sec"
  sleep 2
done

log "FAIL: smoke test failed. Container logs:"
docker logs "$CONTAINER_NAME" || true
exit 1

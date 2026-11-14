#!/usr/bin/env bash
# local_ci.sh: GitHub Actions wali CI pipeline ko local machine pe ek command mein chalata hai
set -euo pipefail

IMAGE_NAME="sample-app"
CONTAINER_NAME="sample-app-ci"
PORT="${1:-8000}"      # pehla argument = port; kuch na diya toh 8000
MAX_TRIES=10

log() {
  echo "[local-ci] $*"
}

cleanup() {
  log "Cleanup: container hata rahe hain"
  docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1 || true
}
trap cleanup EXIT      # script kaise bhi khatam ho, cleanup zaroor chalega

log "Step 1: Docker check"
if ! docker info > /dev/null 2>&1; then
  log "ERROR: Docker Desktop band hai"
  exit 1
fi

log "Step 2: Image build"
docker build -t "$IMAGE_NAME" ./sample_app

log "Step 3: Container start (port $PORT)"
docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1 || true   # purana container ho toh hatao
docker run -d -p "$PORT:8000" --name "$CONTAINER_NAME" "$IMAGE_NAME" > /dev/null

log "Step 4: Smoke test"
for i in $(seq 1 "$MAX_TRIES"); do
  if curl --silent --fail "http://localhost:$PORT/" > /dev/null; then
    log "PASS: app ne jawab diya (try $i)"
    exit 0
  fi

  RUNNING=$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")
  if [ "$RUNNING" != "true" ]; then
    log "Container crash ho gaya (try $i), aur rukne ka fayda nahi"
    break
  fi

  log "Try $i/$MAX_TRIES: app abhi ready nahi, 2 sec ruko..."
  sleep 2
done

log "FAIL: smoke test fail hua. Container logs:"
docker logs "$CONTAINER_NAME" || true
exit 1
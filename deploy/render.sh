#!/bin/bash
# Render the Arena OpenShift manifests for ocp4.lab.local.
#   deploy/render.sh [OUTPUT]      (default: deploy/arena-openshift.json)
# Images default to the initial offline-kit push; the pipeline overrides them with
# API_IMAGE, WEB_IMAGE, HUB_IMAGE and RUNTIME_IMAGE.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT="$HERE/.."
REGISTRY=${ARENA_REGISTRY:-registry.ocp4.lab.local:8443/init}
TAG=bundle-ac55a9e
OUTPUT=${1:-"$HERE/arena-openshift.json"}

python3 "$ROOT/infra/openshift/render.py" \
  --namespace arena \
  --hostname arena.apps.ocp4.lab.local \
  --api-image "${API_IMAGE:-$REGISTRY/arena-api:$TAG}" \
  --web-image "${WEB_IMAGE:-$REGISTRY/arena-web:$TAG}" \
  --hub-image "${HUB_IMAGE:-$REGISTRY/arena-hub:$TAG}" \
  --runtime-image "${RUNTIME_IMAGE:-$REGISTRY/arena-runtime:$TAG}" \
  --postgres-host postgres.arena.svc \
  --storage-class nfs-csi \
  --shared-storage-class nfs-csi \
  --notebook-gpus 0 --evaluation-gpus 1 \
  | python3 "$HERE/overlay.py" > "$OUTPUT.partial"
mv "$OUTPUT.partial" "$OUTPUT"
echo "Wrote $OUTPUT"

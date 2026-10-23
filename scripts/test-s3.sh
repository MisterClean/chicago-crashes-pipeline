#!/usr/bin/env bash
# Run the native signing test against a disposable localhost-only MinIO bucket.
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$task_root"
task_container=""
cleanup() {
  if [ -n "$task_container" ]; then
    docker rm --force "$task_container" >/dev/null
  fi
}
trap cleanup EXIT
# Dummy credentials are scoped to this disposable container and test process.
task_access=local-integration-access
task_secret=local-integration-secret-only
task_bucket=rust-export-integration
task_container="$(docker run --detach --publish 127.0.0.1::9000 \
  --env "MINIO_ROOT_USER=$task_access" --env "MINIO_ROOT_PASSWORD=$task_secret" \
  "${MINIO_IMAGE:-minio/minio:latest}" server /data --address :9000)"
task_address="$(docker port "$task_container" 9000/tcp)"
case "$task_address" in
  127.0.0.1:*) ;;
  *) echo 'Expected an exclusively loopback MinIO port' >&2; exit 1 ;;
esac
task_endpoint="http://$task_address"
task_ready=false
for task_attempt in $(seq 1 225); do
  if curl --fail --silent --max-time 1 "$task_endpoint/minio/health/ready" >/dev/null; then
    task_ready=true
    break
  fi
  sleep 0.2
done
if [ "$task_ready" != true ]; then
  echo 'Disposable MinIO did not become ready' >&2
  exit 1
fi
# curl >= 7.75 supports native AWS SigV4; no SDK or second application is needed.
curl --fail --silent --show-error --max-time 15 \
  --aws-sigv4 aws:amz:us-east-1:s3 --user "$task_access:$task_secret" \
  --request PUT "$task_endpoint/$task_bucket"
TEST_EXPORT_ENDPOINT="$task_endpoint" TEST_EXPORT_BUCKET="$task_bucket" \
TEST_EXPORT_ACCESS_KEY_ID="$task_access" TEST_EXPORT_SECRET_ACCESS_KEY="$task_secret" \
  cargo test --locked \
  storage::tests::live_s3_roundtrip_verifies_signature_upload_head_presign_list_and_delete \
  -- --ignored --exact --nocapture

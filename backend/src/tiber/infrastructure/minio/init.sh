set -eu

: "${MINIO_ENDPOINT:=http://minio:9000}"
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER must be set}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD must be set}"
: "${MINIO_BUCKET:=tiber-artifacts}"
: "${MINIO_MODELS_BUCKET:=tiber-models}"
: "${MINIO_DATASETS_BUCKET:=tiber-datasets}"
: "${MINIO_ALIAS:=local}"

until mc alias set "$MINIO_ALIAS" "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  echo "Waiting for MinIO to become available..."
  sleep 2
done

for bucket in "$MINIO_BUCKET" "$MINIO_MODELS_BUCKET" "$MINIO_DATASETS_BUCKET"; do
  if mc ls "$MINIO_ALIAS/$bucket" >/dev/null 2>&1; then
    echo "Bucket already exists: $bucket"
  else
    echo "Creating bucket: $bucket"
    mc mb -p "$MINIO_ALIAS/$bucket"
  fi
done

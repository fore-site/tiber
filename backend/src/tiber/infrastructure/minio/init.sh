set -eu

: "${MINIO_ENDPOINT:=http://minio:9000}"
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER must be set}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD must be set}"
: "${MINIO_BUCKET:=tiber-artifacts}"
: "${MINIO_ALIAS:=local}"

until mc alias set "$MINIO_ALIAS" "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  echo "Waiting for MinIO to become available..."
  sleep 2
done

if mc ls "$MINIO_ALIAS/$MINIO_BUCKET" >/dev/null 2>&1; then
  echo "Bucket already exists: $MINIO_BUCKET"
else
  echo "Creating bucket: $MINIO_BUCKET"
  mc mb -p "$MINIO_ALIAS/$MINIO_BUCKET"
fi

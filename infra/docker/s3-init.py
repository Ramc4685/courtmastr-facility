"""Create the configured bucket on a local S3-compatible stand-in (RustFS, MinIO) and turn versioning on.
For the stack compose only: in a real cloud the bucket is created by the provider's tooling, not by this."""

import sys
import time

from app.adapters.s3_storage import S3Storage
from app.core.settings import get_settings

cfg = get_settings().storage.s3
client = S3Storage(bucket=cfg.bucket, endpoint_url=cfg.endpoint_url, region=cfg.region, path_style=cfg.path_style).client
for attempt in range(30):
    try:
        client.create_bucket(Bucket=cfg.bucket)
        break
    except Exception as exc:  # noqa: BLE001
        if "BucketAlreadyOwnedByYou" in str(exc) or "BucketAlreadyExists" in str(exc):
            break
        if attempt == 29:
            sys.exit(f"bucket not created: {type(exc).__name__}")
        time.sleep(2)
try:
    client.put_bucket_versioning(Bucket=cfg.bucket, VersioningConfiguration={"Status": "Enabled"})
except Exception:  # noqa: BLE001  # the stand-in may not implement it; real providers do
    print("versioning not enabled on this S3 stand-in")
print(f"bucket {cfg.bucket} ready")

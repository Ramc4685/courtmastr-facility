"""S3-compatible object storage (AWS S3, Fly Tigris, MinIO). The bucket is private; downloads are presigned GETs
that carry the stored content type and Content-Disposition (security-baseline 8.3). Credentials come from the
environment only: FH_S3_ACCESS_KEY_ID and FH_S3_SECRET_ACCESS_KEY, or boto3's default chain (an instance role)
when they are unset."""

import os
from collections.abc import Iterator

import boto3
from botocore.config import Config


class S3Storage:
    def __init__(self, *, bucket: str, endpoint_url: str | None, region: str, path_style: bool) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3", endpoint_url=endpoint_url or None, region_name=region,
            aws_access_key_id=os.environ.get("FH_S3_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("FH_S3_SECRET_ACCESS_KEY"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path" if path_style else "auto"}),
        )  # fmt: skip

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def keys(self, prefix: str) -> Iterator[str]:
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            yield from (item["Key"] for item in page.get("Contents", ()))

    def url(self, key: str, *, expires_in: int, content_type: str, disposition: str) -> str:
        params = {"Bucket": self.bucket, "Key": key, "ResponseContentType": content_type,
                  "ResponseContentDisposition": disposition}  # fmt: skip
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)

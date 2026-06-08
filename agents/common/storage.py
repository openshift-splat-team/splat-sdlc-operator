"""S3-compatible artifact storage. Workflows pass object keys, not payloads."""
from __future__ import annotations

import io
import json

from minio import Minio
from pydantic import BaseModel

from agents.common.settings import BaseAgentSettings


def _client(settings: BaseAgentSettings) -> Minio:
    return Minio(
        settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=settings.s3_secure,
    )


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def put_artifact(key: str, artifact: BaseModel, settings: BaseAgentSettings) -> str:
    """Serialize artifact to JSON and store under key. Returns the key."""
    client = _client(settings)
    _ensure_bucket(client, settings.s3_bucket)
    data = artifact.model_dump_json().encode()
    client.put_object(
        settings.s3_bucket,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type="application/json",
    )
    return key


def get_artifact(key: str, model: type, settings: BaseAgentSettings) -> object:
    """Fetch artifact JSON from S3 and deserialize into model."""
    client = _client(settings)
    response = client.get_object(settings.s3_bucket, key)
    try:
        raw = response.read()
    finally:
        response.close()
        response.release_conn()
    return model.model_validate(json.loads(raw))

import uuid

from django.conf import settings
from minio import Minio
from minio.error import S3Error


def _client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_USE_HTTPS,
    )


def _garantir_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_foto_coleta(file_obj, content_type: str = 'image/jpeg') -> str:
    """Faz upload de uma foto para o MinIO e retorna a URL pública do objeto."""
    ext = content_type.split('/')[-1] if '/' in content_type else 'jpg'
    # Garante extensão razoável para tipos como image/jpeg → jpg
    ext = ext.replace('jpeg', 'jpg')
    object_name = f"coletas/{uuid.uuid4()}.{ext}"

    client = _client()
    bucket = settings.MINIO_BUCKET_NAME
    _garantir_bucket(client, bucket)

    client.put_object(
        bucket,
        object_name,
        file_obj,
        length=file_obj.size,
        content_type=content_type,
    )

    protocol = 'https' if settings.MINIO_USE_HTTPS else 'http'
    return f"{protocol}://{settings.MINIO_ENDPOINT}/{bucket}/{object_name}"

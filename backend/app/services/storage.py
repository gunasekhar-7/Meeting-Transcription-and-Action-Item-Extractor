"""Object storage adapters.

The local backend is the tested default for development and CI. The S3 backend
is used in deployment and is exercised by the deployment smoke test rather than
the unit suite (no network in unit tests).
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import Settings
from app.core.errors import AudioTooLarge, StorageUnavailable

CHUNK = 1024 * 1024


class Storage(Protocol):
    def save(self, fileobj: BinaryIO, key: str, max_bytes: int) -> tuple[int, str]: ...
    def download_to_temp(self, key: str) -> Path: ...
    def delete(self, key: str) -> None: ...
    def list_keys(self, prefix: str = "") -> list[str]: ...
    def healthcheck(self) -> bool: ...


class LocalStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if self.root not in target.parents and target != self.root:
            raise StorageUnavailable("Invalid object key")
        return target

    def save(self, fileobj: BinaryIO, key: str, max_bytes: int) -> tuple[int, str]:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            with target.open("wb") as out:
                while chunk := fileobj.read(CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise AudioTooLarge(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
                    digest.update(chunk)
                    out.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        if size == 0:
            target.unlink(missing_ok=True)
            raise AudioTooLarge("Uploaded file is empty")
        return size, digest.hexdigest()

    def download_to_temp(self, key: str) -> Path:
        return self._resolve(key)

    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def list_keys(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        if not self.root.exists():
            return keys
        for path in self.root.rglob("*"):
            if path.is_file():
                rel = path.relative_to(self.root).as_posix()
                if not prefix or rel.startswith(prefix):
                    keys.append(rel)
        return keys

    def healthcheck(self) -> bool:
        return self.root.exists() and self.root.is_dir()


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        if not settings.s3_bucket:
            raise StorageUnavailable("S3_BUCKET is not configured")
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - deployment path
            raise StorageUnavailable("boto3 is not installed; install the 's3' extra") from exc
        self.bucket = settings.s3_bucket
        self.client = boto3.client("s3", region_name=settings.s3_region, endpoint_url=settings.s3_endpoint_url)

    def save(self, fileobj: BinaryIO, key: str, max_bytes: int) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            temp_path = Path(tmp.name)
            while chunk := fileobj.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    temp_path.unlink(missing_ok=True)
                    raise AudioTooLarge(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
                digest.update(chunk)
                tmp.write(chunk)
        if size == 0:
            temp_path.unlink(missing_ok=True)
            raise AudioTooLarge("Uploaded file is empty")
        try:
            self.client.upload_file(str(temp_path), self.bucket, key)
        except Exception as exc:  # pragma: no cover - deployment path
            raise StorageUnavailable("Could not store the audio file") from exc
        finally:
            temp_path.unlink(missing_ok=True)
        return size, digest.hexdigest()

    def download_to_temp(self, key: str) -> Path:
        suffix = Path(key).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            path = Path(handle.name)
        try:
            self.client.download_file(self.bucket, key, str(path))
        except Exception as exc:  # pragma: no cover - deployment path
            path.unlink(missing_ok=True)
            raise StorageUnavailable("Could not read the audio file") from exc
        return path

    def delete(self, key: str) -> None:  # pragma: no cover - deployment path
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def list_keys(self, prefix: str = "") -> list[str]:  # pragma: no cover - deployment path
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def healthcheck(self) -> bool:  # pragma: no cover - deployment path
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.local_storage_path)


def copy_path_to_temp(path: Path) -> Path:
    """Copy a local object so callers can delete it safely after processing."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=path.suffix) as handle:
        target = Path(handle.name)
    shutil.copyfile(path, target)
    return target

"""Persistent CSV archive storage.

The archive is deliberately independent of PostgreSQL. Only the metadata
(path, size, checksum) is recorded in the database.
"""
from __future__ import annotations

import hashlib
import io
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.exceptions import StorageError
from app.core.logging import get_logger
from app.core.timeutils import to_ist, utcnow

logger = get_logger(__name__)


@dataclass(frozen=True)
class StoredCsv:
    filename: str
    relative_path: str
    size_bytes: int
    checksum_sha256: str
    saved_at: datetime


class StorageBackend(Protocol):
    def save_csv(self, content: bytes, scan_started_at: datetime, scan_id: uuid.UUID) -> StoredCsv: ...
    def read_bytes(self, relative_path: str) -> bytes: ...
    def local_path(self, relative_path: str) -> Path | None: ...
    def delete(self, relative_path: str) -> bool: ...
    def exists(self, relative_path: str) -> bool: ...


def _checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_relative_parts(scan_started_at: datetime, scan_id: uuid.UUID) -> tuple[Path, str]:
    """Return the IST directory tree and the base filename for a scan."""
    ist = to_ist(scan_started_at)
    directory = Path(f"{ist.year:04d}") / f"{ist.month:02d}" / f"{ist.day:02d}"
    base = f"sensibull_oi_scan_{ist:%H%M%S}"
    return directory, base


class LocalStorageBackend:
    def __init__(self, base_path: Path | str) -> None:
        self.base_path = Path(base_path).expanduser().resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self.base_path / relative_path).resolve()
        if not candidate.is_relative_to(self.base_path):
            raise StorageError("Invalid storage path")
        return candidate

    def _next_filename(self, directory: Path, base: str, scan_id: uuid.UUID) -> Path:
        # Never overwrite an existing archive. The scan id keeps collisions unique.
        candidates = [f"{base}.csv", f"{base}_{str(scan_id)[:8]}.csv"]
        candidates.extend(f"{base}_{index}.csv" for index in range(1, 100))
        for name in candidates:
            target = directory / name
            if not target.exists():
                return target
        raise StorageError("Unable to allocate a unique CSV filename")

    def save_csv(self, content: bytes, scan_started_at: datetime, scan_id: uuid.UUID) -> StoredCsv:
        if not content:
            raise StorageError("Refusing to archive an empty CSV")

        directory_parts, base = build_relative_parts(scan_started_at, scan_id)
        directory = self.base_path / directory_parts
        directory.mkdir(parents=True, exist_ok=True)
        target = self._next_filename(directory, base, scan_id)

        temp_path = directory / f".{target.name}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temp_path, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if not temp_path.exists() or temp_path.stat().st_size != len(content):
                raise StorageError("CSV temp file validation failed")
            os.replace(temp_path, target)
        except StorageError:
            raise
        except OSError as exc:
            raise StorageError(f"Unable to write CSV archive: {exc}") from exc
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    logger.warning("csv_temp_cleanup_failed", extra={"path": str(temp_path)})

        relative = target.relative_to(self.base_path).as_posix()
        return StoredCsv(
            filename=target.name,
            relative_path=relative,
            size_bytes=len(content),
            checksum_sha256=_checksum(content),
            saved_at=utcnow(),
        )

    def read_bytes(self, relative_path: str) -> bytes:
        path = self._resolve(relative_path)
        if not path.is_file():
            raise StorageError("CSV archive not found")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise StorageError(f"Unable to read CSV archive: {exc}") from exc

    def local_path(self, relative_path: str) -> Path | None:
        path = self._resolve(relative_path)
        return path if path.is_file() else None

    def delete(self, relative_path: str) -> bool:
        path = self._resolve(relative_path)
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise StorageError(f"Unable to delete CSV archive: {exc}") from exc
        return True

    def exists(self, relative_path: str) -> bool:
        try:
            return self._resolve(relative_path).is_file()
        except StorageError:
            return False


class S3StorageBackend:
    """S3 / Cloudflare R2 compatible backend.

     Only instantiated when ``STORAGE_BACKEND=s3`` so boto3 stays optional.
    """

    def __init__(self) -> None:
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise StorageError(
                "S3 storage requested but boto3 is not installed"
            ) from exc
        settings = get_settings()
        if not settings.s3_bucket:
            raise StorageError("S3 storage requested but S3_BUCKET is not set")
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )

    def _key(self, relative_path: str) -> str:
        return f"{self.prefix}/{relative_path}" if self.prefix else relative_path

    def save_csv(self, content: bytes, scan_started_at: datetime, scan_id: uuid.UUID) -> StoredCsv:
        directory_parts, base = build_relative_parts(scan_started_at, scan_id)
        relative = (directory_parts / f"{base}_{str(scan_id)[:8]}.csv").as_posix()
        key = self._key(relative)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType="text/csv",
                ChecksumAlgorithm="SHA256",
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Unable to upload CSV archive: {exc}") from exc
        return StoredCsv(
            filename=Path(relative).name,
            relative_path=relative,
            size_bytes=len(content),
            checksum_sha256=_checksum(content),
            saved_at=utcnow(),
        )

    def read_bytes(self, relative_path: str) -> bytes:
        buffer = io.BytesIO()
        try:
            self.client.download_fileobj(self.bucket, self._key(relative_path), buffer)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Unable to read CSV archive: {exc}") from exc
        return buffer.getvalue()

    def local_path(self, relative_path: str) -> Path | None:
        return None

    def delete(self, relative_path: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(relative_path))
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Unable to delete CSV archive: {exc}") from exc
        return True

    def exists(self, relative_path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(relative_path))
            return True
        except Exception:  # noqa: BLE001
            return False


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.storage_backend == "local":
            _storage = LocalStorageBackend(settings.resolve_local_path())
        else:
            _storage = S3StorageBackend()
    return _storage


def reset_storage() -> None:
    """Used by tests to re-read configuration."""
    global _storage
    _storage = None

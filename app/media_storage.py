from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import get_settings


class StoredMedia(Protocol):
    disk_path: str


class MediaStorageError(RuntimeError):
    pass


def resolve_media_path(path_value: str | Path) -> Path:
    media_dir = get_settings().media_dir.resolve()
    path = Path(path_value).expanduser().resolve()
    if not path.is_relative_to(media_dir):
        raise MediaStorageError("Il percorso dell'immagine non appartiene alla cartella media configurata")
    return path


@dataclass
class StagedMediaDeletion:
    files: list[tuple[Path, Path]] = field(default_factory=list)

    def restore(self) -> None:
        errors: list[OSError] = []
        for original, staged in reversed(self.files):
            try:
                if staged.exists() and not original.exists():
                    staged.replace(original)
            except OSError as exc:
                errors.append(exc)
        if errors:
            raise MediaStorageError("Non è stato possibile ripristinare le immagini dopo l'errore") from errors[0]

    def finalize(self) -> None:
        errors: list[OSError] = []
        for _, staged in self.files:
            try:
                staged.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(exc)
        if errors:
            raise MediaStorageError("Non è stato possibile completare la rimozione delle immagini") from errors[0]


def stage_media_deletion(assets: Iterable[StoredMedia]) -> StagedMediaDeletion:
    staged_deletion = StagedMediaDeletion()
    seen: set[Path] = set()
    try:
        for asset in assets:
            original = resolve_media_path(asset.disk_path)
            if original in seen or not original.exists():
                continue
            seen.add(original)
            staged = original.with_name(f".{original.name}.{uuid4().hex}.deleting")
            original.replace(staged)
            staged_deletion.files.append((original, staged))
    except (OSError, MediaStorageError) as exc:
        try:
            staged_deletion.restore()
        except MediaStorageError:
            pass
        if isinstance(exc, MediaStorageError):
            raise
        raise MediaStorageError("Non è stato possibile preparare la rimozione delle immagini") from exc
    return staged_deletion


def commit_staged_deletion(db: Session, staged_deletion: StagedMediaDeletion) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            staged_deletion.restore()
        except MediaStorageError:
            pass
        raise
    staged_deletion.finalize()


def commit_uploaded_file(db: Session, path: Path) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise

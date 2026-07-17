from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.media_storage import commit_staged_deletion, commit_uploaded_file, stage_media_deletion


@dataclass
class StoredAsset:
    disk_path: str


class FailingSession:
    def __init__(self) -> None:
        self.rolled_back = False

    def commit(self) -> None:
        raise RuntimeError("database commit failed")

    def rollback(self) -> None:
        self.rolled_back = True


def test_staged_files_are_restored_when_database_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    original = media_dir / "stored.png"
    original.write_bytes(b"image")
    monkeypatch.setenv("WIKI_PARCHINO_MEDIA_DIR", str(media_dir))
    session = FailingSession()

    staged = stage_media_deletion([StoredAsset(str(original))])
    assert not original.exists()
    assert len(staged.files) == 1

    with pytest.raises(RuntimeError, match="database commit failed"):
        commit_staged_deletion(session, staged)  # type: ignore[arg-type]

    assert session.rolled_back
    assert original.read_bytes() == b"image"
    assert not list(media_dir.glob("*.deleting"))


def test_failed_upload_commit_removes_new_file(tmp_path: Path) -> None:
    uploaded = tmp_path / "new.png"
    uploaded.write_bytes(b"image")
    session = FailingSession()

    with pytest.raises(RuntimeError, match="database commit failed"):
        commit_uploaded_file(session, uploaded)  # type: ignore[arg-type]

    assert session.rolled_back
    assert not uploaded.exists()

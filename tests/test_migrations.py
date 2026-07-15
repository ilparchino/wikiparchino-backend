from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_alembic_upgrade_creates_schema(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "migration.sqlite"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", f"sqlite:///{db_path}")
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        tables = connection.execute(text("select name from sqlite_master where type='table'")).scalars().all()
        entity_columns = {
            table: connection.execute(text(f"pragma table_info({table})")).mappings().all()
            for table in ("person", "place", "epoch", "event")
        }
        pullable_columns = connection.execute(text("pragma table_info(pullable)")).mappings().all()
        pullable_fks = connection.execute(text("pragma foreign_key_list(pullable)")).mappings().all()
        person_place_columns = connection.execute(text("pragma table_info(person_place)")).mappings().all()
        person_place_fks = connection.execute(text("pragma foreign_key_list(person_place)")).mappings().all()
        person_event_columns = connection.execute(text("pragma table_info(person_event)")).mappings().all()
        person_event_fks = connection.execute(text("pragma foreign_key_list(person_event)")).mappings().all()
        person_event_sql = connection.execute(
            text("select sql from sqlite_master where type='table' and name='person_event'")
        ).scalar_one()
        media_columns = connection.execute(text("pragma table_info(media_asset)")).mappings().all()
        media_fks = connection.execute(text("pragma foreign_key_list(media_asset)")).mappings().all()
        event_fks = connection.execute(text("pragma foreign_key_list(event)")).mappings().all()
    assert "user_account" in tables
    assert "event" in tables
    assert "pullable" in tables
    assert "pullable_item" not in tables
    metadata_columns = {"created_at", "updated_at", "created_by", "updated_by"}
    assert metadata_columns <= {column["name"] for column in pullable_columns}
    assert {"created_by_id", "updated_by_id"}.isdisjoint(
        {column["name"] for column in pullable_columns}
    )
    for columns in entity_columns.values():
        names = {column["name"] for column in columns}
        assert metadata_columns.isdisjoint(names)
        assert "deleted_at" not in names
    for columns in (person_place_columns, person_event_columns):
        names = {column["name"] for column in columns}
        assert metadata_columns <= names
        assert {"created_by_id", "updated_by_id"}.isdisjoint(names)
    media_names = {column["name"] for column in media_columns}
    assert {"created_at", "created_by"} <= media_names
    assert {"created_by_id", "updated_by_id"}.isdisjoint(media_names)

    assert any(
        fk["from"] == "created_by"
        and fk["table"] == "user_account"
        and fk["on_delete"] == "SET NULL"
        and fk["on_update"] == "CASCADE"
        for fk in pullable_fks
    )
    assert any(
        fk["from"] == "updated_by"
        and fk["table"] == "user_account"
        and fk["on_delete"] == "SET NULL"
        and fk["on_update"] == "CASCADE"
        for fk in pullable_fks
    )
    for foreign_keys in (person_place_fks, person_event_fks):
        assert {"created_by", "updated_by"} <= {
            fk["from"] for fk in foreign_keys if fk["table"] == "user_account"
        }
    assert any(
        fk["from"] == "created_by" and fk["table"] == "user_account"
        for fk in media_fks
    )
    role_column = next(column for column in person_event_columns if column["name"] == "role")
    assert role_column["type"] == "VARCHAR(255)"
    assert role_column["notnull"] == 0
    assert "ck_person_event_role_length" in person_event_sql
    assert any(fk["table"] == "pullable" and fk["on_delete"] == "CASCADE" for fk in event_fks)
    assert any(fk["table"] == "place" and fk["on_delete"] == "RESTRICT" for fk in event_fks)

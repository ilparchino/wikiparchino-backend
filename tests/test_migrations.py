from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def migration_config(backend_dir: Path) -> Config:
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    return config


def test_activity_migration_preserves_data_and_hardens_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "migration.sqlite"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    backend_dir = Path(__file__).resolve().parents[1]
    config = migration_config(backend_dir)
    command.upgrade(config, "0002_audit_activity_index")

    engine = create_engine(database_url)
    timestamp = "2026-07-17 10:00:00.123456"
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into user_account "
                "(id, username, display_name, password_hash, is_active, is_admin, created_at, updated_at) "
                "values (1, 'migration-user', 'Migration User', 'hash', 1, 0, :time, :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text(
                "insert into pullable "
                "(id, rarity, created_at, updated_at, created_by, updated_by) "
                "values (42, 1.0, :time, :time, 1, 1)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text(
                "insert into person (id, alias, sex, connotation) "
                "values (42, 'Migrata', 'unknown', 'unknown')"
            )
        )
        connection.execute(
            text(
                "insert into media_asset "
                "(id, pullable_id, filename, content_type, disk_path, created_at, created_by) "
                "values (77, 42, 'image.png', 'image/png', '/tmp/image.png', :time, 1)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text(
                "insert into audit_log "
                "(id, actor_user_id, entity_type, entity_id, action, payload_json, created_at) "
                "values (88, 1, 'person', 42, 'update', '{\"alias\": \"Migrata\"}', :time)"
            ),
            {"time": timestamp},
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        tables = set(
            connection.execute(
                text("select name from sqlite_master where type='table'")
            ).scalars()
        )
        assert "activity_log" in tables
        assert "audit_log" not in tables

        activity_columns = {
            row["name"]
            for row in connection.execute(
                text("pragma table_info(activity_log)")
            ).mappings()
        }
        assert "occurred_at" in activity_columns
        assert "created_at" not in activity_columns
        migrated = connection.execute(
            text("select * from activity_log where id = 88")
        ).mappings().one()
        assert migrated["entity_type"] == "person"
        assert migrated["entity_id"] == 42
        assert migrated["action"] == "update"
        assert str(migrated["occurred_at"]) == timestamp

        indexes = {
            row["name"]
            for row in connection.execute(
                text("pragma index_list(activity_log)")
            ).mappings()
        }
        assert "ix_activity_log_actor_occurred_at" in indexes
        table_sql = {
            row["name"]: row["sql"]
            for row in connection.execute(
                text(
                    "select name, sql from sqlite_master where type='table' "
                    "and name in ('pullable', 'media_asset', 'activity_log')"
                )
            ).mappings()
        }
        assert all("AUTOINCREMENT" in sql.upper() for sql in table_sql.values())
        assert "ck_activity_log_entity_type" in table_sql["activity_log"]
        assert "ck_activity_log_action" in table_sql["activity_log"]

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "insert into activity_log "
                    "(entity_type, entity_id, action, occurred_at) "
                    "values ('invalid', 42, 'update', :time)"
                ),
                {"time": timestamp},
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "insert into activity_log "
                    "(entity_type, entity_id, action, occurred_at) "
                    "values ('person', 42, 'invalid', :time)"
                ),
                {"time": timestamp},
            )

        connection.execute(
            text(
                "insert into pullable "
                "(id, rarity, created_at, updated_at) values (100, 1.0, :time, :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(text("delete from pullable where id = 100"))
        next_pullable = connection.execute(
            text(
                "insert into pullable (rarity, created_at, updated_at) "
                "values (1.0, :time, :time)"
            ),
            {"time": timestamp},
        ).lastrowid
        assert next_pullable > 100

        connection.execute(
            text(
                "insert into media_asset "
                "(id, pullable_id, filename, content_type, disk_path, created_at) "
                "values (100, 42, 'old.png', 'image/png', '/tmp/old.png', :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(text("delete from media_asset where id = 100"))
        next_media = connection.execute(
            text(
                "insert into media_asset "
                "(pullable_id, filename, content_type, disk_path, created_at) "
                "values (42, 'new.png', 'image/png', '/tmp/new.png', :time)"
            ),
            {"time": timestamp},
        ).lastrowid
        assert next_media > 100

        connection.execute(
            text(
                "insert into activity_log "
                "(id, entity_type, entity_id, action, occurred_at) "
                "values (100, 'person', 42, 'update', :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(text("delete from activity_log where id = 100"))
        next_activity = connection.execute(
            text(
                "insert into activity_log "
                "(entity_type, entity_id, action, occurred_at) "
                "values ('person', 42, 'update', :time)"
            ),
            {"time": timestamp},
        ).lastrowid
        assert next_activity > 100
        assert connection.exec_driver_sql("pragma foreign_key_check").all() == []
    engine.dispose()

    command.downgrade(config, "0002_audit_activity_index")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("select name from sqlite_master where type='table'")
            ).scalars()
        )
        assert "audit_log" in tables
        assert "activity_log" not in tables
        restored = connection.execute(
            text("select * from audit_log where id = 88")
        ).mappings().one()
        assert str(restored["created_at"]) == timestamp
        assert connection.exec_driver_sql("pragma foreign_key_check").all() == []


def test_activity_migration_rejects_unsupported_existing_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "invalid-migration.sqlite"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    backend_dir = Path(__file__).resolve().parents[1]
    config = migration_config(backend_dir)
    command.upgrade(config, "0002_audit_activity_index")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into audit_log "
                "(entity_type, entity_id, action, created_at) "
                "values ('unknown', 1, 'unsupported', '2026-07-17 10:00:00')"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="unsupported entity types: unknown; actions: unsupported"):
        command.upgrade(config, "head")

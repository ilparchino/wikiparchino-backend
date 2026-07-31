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
        assert "security_event_log" in tables
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
        assert "ix_activity_log_occurred_at" in indexes
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
        assert "security_event_log" not in tables
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


def test_maintenance_migration_preserves_existing_data_and_downgrades(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "maintenance-migration.sqlite"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    backend_dir = Path(__file__).resolve().parents[1]
    config = migration_config(backend_dir)
    command.upgrade(config, "0004_admin_security_events")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into user_account "
                "(id, username, display_name, password_hash, is_active, is_admin, "
                "created_at, updated_at) values "
                "(1, 'existing', 'Existing', 'hash', 1, 1, "
                "'2026-07-29 10:00:00', '2026-07-29 10:00:00')"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        assert connection.execute(
            text("select username from user_account where id = 1")
        ).scalar_one() == "existing"
        table_sql = connection.execute(
            text(
                "select sql from sqlite_master "
                "where type = 'table' and name = 'maintenance_window'"
            )
        ).scalar_one()
        assert "AUTOINCREMENT" in table_sql.upper()
        assert "ck_maintenance_window_open_slot" in table_sql
        indexes = {
            row["name"]
            for row in connection.execute(
                text("pragma index_list(maintenance_window)")
            ).mappings()
        }
        assert "ix_maintenance_window_announced_at" in indexes
        connection.execute(
            text(
                "insert into maintenance_window "
                "(open_slot, announced_at, starts_at, message) "
                "values (1, '2026-07-29 10:00:00', '2026-07-29 10:15:00', 'Test')"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "insert into maintenance_window "
                    "(open_slot, announced_at, starts_at) "
                    "values (1, '2026-07-29 11:00:00', '2026-07-29 11:15:00')"
                )
            )
    engine.dispose()

    command.downgrade(config, "0004_admin_security_events")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("select name from sqlite_master where type='table'")
            ).scalars()
        )
        assert "maintenance_window" not in tables
        assert connection.execute(
            text("select username from user_account where id = 1")
        ).scalar_one() == "existing"
    engine.dispose()


def test_owner_migration_preserves_users_and_enforces_invariants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "owner-migration.sqlite"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    backend_dir = Path(__file__).resolve().parents[1]
    config = migration_config(backend_dir)
    command.upgrade(config, "0005_maintenance_mode")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into user_account "
                "(id, username, display_name, password_hash, is_active, is_admin, "
                "created_at, updated_at) values "
                "(1, 'admin1', 'Admin 1', 'hash', 1, 1, "
                "'2026-07-30 10:00:00', '2026-07-30 10:00:00'), "
                "(2, 'admin2', 'Admin 2', 'hash', 1, 1, "
                "'2026-07-30 10:00:00', '2026-07-30 10:00:00'), "
                "(3, 'regular', 'Regular', 'hash', 1, 0, "
                "'2026-07-30 10:00:00', '2026-07-30 10:00:00'), "
                "(4, 'inactive', 'Inactive', 'hash', 0, 1, "
                "'2026-07-30 10:00:00', '2026-07-30 10:00:00')"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.execute(
            text("select username, is_owner from user_account order by id")
        ).all()
        assert rows == [
            ("admin1", 0),
            ("admin2", 0),
            ("regular", 0),
            ("inactive", 0),
        ]
        table_sql = connection.execute(
            text(
                "select sql from sqlite_master "
                "where type = 'table' and name = 'user_account'"
            )
        ).scalar_one()
        assert "ck_user_account_owner_is_active_admin" in table_sql
        indexes = {
            row["name"]
            for row in connection.execute(text("pragma index_list(user_account)")).mappings()
        }
        assert "uq_user_account_single_owner" in indexes

    with engine.begin() as connection:
        connection.execute(text("update user_account set is_owner = 1 where id = 1"))
        with pytest.raises(IntegrityError):
            connection.execute(text("update user_account set is_owner = 1 where id = 2"))
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text("update user_account set is_owner = 1 where id = 3"))
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text("update user_account set is_owner = 1 where id = 4"))
    engine.dispose()

    command.downgrade(config, "0005_maintenance_mode")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute(text("pragma table_info(user_account)")).mappings()
        }
        assert "is_owner" not in columns
        assert connection.execute(text("select count(*) from user_account")).scalar_one() == 4
    engine.dispose()


def test_epoch_partial_date_migration_preserves_data_and_enforces_dates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "epoch-partial-dates.sqlite"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    backend_dir = Path(__file__).resolve().parents[1]
    config = migration_config(backend_dir)
    command.upgrade(config, "0006_protected_owner")

    engine = create_engine(database_url)
    timestamp = "2026-07-30 10:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into user_account "
                "(id, username, display_name, password_hash, is_active, is_admin, "
                "is_owner, created_at, updated_at) values "
                "(1, 'existing', 'Existing', 'hash', 1, 1, 1, :time, :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text(
                "insert into pullable "
                "(id, rarity, created_at, updated_at, created_by, updated_by) values "
                "(10, 1.0, :time, :time, 1, 1), "
                "(11, 1.0, :time, :time, 1, 1), "
                "(12, 1.0, :time, :time, 1, 1)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text(
                "insert into place (id, name, description) "
                "values (10, 'Luogo esistente', null)"
            )
        )
        connection.execute(
            text(
                "insert into epoch (id, name, description) "
                "values (11, 'Epoca esistente', 'Da conservare')"
            )
        )
        connection.execute(
            text(
                "insert into event "
                "(id, epoch_id, place_id, title, year, month, day) "
                "values (12, 11, 10, 'Evento esistente', 2024, 2, 29)"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        epoch = connection.execute(
            text("select * from epoch where id = 11")
        ).mappings().one()
        assert epoch["name"] == "Epoca esistente"
        assert epoch["description"] == "Da conservare"
        assert epoch["start_year"] is None
        assert epoch["end_year"] is None
        event = connection.execute(
            text("select year, month, day from event where id = 12")
        ).one()
        assert event == (2024, 2, 29)

        epoch_sql = connection.execute(
            text(
                "select sql from sqlite_master "
                "where type = 'table' and name = 'epoch'"
            )
        ).scalar_one()
        event_sql = connection.execute(
            text(
                "select sql from sqlite_master "
                "where type = 'table' and name = 'event'"
            )
        ).scalar_one()
        assert "ck_epoch_date_order" in epoch_sql
        assert "ck_epoch_start_day_valid_for_month" in epoch_sql
        assert "ck_epoch_end_day_valid_for_month" in epoch_sql
        assert "ck_event_day_valid_for_month" in event_sql

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "update event set year = 2025, month = 2, day = 29 "
                    "where id = 12"
                )
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "update epoch set start_year = 2025, start_month = 4, "
                    "end_year = 2025, end_month = 3 where id = 11"
                )
            )
        assert connection.exec_driver_sql("pragma foreign_key_check").all() == []
    engine.dispose()

    command.downgrade(config, "0006_protected_owner")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        epoch_columns = {
            row["name"]
            for row in connection.execute(text("pragma table_info(epoch)")).mappings()
        }
        assert "start_year" not in epoch_columns
        assert "end_year" not in epoch_columns
        assert connection.execute(
            text("select name from epoch where id = 11")
        ).scalar_one() == "Epoca esistente"
        assert connection.execute(
            text("select title from event where id = 12")
        ).scalar_one() == "Evento esistente"
        assert connection.exec_driver_sql("pragma foreign_key_check").all() == []
    engine.dispose()


def test_epoch_partial_date_migration_rejects_invalid_legacy_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "invalid-event-date.sqlite"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    backend_dir = Path(__file__).resolve().parents[1]
    config = migration_config(backend_dir)
    command.upgrade(config, "0006_protected_owner")

    engine = create_engine(database_url)
    timestamp = "2026-07-30 10:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into pullable (id, rarity, created_at, updated_at) values "
                "(10, 1.0, :time, :time), (11, 1.0, :time, :time), "
                "(12, 1.0, :time, :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text("insert into place (id, name) values (10, 'Luogo')")
        )
        connection.execute(
            text("insert into epoch (id, name) values (11, 'Epoca')")
        )
        connection.execute(
            text(
                "insert into event "
                "(id, epoch_id, place_id, title, year, month, day) "
                "values (12, 11, 10, 'Evento non valido', 2025, 2, 29)"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="invalid event IDs: 12"):
        command.upgrade(config, "head")


def test_place_address_migration_preserves_data_relationships_and_downgrades(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "place-address.sqlite"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    backend_dir = Path(__file__).resolve().parents[1]
    config = migration_config(backend_dir)
    command.upgrade(config, "0007_epoch_partial_dates")

    engine = create_engine(database_url)
    timestamp = "2026-07-31 10:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into pullable (id, rarity, created_at, updated_at) values "
                "(10, 1.0, :time, :time), (11, 1.0, :time, :time), "
                "(12, 1.0, :time, :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text(
                "insert into place (id, name, description) "
                "values (10, 'Luogo esistente', 'Da conservare')"
            )
        )
        connection.execute(
            text("insert into epoch (id, name) values (11, 'Epoca esistente')")
        )
        connection.execute(
            text(
                "insert into event (id, epoch_id, place_id, title) "
                "values (12, 11, 10, 'Evento collegato')"
            )
        )
    engine.dispose()


    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        place = connection.execute(
            text("select * from place where id = 10")
        ).mappings().one()
        assert place["name"] == "Luogo esistente"
        assert place["description"] == "Da conservare"
        assert place["address"] is None
        assert connection.execute(
            text("select place_id from event where id = 12")
        ).scalar_one() == 10

        table_sql = connection.execute(
            text(
                "select sql from sqlite_master "
                "where type = 'table' and name = 'place'"
            )
        ).scalar_one()
        assert "ck_place_address_length" in table_sql
        connection.execute(
            text("update place set address = :address where id = 10"),
            {"address": "x" * 500},
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text("update place set address = :address where id = 10"),
                {"address": "x" * 501},
            )
        assert connection.exec_driver_sql("pragma foreign_key_check").all() == []
    engine.dispose()

    command.downgrade(config, "0007_epoch_partial_dates")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute(text("pragma table_info(place)")).mappings()
        }
        assert "address" not in columns
        assert connection.execute(
            text("select name from place where id = 10")
        ).scalar_one() == "Luogo esistente"
        assert connection.execute(
            text("select place_id from event where id = 12")
        ).scalar_one() == 10
        assert connection.exec_driver_sql("pragma foreign_key_check").all() == []
    engine.dispose()


def test_social_group_migration_preserves_activity_and_guards_downgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "social-groups.sqlite"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    backend_dir = Path(__file__).resolve().parents[1]
    config = migration_config(backend_dir)
    command.upgrade(config, "0008_place_address")

    engine = create_engine(database_url)
    timestamp = "2026-07-31 12:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into pullable (id, rarity, created_at, updated_at) "
                "values (10, 1.0, :time, :time), (11, 1.0, :time, :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text(
                "insert into person (id, alias, sex, connotation) "
                "values (10, 'Persona', 'unknown', 'unknown')"
            )
        )
        connection.execute(text("insert into epoch (id, name) values (11, 'Epoca')"))
        connection.execute(
            text(
                "insert into activity_log "
                "(id, entity_type, entity_id, action, occurred_at) "
                "values (90, 'person', 10, 'create', :time)"
            ),
            {"time": timestamp},
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("select name from sqlite_master where type = 'table'")
            )
        }
        assert {"social_group", "social_group_person", "social_group_epoch"} <= tables
        assert connection.execute(
            text("select entity_type from activity_log where id = 90")
        ).scalar_one() == "person"
        activity_sql = connection.execute(
            text(
                "select sql from sqlite_master "
                "where type = 'table' and name = 'activity_log'"
            )
        ).scalar_one()
        assert "'group'" in activity_sql
        assert "'replace_group_people'" in activity_sql
        assert "'replace_group_epochs'" in activity_sql
        indexes = {
            row[1]
            for row in connection.execute(text("pragma index_list(activity_log)"))
        }
        assert "ix_activity_log_actor_occurred_at" in indexes
        assert "ix_activity_log_occurred_at" in indexes

        next_log_id = connection.execute(
            text(
                "insert into activity_log "
                "(entity_type, entity_id, action, occurred_at) "
                "values ('group', 12, 'create', :time) returning id"
            ),
            {"time": timestamp},
        ).scalar_one()
        assert next_log_id > 90
        connection.execute(
            text(
                "insert into pullable (id, rarity, created_at, updated_at) "
                "values (12, 1.0, :time, :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text("insert into social_group (id, name) values (12, 'Cerchia')")
        )
        connection.execute(
            text(
                "insert into social_group_person "
                "(group_id, person_id, created_at, updated_at) "
                "values (12, 10, :time, :time)"
            ),
            {"time": timestamp},
        )
        connection.execute(
            text(
                "insert into social_group_epoch "
                "(group_id, epoch_id, created_at, updated_at) "
                "values (12, 11, :time, :time)"
            ),
            {"time": timestamp},
        )
        assert connection.exec_driver_sql("pragma foreign_key_check").all() == []
    engine.dispose()

    with pytest.raises(RuntimeError, match="Cerchia data or activity"):
        command.downgrade(config, "0008_place_address")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("delete from activity_log where entity_type = 'group'"))
        connection.execute(text("delete from social_group_person where group_id = 12"))
        connection.execute(text("delete from social_group_epoch where group_id = 12"))
        connection.execute(text("delete from social_group where id = 12"))
        connection.execute(text("delete from pullable where id = 12"))
    engine.dispose()

    command.downgrade(config, "0008_place_address")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("select name from sqlite_master where type = 'table'")
            )
        }
        assert "social_group" not in tables
        assert connection.execute(
            text("select entity_type from activity_log where id = 90")
        ).scalar_one() == "person"
        assert connection.exec_driver_sql("pragma foreign_key_check").all() == []
    engine.dispose()

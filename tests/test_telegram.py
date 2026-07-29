from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from app import database
from app.config import get_settings
from app.database import Base
from app.manage_maintenance import (
    MaintenanceCommandError,
    command_schedule,
    end_maintenance,
    notify_window,
    schedule_maintenance,
)
from app.models import MaintenanceWindow
from app.security import utcnow
from app.telegram import (
    TelegramConfigurationError,
    TelegramDeliveryError,
    send_message,
    telegram_credentials,
)


@pytest.fixture()
def maintenance_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{tmp_path / 'maintenance.sqlite'}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    database.configure_database(database_url)
    Base.metadata.create_all(bind=database.engine)
    with database.SessionLocal() as db:
        yield db


def configure_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIKI_PARCHINO_TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("WIKI_PARCHINO_TELEGRAM_CHAT_ID", "-100123")
    monkeypatch.setenv(
        "WIKI_PARCHINO_FRONTEND_URL",
        "https://ilparchino.github.io/wikiparchino/",
    )


def test_send_message_is_outbound_only_and_uses_normal_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_telegram(monkeypatch)
    calls: list[tuple[str, dict, float]] = []

    def fake_post(url: str, *, json: dict, timeout: float) -> httpx.Response:
        calls.append((url, json, timeout))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 91}})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = send_message(get_settings(), "Messaggio di prova")

    assert result is not None and result.message_id == 91
    assert calls == [
        (
            "https://api.telegram.org/botsecret-token/sendMessage",
            {
                "chat_id": "-100123",
                "text": "Messaggio di prova",
                "disable_notification": False,
            },
            10.0,
        )
    ]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(502), "HTTP 502"),
        (httpx.Response(200, text="not-json"), "risposta non valida"),
        (
            httpx.Response(200, json={"ok": False, "description": "secret-token"}),
            "rifiutato",
        ),
        (httpx.Response(200, json={"ok": True, "result": {}}), "identificativo"),
    ],
)
def test_telegram_failures_are_safe(
    response: httpx.Response,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_telegram(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(TelegramDeliveryError, match=message) as raised:
        send_message(get_settings(), "Test")
    assert "secret-token" not in str(raised.value)


def test_telegram_connection_errors_do_not_expose_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_telegram(monkeypatch)

    def fail(*args, **kwargs):
        raise httpx.ConnectError(
            "failed secret-token",
            request=httpx.Request("POST", "https://example.invalid"),
        )

    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(TelegramDeliveryError) as raised:
        send_message(get_settings(), "Test")
    assert "secret-token" not in str(raised.value)


def test_missing_and_partial_telegram_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WIKI_PARCHINO_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("WIKI_PARCHINO_TELEGRAM_CHAT_ID", raising=False)
    assert telegram_credentials(get_settings()) is None
    assert send_message(get_settings(), "Test") is None

    monkeypatch.setenv("WIKI_PARCHINO_TELEGRAM_BOT_TOKEN", "token")
    with pytest.raises(TelegramConfigurationError, match="incompleta"):
        telegram_credentials(get_settings())


def test_schedule_and_end_notifications_are_recorded_and_not_duplicated(
    maintenance_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_telegram(monkeypatch)
    sent: list[dict] = []

    def fake_post(url: str, *, json: dict, timeout: float) -> httpx.Response:
        sent.append(json)
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": len(sent)}},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    now = utcnow()
    window = schedule_maintenance(
        maintenance_db,
        15,
        "Aggiornamento del server",
        now,
    )
    scheduled = notify_window(
        maintenance_db,
        window,
        "schedule",
    )
    duplicate = notify_window(
        maintenance_db,
        window,
        "schedule",
    )
    ended, cancelled = end_maintenance(
        maintenance_db,
        now + timedelta(minutes=16),
    )
    completed = notify_window(
        maintenance_db,
        ended,
        "end",
    )

    assert scheduled.sent is True
    assert duplicate.sent is False
    assert cancelled is False
    assert completed.sent is True
    assert len(sent) == 2
    assert "tra 15 minuti" in sent[0]["text"]
    assert "Aggiornamento del server" in sent[0]["text"]
    assert "https://ilparchino.github.io/wikiparchino" in sent[0]["text"]
    assert "nuovamente disponibile" in sent[1]["text"]
    maintenance_db.refresh(ended)
    assert ended.telegram_schedule_message_id == 1
    assert ended.telegram_end_message_id == 2


def test_cancel_notification_and_delivery_failure_preserve_database_transition(
    maintenance_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_telegram(monkeypatch)
    now = utcnow()
    window = schedule_maintenance(maintenance_db, 30, None, now)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            httpx.ConnectError("offline")
        ),
    )
    failed = notify_window(maintenance_db, window, "schedule")
    assert failed.sent is False
    assert "raggiungibile" in failed.detail
    assert maintenance_db.get(MaintenanceWindow, window.id) is not None

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            200, json={"ok": True, "result": {"message_id": 7}}
        ),
    )
    ended, cancelled = end_maintenance(
        maintenance_db,
        now + timedelta(minutes=1),
    )
    result = notify_window(
        maintenance_db,
        ended,
        "end",
    )
    assert cancelled is True
    assert result.sent is True


def test_schedule_validation_and_single_open_window(maintenance_db) -> None:
    now = utcnow()
    with pytest.raises(MaintenanceCommandError, match="compreso"):
        schedule_maintenance(maintenance_db, -1, None, now)
    with pytest.raises(MaintenanceCommandError, match="500"):
        schedule_maintenance(maintenance_db, 1, "x" * 501, now)
    schedule_maintenance(maintenance_db, 1, None, now)
    with pytest.raises(MaintenanceCommandError, match="già"):
        schedule_maintenance(maintenance_db, 1, None, now)


def test_cli_keeps_a_successful_exit_when_telegram_delivery_fails(
    maintenance_db,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_telegram(monkeypatch)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            httpx.ConnectError("offline secret-token")
        ),
    )

    assert command_schedule(5, "Test CLI") == 0

    captured = capsys.readouterr()
    assert "ATTENZIONE Telegram" in captured.err
    assert "secret-token" not in captured.err
    maintenance_db.expire_all()
    assert maintenance_db.query(MaintenanceWindow).count() == 1

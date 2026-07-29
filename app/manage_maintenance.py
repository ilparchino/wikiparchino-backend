from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import sys

from sqlalchemy.orm import Session

from app import database
from app.config import get_settings
from app.maintenance import (
    DEFAULT_MAINTENANCE_MESSAGE,
    activate_due_maintenance,
    maintenance_status,
    open_maintenance_window,
)
from app.models import MaintenanceWindow
from app.security import utcnow
from app.telegram import (
    TelegramConfigurationError,
    TelegramDeliveryError,
    send_message,
)


MAX_DELAY_MINUTES = 10_080


class MaintenanceCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    detail: str


def normalized_message(message: str | None) -> str | None:
    normalized = message.strip() if message else ""
    if len(normalized) > 500:
        raise MaintenanceCommandError(
            "Il messaggio di manutenzione non può superare 500 caratteri."
        )
    return normalized or None


def schedule_maintenance(
    db: Session,
    minutes: int,
    message: str | None,
    now: datetime,
) -> MaintenanceWindow:
    if minutes < 0 or minutes > MAX_DELAY_MINUTES:
        raise MaintenanceCommandError(
            f"MINUTES deve essere compreso tra 0 e {MAX_DELAY_MINUTES}."
        )
    if open_maintenance_window(db) is not None:
        raise MaintenanceCommandError(
            "Esiste già una manutenzione programmata o attiva."
        )
    window = MaintenanceWindow(
        open_slot=1,
        announced_at=now,
        starts_at=now + timedelta(minutes=minutes),
        message=normalized_message(message),
    )
    db.add(window)
    db.commit()
    db.refresh(window)
    return window


def end_maintenance(
    db: Session,
    now: datetime,
) -> tuple[MaintenanceWindow, bool]:
    window = open_maintenance_window(db)
    if window is None:
        raise MaintenanceCommandError("Non è presente una manutenzione da terminare.")
    if now >= window.starts_at:
        window = activate_due_maintenance(db, window, now)
    cancelled = now < window.starts_at
    window.ended_at = now
    window.open_slot = None
    db.commit()
    db.refresh(window)
    return window, cancelled


def schedule_text(window: MaintenanceWindow, frontend_url: str) -> str:
    seconds = max(
        0, int((window.starts_at - window.announced_at).total_seconds())
    )
    minutes = (seconds + 59) // 60
    timing = (
        "immediatamente"
        if minutes == 0
        else f"tra {minutes} minut{'o' if minutes == 1 else 'i'}"
    )
    reason = window.message or DEFAULT_MAINTENANCE_MESSAGE
    return (
        f"⚠ Wiki Parchino entrerà in manutenzione {timing}. ⚠\n"
        "Durante la manutenzione il servizio non sarà disponibile.\n\n"
        f"Dettagli: {reason}\n\n"
        f"{frontend_url}"
    )


def end_text(
    window: MaintenanceWindow,
    frontend_url: str,
    cancelled: bool,
) -> str:
    if cancelled:
        return (
            "❌ La manutenzione programmata di Wiki Parchino è stata annullata.\n\n"
            f"{frontend_url}"
        )
    return (
        "✔ La manutenzione di Wiki Parchino è terminata. "
        "Il servizio è nuovamente disponibile.\n\n"
        f"{frontend_url}"
    )


def notify_window(
    db: Session,
    window: MaintenanceWindow,
    event: str,
) -> NotificationResult:
    settings = get_settings()
    if event == "schedule":
        if window.telegram_schedule_sent_at is not None:
            return NotificationResult(False, "Notifica di programmazione già inviata.")
        text = schedule_text(window, settings.frontend_url)
    elif event == "end":
        if window.ended_at is None:
            raise MaintenanceCommandError(
                "La manutenzione non è ancora terminata."
            )
        if window.telegram_end_sent_at is not None:
            return NotificationResult(False, "Notifica finale già inviata.")
        text = end_text(
            window,
            settings.frontend_url,
            cancelled=window.ended_at < window.starts_at,
        )
    else:
        raise MaintenanceCommandError("Tipo di notifica non valido.")

    try:
        result = send_message(settings, text)
    except (TelegramConfigurationError, TelegramDeliveryError) as exc:
        return NotificationResult(False, str(exc))
    if result is None:
        return NotificationResult(False, "Integrazione Telegram non configurata.")

    sent_at = utcnow()
    if event == "schedule":
        window.telegram_schedule_sent_at = sent_at
        window.telegram_schedule_message_id = result.message_id
    else:
        window.telegram_end_sent_at = sent_at
        window.telegram_end_message_id = result.message_id
    db.commit()
    return NotificationResult(True, "Notifica Telegram inviata.")


def latest_window(db: Session) -> MaintenanceWindow | None:
    return db.query(MaintenanceWindow).order_by(MaintenanceWindow.id.desc()).first()


def print_notification(result: NotificationResult) -> None:
    stream = sys.stdout if result.sent else sys.stderr
    prefix = "Telegram:" if result.sent else "ATTENZIONE Telegram:"
    print(f"{prefix} {result.detail}", file=stream)


def command_schedule(minutes: int, message: str | None) -> int:
    now = utcnow()
    with database.SessionLocal() as db:
        window = schedule_maintenance(db, minutes, message, now)
        print(
            f"Manutenzione programmata per {window.starts_at.isoformat()} "
            f"(tra {minutes} minuti)."
        )
        print_notification(notify_window(db, window, "schedule"))
    return 0


def command_status() -> int:
    with database.SessionLocal() as db:
        status = maintenance_status(db, utcnow())
    print(f"Stato: {status.state}")
    if status.starts_at is not None:
        print(f"Inizio: {status.starts_at.isoformat()}")
    if status.message:
        print(f"Messaggio: {status.message}")
    return 0


def command_end() -> int:
    with database.SessionLocal() as db:
        window, cancelled = end_maintenance(db, utcnow())
        print(
            "Manutenzione annullata."
            if cancelled
            else "Manutenzione terminata."
        )
        print_notification(notify_window(db, window, "end"))
    return 0


def command_notify() -> int:
    with database.SessionLocal() as db:
        window = latest_window(db)
        if window is None:
            raise MaintenanceCommandError(
                "Non esiste una manutenzione da notificare."
            )
        event = "end" if window.ended_at is not None else "schedule"
        print_notification(notify_window(db, window, event))
    return 0


def command_telegram_test() -> int:
    settings = get_settings()
    try:
        result = send_message(
            settings,
            "Test notifiche Wiki Parchino completato correttamente.",
        )
    except (TelegramConfigurationError, TelegramDeliveryError) as exc:
        print(f"Errore Telegram: {exc}", file=sys.stderr)
        return 1
    if result is None:
        print("Errore Telegram: integrazione non configurata.", file=sys.stderr)
        return 1
    print(f"Telegram configurato correttamente. Messaggio {result.message_id} inviato.")
    return 0


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(
        description="Gestisce la modalità manutenzione di Wiki Parchino."
    )
    subparsers = command_parser.add_subparsers(dest="command", required=True)
    schedule = subparsers.add_parser("schedule")
    schedule.add_argument("--minutes", type=int, required=True)
    schedule.add_argument("--message")
    subparsers.add_parser("status")
    subparsers.add_parser("end")
    subparsers.add_parser("notify")
    subparsers.add_parser("telegram-test")
    return command_parser


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "schedule":
            return command_schedule(args.minutes, args.message)
        if args.command == "status":
            return command_status()
        if args.command == "end":
            return command_end()
        if args.command == "notify":
            return command_notify()
        return command_telegram_test()
    except MaintenanceCommandError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

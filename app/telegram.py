from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Settings


TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_TIMEOUT_SECONDS = 10.0


class TelegramConfigurationError(RuntimeError):
    pass


class TelegramDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramMessage:
    message_id: int


def telegram_credentials(settings: Settings) -> tuple[str, str] | None:
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if token is None and chat_id is None:
        return None
    if token is None or chat_id is None:
        raise TelegramConfigurationError(
            "Configurazione Telegram incompleta: servono token e chat ID."
        )
    return token, chat_id


def send_message(settings: Settings, text: str) -> TelegramMessage | None:
    credentials = telegram_credentials(settings)
    if credentials is None:
        return None
    token, chat_id = credentials
    try:
        response = httpx.post(
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_notification": False,
            },
            timeout=TELEGRAM_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise TelegramDeliveryError(
            "Telegram non è raggiungibile."
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise TelegramDeliveryError(
            f"Telegram ha risposto con HTTP {response.status_code}."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise TelegramDeliveryError(
            "Telegram ha restituito una risposta non valida."
        ) from exc
    if payload.get("ok") is not True:
        raise TelegramDeliveryError("Telegram ha rifiutato il messaggio.")
    message_id = payload.get("result", {}).get("message_id")
    if not isinstance(message_id, int):
        raise TelegramDeliveryError(
            "La risposta Telegram non contiene l'identificativo del messaggio."
        )
    return TelegramMessage(message_id=message_id)

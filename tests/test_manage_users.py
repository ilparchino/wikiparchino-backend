from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.manage_users import prompt_and_save_user
from app.models import UserAccount
from app.security import verify_password


def answers(values: list[str]):
    iterator: Iterator[str] = iter(values)
    return lambda _prompt: next(iterator)


def passwords(values: list[str]):
    iterator: Iterator[str] = iter(values)
    return lambda _prompt: next(iterator)


def test_interactive_user_management_creates_and_updates_accounts(client) -> None:
    from app.database import SessionLocal

    with SessionLocal() as db:
        user, created = prompt_and_save_user(
            db,
            input_fn=answers(["  NewUser  ", "Nuovo Utente", "yes"]),
            password_fn=passwords(["a-secure-password", "a-secure-password"]),
        )
        assert created is True
        assert user.username == "newuser"
        assert user.is_admin is True
        assert verify_password("a-secure-password", user.password_hash)

    with SessionLocal() as db:
        other_user_count = db.query(UserAccount).count()
        user, created = prompt_and_save_user(
            db,
            input_fn=answers(["newuser", "Nome Aggiornato", "no"]),
            password_fn=passwords(["another-secure-password", "another-secure-password"]),
        )
        assert created is False
        assert user.display_name == "Nome Aggiornato"
        assert user.is_admin is False
        assert verify_password("another-secure-password", user.password_hash)
        assert db.query(UserAccount).count() == other_user_count


@pytest.mark.parametrize(
    ("password_values", "message"),
    [
        (["short", "short"], "at least 12"),
        (["a-secure-password", "different-password"], "do not match"),
        (
            [" password-sicura", " password-sicura"],
            "begin or end with whitespace",
        ),
        (
            ["password\tvalida", "password\tvalida"],
            "printable characters",
        ),
    ],
)
def test_interactive_user_management_rejects_invalid_passwords(
    client, password_values: list[str], message: str
) -> None:
    from app.database import SessionLocal

    with SessionLocal() as db:
        with pytest.raises(ValueError, match=message):
            prompt_and_save_user(
                db,
                input_fn=answers(["invalid-user", "Invalid User"]),
                password_fn=passwords(password_values),
            )


def test_interactive_user_management_cannot_demote_the_owner(client) -> None:
    from app.database import SessionLocal

    with SessionLocal() as db:
        with pytest.raises(ValueError, match="Transfer ownership"):
            prompt_and_save_user(
                db,
                input_fn=answers(["admin", "", "no"]),
                password_fn=passwords(["owner-password-nuova", "owner-password-nuova"]),
            )

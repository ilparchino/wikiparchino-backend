from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import AdminPasswordResetIn, AdminUserCreate, PasswordChangeIn
from app.security import hash_password, validate_new_password, verify_password


def test_password_policy_preserves_printable_unicode_and_internal_spaces() -> None:
    password = "frase café con simboli ☕"

    assert validate_new_password(password) == password
    stored_hash = hash_password(password)
    assert verify_password(password, stored_hash)
    assert not verify_password(password.replace(" ", ""), stored_hash)
    assert validate_new_password("🧭" * 12) == "🧭" * 12
    assert validate_new_password("🧭" * 200) == "🧭" * 200


@pytest.mark.parametrize(
    "password",
    [
        "troppo-cort",
        "x" * 201,
        " password-valida",
        "password-valida ",
        "\tpassword-valida",
        "password-valida\n",
        "password\tvalida",
        "password\nvalida",
        "password\0valida",
        "password\u200bvalida",
        "password\u00a0valida",
    ],
)
def test_password_policy_rejects_invalid_boundaries_and_characters(
    password: str,
) -> None:
    with pytest.raises(ValueError):
        validate_new_password(password)


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            AdminUserCreate,
            {
                "username": "utente",
                "display_name": "Utente",
                "password": "password\tnon-valida",
            },
        ),
        (
            AdminPasswordResetIn,
            {"new_password": " password-non-valida"},
        ),
        (
            PasswordChangeIn,
            {
                "current_password": "password-attuale",
                "new_password": "password-non-valida\n",
            },
        ),
    ],
)
def test_all_password_write_schemas_use_the_shared_policy(
    schema,
    payload: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)

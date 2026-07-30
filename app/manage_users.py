from __future__ import annotations

from collections.abc import Callable
from getpass import getpass

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import UserAccount
from app.security import hash_password, validate_new_password


def required_text(prompt: str, maximum: int, input_fn: Callable[[str], str]) -> str:
    value = input_fn(prompt).strip()
    if not value:
        raise ValueError("The value cannot be empty")
    if len(value) > maximum:
        raise ValueError(f"The value cannot exceed {maximum} characters")
    return value


def yes_no(prompt: str, default: bool, input_fn: Callable[[str], str]) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input_fn(prompt + suffix).strip().lower()
    if not answer:
        return default
    if answer in {"y", "yes"}:
        return True
    if answer in {"n", "no"}:
        return False
    raise ValueError("Answer yes or no")


def prompt_password(password_fn: Callable[[str], str]) -> str:
    password = password_fn("Password: ")
    confirmation = password_fn("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match")
    return validate_new_password(password)


def prompt_and_save_user(
    db: Session,
    input_fn: Callable[[str], str] = input,
    password_fn: Callable[[str], str] = getpass,
) -> tuple[UserAccount, bool]:
    username = required_text("Username: ", 80, input_fn).lower()
    existing = (
        db.query(UserAccount).filter(UserAccount.username == username).first()
    )
    display_default = existing.display_name if existing else ""
    display_prompt = (
        f"Display name [{display_default}]: " if display_default else "Display name: "
    )
    display_input = input_fn(display_prompt).strip()
    display_name = display_input or display_default
    if not display_name:
        raise ValueError("The display name cannot be empty")
    if len(display_name) > 160:
        raise ValueError("The display name cannot exceed 160 characters")

    password = prompt_password(password_fn)
    is_admin = yes_no("Administrator", existing.is_admin if existing else False, input_fn)
    if existing is not None and existing.is_owner and not is_admin:
        raise ValueError("Transfer ownership before removing the Owner's administrator role")

    created = existing is None
    user = existing or UserAccount(username=username, display_name=display_name)
    user.display_name = display_name
    user.password_hash = hash_password(password)
    user.is_admin = is_admin
    user.is_active = True
    if created:
        user.is_owner = False
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, created


def main() -> None:
    try:
        with SessionLocal() as db:
            user, created = prompt_and_save_user(db)
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("User management cancelled") from None
    except ValueError as error:
        raise SystemExit(f"Error: {error}") from None

    action = "Created" if created else "Updated"
    role = "administrator" if user.is_admin else "user"
    print(f"{action} {role} account: {user.username}")


if __name__ == "__main__":
    main()

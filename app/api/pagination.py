from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy.orm import Query

from app.schemas import Page


ItemT = TypeVar("ItemT")
OutputT = TypeVar("OutputT")


def paginate_query(
    query: Query,
    page: int,
    page_size: int,
    serialize: Callable[[Any], OutputT] | None = None,
) -> Page[OutputT | Any]:
    total = query.order_by(None).count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [serialize(row) for row in rows] if serialize else rows
    return Page(items=items, total=total, page=page, page_size=page_size)

"""Utilidades de paginação e ordenação."""
from __future__ import annotations

from math import ceil
from typing import Any

from sqlalchemy import asc, desc
from sqlalchemy.orm import Query


def parse_pagination(
    page: int = 1, size: int = 20, sort: str | None = None
) -> tuple[int, int, str | None, str | None]:
    """Normaliza parâmetros de paginação e ordenação (?page&size&sort).

    `sort` aceita o formato `campo` (asc) ou `-campo` (desc).
    """
    page = max(1, page)
    size = min(max(1, size), 200)
    sort_field: str | None = None
    sort_dir: str | None = None
    if sort:
        if sort.startswith("-"):
            sort_field, sort_dir = sort[1:], "desc"
        else:
            sort_field, sort_dir = sort, "asc"
    return page, size, sort_field, sort_dir


def apply_sort(query: Query, sort_field: str | None, sort_dir: str | None, allowed: set[str]) -> Query:
    """Aplica ordenação com whitelist de colunas (evita SQL injection)."""
    if sort_field and sort_field in allowed:
        column = getattr(query.column_descriptions[0]["entity"], sort_field)
        return query.order_by(desc(column) if sort_dir == "desc" else asc(column))
    return query


def paginate(query: Query, page: int, size: int) -> dict[str, Any]:
    """Executa paginação e retorna envelope padronizado {items, total, page...}."""
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": ceil(total / size) if total else 0,
    }

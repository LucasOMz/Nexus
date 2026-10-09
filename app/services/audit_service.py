"""Serviço de auditoria — registra mutações com diff JSON e IP (append-only).

A coluna `diff` é JSON. Valores que vêm de dentro do Python (`date`, `datetime`,
`Decimal`, enums, `UUID`) **não** são serializáveis pelo `json.dumps` que o
SQLAlchemy usa — e a falha só aparece no `commit`, já fora do `try` daqui, o que
derrubava o request inteiro com erro 500.

Foi exatamente o que acontecia ao salvar a **data de garantia**: o diff levava
um objeto `date` e a gravação da auditoria estourava. Por isso todo diff passa
por `json_safe` antes de ser gravado.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.core import LogAuditoria, Usuario


def json_safe(valor: Any) -> Any:
    """Converte recursivamente qualquer valor em algo serializável em JSON.

    A saída é **sempre** JSON-safe: o fallback final é `str()`, então nenhum
    valor desconhecido consegue quebrar a gravação.
    """
    if valor is None:
        return None

    # Enum antes de str: `class Dominio(str, Enum)` também é uma str.
    if isinstance(valor, enum.Enum):
        return json_safe(valor.value)

    if isinstance(valor, (str, bool, int, float)):
        return valor

    # datetime é subclasse de date; os dois viram ISO 8601.
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()

    if isinstance(valor, Decimal):
        return float(valor)

    if isinstance(valor, UUID):
        return str(valor)

    if isinstance(valor, (bytes, bytearray)):
        return bytes(valor).decode("utf-8", "replace")

    if isinstance(valor, dict):
        return {str(chave): json_safe(v) for chave, v in valor.items()}

    if isinstance(valor, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in valor]

    return str(valor)


def audit(
    db: Session,
    usuario: Usuario | None,
    acao: str,
    entidade: str,
    entidade_id: int | None = None,
    ip: str | None = None,
    diff: dict[str, Any] | None = None,
) -> None:
    """Grava uma entrada de auditoria. Nunca lança exceção (fail-safe)."""
    try:
        db.add(
            LogAuditoria(
                usuario_id=usuario.id if usuario else None,
                acao=acao,
                entidade=entidade,
                entidade_id=entidade_id,
                ip=ip,
                diff=json_safe(diff) if diff is not None else None,
            )
        )
        # commit é responsabilidade do chamador; aqui apenas enfileira.
    except Exception:  # pragma: no cover - auditoria nunca deve derrubar o request
        pass


def serialize_entity(entity: object) -> dict[str, Any]:
    """Serializa um modelo para diff, ignorando campos não JSON-safe."""
    out: dict[str, Any] = {}
    for col in entity.__table__.columns:  # type: ignore[attr-defined]
        out[col.name] = json_safe(getattr(entity, col.name))
    return out

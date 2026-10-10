"""Endpoint da busca global (Ctrl+K).

Só transporte: a regra de o que pesquisar e como pontuar vive em
`app/services/busca.py`, que é testável sem subir a API.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.core import Usuario
from app.services import busca as servico

router = APIRouter(prefix="/busca", tags=["busca"])


@router.get("", response_model=dict)
def buscar(
    q: str = Query(default="", description="Termo pesquisado."),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Procura o termo em ativos, produtos, usuários e plantas.

    Respeita a planta do usuário: quem está preso a uma planta não encontra
    ativos de outra. Sem isso, a busca furaria o isolamento multi-tenant, que
    é justamente o que o resto do sistema protege.
    """
    resultado = servico.buscar(db, q, planta_id=user.planta_id)
    return resultado.para_dict()

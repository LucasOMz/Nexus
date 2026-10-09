"""Resolução da PLANTA ATIVA.

Regra do sistema: **o usuário pertence a uma planta**, e tudo que ele cria,
edita ou consulta acontece nessa planta. Administradores sem planta enxergam
tudo (visão consolidada), e podem escolher uma planta específica pelo cabeçalho
`X-Planta-Id` — é o seletor da tela de inventário.

Centralizar aqui é o que evita vazamento entre plantas: nenhum router monta o
filtro na mão.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.core import Planta, Usuario
from app.models.enums import PapelUsuario

# Valores aceitos no cabeçalho para pedir a visão consolidada.
TODAS = {"todas", "todos", "all", "*", "0"}


def resolver_planta_id(user: Usuario, request: Request | None = None) -> int | None:
    """Planta que este usuário enxerga agora.

    * `None` → todas as plantas (administrador na visão consolidada).
    * `int`  → somente aquela planta.
    """
    if user.papel == PapelUsuario.ADMIN and request is not None:
        bruto = (request.headers.get("X-Planta-Id") or "").strip()
        if bruto.lower() in TODAS:
            return None
        if bruto.isdigit():
            return int(bruto)
    return user.planta_id


def planta_ativa(
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> int | None:
    """Dependência do FastAPI: devolve o id da planta ativa (ou None = todas)."""
    planta_id = resolver_planta_id(user, request)

    # Administrador escolhendo uma planta que não existe: erro claro em vez de
    # devolver uma lista vazia sem explicação.
    if planta_id is not None and user.papel == PapelUsuario.ADMIN:
        if db.get(Planta, planta_id) is None:
            raise HTTPException(404, f"Planta {planta_id} não encontrada.")
    return planta_id


def exigir_planta_do_usuario(user: Usuario, planta_id: int | None) -> int | None:
    """Para usuário COMUM, a planta é obrigatória.

    Sem planta, `planta_id` seria `None` e o filtro não seria aplicado — a
    pessoa veria equipamentos de TODAS as plantas, o oposto do desejado.

    O administrador continua livre (`None` = visão de todas as plantas).
    """
    if user.papel == PapelUsuario.ADMIN:
        return planta_id
    if planta_id is None:
        raise HTTPException(
            400,
            "Seu usuário não está vinculado a uma planta, então não há o que mostrar. "
            "Peça ao administrador para definir a planta do seu acesso "
            "(Administração → Usuários).",
        )
    return planta_id


def aplicar_filtro(consulta, modelo, planta_id: int | None):
    """Aplica o filtro de planta numa consulta (None = todas as plantas)."""
    if planta_id is None:
        return consulta
    return consulta.filter(modelo.planta_id == planta_id)


def exigir_planta(db: Session, planta_id: int | None, acao: str = "cadastrar") -> int:
    """Garante a planta onde o registro será gravado.

    Ordem: a planta ativa → a primeira planta cadastrada (caso típico de uma
    unidade só) → erro claro se ainda não existe nenhuma.

    Sem esse recuo, um sistema recém-instalado (ou um administrador sem planta)
    não conseguiria cadastrar nada, e a mensagem apareceria no meio de um
    formulário já preenchido.
    """
    if planta_id is not None:
        return planta_id

    padrao = db.query(Planta).order_by(Planta.id).first()
    if padrao is not None:
        return padrao.id

    raise HTTPException(
        400,
        f"Cadastre uma planta antes de {acao} (Administração → Plantas). "
        "Todo ativo pertence a uma planta.",
    )

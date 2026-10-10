"""Modelo de permissões por usuário.

Cada usuário tem um conjunto de permissões:
  - inventarios : quais inventários pode abrir ("ti", "impressora")
  - modulos     : quais telas/módulos pode acessar
  - pode_escrever : criar/editar registros
  - pode_excluir  : excluir (soft delete) registros

Se `Usuario.permissoes` for NULL, as permissões são derivadas do `papel`
(compatibilidade). O papel `admin` sempre tem acesso total.
"""
from __future__ import annotations

from typing import Any

# Módulos disponíveis no sistema (chave -> rótulo exibido no admin).
# O antigo "dashboard" foi incorporado a "relatorios".
MODULOS: dict[str, str] = {
    "ativos": "Ativos",
    "produtos": "Consumíveis",
    "movimentacoes": "Movimentações",
    "manutencoes": "Manutenções",
    "scanner": "Leitura (Scanner)",
    "financeiro": "Painel financeiro",
    "contratos": "Contratos de locação",
    "descarte": "Certificado de descarte",
    "emprestimos": "Empréstimos e devoluções",
    "monitor": "Monitor de impressoras",
    "seguranca": "Segurança da conta",
    "contagens": "Inventário cíclico (contagem)",
    "relatorios": "Relatórios",
    "cadastros": "Cadastros",
    # Canal de reporte de erro (temporario, para todos os perfis).
    "reporte": "Reporte de Erro",
    # Gestão da impressora da própria planta (perfil TI e administrador).
    "impressao": "Impressão (minha planta)",
    # Agenda de empréstimos e devoluções.
    "calendario": "Calendário de empréstimos",
}

INVENTARIOS: dict[str, str] = {"ti": "Inventário de TI", "impressora": "Inventário de Impressoras"}

ACOES: tuple[str, ...] = ("pode_escrever", "pode_excluir")


def _papel(usuario: Any) -> str:
    papel = getattr(usuario, "papel", None)
    return getattr(papel, "value", papel) or "leitor"


def permissoes_padrao(papel: str) -> dict[str, Any]:
    """Permissões padrão por papel (usadas quando não há customização)."""
    todos_inv = list(INVENTARIOS)
    if papel == "admin":
        return {"inventarios": todos_inv, "modulos": list(MODULOS), "pode_escrever": True, "pode_excluir": True}
    if papel == "ti":
        return {
            "inventarios": todos_inv,
            "modulos": ["ativos", "produtos", "movimentacoes", "manutencoes", "scanner", "contagens", "contratos", "descarte", "financeiro", "emprestimos", "monitor", "seguranca", "relatorios", "impressao", "calendario", "reporte"],
            "pode_escrever": True,
            "pode_excluir": False,
        }
    if papel == "auditor":
        return {
            "inventarios": todos_inv,
            "modulos": ["ativos", "produtos", "movimentacoes", "manutencoes", "contagens", "contratos", "descarte", "financeiro", "emprestimos", "monitor", "seguranca", "relatorios", "calendario", "reporte"],
            "pode_escrever": False,
            "pode_excluir": False,
        }
    # leitor — o calendário é visível para TODOS (cada um vê a sua planta).
    return {
        "inventarios": todos_inv,
        "modulos": ["ativos", "produtos", "movimentacoes", "manutencoes", "scanner", "contagens", "contratos", "descarte", "financeiro", "emprestimos", "monitor", "seguranca", "calendario", "reporte"],
        "pode_escrever": False,
        "pode_excluir": False,
    }


def permissoes_efetivas(usuario: Any) -> dict[str, Any]:
    """Combina o padrão do papel com as customizações do usuário."""
    papel = _papel(usuario)
    base = permissoes_padrao(papel)
    custom = getattr(usuario, "permissoes", None) or {}
    efetivas = dict(base)
    for chave in ("inventarios", "modulos"):
        if custom.get(chave) is not None:
            efetivas[chave] = list(custom[chave])
    for chave in ACOES:
        if custom.get(chave) is not None:
            efetivas[chave] = bool(custom[chave])

    # Admin nunca perde acesso.
    if papel == "admin":
        efetivas.update(
            inventarios=list(INVENTARIOS), modulos=list(MODULOS), pode_escrever=True, pode_excluir=True
        )
    return efetivas


def pode_modulo(usuario: Any, modulo: str) -> bool:
    return modulo in (permissoes_efetivas(usuario).get("modulos") or [])


def pode_acao(usuario: Any, acao: str) -> bool:
    if acao not in ACOES:
        return False
    if _papel(usuario) == "admin":
        return True
    return bool(permissoes_efetivas(usuario).get(acao))


def pode_inventario(usuario: Any, dominio: str) -> bool:
    if _papel(usuario) == "admin":
        return True
    return dominio in (permissoes_efetivas(usuario).get("inventarios") or [])


def eh_admin(usuario: Any) -> bool:
    return _papel(usuario) == "admin"

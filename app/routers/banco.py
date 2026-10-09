"""Conexão com o banco de dados — tela de **visualização**.

Esta aba é **somente leitura**, por decisão de projeto. A conexão não é uma
configuração de tela: ela é fixada quando o sistema sobe (`app/database.py`).
Se ela pudesse ser alterada daqui, um endereço errado derrubaria justamente a
tela que serviria para corrigir — o sistema perderia a única forma de se
consertar pela interface.

Por isso não existe endpoint de escrita neste módulo. Trocar de banco é feito
pelo `.env` + reinício, ou pelo setup inicial (que roda **antes** de o sistema
depender de um banco).

A senha **nunca** é devolvida, nem mascarada parcialmente: só se ela existe.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import require_admin
from app.database import get_db
from app.models.core import Usuario

router = APIRouter(prefix="/admin/banco", tags=["banco de dados"])

# Tabelas cujo tamanho interessa ver de relance.
TABELAS_PRINCIPAIS = (
    "ativos", "produtos", "movimentacoes", "manutencoes",
    "usuarios", "plantas", "transferencias", "logs_auditoria",
)


def _url_mascarada() -> dict[str, Any]:
    """Separa a URL em partes, **sem nunca revelar a senha**."""
    try:
        url = make_url(settings.database_url)
    except Exception:  # noqa: BLE001 — URL malformada não pode derrubar a tela
        return {
            "tipo": "desconhecido",
            "url": "(endereço inválido)",
            "senha_definida": False,
        }

    dialeto = url.get_backend_name()
    return {
        "tipo": {
            "sqlite": "SQLite",
            "postgresql": "PostgreSQL",
            "mysql": "MySQL",
            "mssql": "SQL Server",
        }.get(dialeto, dialeto),
        "dialeto": dialeto,
        # `hide_password` troca a senha por *** — é o próprio SQLAlchemy que
        # garante isso, sem eu montar a string à mão.
        "url": url.render_as_string(hide_password=True),
        "driver": url.get_driver_name(),
        "servidor": url.host,
        "porta": url.port,
        "banco": url.database,
        "usuario": url.username,
        "senha_definida": bool(url.password),
    }


def _info_sqlite() -> dict[str, Any]:
    from app.database import caminho_sqlite

    caminho = caminho_sqlite()
    existe = bool(caminho and os.path.exists(caminho))
    tamanho = os.path.getsize(caminho) if existe else 0

    return {
        "arquivo": caminho,
        "absoluto": os.path.abspath(caminho) if caminho else None,
        "existe": existe,
        "tamanho_bytes": tamanho,
        "tamanho_legivel": _legivel(tamanho),
    }


def _legivel(bytes_: int) -> str:
    """Tamanho em unidade que se lê de relance."""
    valor = float(bytes_ or 0)
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidade == "TB":
            return f"{valor:.1f} {unidade}" if unidade != "B" else f"{int(valor)} B"
        valor /= 1024
    return f"{valor:.1f} TB"


def _contagem_tabelas(db: Session) -> list[dict[str, Any]]:
    """Quantas linhas há nas tabelas principais.

    Só as principais: contar tudo a cada abertura de tela seria desperdício.
    Tabela que não existe é simplesmente omitida.
    """
    # A conexão DA SESSÃO, não o engine global: em teste eles apontam para
    # bancos diferentes, e usar o global devolvia lista vazia.
    existentes = set(inspect(db.get_bind()).get_table_names())
    saida = []
    for nome in TABELAS_PRINCIPAIS:
        if nome not in existentes:
            continue
        try:
            total = db.execute(text(f'SELECT COUNT(*) FROM "{nome}"')).scalar() or 0
        except Exception:  # noqa: BLE001 — uma tabela problemática não derruba o resto
            continue
        saida.append({"tabela": nome, "linhas": int(total)})
    return saida


@router.get("")
def visualizar(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Situação da conexão com o banco. **Somente leitura.**"""
    partes = _url_mascarada()
    dialeto = partes.get("dialeto")

    info: dict[str, Any] = {
        "conexao": partes,
        "somente_leitura": True,
        "como_alterar": (
            "A conexão é definida pela variável DATABASE_URL no arquivo .env e "
            "passa a valer quando o sistema é reiniciado. Não há alteração por "
            "esta tela de propósito: se o endereço fosse trocado daqui e "
            "estivesse errado, esta própria tela deixaria de abrir."
        ),
    }

    if dialeto == "sqlite":
        info["sqlite"] = _info_sqlite()
    else:
        # O pool vem da conexão da sessão — o `engine` global apontaria para
        # outro banco em ambiente de teste.
        pool = getattr(db.get_bind(), "pool", None)
        info["postgres"] = {
            "pool_tamanho": getattr(pool, "size", lambda: None)() if pool else None,
            "pool_em_uso": getattr(pool, "checkedout", lambda: None)() if pool else None,
            "pool_disponivel": getattr(pool, "checkedin", lambda: None)() if pool else None,
        }

    # --- Versão do servidor e saúde da conexão ---
    try:
        if dialeto == "sqlite":
            versao = db.execute(text("SELECT sqlite_version()")).scalar()
            info["servidor_versao"] = f"SQLite {versao}"
        elif dialeto == "postgresql":
            versao = db.execute(text("SHOW server_version")).scalar()
            info["servidor_versao"] = f"PostgreSQL {versao}"
        else:
            info["servidor_versao"] = db.execute(text("SELECT version()")).scalar()
        info["saudavel"] = True
        info["mensagem"] = "Conectado."
    except Exception as e:  # noqa: BLE001 — a tela precisa abrir mesmo se o banco falhar
        info["saudavel"] = False
        info["mensagem"] = f"Sem resposta do banco: {e}"
        return info

    # --- Tamanho do banco (quando o servidor souber informar) ---
    try:
        if dialeto == "postgresql":
            banco = partes.get("banco")
            total = db.execute(
                text("SELECT pg_database_size(:b)"), {"b": banco}
            ).scalar()
            info["tamanho_bytes"] = int(total or 0)
            info["tamanho_legivel"] = _legivel(int(total or 0))
    except Exception:  # noqa: BLE001 — opcional, não impede a tela
        pass

    # --- Estrutura ---
    try:
        tabelas = inspect(db.get_bind()).get_table_names()
        info["total_tabelas"] = len(tabelas)
        info["contagens"] = _contagem_tabelas(db)
    except Exception:  # noqa: BLE001
        info["total_tabelas"] = None

    # --- Configurações que afetam o banco (do .env, não editáveis aqui) ---
    info["configuracoes"] = {
        "criar_tabelas_ao_subir": settings.auto_create_tables,
        "pool_pre_ping": True,
        "backups_habilitados": settings.backup_ativo if hasattr(settings, "backup_ativo") else None,
    }

    return info

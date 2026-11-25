"""Registra eventos de auditoria na mesma transação da operação."""
from __future__ import annotations

import enum
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import event, false, func, insert, select, update
from sqlalchemy.orm import Session, SessionTransaction

from app.models.core import LogAuditoria, Usuario
from app.services.auditoria_cadeia import GENESIS, calcular_hash, registro

log = logging.getLogger(__name__)
_PENDENTES = "nexus.auditoria_pendente"
# Identificador estável do bloqueio da cadeia em todas as instâncias da API.
_TRAVA_AUDITORIA = 0x4E45585553415544


class AuditoriaIndisponivel(RuntimeError):
    """A transação não pode ser confirmada sem seu registro de auditoria."""

# Campos que NUNCA entram no diff da auditoria.
#
# A auditoria é encadeada por hash: o que entra nela não pode ser editado nem
# apagado depois. Um segredo gravado aqui está vazado de forma permanente —
# então a proteção precisa ser por NOME de campo, e valer para qualquer modelo
# que venha a existir.
#
# Ver `serialize_entity` para o raciocínio completo.
CAMPOS_PROTEGIDOS: frozenset[str] = frozenset({
    # Chaves de licença de software (ver app/core/segredos.py)
    "chave", "chave_cifrada", "chave_hash", "chave_impressao",
    # Segredos de autenticação
    "senha", "senha_hash", "password", "password_hash",
    "totp_segredo", "mfa_segredo", "recovery_codes",
    "token", "access_token", "refresh_token", "api_key", "secret",
    # Chaves de integração
    "ocs_senha", "ldap_senha", "smtp_senha",
})


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
    """Prepara um evento para ser gravado no commit da transação atual."""
    transacao = db.get_nested_transaction() or db.get_transaction() or db.begin()
    evento = {
        "usuario_id": usuario.id if usuario else None,
        "acao": acao,
        "entidade": entidade,
        "entidade_id": entidade_id,
        "ip": ip,
        "created_at": datetime.now(timezone.utc),
    }
    try:
        evento["diff"] = json_safe(diff)
    except Exception as exc:
        _avisar_falha(evento, exc)
        raise AuditoriaIndisponivel() from None
    db.info.setdefault(_PENDENTES, {}).setdefault(transacao, []).append(evento)


def _avisar_falha(evento: dict, erro: Exception) -> None:
    # Exceções do banco podem incluir diff e parâmetros sensíveis.
    log.error(
        "Falha na auditoria. acao=%s entidade=%s entidade_id=%s usuario_id=%s erro=%s",
        evento["acao"], evento["entidade"], evento["entidade_id"], evento["usuario_id"], type(erro).__name__,
    )


@event.listens_for(Session, "before_commit")
def _gravar_auditoria(db: Session) -> None:
    if db.in_nested_transaction():
        return
    eventos = db.info.get(_PENDENTES, {}).get(db.get_transaction())
    if not eventos:
        return

    # Finaliza as escritas da operação antes de bloquear a cadeia. A trava
    # fica reservada somente durante a gravação final e o commit.
    db.flush()
    tabela = LogAuditoria.__table__
    evento = eventos[0]
    try:
        conexao = db.connection()
        if conexao.dialect.name == "postgresql":
            _, isolamento = conexao.execute(select(
                func.pg_advisory_xact_lock(_TRAVA_AUDITORIA), func.current_setting("transaction_isolation"),
            )).one()
            if isolamento not in {"read committed", "read uncommitted"}:
                log.error("A auditoria exige READ COMMITTED no PostgreSQL para ler o topo atualizado da cadeia.")
                raise AuditoriaIndisponivel()
        elif conexao.dialect.name == "sqlite":
            # Abre a transação de escrita antes de ler o topo. Também evita
            # que o primeiro SAVEPOINT do driver funcione como transação raiz.
            conexao.execute(update(tabela).where(false()).values(hash=tabela.c.hash))

        with conexao.begin_nested():
            ultima = conexao.execute(
                select(tabela.c.id, tabela.c.hash).where(tabela.c.hash.is_not(None)).order_by(tabela.c.id.desc()).limit(1)
            ).first()
            id_anterior, anterior = ultima if ultima else (None, GENESIS)
            for evento in eventos:
                resultado = conexao.execute(insert(tabela).values(**evento, hash_anterior=anterior))
                id_log = resultado.inserted_primary_key[0]
                if id_anterior is not None and id_log <= id_anterior:
                    log.error("A sequência de IDs da auditoria produziu um valor anterior ao topo da cadeia.")
                    raise AuditoriaIndisponivel()
                anterior = calcular_hash({"id": id_log, **registro(**evento)}, anterior)
                conexao.execute(update(tabela).where(tabela.c.id == id_log).values(hash=anterior))
                id_anterior = id_log
    except Exception as exc:
        _avisar_falha(evento, exc)
        raise AuditoriaIndisponivel() from None


@event.listens_for(Session, "after_commit")
def _promover_auditoria_do_savepoint(db: Session) -> None:
    savepoint = db.get_nested_transaction()
    pendentes = db.info.get(_PENDENTES)
    if savepoint is not None and pendentes is not None:
        eventos = pendentes.pop(savepoint, [])
        if eventos:
            pendentes.setdefault(savepoint.parent, []).extend(eventos)


@event.listens_for(Session, "after_transaction_end")
def _descartar_auditoria_da_transacao(db: Session, transacao: SessionTransaction) -> None:
    pendentes = db.info.get(_PENDENTES)
    if pendentes is not None:
        pendentes.pop(transacao, None)
        if not pendentes:
            db.info.pop(_PENDENTES)


def serialize_entity(entity: object) -> dict[str, Any]:
    """Serializa um modelo para diff, ignorando campos não JSON-safe.

    ## 🚨 Por que há uma lista de exclusão

    **O diff é permanente.** A auditoria é encadeada por hash: uma linha
    gravada não pode ser editada nem apagada sem quebrar a corrente. Isso é o
    que dá valor ao registro — e é o que torna um segredo vazado nele
    **irrecuperável**.

    Guardar o antes e o depois de `chave_cifrada` parece inofensivo (é o valor
    cifrado), mas é errado por dois motivos:

    1. **Não é o dado, é o rastro.** O operador não tem como ler a chave ali
       para conferir nada — o diff só acumula ruído.
    2. **A exceção vira a regra.** No dia em que alguém adicionar um campo
       `chave` em claro, ele entra no diff automaticamente — e aí o vazamento
       é permanente. A lista protege o campo de hoje **e o de amanhã**.

    O nome do campo continua aparecendo com o marcador `<protegido>`, para o
    registro dizer **que algo mudou** sem dizer o quê.
    """
    out: dict[str, Any] = {}
    for col in entity.__table__.columns:  # type: ignore[attr-defined]
        if col.name in CAMPOS_PROTEGIDOS:
            out[col.name] = "<protegido>"
            continue
        out[col.name] = json_safe(getattr(entity, col.name))
    return out

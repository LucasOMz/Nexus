"""Integração com o OCS Inventory (Administração → OCS).

Somente administrador. O token da API é gravado **cifrado** (mesmo mecanismo da
senha do AD) e nunca volta em claro para a tela.
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.cripto import cifrar, esta_cifrado
from app.core.deps import require_admin
from app.database import get_db
from app.models.core import Planta, Usuario
from app.models.ocs import ConfiguracaoOCS, SincronizacaoOCS
from app.services import ocs_service
from app.services.audit_service import audit
from app.services.config_service import obter_config_ocs
from app.services.ocs_sync import sincronizar

router = APIRouter(prefix="/ocs", tags=["ocs"])


class OCSUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ativo: bool | None = None
    servidor: str | None = None
    # Vazio = mantém o token atual.
    token: str | None = None
    verificar_ssl: bool | None = None
    timeout_s: int | None = Field(default=None, ge=5, le=300)

    sync_automatica: bool | None = None
    sync_intervalo_minutos: int | None = Field(default=None, ge=5, le=10080)  # 5 min a 7 dias

    criar_novos: bool | None = None
    atualizar_existentes: bool | None = None
    ignorar_sem_serial: bool | None = None
    dominio_padrao: str | None = None
    status_padrao: str | None = None
    filtrar_hostname: str | None = None

    # [{"prefixo": "BNT-", "planta_id": 2}, ...]
    regras_planta: list[dict] | None = None


class RegraPlanta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefixo: str = Field(min_length=1, max_length=40)
    planta_id: int


def _serializar(cfg: ConfiguracaoOCS) -> dict[str, Any]:
    regras = []
    if cfg.regras_planta:
        try:
            regras = json.loads(cfg.regras_planta)
        except (ValueError, TypeError):
            regras = []

    return {
        "ativo": cfg.ativo,
        "servidor": cfg.servidor,
        "token_definido": bool(cfg.token),
        "token_cifrado": esta_cifrado(cfg.token),
        "verificar_ssl": cfg.verificar_ssl,
        "timeout_s": cfg.timeout_s,
        "sync_automatica": cfg.sync_automatica,
        "sync_intervalo_minutos": cfg.sync_intervalo_minutos,
        "criar_novos": cfg.criar_novos,
        "atualizar_existentes": cfg.atualizar_existentes,
        "ignorar_sem_serial": cfg.ignorar_sem_serial,
        "dominio_padrao": cfg.dominio_padrao,
        "status_padrao": cfg.status_padrao,
        "filtrar_hostname": cfg.filtrar_hostname,
        "regras_planta": regras,
        "ultimo_teste_ok": cfg.ultimo_teste_ok,
        "ultimo_teste_msg": cfg.ultimo_teste_msg,
        "ultima_sync_em": cfg.ultima_sync_em,
        "ultima_sync_resumo": cfg.ultima_sync_resumo,
    }


@router.get("/config")
def ler_config(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    return _serializar(obter_config_ocs(db))


@router.put("/config")
def salvar_config(
    body: OCSUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    """Grava a configuração. Só os campos enviados são alterados."""
    cfg = obter_config_ocs(db)
    dados = body.model_dump(exclude_unset=True)

    # O token é o único campo cifrado.
    if "token" in dados:
        token = dados.pop("token")
        cfg.token = cifrar(token) if token else None

    if "regras_planta" in dados:
        regras = dados.pop("regras_planta") or []
        validadas = []
        for r in regras:
            padrao = (r.get("prefixo") or r.get("padrao") or "").strip()
            planta_id = r.get("planta_id")
            tipo = (r.get("tipo") or "comeca_com").lower()
            if not padrao or planta_id is None:
                continue
            if tipo not in ("comeca_com", "contem", "regex"):
                raise HTTPException(400, f"Tipo de comparação inválido: {tipo}.")
            if tipo == "regex":
                try:
                    re.compile(padrao)
                except re.error as e:
                    raise HTTPException(400, f"Expressão regular inválida em '{padrao}': {e}") from e
            if not db.get(Planta, planta_id):
                raise HTTPException(400, f"Planta {planta_id} não encontrada.")
            validadas.append({"prefixo": padrao[:120], "tipo": tipo, "planta_id": int(planta_id)})
        cfg.regras_planta = json.dumps(validadas, ensure_ascii=False) if validadas else None

    if dados.get("servidor"):
        dados["servidor"] = dados["servidor"].strip().rstrip("/")

    for campo, valor in dados.items():
        setattr(cfg, campo, valor)

    audit(db, user, "ocs_config", "integracao", None,
          ip=request.client.host if request.client else None,
          diff={"campos": sorted(body.model_dump(exclude_unset=True).keys())})
    db.commit()
    return _serializar(cfg)


@router.post("/testar")
def testar(
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    """Testa endereço e token contra o servidor do OCS."""
    cfg = obter_config_ocs(db)
    ok, mensagem = ocs_service.testar_conexao(cfg)

    cfg.ultimo_teste_ok = mensagem[:40] if ok else None
    cfg.ultimo_teste_msg = mensagem
    audit(db, user, "ocs_teste", "integracao", None,
          ip=request.client.host if request.client else None,
          diff={"ok": ok, "mensagem": mensagem[:120]})
    db.commit()
    return {"ok": ok, "mensagem": mensagem}


@router.post("/simular")
def simular(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Mostra o que a sincronização faria, **sem gravar nada**."""
    return sincronizar(db, obter_config_ocs(db), simular=True)


@router.post("/sincronizar")
def executar(
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    """Executa a sincronização de verdade."""
    cfg = obter_config_ocs(db)
    if not cfg.ativo:
        raise HTTPException(400, "Ative a integração antes de sincronizar.")
    return sincronizar(db, cfg, simular=False, origem="manual", usuario=user)


@router.get("/historico")
def historico(
    limite: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    itens = (
        db.query(SincronizacaoOCS)
        .order_by(SincronizacaoOCS.id.desc())
        .limit(limite)
        .all()
    )
    return {
        "total": len(itens),
        "itens": [{
            "id": i.id,
            "origem": i.origem,
            "sucesso": i.sucesso,
            "novas": i.novas,
            "atualizadas": i.atualizadas,
            "ignoradas": i.ignoradas,
            "sem_planta": i.sem_planta,
            "erros": i.erros,
            "duracao_ms": i.duracao_ms,
            "mensagem": i.mensagem,
            "criado_em": (i.created_at.isoformat() + ("" if i.created_at.tzinfo else "+00:00")) if i.created_at else None,
        } for i in itens],
    }


@router.get("/previa-regras")
def previa_regras(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Quantas máquinas do OCS casariam com cada regra de planta.

    Serve para conferir as regras **antes** de sincronizar — evita descobrir
    depois que dezenas de máquinas foram para a planta errada.
    """
    cfg = obter_config_ocs(db)
    if not cfg.ativo:
        raise HTTPException(400, "Ative a integração para consultar o OCS.")

    regras = []
    if cfg.regras_planta:
        try:
            regras = json.loads(cfg.regras_planta)
        except (ValueError, TypeError):
            regras = []

    try:
        maquinas = ocs_service.listar_maquinas(cfg)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Não foi possível consultar o OCS: {e}") from e

    plantas = {p.id: p.sigla for p in db.query(Planta).all()}
    contagem = {r["prefixo"]: 0 for r in regras if r.get("prefixo")}
    sem_regra = 0
    exemplos_sem_regra: list[str] = []

    for m in maquinas:
        hostname = (m.get("NAME") or m.get("name") or "").strip()
        if not hostname:
            continue
        # Usa a MESMA função da sincronização, para a contagem na tela nunca
        # discordar do que a importação realmente faz.
        regra = ocs_service.regra_que_casa(regras, hostname)
        if regra is None:
            sem_regra += 1
            if len(exemplos_sem_regra) < 5:
                exemplos_sem_regra.append(hostname)
            continue
        chave = (regra.get("prefixo") or regra.get("padrao") or "").strip()
        contagem[chave] = contagem.get(chave, 0) + 1

    return {
        "total_ocs": len(maquinas),
        "por_regra": [
            {
                "prefixo": p,
                "tipo": next((r.get("tipo") or "comeca_com" for r in regras
                              if (r.get("prefixo") or r.get("padrao")) == p), "comeca_com"),
                "planta_id": next((r["planta_id"] for r in regras if (r.get("prefixo") or r.get("padrao")) == p), None),
                "planta_sigla": plantas.get(next((r["planta_id"] for r in regras if (r.get("prefixo") or r.get("padrao")) == p), None)),
                "maquinas": n,
            }
            for p, n in contagem.items()
        ],
        "sem_regra": sem_regra,
        "exemplos_sem_regra": exemplos_sem_regra,
    }

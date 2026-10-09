"""Reconciliação do inventário com o OCS — endpoint de leitura.

Só lê. A regra é: **nada é alterado automaticamente**. A tela aponta o que
divergiu; quem decide o que fazer é a pessoa. Criar ativos sozinho a partir da
rede, ou apagar os que sumiram, seria transformar um relatório de conferência
numa fonte de surpresas no inventário.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.planta import aplicar_filtro, planta_ativa
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.models.enums import Dominio
from app.models.ocs import ConfiguracaoOCS
from app.models.ti import AtivoTI
from app.services import ocs_service
from app.services.ocs_reconciliacao import DIAS_PADRAO, comparar

log = logging.getLogger("app.ocs.reconciliacao")

router = APIRouter(prefix="/admin/ocs", tags=["ocs"])


def _inventario(db: Session, planta_id: int | None) -> list[dict]:
    """Ativos de TI com a ficha técnica, no formato que a comparação espera."""
    q = (
        db.query(Ativo, AtivoTI)
        .outerjoin(AtivoTI, AtivoTI.ativo_id == Ativo.id)
        .filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.TI)
    )
    q = aplicar_filtro(q, Ativo, planta_id)

    saida = []
    for ativo, ficha in q.all():
        saida.append({
            "ativo_id": ativo.id,
            "patrimonio": ativo.patrimonio,
            "hostname": ficha.hostname if ficha else None,
            "ip": ficha.ip if ficha else None,
            "mac_address": ficha.mac_address if ficha else None,
            "so": ficha.so if ficha else None,
            "ocs_id": ficha.ocs_id if ficha else None,
            "ocs_ultimo_contato": getattr(ficha, "ocs_ultimo_contato", None) if ficha else None,
        })
    return saida


@router.get("/reconciliacao")
def reconciliacao(
    dias: int = Query(default=DIAS_PADRAO, ge=1, le=365,
                      description="Dias sem contato para considerar o ativo sumido"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
    planta_id: int | None = Depends(planta_ativa),
):
    """Compara o inventário de TI com o que o OCS enxerga na rede.

    Devolve três listas:

    * **fantasmas** — na rede, fora do inventário (candidatos a cadastro)
    * **perdidos** — no inventário, sem contato há mais de `dias`
    * **divergencias** — casados, mas com hostname/IP/MAC/SO diferentes

    Se o OCS não responder, ainda devolve o lado do inventário e explica o
    motivo em `aviso` — um relatório parcial é mais útil que um erro.
    """
    inventario = _inventario(db, planta_id)
    cfg = db.query(ConfiguracaoOCS).first()

    dispositivos: list[dict] = []
    aviso = None

    if cfg is None or not cfg.ativo:
        aviso = "O OCS não está configurado — mostrando apenas o lado do inventário."
    else:
        try:
            maquinas = ocs_service.listar_maquinas(cfg)
            for m in maquinas or []:
                dados = ocs_service.mapear(m, {}) if isinstance(m, dict) else {}
                # `mapear` pode devolver nomes diferentes dos da ficha técnica;
                # normalizamos aqui para a comparação não depender disso.
                dispositivos.append({
                    "ocs_id": dados.get("ocs_id") or m.get("id") or m.get("ID"),
                    "hostname": dados.get("hostname") or m.get("name") or m.get("NOME"),
                    "ip": dados.get("ip") or m.get("ipAddress") or m.get("IP"),
                    "mac_address": dados.get("mac_address") or m.get("macaddr") or m.get("MAC"),
                    "so": dados.get("so") or m.get("osName"),
                    "numero_serie": dados.get("numero_serie") or m.get("serial") or m.get("SSN"),
                })
        except Exception as e:  # noqa: BLE001 — o relatório não pode morrer por causa da rede
            log.warning("Falha ao consultar o OCS: %s", e)
            aviso = (
                "Não foi possível consultar o OCS agora "
                f"({type(e).__name__}). Mostrando apenas o lado do inventário."
            )

    resultado = comparar(inventario, dispositivos, dias_sem_contato=dias)
    resultado["aviso"] = aviso
    resultado["ocs_configurado"] = bool(cfg and cfg.ativo)
    return resultado


@router.get("/reconciliacao/fantasmas")
def listar_fantasmas(
    dias: int = Query(default=DIAS_PADRAO, ge=1, le=365),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
    planta_id: int | None = Depends(planta_ativa),
):
    """Só os fantasmas — atalho para quem vai cadastrar os que faltam."""
    cfg = db.query(ConfiguracaoOCS).first()
    if cfg is None or not cfg.ativo:
        raise HTTPException(400, "O OCS não está configurado.")
    dados = reconciliacao(dias=dias, db=db, _=_, planta_id=planta_id)
    return {"fantasmas": dados["fantasmas"], "total": len(dados["fantasmas"])}

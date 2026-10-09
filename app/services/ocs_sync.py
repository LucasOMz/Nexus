"""Sincronização: traz o parque do OCS para o inventário de ativos.

Regras que valem a pena ter em mente ao ler este arquivo:

* **O OCS não manda no que é do sistema.** Planta, responsável, garantia, valor
  e patrimônio nunca são sobrescritos por uma sincronização.
* **Casamento por número de série**, com o patrimônio como reserva. É o que
  permite reconhecer máquinas já cadastradas antes da integração.
* **Simulação antes de gravar.** `simular=True` percorre tudo e devolve o que
  aconteceria, sem tocar no banco.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.core import Ativo, Planta, StatusAtivo
from app.models.ocs import SincronizacaoOCS
from app.models.ti import AtivoTI
from app.services import ocs_service
from app.services.audit_service import audit


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _regras(cfg) -> list[dict]:
    """Lê a lista de regras de planta, ignorando um JSON inválido."""
    if not cfg.regras_planta:
        return []
    try:
        dados = json.loads(cfg.regras_planta)
        return dados if isinstance(dados, list) else []
    except (ValueError, TypeError):
        return []


def _normalizar_serie(valor: str | None) -> str | None:
    """Número de série sem espaços e em maiúsculas.

    Fabricantes variam a caixa e às vezes inserem espaços; comparar cru faria
    duas leituras da mesma máquina parecerem diferentes.
    """
    if not valor:
        return None
    limpo = "".join(str(valor).split()).upper()
    return limpo or None


def _serial_placeholder(serie: str | None) -> bool:
    """Detecta números de série que não identificam nada.

    Placas genéricas e máquinas virtuais devolvem textos fixos. Tratá-los como
    identificador faria dezenas de máquinas colidirem num registro só.

    Normaliza internamente para não depender de o chamador já ter limpado.
    """
    serie = _normalizar_serie(serie)
    if not serie:
        return True
    lixo = {
        "TOBEFILLEDBYO.E.M.", "TOBEFILLEDBYOEM", "DEFAULTSTRING", "SYSTEMSERIALNUMBER",
        "NONE", "NA", "N/A", "00000000", "NOTSPECIFIED", "INVALID", "CHASSISNUMBER",
    }
    if serie.upper() in lixo:
        return True
    # Placeholders de virtualização, que se repetem em todas as VMs.
    return serie.upper().startswith(("VMWARE-", "VIRTUALBOX", "XEN", "QEMU", "PRL"))


def _precisa_atualizar(ativo: Ativo, dados: dict[str, Any]) -> dict[str, Any]:
    """Quais campos técnicos realmente mudaram (evita escrita desnecessária)."""
    mudancas = {}
    for campo in ("modelo", "marca"):
        novo = dados.get(campo)
        if novo and getattr(ativo, campo) != novo:
            mudancas[campo] = novo
    return mudancas


def _aplicar_ti(ativo: Ativo, dados: dict[str, Any], db: Session) -> AtivoTI:
    """Cria ou atualiza a ficha técnica do ativo."""
    ti = ativo.ti or AtivoTI(ativo_id=ativo.id)
    if ativo.ti is None:
        db.add(ti)

    for campo in ("hostname", "mac_address", "ip", "so", "cpu", "ram_gb", "armazenamento_gb"):
        novo = dados.get(campo)
        if novo not in (None, ""):
            setattr(ti, campo, novo)

    if dados.get("ocs_id") is not None:
        ti.ocs_id = str(dados["ocs_id"])[:40]
    if dados.get("ultimo_contato"):
        ti.ocs_ultimo_contato = str(dados["ultimo_contato"])[:40]
    return ti


def _registrar_falha(db: Session, cfg, mensagem: str, duracao_ms: int, origem: str) -> None:
    """Guarda a falha no histórico e nos campos de aviso do sino.

    Nunca deixa uma exceção escapar: perder o aviso é ruim, mas derrubar a
    sincronização por causa dele seria pior.
    """
    try:
        db.rollback()
        db.add(SincronizacaoOCS(
            origem=origem, sucesso=False, erros=1, duracao_ms=duracao_ms,
            mensagem=mensagem[:500],
        ))
        cfg.ultimo_erro_em = _agora()
        cfg.ultimo_erro_msg = mensagem[:500]
        cfg.falhas_consecutivas = int(cfg.falhas_consecutivas or 0) + 1
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _status_valido(valor: str | None) -> StatusAtivo:
    try:
        return StatusAtivo(valor)
    except (ValueError, TypeError):
        return StatusAtivo.ESTOQUE


def sincronizar(
    db: Session,
    cfg,
    *,
    simular: bool = False,
    origem: str = "manual",
    usuario=None,
) -> dict[str, Any]:
    """Executa (ou simula) a sincronização com o OCS.

    Devolve um resumo com quantas máquinas seriam criadas, atualizadas ou
    ignoradas — e por quê.
    """
    inicio = time.monotonic()
    resumo: dict[str, Any] = {
        "novas": 0, "atualizadas": 0, "ignoradas": 0,
        "sem_planta": 0, "erros": 0,
        "detalhes": [], "avisos": [],
    }

    if not cfg.ativo:
        return {"sucesso": False, "mensagem": "A integração está desativada.", **resumo}
    if simular:
        origem = "simulacao"

    regras = _regras(cfg)
    plantas_validas = {p.id for p in db.query(Planta).all()}
    filtro = ocs_service.compilar_filtro(cfg.filtrar_hostname)
    if cfg.filtrar_hostname and filtro is None:
        resumo["avisos"].append(f"O filtro de hostname '{cfg.filtrar_hostname}' é inválido e foi ignorado.")

    try:
        maquinas = ocs_service.listar_maquinas(cfg)
    except Exception as e:  # noqa: BLE001 — qualquer falha vira mensagem para a tela
        # A falha também entra no histórico e alimenta o aviso no sino. Antes
        # ela só aparecia na tela de quem clicasse em "Sincronizar".
        resumo["erros"] = 1
        resumo["duracao_ms"] = int((time.monotonic() - inicio) * 1000)
        mensagem = f"Não foi possível consultar o OCS: {e}"
        if not simular:
            _registrar_falha(db, cfg, mensagem, resumo["duracao_ms"], origem)
        return {"sucesso": False, "mensagem": mensagem, **resumo}

    for maquina in maquinas:
        try:
            det = ocs_service.detalhes(cfg, maquina.get("ID") or maquina.get("id"))
            dados = ocs_service.mapear(maquina, det)
        except Exception as e:  # noqa: BLE001
            resumo["erros"] += 1
            resumo["detalhes"].append({"hostname": maquina.get("NAME"), "acao": "erro", "motivo": str(e)[:120]})
            continue

        hostname = dados.get("hostname")
        if filtro is not None and hostname and not filtro.search(hostname):
            resumo["ignoradas"] += 1
            continue

        serie = _normalizar_serie(dados.get("numero_serie"))
        # Série sem valor de identificação é descartada — mas a máquina ainda
        # pode ser reconhecida pelo patrimônio logo abaixo. Só desistimos dela
        # na hora de CRIAR um cadastro novo.
        serial_ruim = _serial_placeholder(serie)
        if serial_ruim:
            serie = None

        # --- Casamento: série primeiro, patrimônio depois ---
        ativo = None
        if serie:
            ativo = (
                db.query(Ativo)
                .filter(Ativo.numero_serie == serie, Ativo.deleted_at.is_(None))
                .first()
            )
        if ativo is None and hostname:
            ativo = (
                db.query(Ativo)
                .filter(Ativo.patrimonio == hostname, Ativo.deleted_at.is_(None))
                .first()
            )

        planta_id = ocs_service.planta_por_hostname(regras, hostname)

        if ativo is not None:
            # --- Já existe: atualiza só o técnico ---
            # Vale mesmo quando o serial é ruim: completar uma ficha existente é
            # seguro e útil. O que não pode é CRIAR cadastro sem identificação.
            if not cfg.atualizar_existentes:
                resumo["ignoradas"] += 1
                continue
            mudancas = _precisa_atualizar(ativo, dados)
            if not simular:
                for campo, valor in mudancas.items():
                    setattr(ativo, campo, valor)
                if serie and not ativo.numero_serie:
                    ativo.numero_serie = serie
                _aplicar_ti(ativo, dados, db)
            resumo["atualizadas"] += 1
            resumo["detalhes"].append({
                "hostname": hostname, "patrimonio": ativo.patrimonio,
                "acao": "atualizada", "planta": None,
            })
            continue

        # --- Máquina nova ---
        if serial_ruim and cfg.ignorar_sem_serial:
            resumo["ignoradas"] += 1
            resumo["detalhes"].append({
                "hostname": hostname, "acao": "ignorada",
                "motivo": "sem número de série utilizável",
            })
            continue

        if not cfg.criar_novos:
            resumo["ignoradas"] += 1
            resumo["detalhes"].append({"hostname": hostname, "acao": "ignorada", "motivo": "criação desativada"})
            continue

        if planta_id not in plantas_validas:
            planta_id = None
        if planta_id is None:
            resumo["sem_planta"] += 1

        if simular:
            resumo["novas"] += 1
            resumo["detalhes"].append({
                "hostname": hostname,
                "patrimonio": hostname,
                "acao": "nova",
                "planta": planta_id,
                "sem_planta": planta_id is None,
                "serie": serie,
                "modelo": dados.get("modelo"),
            })
            continue

        novo = Ativo(
            planta_id=planta_id,
            dominio=cfg.dominio_padrao or "ti",
            tipo_item="ativo",
            # O patrimônio fica com o hostname até alguém digitar o número real.
            patrimonio=(hostname or serie or f"OCS-{dados.get('ocs_id')}")[:60],
            numero_serie=serie,
            modelo=dados.get("modelo"),
            marca=dados.get("marca"),
            status=_status_valido(cfg.status_padrao),
        )
        db.add(novo)
        db.flush()
        _aplicar_ti(novo, dados, db)
        resumo["novas"] += 1
        resumo["detalhes"].append({
            "hostname": hostname, "patrimonio": novo.patrimonio,
            "acao": "nova", "planta": planta_id, "sem_planta": planta_id is None,
        })

    resumo["duracao_ms"] = int((time.monotonic() - inicio) * 1000)

    if not simular:
        # Registra no histórico e na auditoria.
        try:
            db.add(SincronizacaoOCS(
                origem=origem, sucesso=True,
                novas=resumo["novas"], atualizadas=resumo["atualizadas"],
                ignoradas=resumo["ignoradas"], sem_planta=resumo["sem_planta"],
                erros=resumo["erros"], duracao_ms=resumo["duracao_ms"],
                mensagem=f"{len(maquinas)} máquina(s) no OCS",
            ))
            if usuario is not None:
                audit(db, usuario, "ocs_sincronizado", "integracao", None,
                      diff={"novas": resumo["novas"], "atualizadas": resumo["atualizadas"],
                            "origem": origem})
            db.commit()
        except Exception:  # noqa: BLE001 — o histórico não pode derrubar a sincronização
            db.rollback()

        cfg.ultima_sync_em = _agora()
        cfg.ultima_sync_resumo = (
            f"{resumo['novas']} nova(s), {resumo['atualizadas']} atualizada(s), "
            f"{resumo['ignoradas']} ignorada(s)"
        )
        # Deu certo: o aviso de falha sai do sino.
        cfg.falhas_consecutivas = 0
        cfg.ultimo_erro_msg = None
        db.commit()
        resumo["sucesso"] = True
        resumo["mensagem"] = cfg.ultima_sync_resumo
    else:
        resumo["sucesso"] = True
        resumo["mensagem"] = (
            f"Simulação: {resumo['novas']} nova(s), {resumo['atualizadas']} atualizada(s), "
            f"{resumo['ignoradas']} ignorada(s). Nada foi gravado."
        )

    return resumo

"""Agendador da sincronização automática com o OCS.

**Por que existe:** o sistema é todo guiado por ação do usuário — nada acontece
sozinho. A integração com o OCS é o primeiro recurso que precisa rodar em
intervalos, porque o parque de máquinas muda sem ninguém avisar.

**Como funciona:** uma linha de execução em segundo plano, iniciada junto com a
aplicação, que dorme e acorda conferindo se já passou o intervalo configurado.

**Limitação honesta:** rodar dentro do processo significa **uma execução por
processo**. O `run.sh` sobe um único processo uvicorn, então não há duplicação
hoje. Se um dia o sistema subir com vários processos (`--workers`), cada um
dispararia sua própria sincronização — nesse cenário, o certo é desligar esta
opção e usar o agendador do sistema operacional (cron / Tarefa Agendada).
"""
from __future__ import annotations

import logging
import threading
import time

from app.database import SessionLocal
from app.services.config_service import obter_config_ocs
from app.services.ocs_sync import sincronizar

log = logging.getLogger(__name__)

# De quanto em quanto tempo o agendador ACORDA para conferir se já é hora.
# Não é o intervalo da sincronização — esse vem da configuração.
PASSO_DE_VERIFICACAO_S = 60

_parar = threading.Event()
_thread: threading.Thread | None = None


def _ultima_execucao_ts(db) -> float | None:
    """Momento da última sincronização (a partir do texto ISO gravado)."""
    from datetime import datetime

    cfg = obter_config_ocs(db)
    if not cfg.ultima_sync_em:
        return None
    try:
        return datetime.fromisoformat(cfg.ultima_sync_em).timestamp()
    except (ValueError, TypeError):
        return None


def _laco() -> None:
    while not _parar.is_set():
        _parar.wait(PASSO_DE_VERIFICACAO_S)
        if _parar.is_set():
            break

        db = SessionLocal()
        try:
            cfg = obter_config_ocs(db)
            if not (cfg.ativo and cfg.sync_automatica):
                continue

            intervalo_s = max(5, int(cfg.sync_intervalo_minutos or 60)) * 60
            ultima = _ultima_execucao_ts(db)
            agora = time.time()

            if ultima is not None and (agora - ultima) < intervalo_s:
                continue

            log.info("OCS: iniciando sincronização automática")
            resultado = sincronizar(db, cfg, simular=False, origem="automatico")
            log.info("OCS: %s", resultado.get("mensagem"))
        except Exception:  # noqa: BLE001 — o laço nunca pode morrer por um erro
            log.exception("OCS: falha na sincronização automática")
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close()


def iniciar() -> None:
    """Liga o agendador (chamado na subida da aplicação)."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _parar.clear()
    _thread = threading.Thread(target=_laco, name="ocs-agendador", daemon=True)
    _thread.start()
    log.info("OCS: agendador iniciado (verificação a cada %ss)", PASSO_DE_VERIFICACAO_S)


def parar() -> None:
    """Desliga o agendador (usado no encerramento e nos testes)."""
    _parar.set()


def esta_rodando() -> bool:
    return _thread is not None and _thread.is_alive()

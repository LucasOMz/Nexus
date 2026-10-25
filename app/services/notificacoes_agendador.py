"""Agendador das notificações por e-mail.

## Por que uma thread, e não um cron do sistema

O cron exigiria um segundo processo, um comando para manter em sincronia com o
código, e um lugar a mais onde a configuração se perde. Uma thread no processo
que já existe não tem nada disso — e o intervalo é uma variável de ambiente.

A desvantagem conhecida: **com mais de uma réplica, cada uma enviaria**. Como
o `EmailEnviado` funciona como trava de repetição e o envio grava antes de
considerar concluído, a duplicata é improvável, mas não impossível. Com uma réplica
— o caso normal deste sistema — não existe o problema.

## A regra que veio do OCS, e vale mais aqui

**Falha no agendador não pode derrubar a aplicação.** Já aconteceu neste
projeto: `can't start new thread` no boot virou laço de reinício no container,
e o sistema inteiro ficou fora do ar por causa de um recurso acessório.

O mesmo vale dentro do laço: uma falha de SMTP é registrada e o ciclo
continua — a próxima tentativa tenta de novo.
"""
from __future__ import annotations

import logging
import threading

from app.config import settings
from app.database import SessionLocal
from app.services import notificacoes_email

log = logging.getLogger("app.notificacoes")

_parar = threading.Event()
_thread: threading.Thread | None = None

# Cinco minutos é o compasso: avisos são estado, não eventos em tempo real.
# Mais frequente que isso só gasta consulta para descobrir que nada mudou.
INTERVALO_PADRAO = 300


def _intervalo() -> int:
    try:
        return max(60, int(settings.smtp_intervalo or INTERVALO_PADRAO))
    except (TypeError, ValueError):
        return INTERVALO_PADRAO


def _laco() -> None:
    log.info("E-mail: agendador iniciado (verificação a cada %ss)", _intervalo())

    while not _parar.wait(_intervalo()):
        db = SessionLocal()
        try:
            resultado = notificacoes_email.despachar(db)
            if resultado.enviados or resultado.falhas:
                log.info(
                    "E-mail: %s enviado(s), %s falha(s), %s pulado(s)",
                    resultado.enviados, resultado.falhas, resultado.pulados,
                )
        except Exception:  # noqa: BLE001
            # Um ciclo ruim não pode encerrar o agendador: o próximo tenta de
            # novo, e o sistema segue servindo normalmente.
            log.exception("E-mail: falha no ciclo de envio")
        finally:
            db.close()


def iniciar() -> None:
    """Sobe a thread. Idempotente: chamar duas vezes não cria duas."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _parar.clear()
    _thread = threading.Thread(target=_laco, name="notificacoes-email", daemon=True)
    _thread.start()


def parar() -> None:
    """Sinaliza a parada e espera a thread terminar."""
    global _thread
    _parar.set()
    if _thread is not None:
        _thread.join(timeout=5)
        _thread = None

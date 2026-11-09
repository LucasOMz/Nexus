"""O boot não pode morrer por causa de um agendador de fundo.

## O que aconteceu na implantação

O container subia e entrava em **laço de reinício**:

    File "app/services/ocs_agendador.py", line 88, in iniciar
        _thread.start()
    RuntimeError: can't start new thread

    ERROR: Application startup failed. Exiting.

O Portainer mostrava `restarting`, a aplicação nunca respondia, e a tela
ficava fora do ar.

**A correção precisou valer para todo agendador**, não só para o do OCS — que
desde então foi removido do sistema. O de **notificações** continua, e é ele
que este teste cobre hoje.

## Por que é defeito de projeto, e não só de ambiente

Um agendador é **conveniência**: a aplicação serve tudo sem ele, e o operador
ainda dispara à mão.

**Recurso que não conseguiu subir não pode virar indisponibilidade total.**
Quem perde a função perde uma função; quem perde o boot perde o sistema.

## Por que o teste existe

O erro depende do ambiente — limite de threads no container. **Não dá para
reproduzir num teste comum.** Então o teste simula a exceção exata e
verifica que o boot continua.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch


class TestAgendadorNaoDerrubaOBoot:
    def test_falha_ao_iniciar_nao_impede_a_subida(self):
        """O caso exato do container: `can't start new thread`."""
        import app.main as m

        async def sobe():
            async with m.lifespan(m.app):
                return "subiu"

        with patch.object(
            m.notificacoes_agendador, "iniciar",
            side_effect=RuntimeError("can't start new thread"),
        ):
            assert asyncio.run(sobe()) == "subiu"

    def test_qualquer_erro_no_agendador_e_contido(self):
        """Não só o de thread: qualquer falha ao iniciar é contida.

        O agendador abre sessão de banco e lê configuração — e pode falhar
        por banco fora do ar, permissão, o que for. Nenhuma dessas razões
        justifica deixar o sistema inteiro sem subir.
        """
        import app.main as m

        async def sobe():
            async with m.lifespan(m.app):
                return "subiu"

        for erro in (RuntimeError("x"), OSError("sem recurso"), Exception("qualquer")):
            with patch.object(m.notificacoes_agendador, "iniciar", side_effect=erro):
                assert asyncio.run(sobe()) == "subiu", f"derrubou com {erro!r}"

    def test_o_agendador_ainda_inicia_quando_da_certo(self):
        """A correção não pode ter desligado o agendador.

        Trocar "quebra o boot" por "nunca funciona" seria pior: o defeito
        sumiria do log e os avisos agendados parariam sem aviso.
        """
        import app.main as m

        chamadas = []

        async def sobe():
            async with m.lifespan(m.app):
                return "subiu"

        with patch.object(m.notificacoes_agendador, "iniciar",
                          side_effect=lambda: chamadas.append(1)):
            asyncio.run(sobe())

        # Só conta se o agendador está ligado na configuração do teste.
        if m.settings.scheduler_ativo:
            assert chamadas == [1], "o agendador não foi chamado"

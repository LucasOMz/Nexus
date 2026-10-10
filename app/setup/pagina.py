"""Página do assistente de configuração inicial.

Em modo setup, o sistema **não** serve o PWA normal: não haveria banco para ele
funcionar. Esta página é independente — HTML, CSS e JS próprios — e por isso
continua funcionando mesmo sem nenhuma conexão configurada.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

log = logging.getLogger(__name__)

# Caminho público da página do assistente.
ROTA_PAGINA = "/instalacao"


def montar(app: FastAPI, frontend_dir: Path) -> None:
    """Registra a página do assistente e as rotas que ela consome."""
    pasta = frontend_dir / "setup"

    @app.get(ROTA_PAGINA, include_in_schema=False)
    @app.get(f"{ROTA_PAGINA}/", include_in_schema=False)
    def pagina():
        arquivo = pasta / "index.html"
        if not arquivo.exists():
            return JSONResponse(
                status_code=500,
                content={"detail": f"Página do assistente não encontrada em {arquivo}"},
            )
        return FileResponse(arquivo, media_type="text/html")

    @app.get(f"{ROTA_PAGINA}/{{arquivo:path}}", include_in_schema=False)
    def recurso(arquivo: str):
        # Impede sair da pasta com "../" — o caminho vem da URL.
        alvo = (pasta / arquivo).resolve()
        if not str(alvo).startswith(str(pasta.resolve())) or not alvo.is_file():
            return JSONResponse(status_code=404, content={"detail": "Recurso não encontrado."})
        return FileResponse(alvo)

    @app.get("/icons/{arquivo:path}", include_in_schema=False)
    def icone(arquivo: str):
        """Ícones do sistema: favicon da aba e logotipo do assistente.

        O modo setup **não** monta a pasta do PWA — não haveria banco para ela
        funcionar. Mas a aba do navegador e o logo da página precisam da
        imagem, e sem esta rota `/icons/...` respondia 404 justamente na tela
        em que o logo mais aparece.
        """
        raiz = (frontend_dir / "icons").resolve()
        alvo = (raiz / arquivo).resolve()
        # Mesma proteção de "../" da rota acima.
        if not str(alvo).startswith(str(raiz)) or not alvo.is_file():
            return JSONResponse(status_code=404, content={"detail": "Ícone não encontrado."})
        return FileResponse(alvo)

    @app.get("/", include_in_schema=False)
    def raiz():
        """A raiz recebe quem abre o endereço do sistema.

        Antes devolvia um JSON — informativo, mas quem chega pelo navegador via
        uma linha de texto técnico. Agora abre uma tela de boas-vindas no padrão
        do sistema, com o caminho para a configuração inicial.

        Nada se perde para uso programático: `/setup/estado` continua devolvendo
        o estado em JSON.
        """
        arquivo = pasta / "boas-vindas.html"
        if arquivo.exists():
            return FileResponse(arquivo, media_type="text/html")
        # Sem a página, ao menos o endereço do assistente.
        return JSONResponse({
            "sistema": "não instalado",
            "mensagem": "Abra o assistente de configuração inicial para começar.",
            "assistente": ROTA_PAGINA,
        })

    log.info("Modo setup: assistente disponível em %s", ROTA_PAGINA)

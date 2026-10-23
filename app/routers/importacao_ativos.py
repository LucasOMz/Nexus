"""Rotas da importacao de ativos.

## Por que as rotas ficam em arquivo proprio

`app/routers/ativos.py` ja tem o CRUD inteiro. Importacao tem ciclo de vida
diferente — quatro etapas, exige administrador, e **cria backup**. Misturar
as duas coisas faria o arquivo mais longo do sistema ficar pior ainda de
navegar.

## `admin` em todas

Importacao cria ativos em lote e dispara backup. Nao e operacao de rotina, e
nao deve estar disponivel para quem so cadastra.

## O arquivo viaja duas vezes, de proposito

`/analisar` e `/confirmar` recebem o MESMO arquivo. Parece redundante enviar
duas vezes, mas e o que garante que a previsao e a gravacao partem do mesmo
conteudo: entre uma e outra alguem pode ter cadastrado o patrimonio que a
previa dizia estar livre.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.planta import planta_ativa
from app.database import get_db
from app.models.core import Usuario
from app.services import importar_ativos

router = APIRouter(prefix="/ativos/importar", tags=["importacao de ativos"])

# Teto do arquivo. Um CSV de 100 mil linhas tem poucos MB — o limite existe
# contra engano (subir a planilha inteira em .xlsx) e contra abuso.
TAMANHO_MAX = 20 * 1024 * 1024


@router.get("/colunas")
def colunas(
    dominio: str | None = Query(default=None, description="ti ou impressora"),
    _: Usuario = Depends(require_admin),
) -> dict:
    """As colunas, o que cada uma significa e o que é obrigatório.

    A tela mostra isto **antes** de a pessoa abrir o Excel. Explicar depois
    do arquivo errado chegar não ajuda quem já montou a planilha.

    ## Por que a lista depende do inventário

    As fichas técnicas são diferentes: TI tem `hostname`, `cpu`, `ram_gb`;
    impressora tem `tipo_impressao`, `colorida`, `contador_paginas`. Mostrar
    as duas famílias juntas — como era — fazia quem importa **TI** ver
    colunas de impressora e concluir que os dois inventários são o mesmo.

    Não são: são tabelas de ficha separadas (`ativos_ti`,
    `ativos_impressora`), e uma coluna da outra família é **ignorada** na
    importação.

    ## O que decide o domínio de cada coluna

    O marcador que já existia na descrição — `[TI]` e `[Impressora]`. A coluna
    sem marcador é comum aos dois (`patrimonio`, `modelo`, `valor`…).

    Fosse hoje, a lista teria um campo estruturado em vez de um prefixo em
    prosa. Enquanto o prefixo existir e este filtro o ler, o comportamento é
    o mesmo — e o custo de mudar é baixo quando valer a pena.
    """
    def do_dominio(desc: str) -> str | None:
        if desc.startswith("[Impressora]"):
            return "impressora"
        if desc.startswith("[TI]"):
            return "ti"
        return None

    linhas = []
    for nome, obrig, desc in importar_ativos.COLUNAS:
        alvo = do_dominio(desc)
        if dominio and alvo and alvo != dominio:
            continue
        # O marcador é documentação para quem lê o código; na tela ele
        # poluiria o texto da coluna.
        limpa = desc.replace("[TI] ", "").replace("[Impressora] ", "")
        linhas.append({"nome": nome, "obrigatoria": obrig, "descricao": limpa})

    return {
        "dominio": dominio,
        "colunas": linhas,
        "exemplo": importar_ativos.modelo_texto(),
    }


@router.get("/modelo")
def modelo(_: Usuario = Depends(require_admin)) -> Response:
    """O arquivo de exemplo, pronto para abrir no Excel.

    Vem com duas linhas preenchidas — uma de TI e uma de impressora. Quem abre
    ve o formato certo sem precisar ler instrucao nenhuma.
    """
    return Response(
        content=importar_ativos.modelo_csv(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="modelo-ativos.csv"',
            "Cache-Control": "no-store",
        },
    )


async def _ler(arquivo: UploadFile) -> bytes:
    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "O arquivo está vazio.")
    if len(conteudo) > TAMANHO_MAX:
        raise HTTPException(
            413,
            f"O arquivo tem {len(conteudo) / 1024 / 1024:.1f} MB e o limite é "
            f"{TAMANHO_MAX / 1024 / 1024:.0f} MB. Se for uma planilha do Excel, "
            "salve como CSV antes de enviar.",
        )
    return conteudo


def _serializar(a: importar_ativos.Analise) -> dict:
    """A analise em JSON, para a tela montar a previa."""
    return {
        "erro_geral": a.erro_geral,
        "colunas_faltando": a.colunas_faltando,
        "colunas_desconhecidas": a.colunas_desconhecidas,
        "total": len(a.linhas),
        "validas": len(a.validas),
        "invalidas": len(a.invalidas),
        "linhas": [
            {
                "numero": linha.numero,
                "patrimonio": linha.dados.get("patrimonio"),
                "dominio": getattr(linha.dados.get("dominio"), "value",
                                   linha.dados.get("dominio")),
                "modelo": linha.dados.get("modelo"),
                "marca": linha.dados.get("marca"),
                "status": getattr(linha.dados.get("status"), "value",
                                  linha.dados.get("status")),
                "valor": str(linha.dados["valor"]) if linha.dados.get("valor") is not None else None,
                "foto_id": linha.dados.get("foto_id"),
                "ok": linha.ok,
                "erros": linha.erros,
                "avisos": linha.avisos,
                "criar": linha.criar,
            }
            for linha in a.linhas
        ],
        # O que sera criado no cadastro, somando todas as linhas — e o que a
        # confirmacao precisa destacar antes de gravar.
        "a_criar": sorted({item for linha in a.validas for item in linha.criar}),
    }


@router.post("/analisar")
async def analisar(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
    planta_id: int | None = Depends(planta_ativa),
) -> dict:
    """Le e valida o arquivo **sem gravar nada**.

    E a etapa que torna a importacao reversivel na decisao: quem importa ve
    quantas linhas entram, quais falham e o que sera criado — e desiste ainda
    a tempo.
    """
    conteudo = await _ler(arquivo)
    return _serializar(importar_ativos.analisar(conteudo, db, planta_id))


@router.post("/confirmar")
async def confirmar(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
    planta_id: int | None = Depends(planta_ativa),
) -> dict:
    """Grava o arquivo, **criando um backup antes**.

    Reanalisa em vez de confiar na previa anterior: entre uma etapa e outra o
    mundo muda, e o que precisa entrar e o que e valido **agora**.
    """
    conteudo = await _ler(arquivo)
    resultado = importar_ativos.importar(conteudo, db, planta_id, usuario=user)
    if not resultado.get("ok"):
        # 409: o pedido era valido, o estado do sistema e que nao permite.
        raise HTTPException(409, resultado.get("mensagem", "A importação não foi concluída."))
    return resultado

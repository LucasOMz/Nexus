"""Ponto de entrada da API FastAPI.

Responsabilidades:
- Criar a aplicação, configurar CORS restrito e headers de segurança.
- Registrar todos os routers sob o prefixo /api/v1.
- Servir o frontend (PWA) como arquivos estáticos.
- Health check e inicialização do banco (tabelas + usuário admin).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.config import settings
from app.core.deps import require_module
from app.core.rate_limit import api_limiter, chave_do_cliente
from app.database import SessionLocal, init_db
from app.routers import (
    admin,
    ativos,
    auditoria,
    auth,
    backups,
    banco,
    busca,
    cadastros,
    calendario,
    checklist,
    config_sistema,
    contagens,
    contratos,
    dashboard,
    emprestimos,
    etiquetas,
    financeiro,
    graficos,
    lgpd,
    manutencoes,
    mfa,
    monitor_impressoras,
    movimentacoes,
    notificacoes,
    ocs,
    ocs_reconciliacao,
    plantas,
    produtos,
    qrcode,
    relatorios,
    reportes,
    scanner,
    transferencias,
    zerados,
)
from app.routers import (
    print as print_router,
)
from app.services import ocs_agendador
from app.setup import estado as setup_estado

# O sistema tem DOIS modos, decididos por um arquivo marcador (ver
# app/setup/estado.py). Sem ele, só o assistente responde -- é o que permite
# configurar o banco antes de o sistema depender de um.
INSTALADO = setup_estado.instalado()




def _montar_pagina_setup(instancia) -> None:
    """Liga a página do assistente (import tardio: só existe em modo setup)."""
    from app.setup.pagina import montar

    montar(instancia, FRONTEND_DIR)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# ---------------------------------------------------------------------------
# Logging JSON (observabilidade — seção 7 da especificação).
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Em modo setup NÃO se toca no banco: o assistente trabalha com uma
    # conexão própria e temporária, e a troca vale no próximo início.
    if INSTALADO and settings.auto_create_tables:
        init_db()
    # Sincronização automática com o OCS (o intervalo é configurado na tela).
    # Desligado por padrão nos testes para não abrir sessões de banco paralelas.
    if INSTALADO and settings.scheduler_ativo:
        ocs_agendador.iniciar()
    yield
    ocs_agendador.parar()


app = FastAPI(
    title="Nexus",
    version="1.0.0",
    description="Inventário de TI + Impressoras com QR Code assinado e impressão térmica.",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS restrito (origens configuráveis via .env).
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Headers de segurança (HSTS/CSP/X-Frame/etc.).
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # CSP: sem scripts inline e sem recursos de terceiros (PWA offline-first).
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; "
        "worker-src 'self'; manifest-src 'self'"
    )
    # Frontend sempre revalidado: evita o navegador ficar preso em uma versão
    # antiga do app.js/styles.css (o service worker versionado cuida do offline).
    caminho = request.url.path
    if caminho == "/" or caminho.endswith((".html", ".js", ".css", ".json")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    if settings.env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ---------------------------------------------------------------------------
# Limite de requisições da API.
#
# O login já tinha o seu (10/min, contra força bruta). Todo o resto da API
# ficava aberto: um cliente com token válido podia varrer `/ativos` à vontade
# e extrair o inventário inteiro em minutos.
#
# Este teto é FOLGADO (600/min) de propósito — existe para travar varredura,
# não uso. Ver `api_limiter` em core/rate_limit.py.
# ---------------------------------------------------------------------------
# Rotas que NÃO entram na conta. O login tem limitador próprio e bem mais
# apertado; contar duas vezes faria o teto geral disparar antes do específico
# e mascarar a mensagem certa.
FORA_DO_LIMITE = ("/api/v1/auth/login", "/api/v1/auth/refresh")


@app.middleware("http")
async def limite_de_requisicoes(request: Request, call_next):
    caminho = request.url.path

    # Só a API. Os arquivos do PWA são muitos por tela e não são o alvo de
    # uma varredura de dados.
    if not caminho.startswith("/api/") or caminho.startswith(FORA_DO_LIMITE):
        return await call_next(request)

    chave = chave_do_cliente(request)
    if not api_limiter.is_allowed(chave):
        from fastapi.responses import JSONResponse as _JSON

        return _JSON(
            status_code=429,
            content={
                "detail": (
                    "Muitas requisições em pouco tempo. Aguarde um instante e "
                    "tente de novo."
                )
            },
            headers={"Retry-After": "60"},
        )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Erros tratados de forma clara (em vez de "Internal Server Error").
# ---------------------------------------------------------------------------
@app.exception_handler(IntegrityError)
async def tratar_integridade(request: Request, exc: IntegrityError) -> JSONResponse:
    """Violação de unicidade/chave estrangeira vira 409 com mensagem legível."""
    texto_erro = str(getattr(exc, "orig", exc))
    if "unique" in texto_erro.lower() or "duplicate" in texto_erro.lower():
        detalhe = "Já existe um registro com esse valor. Verifique se o nome, o patrimônio, o SKU ou o e-mail não estão repetidos."
    elif "foreign key" in texto_erro.lower() or "not null" in texto_erro.lower():
        detalhe = "Não foi possível salvar: há um campo obrigatório vazio ou uma referência inválida."
    else:
        detalhe = "Não foi possível salvar o registro por uma restrição do banco de dados."
    return JSONResponse(status_code=409, content={"detail": detalhe})


@app.exception_handler(Exception)
async def tratar_erro_interno(request: Request, exc: Exception) -> JSONResponse:
    """Registra o erro no log e devolve uma mensagem útil (sem detalhes internos)."""
    logging.getLogger("app").exception("Erro não tratado em %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno ao processar a solicitação. O detalhe foi registrado no log do servidor."},
    )


# ---------------------------------------------------------------------------
# Health check.
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> JSONResponse:
    db_ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover
        db_ok = False
    # `version` permite ao frontend perceber que está falando com um processo
    # antigo (servidor iniciado antes de uma atualização) — era a causa de
    # "método não permitido" em recursos recém-criados.
    return JSONResponse({
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "version": __version__,
    })


# ---------------------------------------------------------------------------
if INSTALADO:
# Routers da API v1.
# ---------------------------------------------------------------------------
    API = "/api/v1"
# `require_module` protege o módulo inteiro; o frontend respeita as mesmas chaves.
    app.include_router(auth.router, prefix=API)
    app.include_router(cadastros.router, prefix=API)
    app.include_router(dashboard.router, prefix=API)
    app.include_router(produtos.router, prefix=API, dependencies=[Depends(require_module("produtos"))])
    app.include_router(ativos.router, prefix=API)  # gate no próprio router
    app.include_router(movimentacoes.router, prefix=API, dependencies=[Depends(require_module("movimentacoes"))])
    app.include_router(manutencoes.router, prefix=API, dependencies=[Depends(require_module("manutencoes"))])
    app.include_router(qrcode.router, prefix=API)
    app.include_router(zerados.router, prefix=API)
    app.include_router(print_router.router, prefix=API)
    app.include_router(scanner.router, prefix=API)
    app.include_router(contagens.router, prefix=API)
    app.include_router(relatorios.router, prefix=API, dependencies=[Depends(require_module("relatorios"))])
    app.include_router(graficos.router, prefix=API)
    app.include_router(admin.router, prefix=API)
    app.include_router(emprestimos.router, prefix=API)
    app.include_router(etiquetas.router, prefix=API)
    app.include_router(mfa.router, prefix=API)
    app.include_router(monitor_impressoras.router, prefix=API)
    app.include_router(checklist.router, prefix=API)
    app.include_router(financeiro.router, prefix=API)
    app.include_router(backups.router, prefix=API)
    app.include_router(config_sistema.router, prefix=API)
    app.include_router(auditoria.router, prefix=API)
    app.include_router(plantas.router, prefix=API)
    app.include_router(calendario.router, prefix=API)
    app.include_router(notificacoes.router, prefix=API)
    app.include_router(reportes.router, prefix=API)
    app.include_router(ocs.router, prefix=API)
    app.include_router(ocs_reconciliacao.router, prefix=API)
    app.include_router(banco.router, prefix=API)
    app.include_router(busca.router, prefix=API)
    app.include_router(contratos.router, prefix=API)
    app.include_router(lgpd.router, prefix=API)
    app.include_router(transferencias.router, prefix=API)


# ---------------------------------------------------------------------------


else:
    # --- Modo setup -----------------------------------------------------
    # Só o assistente responde. Os módulos do sistema ficam de fora de
    # propósito: nada deve poder ser usado antes de existir um banco.
    from app.setup import rotas as setup_rotas

    app.include_router(setup_rotas.router)
    _montar_pagina_setup(app)


# Frontend estático.
# ---------------------------------------------------------------------------
if FRONTEND_DIR.exists():
    # Serve o PWA. Mount registrado por último para não sombrear /api e /health.
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

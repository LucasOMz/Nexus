"""Fixtures de teste: banco SQLite em memória + cliente HTTP + token admin."""
from __future__ import annotations

import os
import tempfile

# Configura o ambiente de teste ANTES de importar a aplicação.
#
# `ENV=development` é obrigatório aqui: a configuração recusa SQLite quando
# `ENV=production` (o `.env` do projeto define production). A suíte roda em
# SQLite na memória, e o teste é justamente um contexto de desenvolvimento —
# sem esta linha, o guarda de produção derruba a coleta inteira.
os.environ["ENV"] = "development"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "teste-jwt-secret-super-seguro-32-bytes-ou-mais"
os.environ["QR_HMAC_SECRET"] = "teste-qr-hmac-super-seguro-32-bytes-ou-mais"
os.environ["AUTO_CREATE_TABLES"] = "false"
# Fotos/termos dos testes vão para uma pasta temporária, para não sujar o
# projeto com artefatos (media/fotos, media/termos).
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="estoque-testes-")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.core.security import create_access_token, hash_password
from app.database import get_db
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.core import Planta, Usuario  # noqa: E402

# TRAVA DE SEGURANÇA ---------------------------------------------------------
# Os testes rodam em banco em memória. Se por qualquer motivo o caminho
# apontar para um arquivo (o banco real!), abortamos ANTES de criar/derrubar
# qualquer tabela. Foi assim que um banco de trabalho foi zerado uma vez.
if "memory" not in settings.database_url and settings.database_url != "sqlite://":
    raise RuntimeError(
        "Os testes apontam para um banco em ARQUIVO: "
        f"{settings.database_url!r}. Isso pode APAGAR dados reais. "
        "Verifique DATABASE_URL no .env e as variáveis definidas acima."
    )

# O agendador da sincronização com o OCS roda numa linha de execução própria e
# abriria sessões de banco em paralelo com os testes. Aqui ele fica desligado;
# o comportamento dele é testado diretamente em tests/test_ocs.py.
settings.scheduler_ativo = False

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    # Toda instalação nasce com uma planta (é a ela que os ativos pertencem).
    db.add(Planta(nome="Matriz", sigla="MAT", ativa=True))
    db.flush()
    db.add(Usuario(nome="Admin", email="admin@teste.com", senha_hash=hash_password("admin123"), papel="admin", ativo=True))
    db.commit()
    db.close()

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Token de acesso admin (id=1, primeiro registro do banco de teste)."""
    return {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}


@pytest.fixture(autouse=True)
def _zerar_limitadores():
    """Zera os limitadores entre testes.

    Eles sao GLOBAIS e EM MEMORIA. A suite faz muitos logins seguidos, e sem
    zerar o limitador de login (10 por minuto) comeca a devolver 429 no meio
    da execucao - falha que nada tem a ver com o que o teste verifica.

    Foi o que fez classes de teste passarem sozinhas e falharem em conjunto.

    O `api_limiter` entrou depois, quando o teto geral da API passou a valer:
    a suite inteira faz muito mais de 600 requisicoes, e o contador estouraria
    no meio da execucao. Um teste que verifica 429 de verdade recria o seu.
    """
    from app import main as app_main
    from app.core import rate_limit
    from app.routers import auth as auth_router

    def novo(limiter):
        return rate_limit.SlidingWindowLimiter(
            max_requests=limiter.max_requests,
            window_seconds=limiter.window_seconds,
        )

    # `auth` e `main` importam os limitadores POR NOME, então cada um tem a
    # sua referência. Trocar só o atributo do módulo de origem não muda o que
    # eles usam — é preciso trocar nos dois lugares.
    auth_router.login_limiter = novo(rate_limit.login_limiter)
    app_main.api_limiter = novo(rate_limit.api_limiter)
    yield
    auth_router.login_limiter = novo(rate_limit.login_limiter)
    app_main.api_limiter = novo(rate_limit.api_limiter)

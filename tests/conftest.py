"""Fixtures de teste: banco SQLite em memória + cliente HTTP + token admin."""
from __future__ import annotations

import os
import tempfile

# Configura o ambiente de teste ANTES de importar a aplicação.
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

# Os testes exercitam o SISTEMA, não o assistente de configuração.
#
# O modo é decidido quando `app.main` é importado, olhando o marcador
# `.instalado` e — na falta dele — se o banco já tem estrutura. Numa máquina
# recém-zerada (sem banco, sem marcador) o sistema subiria em modo setup e as
# rotas da API nem existiriam, fazendo a suíte inteira falhar com
# "Method Not Allowed".
#
# A correção é aqui, e não no app: em produção a decisão pelo marcador está
# certa. Nos testes queremos sempre o sistema completo. Precisa vir ANTES de
# `app.main` ser importado (o que acontece dentro da fixture `client`).
from app.setup import estado as _estado_setup  # noqa: E402

# Guardamos a implementação real: os testes do assistente precisam dela.
# (`tests/test_setup_inicial.py` usa `INSTALADO_REAL`.)
INSTALADO_REAL = _estado_setup.instalado  # noqa: E402
_estado_setup.instalado = lambda: True  # noqa: E402
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

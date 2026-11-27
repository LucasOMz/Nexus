"""Testes de autenticação (JWT + roles)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.security import create_refresh_token, decode_token
from app.models import Base
from app.models.core import Usuario
from app.models.sessao import SessaoUsuario
from app.services import sessoes
from tests.conftest import TestingSession, engine


def _login(client):
    resposta = client.post("/api/v1/auth/login", data={"username": "admin@teste.com", "password": "admin123"})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _me(client, sessao):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {sessao['access_token']}"})


def _refresh(client, sessao):
    return client.post("/api/v1/auth/refresh", json={"refresh_token": sessao["refresh_token"]})


def _controlar_relogio(monkeypatch):
    class Relogio(datetime):
        agora = datetime.now(timezone.utc)

        @classmethod
        def now(cls, tz):
            return cls.agora.astimezone(tz)

    monkeypatch.setattr(sessoes, "datetime", Relogio)
    return Relogio


def test_inatividade_expira_access_e_refresh_mesmo_com_consultas_automaticas(client, monkeypatch):
    relogio = _controlar_relogio(monkeypatch)
    inicio = relogio.agora
    sessao = _login(client)
    atividade = "/api/v1/auth/atividade"
    relogio.agora = inicio + timedelta(minutes=9, seconds=59)
    assert _me(client, sessao).status_code == 200
    renovada = _refresh(client, sessao)
    assert renovada.status_code == 200
    sessao = renovada.json()
    headers = {"Authorization": f"Bearer {sessao['access_token']}"}
    relogio.agora = inicio + timedelta(minutes=10)
    perfil = _me(client, sessao)
    assert perfil.status_code == 401
    assert perfil.headers["WWW-Authenticate"] == "Bearer"
    assert client.post(atividade, headers=headers).status_code == 401
    assert _refresh(client, sessao).status_code == 401


def test_atividade_prorroga_a_sessao_pelo_momento_da_interacao(client, monkeypatch):
    relogio = _controlar_relogio(monkeypatch)
    inicio = relogio.agora
    sessao = _login(client)
    headers = {"Authorization": f"Bearer {sessao['access_token']}"}
    relogio.agora = inicio + timedelta(minutes=5)
    assert client.post("/api/v1/auth/atividade?atraso_ms=5000", headers=headers).status_code == 204
    # Evento atrasado de outra aba, anterior ao último já registrado.
    assert client.post("/api/v1/auth/atividade?atraso_ms=15000", headers=headers).status_code == 204
    relogio.agora = inicio + timedelta(minutes=14, seconds=54)
    assert _me(client, sessao).status_code == 200
    relogio.agora += timedelta(seconds=1)
    assert _me(client, sessao).status_code == 401


def test_login_success(client):
    res = client.post("/api/v1/auth/login", data={"username": "admin@teste.com", "password": "admin123"})
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == "admin@teste.com"


def test_login_wrong_password(client):
    res = client.post("/api/v1/auth/login", data={"username": "admin@teste.com", "password": "errada"})
    assert res.status_code == 401


def test_me(client, auth_headers):
    res = client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["email"] == "admin@teste.com"


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_refresh_rotaciona_e_reutilizacao_revoga_sessao(client):
    original = _login(client)
    credencial = original["refresh_token"]
    antigo = decode_token(credencial)
    renovacao = _refresh(client, original)
    assert renovacao.status_code == 200, renovacao.text
    renovada = renovacao.json()
    novo = decode_token(renovada["refresh_token"])
    assert antigo["sid"] == novo["sid"]
    assert antigo["jti"] != novo["jti"]
    with TestingSession() as db:
        sessao = db.get(SessaoUsuario, novo["sid"])
        assert sessao.refresh_hash == sha256(renovada["refresh_token"].encode()).hexdigest()
    assert _me(client, renovada).status_code == 200
    assert _refresh(client, original).status_code == 401
    with TestingSession() as db:
        assert db.get(SessaoUsuario, novo["sid"]).revogada_em is not None
    assert _me(client, renovada).status_code == 401
    assert _refresh(client, renovada).status_code == 401


def test_logout_revoga_apenas_a_sessao_informada(client):
    primeira = _login(client)
    segunda = _login(client)
    assert client.post("/api/v1/auth/logout", json={"refresh_token": primeira["refresh_token"]}).status_code == 200
    assert _me(client, primeira).status_code == 401
    assert _refresh(client, primeira).status_code == 401
    assert _me(client, segunda).status_code == 200
    assert _refresh(client, segunda).status_code == 200


def test_refresh_anterior_ao_registro_persistente_prescreve(client):
    token = create_refresh_token(1, "admin", "admin@teste.com")
    assert _refresh(client, {"refresh_token": token}).status_code == 401


def test_sessao_da_versao_anterior_exige_novo_login(client):
    anterior = _login(client)
    sid = decode_token(anterior["access_token"])["sid"]
    with TestingSession() as db:
        db.get(SessaoUsuario, sid).ultima_atividade_em = None
        db.commit()
    assert _me(client, anterior).status_code == 401
    assert _refresh(client, anterior).status_code == 401
    assert _me(client, _login(client)).status_code == 200


def test_politica_de_inatividade_pode_ser_alterada_sem_reativar_sessoes(client, monkeypatch):
    relogio = _controlar_relogio(monkeypatch)
    anterior = _login(client)
    relogio.agora += timedelta(minutes=10)
    admin = _login(client)
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    politica = "/api/v1/auth/politica-sessao"
    configurar = "/api/v1/admin/config/politica-sessao"
    assert client.get(politica, headers=headers).json() == {"inatividade_minutos": 10}
    assert client.put(configurar, headers=headers, json={"inatividade_minutos": 0}).status_code == 422
    assert client.put(configurar, headers=headers, json={"inatividade_minutos": 20}).status_code == 200
    assert _refresh(client, anterior).status_code == 401
    assert client.get(politica, headers=headers).json() == {"inatividade_minutos": 20}
    relogio.agora += timedelta(minutes=11)
    assert _me(client, admin).status_code == 200
    assert client.put(configurar, headers=headers, json={"inatividade_minutos": 5}).status_code == 200
    assert _me(client, admin).status_code == 401


def test_banco_restaurado_descarta_sessoes_anteriores(client):
    existente = _login(client)
    sessoes.limpar_em_banco_restaurado(engine)
    assert _me(client, existente).status_code == 401
    assert _refresh(client, existente).status_code == 401
    assert _me(client, _login(client)).status_code == 200


def test_duas_renovacoes_concorrentes_gravam_um_unico_refresh(tmp_path):
    motor = create_engine(f"sqlite:///{tmp_path / 'rotacao.sqlite'}")
    ttl = timedelta(minutes=5)
    Base.metadata.create_all(motor)
    try:
        with Session(motor) as db:
            usuario = Usuario(nome="Operador", email="operador@teste.com", senha_hash="teste")
            db.add(usuario)
            db.flush()
            uid = usuario.id
            sessoes.registrar(db, "sessao-teste", uid, ttl, "anterior")
            db.commit()
        barreira = Barrier(2)

        def renovar(refresh):
            with Session(motor) as db:
                barreira.wait(timeout=5)
                venceu = sessoes.renovar(db, "sessao-teste", uid, "anterior", refresh, ttl)
                db.commit()
                return venceu

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(renovar, ("novo-a", "novo-b"))) == [False, True]
    finally:
        motor.dispose()

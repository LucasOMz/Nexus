"""Limite de requisições da API.

O login já tinha o seu (10/min, contra força bruta). Todo o resto da API
ficava aberto: um cliente com token válido podia varrer `/ativos` à vontade e
extrair o inventário inteiro em minutos.

O teto geral é FOLGADO (600/min) de propósito — existe para travar varredura,
não uso. Um teto apertado quebraria a navegação normal e seria afrouxado no
primeiro chamado, voltando a não proteger nada.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core import rate_limit
from app.core.rate_limit import SlidingWindowLimiter


@pytest.fixture
def limite_baixo(monkeypatch):
    """Troca o teto geral por um pequeno, para não fazer 600 requisições.

    O patch é em `app.main`, e NÃO em `app.core.rate_limit`: o main importa o
    limitador **por nome** (`from ... import api_limiter`), então passa a ter
    a sua própria referência. Trocar o atributo do módulo de origem não muda
    o que o middleware usa — é o mesmo detalhe de `auth_router.login_limiter`.
    """
    def aplicar(maximo=3):
        from app import main as app_main

        monkeypatch.setattr(
            app_main, "api_limiter",
            SlidingWindowLimiter(max_requests=maximo, window_seconds=60),
        )
    return aplicar


class TestMotor:
    def test_permite_ate_o_teto(self):
        lim = SlidingWindowLimiter(max_requests=3, window_seconds=60)
        assert [lim.is_allowed("x") for _ in range(3)] == [True, True, True]

    def test_bloqueia_depois_do_teto(self):
        lim = SlidingWindowLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            lim.is_allowed("x")
        assert lim.is_allowed("x") is False

    def test_chaves_diferentes_nao_se_afetam(self):
        """Dois usuários não podem consumir o teto um do outro."""
        lim = SlidingWindowLimiter(max_requests=2, window_seconds=60)
        assert lim.is_allowed("a") is True
        assert lim.is_allowed("a") is True
        assert lim.is_allowed("a") is False
        assert lim.is_allowed("b") is True


class TestMiddleware:
    def test_requisicao_normal_passa(self, client, auth_headers):
        r = client.get("/api/v1/ativos", headers=auth_headers)
        assert r.status_code == 200

    def test_estoura_com_429(self, client, auth_headers, limite_baixo):
        limite_baixo(3)
        codigos = [
            client.get("/api/v1/ativos", headers=auth_headers).status_code
            for _ in range(6)
        ]
        assert 429 in codigos, f"nunca limitou: {codigos}"

    def test_o_429_traz_retry_after(self, client, auth_headers, limite_baixo):
        """Sem o cabeçalho, o cliente não sabe quando tentar de novo."""
        limite_baixo(1)
        client.get("/api/v1/ativos", headers=auth_headers)
        r = client.get("/api/v1/ativos", headers=auth_headers)
        assert r.status_code == 429
        assert r.headers.get("retry-after") == "60"

    def test_a_mensagem_explica_o_motivo(self, client, auth_headers, limite_baixo):
        limite_baixo(1)
        client.get("/api/v1/ativos", headers=auth_headers)
        r = client.get("/api/v1/ativos", headers=auth_headers)
        assert "Muitas requisições" in r.json()["detail"]

    def test_arquivos_do_pwa_nao_sao_limitados(self, client, limite_baixo):
        """Uma tela carrega dezenas de arquivos, e eles não são o alvo de
        uma varredura de dados."""
        limite_baixo(1)
        client.get("/api/v1/ativos")   # consome
        # Fora de /api/: continua respondendo (404 do roteador, não 429).
        r = client.get("/qualquer-coisa.js")
        assert r.status_code != 429

    def test_o_login_tem_o_seu_proprio_limite(self, client, auth_headers, limite_baixo):
        """Contar duas vezes faria o teto geral disparar antes do específico
        e mascarar a mensagem certa.

        O login está na lista de exceção: com o teto geral em 1, a segunda
        tentativa de login ainda chega ao limitador de login.
        """
        limite_baixo(1)
        client.get("/api/v1/ativos", headers=auth_headers)   # consome o geral
        r = client.post("/api/v1/auth/login",
                        data={"username": "x@teste.com", "password": "errada"})
        assert r.status_code != 429


class TestChaveDoCliente:
    class _Req:
        def __init__(self, usuario_id=None, ip="10.0.0.1", encaminhado=None):
            self.state = type("S", (), {"usuario_id": usuario_id})()
            self.client = type("C", (), {"host": ip})()
            self.headers = {"x-forwarded-for": encaminhado} if encaminhado else {}

    def test_usa_o_usuario_quando_autenticado(self):
        """Sem isto, quatro pessoas atrás do mesmo NAT dividiriam o teto."""
        k = rate_limit.chave_do_cliente(self._Req(usuario_id=7))
        assert k == "u:7"

    def test_cai_para_o_ip_sem_usuario(self):
        assert rate_limit.chave_do_cliente(self._Req()) == "ip:10.0.0.1"

    def test_usa_o_ip_apurado_pelo_servidor_asgi(self):
        r = self._Req(encaminhado="203.0.113.9, 10.0.0.1")
        assert rate_limit.chave_do_cliente(r) == "ip:10.0.0.1"

    def test_sem_cliente_nao_estoura(self):
        class SemCliente:
            state = type("S", (), {"usuario_id": None})()
            client = None
            headers = {}

        assert rate_limit.chave_do_cliente(SemCliente()) == "ip:desconhecido"


class TestConfiguracao:
    def test_o_teto_geral_e_folgado(self):
        """Se um dia alguém baixar isto para proteger "mais", a navegação
        normal quebra — e o limite seria afrouxado de volta."""
        assert rate_limit.api_limiter.max_requests >= 300

    def test_o_login_continua_apertado(self):
        """O limite que realmente protege é o do login: é por identidade e
        contra força bruta."""
        assert rate_limit.login_limiter.max_requests <= 20


def test_reserva_local_mantem_contagem_se_redis_ficar_indisponivel(monkeypatch, caplog):
    redis = rate_limit.RedisContadores("redis://localhost:6379/0")
    lim = SlidingWindowLimiter(2, 60, redis=redis, grupo="teste")
    monkeypatch.setattr(redis, "_decidir", lambda **_: 1)
    assert lim.is_allowed("cliente")

    def indisponivel(**_):
        raise RedisConnectionError("conexão de teste")

    monkeypatch.setattr(redis, "_decidir", indisponivel)
    assert lim.is_allowed("cliente")
    assert not lim.is_allowed("cliente")
    assert sum("Usando contadores locais" in r.message for r in caplog.records) == 1
    redis.fechar()


@pytest.fixture
def contadores_redis():
    url = os.getenv("NEXUS_TEST_REDIS_URL")
    if not url:
        pytest.skip("Configure NEXUS_TEST_REDIS_URL para testar com um Redis descartável.")
    primeiro = rate_limit.RedisContadores(url)
    segundo = rate_limit.RedisContadores(url)
    try:
        yield primeiro, segundo
    finally:
        primeiro.fechar()
        segundo.fechar()


def test_redis_compartilha_teto_atomico_e_expira_a_janela(contadores_redis):
    grupo = uuid4().hex
    a, b = [SlidingWindowLimiter(3, 2, redis=redis, grupo=grupo) for redis in contadores_redis]
    with ThreadPoolExecutor(max_workers=8) as executor:
        resultados = list(executor.map(lambda n: (a if n % 2 else b).is_allowed("cliente"), range(20)))
    assert sum(resultados) == 3
    prazo = time.monotonic() + 5
    while not b.is_allowed("cliente"):
        assert time.monotonic() < prazo, "A janela do cliente ainda não expirou."
        time.sleep(0.05)


def test_redis_mantem_429_ao_recriar_limitador_da_api(client, auth_headers, contadores_redis, monkeypatch):
    from app import main as app_main

    grupo = uuid4().hex
    primeiro, segundo = contadores_redis
    monkeypatch.setattr(app_main, "api_limiter", SlidingWindowLimiter(1, 60, redis=primeiro, grupo=grupo))
    assert client.get("/api/v1/ativos", headers=auth_headers).status_code == 200
    primeiro.fechar()

    monkeypatch.setattr(app_main, "api_limiter", SlidingWindowLimiter(1, 60, redis=segundo, grupo=grupo))
    resposta = client.get("/api/v1/ativos", headers=auth_headers)
    assert resposta.status_code == 429
    assert resposta.headers["retry-after"] == "60"
    assert SlidingWindowLimiter(1, 60, redis=segundo, grupo=uuid4().hex).is_allowed("ip:testclient")

"""Aba "Conexão com DBA" — visualização apenas.

A tela existe para o administrador **ver** onde o sistema está gravando. Ela não
altera nada, e isso é decisão de projeto: a conexão é fixada quando o sistema
sobe. Se o endereço pudesse ser trocado daqui e estivesse errado, esta própria
tela deixaria de abrir — e o sistema perderia a única forma de se consertar pela
interface.

O teste mais importante deste arquivo é o que garante que a **senha do banco
nunca sai do servidor**.
"""
from __future__ import annotations

import json

import pytest

from app.core.rate_limit import login_limiter, scan_limiter


@pytest.fixture(autouse=True)
def _liberar_rate_limit():
    login_limiter._hits.clear()
    scan_limiter._hits.clear()
    yield
    login_limiter._hits.clear()
    scan_limiter._hits.clear()


def _info(client, headers):
    r = client.get("/api/v1/admin/banco", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


class TestVisualizacao:
    def test_mostra_tipo_e_endereco(self, client, auth_headers):
        d = _info(client, auth_headers)
        assert d["conexao"]["tipo"]  # SQLite no ambiente de teste
        assert d["conexao"]["url"]
        assert d["saudavel"] is True

    def test_mostra_versao_do_servidor(self, client, auth_headers):
        assert _info(client, auth_headers)["servidor_versao"]

    def test_mostra_as_contagens(self, client, auth_headers):
        client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "DBA-001"},
                    headers=auth_headers)
        contagens = {c["tabela"]: c["linhas"] for c in _info(client, auth_headers)["contagens"]}
        assert contagens.get("ativos", 0) >= 1

    def test_mostra_quantas_tabelas(self, client, auth_headers):
        assert _info(client, auth_headers)["total_tabelas"] > 10

    def test_informa_que_e_somente_leitura(self, client, auth_headers):
        d = _info(client, auth_headers)
        assert d["somente_leitura"] is True
        assert "DATABASE_URL" in d["como_alterar"]
        assert "reiniciado" in d["como_alterar"]

    def test_sqlite_mostra_o_arquivo(self, client, auth_headers):
        d = _info(client, auth_headers)
        if d["conexao"]["tipo"] != "SQLite":
            pytest.skip("só vale para SQLite")
        assert d["sqlite"]["arquivo"]
        assert "tamanho_legivel" in d["sqlite"]


class TestSenhaNuncaVaza:
    """O ponto mais crítico desta tela."""

    def test_senha_nao_aparece(self, client, auth_headers):
        d = _info(client, auth_headers)
        bruto = json.dumps(d, ensure_ascii=False)

        # A senha do usuário de banco aparece em qualquer campo?
        for suspeita in ("senha", "password"):
            valor = d["conexao"].get(suspeita)
            assert valor in (None, ""), f"campo {suspeita} devolveu valor"

        # E o marcador de máscara está no lugar.
        if d["conexao"]["senha_definida"]:
            assert "***" in d["conexao"]["url"], "faltou mascarar a senha na URL"
        assert "senha" not in bruto.lower() or "senha_definida" in bruto

    def test_url_mascarada_de_verdade(self):
        """A máscara é feita pelo próprio SQLAlchemy, não à mão."""
        from sqlalchemy.engine import make_url

        url = make_url("postgresql+psycopg://gp_app:segredo123@10.0.0.5:5432/estoque")
        mascarada = url.render_as_string(hide_password=True)
        assert "segredo123" not in mascarada
        assert "***" in mascarada
        assert "gp_app" in mascarada          # usuário pode aparecer
        assert "10.0.0.5" in mascarada        # servidor também
        assert "estoque" in mascarada

    def test_senha_em_postgres_nao_vaza(self, client, auth_headers, monkeypatch):
        """Simula uma conexão PostgreSQL com senha e confere a saída."""
        from app.routers import banco as modulo_banco

        monkeypatch.setattr(
            modulo_banco.settings, "database_url",
            "postgresql+psycopg://gp_app:SenhaSecreta@db.interno:5432/estoque",
        )
        partes = modulo_banco._url_mascarada()

        assert partes["tipo"] == "PostgreSQL"
        assert partes["servidor"] == "db.interno"
        assert partes["porta"] == 5432
        assert partes["banco"] == "estoque"
        assert partes["usuario"] == "gp_app"
        assert partes["senha_definida"] is True
        assert "SenhaSecreta" not in json.dumps(partes)


class TestSomenteLeitura:
    def test_nao_existe_endpoint_de_escrita(self, client, auth_headers):
        """Não há como alterar a conexão por aqui — nem por acidente."""
        for metodo in ("put", "post", "patch", "delete"):
            r = getattr(client, metodo)("/api/v1/admin/banco", headers=auth_headers,
                                        **({"json": {}} if metodo in ("put", "post", "patch") else {}))
            assert r.status_code in (404, 405), f"{metodo.upper()} deveria ser recusado"

    def test_o_modulo_nao_importa_escrita(self):
        import inspect

        from app.routers import banco as modulo_banco

        fonte = inspect.getsource(modulo_banco)
        assert "router.put" not in fonte
        assert "router.post" not in fonte
        assert "router.patch" not in fonte
        assert "router.delete" not in fonte


class TestAcesso:
    def test_somente_admin(self, client, auth_headers):
        client.post("/api/v1/usuarios",
                    json={"nome": "Tec", "email": "tec.banco@teste.com", "papel": "ti",
                          "senha": "senha123"}, headers=auth_headers)
        login = client.post("/api/v1/auth/login",
                            data={"username": "tec.banco@teste.com", "password": "senha123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        assert client.get("/api/v1/admin/banco", headers=h).status_code == 403

    def test_exige_login(self, client):
        assert client.get("/api/v1/admin/banco").status_code == 401


class TestResiliencia:
    def test_falha_ao_listar_tabelas_nao_derruba_a_tela(self, client, auth_headers, monkeypatch):
        """Se a inspeção do banco falhar, a tela abre e diz que não conseguiu."""
        from app.routers import banco as modulo_banco

        def inspecao_quebrada(*a, **k):
            raise RuntimeError("catálogo indisponível")

        monkeypatch.setattr(modulo_banco, "inspect", inspecao_quebrada)
        d = _info(client, auth_headers)
        assert d["saudavel"] is True          # a conexão em si funciona
        assert d["total_tabelas"] is None     # mas a listagem não veio

    def test_contagem_de_tabela_ausente_nao_quebra(self, client, auth_headers, monkeypatch):
        """Tabela que não existe é omitida, não gera erro."""
        from app.routers import banco as modulo_banco

        monkeypatch.setattr(modulo_banco, "TABELAS_PRINCIPAIS",
                            ("ativos", "tabela_que_nao_existe", "usuarios"))
        d = _info(client, auth_headers)
        nomes = [c["tabela"] for c in d["contagens"]]
        assert "ativos" in nomes
        assert "tabela_que_nao_existe" not in nomes

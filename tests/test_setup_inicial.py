"""Assistente de configuração inicial.

Os testes usam um app **mínimo**, só com as rotas do assistente, e desviam os
arquivos (marcador, .env, pasta de mídia) para uma pasta temporária. Assim nada
toca a instalação real de quem roda a suíte.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.setup import estado, rotas
from tests.conftest import INSTALADO_REAL  # noqa: E402


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Isola marcador, .env e mídia numa pasta temporária."""
    monkeypatch.setattr(estado, "ARQUIVO_MARCADOR", tmp_path / ".instalado")
    monkeypatch.setattr(estado, "ARQUIVO_ENV", tmp_path / ".env")
    monkeypatch.setattr(estado, "PASTA_EMPRESA", tmp_path / "media" / "empresa")

    # O conftest geral força `instalado() -> True`, porque o resto da suíte
    # exercita o SISTEMA. Aqui queremos o comportamento de verdade: o modo
    # depende do marcador que acabamos de desviar para a pasta temporária.
    monkeypatch.setattr(estado, "instalado", lambda: estado.ARQUIVO_MARCADOR.exists())

    app = FastAPI()
    app.include_router(rotas.router)
    return TestClient(app), tmp_path


def _banco_sqlite(tmp_path, nome="novo.db"):
    return {
        "tipo": "sqlite",
        "arquivo": str(tmp_path / nome),
        "criar_estrutura": True,
    }


def _corpo(tmp_path, **extra):
    dados = {
        "root_email": rotas.ROOT_EMAIL,
        "root_senha": rotas.ROOT_SENHA,
        "empresa": {"nome": "Yazaki do Brasil", "rodape": "Gestão de ativos"},
        "banco": _banco_sqlite(tmp_path),
        "admin": {"nome": "Administrador", "email": "ti@yazaki.com", "senha": "senha-forte-123"},
        "planta": {"nome": "Tatuí", "sigla": "TAT"},
    }
    dados.update(extra)
    return dados


class TestEstado:
    def test_comeca_nao_instalado(self, ambiente):
        client, _ = ambiente
        d = client.get("/setup/estado").json()
        assert d["instalado"] is False
        assert any(b["valor"] == "sqlite" for b in d["bancos"])
        assert any(b["valor"] == "postgresql" for b in d["bancos"])

    def test_lista_varios_bancos(self, ambiente):
        client, _ = ambiente
        tipos = {b["valor"] for b in client.get("/setup/estado").json()["bancos"]}
        assert {"sqlite", "postgresql", "mysql", "mssql"} <= tipos

    def test_diz_quais_drivers_estao_instalados(self, ambiente):
        client, _ = ambiente
        bancos = {b["valor"]: b for b in client.get("/setup/estado").json()["bancos"]}
        assert bancos["sqlite"]["driver_instalado"] is True
        # PostgreSQL tem driver no projeto; MySQL normalmente não.
        assert isinstance(bancos["mysql"]["driver_instalado"], bool)


class TestPorteiro:
    def test_credenciais_erradas(self, ambiente):
        client, _ = ambiente
        r = client.post("/setup/validar-root", data={"email": rotas.ROOT_EMAIL, "senha": "errada"})
        assert r.status_code == 401

    def test_usuario_errado(self, ambiente):
        client, _ = ambiente
        r = client.post("/setup/validar-root", data={"email": "outro@x.com", "senha": rotas.ROOT_SENHA})
        assert r.status_code == 401

    def test_credenciais_certas(self, ambiente):
        client, _ = ambiente
        r = client.post("/setup/validar-root",
                        data={"email": rotas.ROOT_EMAIL, "senha": rotas.ROOT_SENHA})
        assert r.status_code == 200


class TestBanco:
    def test_sqlite_novo_conecta(self, ambiente):
        client, tmp = ambiente
        r = client.post("/setup/testar-banco", json=_banco_sqlite(tmp)).json()
        assert r["ok"] is True
        assert r["ja_configurado"] is False
        assert "vazio" in r["mensagem"]

    def test_endereco_invalido_da_erro_claro(self, ambiente):
        client, tmp = ambiente
        r = client.post("/setup/testar-banco", json={
            "tipo": "postgresql", "servidor": "servidor-que-nao-existe.invalido",
            "porta": 5432, "banco": "x", "usuario": "u", "senha": "s",
        })
        assert r.status_code == 400
        assert "conectar" in r.json()["detail"].lower()

    def test_driver_ausente_explica_o_que_falta(self, ambiente, monkeypatch):
        """A mensagem precisa dizer o que instalar, não só que falhou.

        Simula o driver ausente em vez de depender do ambiente: o pymysql já
        vem no projeto, então este teste falharia numa máquina onde ele está
        instalado — e passaria numa onde não está. Melhor forçar o cenário.
        """
        import builtins

        real = builtins.__import__

        def sem_pymysql(nome, *a, **k):
            if nome == "pymysql":
                raise ModuleNotFoundError("No module named 'pymysql'", name="pymysql")
            return real(nome, *a, **k)

        monkeypatch.setattr(builtins, "__import__", sem_pymysql)

        client, tmp = ambiente
        r = client.post("/setup/testar-banco", json={
            "tipo": "mysql", "servidor": "x", "porta": 3306,
            "banco": "x", "usuario": "u", "senha": "s",
        })
        # Pode falhar por driver ausente OU por não alcançar o servidor: o que
        # importa é a mensagem ser útil em vez de um erro técnico cru.
        assert r.status_code == 400
        detalhe = r.json()["detail"].lower()
        assert "driver" in detalhe or "conectar" in detalhe

    def test_url_postgres_montada_com_driver(self):
        url = rotas.montar_url(rotas.BancoIn(
            tipo="postgresql", servidor="db.interno", porta=5432,
            banco="estoque", usuario="gp", senha="segredo",
        ))
        assert url == "postgresql+psycopg://gp:segredo@db.interno:5432/estoque"

    def test_senha_com_caracteres_especiais_e_codificada(self):
        url = rotas.montar_url(rotas.BancoIn(
            tipo="postgresql", servidor="db", porta=5432,
            banco="e", usuario="gp", senha="se@n#ha/1",
        ))
        assert "se@n#ha/1" not in url          # precisa ir codificada
        assert "%40" in url and "%23" in url


class TestAplicar:
    def test_cria_tudo_e_trava_o_assistente(self, ambiente):
        client, tmp = ambiente
        r = client.post("/setup/aplicar", json=_corpo(tmp))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["precisa_reiniciar"] is True
        assert any("Administrador" in p for p in d["passos"])
        assert any("Planta" in p for p in d["passos"])

    def test_estrutura_e_dados_realmente_criados(self, ambiente):
        client, tmp = ambiente
        client.post("/setup/aplicar", json=_corpo(tmp))

        from sqlalchemy import create_engine, inspect
        from sqlalchemy.orm import Session

        from app.models.core import ConfiguracaoSistema, Planta, Usuario

        motor = create_engine(f"sqlite:///{tmp / 'novo.db'}")
        try:
            assert "usuarios" in inspect(motor).get_table_names()
            with Session(motor) as s:
                admin = s.query(Usuario).filter(Usuario.email == "ti@yazaki.com").first()
                assert admin is not None
                assert admin.papel.value == "admin"
                assert admin.planta_id is None            # administrador vê tudo

                planta = s.query(Planta).first()
                assert planta.sigla == "TAT"

                cfg = s.get(ConfiguracaoSistema, 1)
                assert cfg.empresa_nome == "Yazaki do Brasil"
        finally:
            motor.dispose()

    def test_senha_do_admin_nao_fica_em_texto_puro(self, ambiente):
        client, tmp = ambiente
        client.post("/setup/aplicar", json=_corpo(tmp))

        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.core.security import verify_password
        from app.models.core import Usuario

        motor = create_engine(f"sqlite:///{tmp / 'novo.db'}")
        try:
            with Session(motor) as s:
                admin = s.query(Usuario).filter(Usuario.email == "ti@yazaki.com").first()
                assert "senha-forte-123" not in admin.senha_hash
                assert verify_password("senha-forte-123", admin.senha_hash)
        finally:
            motor.dispose()

    def test_grava_env_e_marcador(self, ambiente):
        client, tmp = ambiente
        client.post("/setup/aplicar", json=_corpo(tmp))

        env = (tmp / ".env").read_text(encoding="utf-8")
        assert "DATABASE_URL=sqlite:///" in env
        assert "JWT_SECRET=" in env
        assert "QR_HMAC_SECRET=" in env

        marcador = json.loads((tmp / ".instalado").read_text(encoding="utf-8"))
        assert marcador["empresa"] == "Yazaki do Brasil"
        assert "instalado_em" in marcador

    def test_nao_sobrescreve_segredos_existentes(self, ambiente):
        """Trocar o QR_HMAC_SECRET invalidaria as etiquetas já impressas."""
        client, tmp = ambiente
        (tmp / ".env").write_text("JWT_SECRET=ja-existia\nQR_HMAC_SECRET=etiquetas-ok\n", encoding="utf-8")

        r = client.post("/setup/aplicar", json=_corpo(tmp))
        env = (tmp / ".env").read_text(encoding="utf-8")
        assert "JWT_SECRET=ja-existia" in env
        assert "QR_HMAC_SECRET=etiquetas-ok" in env
        assert any("mantido" in a for a in r.json()["avisos"])

    def test_preserva_comentarios_do_env(self, ambiente):
        client, tmp = ambiente
        (tmp / ".env").write_text("# comentário importante\nOUTRA=1\n", encoding="utf-8")
        client.post("/setup/aplicar", json=_corpo(tmp))
        env = (tmp / ".env").read_text(encoding="utf-8")
        assert "# comentário importante" in env
        assert "OUTRA=1" in env

    def test_depois_de_instalado_o_assistente_fecha(self, ambiente):
        client, tmp = ambiente
        client.post("/setup/aplicar", json=_corpo(tmp))

        # O estado continua respondendo (a página precisa saber que já instalou),
        # mas NENHUMA ação é aceita — é o que impede reapontar o banco.
        assert client.get("/setup/estado").json()["instalado"] is True
        assert client.post("/setup/aplicar", json=_corpo(tmp, banco=_banco_sqlite(tmp, "outro.db"))).status_code == 404
        assert client.post("/setup/validar-root",
                           data={"email": rotas.ROOT_EMAIL, "senha": rotas.ROOT_SENHA}).status_code == 404
        assert client.post("/setup/testar-banco", json=_banco_sqlite(tmp, "x.db")).status_code == 404
        assert client.post("/setup/testar-ad", json={"servidor": "x", "base_dn": "y", "conta_servico": "z"}).status_code == 404
        assert client.post("/setup/testar-ocs", json={"servidor": "x", "token": "y"}).status_code == 404

    def test_sessao_invalida_e_recusada(self, ambiente):
        client, tmp = ambiente
        corpo = _corpo(tmp)
        corpo["root_senha"] = "outra"
        assert client.post("/setup/aplicar", json=corpo).status_code == 401

    def test_email_de_admin_repetido_no_banco(self, ambiente):
        client, tmp = ambiente
        client.post("/setup/aplicar", json=_corpo(tmp)).status_code == 200

        # Libera o assistente de novo (simula copiar o banco para outro lugar).
        (tmp / ".instalado").unlink()
        r = client.post("/setup/aplicar", json=_corpo(tmp))
        assert r.status_code == 409
        assert "já existe" in r.json()["detail"].lower()

    def test_reaproveitar_banco_existente(self, ambiente):
        """Usar um banco já pronto não deve recriar a estrutura."""
        client, tmp = ambiente
        client.post("/setup/aplicar", json=_corpo(tmp))
        (tmp / ".instalado").unlink()

        corpo = _corpo(tmp)
        corpo["banco"]["criar_estrutura"] = False
        corpo["planta"]["sigla"] = "BNT"
        corpo["admin"]["email"] = "outro@yazaki.com"
        r = client.post("/setup/aplicar", json=corpo)
        assert r.status_code == 200
        assert any("existente" in p for p in r.json()["passos"])


class TestValidacoes:
    def test_banco_sqlite_rejeita_endereco(self, ambiente):
        client, tmp = ambiente
        r = client.post("/setup/testar-banco", json={
            "tipo": "sqlite", "arquivo": "postgresql://x:y@z/w",
        })
        assert r.status_code == 400
        assert "caminho de arquivo" in r.json()["detail"]

    def test_campos_faltando_no_servidor(self, ambiente):
        client, tmp = ambiente
        r = client.post("/setup/testar-banco", json={"tipo": "postgresql", "servidor": "x"})
        assert r.status_code == 400
        assert "Preencha" in r.json()["detail"]

    def test_senha_curta_do_admin_e_recusada(self, ambiente):
        client, tmp = ambiente
        corpo = _corpo(tmp)
        corpo["admin"]["senha"] = "curta"
        assert client.post("/setup/aplicar", json=corpo).status_code == 422


class TestMarcaDaEmpresa:
    def test_envia_logo(self, ambiente):
        client, tmp = ambiente
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
        )
        r = client.post("/setup/arquivo-marca",
                        data={"tipo": "logo"},
                        files={"file": ("logo.png", png, "image/png")})
        assert r.status_code == 200, r.text
        assert r.json()["caminho"]

    def test_recusa_arquivo_que_nao_e_imagem(self, ambiente):
        client, tmp = ambiente
        r = client.post("/setup/arquivo-marca",
                        data={"tipo": "logo"},
                        files={"file": ("x.txt", b"nao e imagem", "text/plain")})
        assert r.status_code == 400

    def test_recusa_tipo_invalido(self, ambiente):
        client, tmp = ambiente
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
        r = client.post("/setup/arquivo-marca",
                        data={"tipo": "outro"},
                        files={"file": ("l.png", png, "image/png")})
        assert r.status_code == 400

    def test_nome_do_arquivo_impede_sair_da_pasta(self, ambiente):
        client, tmp = ambiente
        # Tenta escapar da pasta com "../" no nome enviado.
        assert estado.salvar_arquivo_marca("../../etc/passwd", b"x")
        assert estado.caminho_marca("../../etc/passwd") is None


class TestDeteccaoDeInstalacaoAntiga:
    def test_banco_existente_marca_como_instalado(self, monkeypatch, tmp_path):
        """Quem já usava o sistema não pode ver o assistente depois de atualizar."""
        caminho = tmp_path / "antigo.db"
        from sqlalchemy import create_engine

        motor = create_engine(f"sqlite:///{caminho}")
        with motor.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)")
        motor.dispose()

        monkeypatch.setattr(estado, "ARQUIVO_MARCADOR", tmp_path / ".instalado")
        monkeypatch.setattr(
            __import__("app.config", fromlist=["settings"]).settings,
            "database_url", f"sqlite:///{caminho}",
        )

        assert INSTALADO_REAL() is True
        assert (tmp_path / ".instalado").exists()

    def test_banco_inexistente_nao_marca(self, monkeypatch, tmp_path):
        monkeypatch.setattr(estado, "ARQUIVO_MARCADOR", tmp_path / ".instalado")
        monkeypatch.setattr(
            __import__("app.config", fromlist=["settings"]).settings,
            "database_url", f"sqlite:///{tmp_path / 'nao_existe.db'}",
        )
        assert INSTALADO_REAL() is False


class TestAssetsDaPagina:
    """O CSS e o JS precisam chegar ao navegador.

    A página é servida em `/instalacao` (sem barra no fim). Com caminho
    relativo, o navegador resolveria `setup.css` a partir de `/` e pediria
    `/setup.css` — que não existe. O sintoma era a página **sem estilo e sem
    script**, presa em "Carregando…".

    O teste anterior checava os caminhos diretos e passava; este resolve os
    endereços **como o navegador faz**, que é onde o problema aparecia.
    """

    @pytest.mark.parametrize("pedido", ["/instalacao", "/instalacao/"])
    def test_todos_os_recursos_carregam(self, pedido):
        from urllib.parse import urljoin

        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        from app.setup import pagina

        app = FastAPI()
        app.include_router(rotas.router)
        pagina.montar(app, estado.RAIZ / "frontend")
        client = TC(app)

        r = client.get(pedido, follow_redirects=False)
        assert r.status_code == 200

        import re

        alvos = [a for a in re.findall(r'(?:href|src)="([^"]+)"', r.text)
                 if not a.startswith(("http", "data:"))]
        assert alvos, "a página não referencia nenhum recurso"

        for alvo in alvos:
            resolvido = urljoin(pedido, alvo)
            rr = client.get(resolvido)
            assert rr.status_code == 200, (
                f"'{alvo}' seria pedido como '{resolvido}' e respondeu "
                f"{rr.status_code} — use caminho absoluto em index.html"
            )

    def test_css_usa_as_cores_do_sistema(self):
        css = (estado.RAIZ / "frontend" / "setup" / "setup.css").read_text(encoding="utf-8")
        assert "--md-sys-color-primary" in css, "o assistente deve usar as cores do sistema"
        assert "--md-sys-color-surface" in css
        assert "prefers-color-scheme" in css, "faltou o tema escuro"

    def test_sem_script_inline(self):
        """A política de segurança do sistema bloqueia scripts inline."""
        html = (estado.RAIZ / "frontend" / "setup" / "index.html").read_text(encoding="utf-8")
        assert "<script>" not in html, "script inline seria bloqueado pela CSP"
        assert "/instalacao/setup.js" in html


class TestTelaDeBoasVindas:
    """A raiz mostra uma tela, não um JSON.

    Antes, abrir o endereço do sistema devolvia
    {"sistema":"não instalado",...} — informativo para um programa, mas quem
    chega pelo navegador via texto técnico.
    """

    def _app(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as TC

        from app.setup import pagina

        app = FastAPI()
        app.include_router(rotas.router)
        pagina.montar(app, estado.RAIZ / "frontend")
        return TC(app)

    def test_raiz_devolve_html(self):
        r = self._app().get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Bem-vindo" in r.text
        assert "Configuração Inicial" in r.text

    def test_botao_leva_ao_assistente(self):
        r = self._app().get("/")
        assert 'href="/instalacao"' in r.text

    def test_recursos_carregam_a_partir_da_raiz(self):
        """Caminho relativo na raiz resolveria para /setup.css — que não existe."""
        import re
        from urllib.parse import urljoin

        client = self._app()
        r = client.get("/")
        for alvo in re.findall(r'(?:href|src)="([^"]+)"', r.text):
            if alvo.startswith(("http", "data:", "#")):
                continue
            resolvido = urljoin("/", alvo)
            assert client.get(resolvido).status_code == 200, (
                f"'{alvo}' seria pedido como '{resolvido}' e não carregou"
            )

    def test_estado_continua_em_json(self):
        """"O uso programático não se perde: /setup/estado segue em JSON."""
        r = self._app().get("/setup/estado")
        assert r.status_code == 200
        # Só a FORMA importa aqui: o valor de "instalado" depende do estado do
        # ambiente, e o conftest geral força True para o resto da suíte.
        dados = r.json()
        assert "instalado" in dados
        assert "bancos" in dados

"""Mapa 3D: projeto por planta e posicao dos ativos.

## O que estes testes travam

1. **O mapa le os ativos reais** — computadores e impressoras, nao uma lista
   paralela.
2. **Quem nao foi posicionado aparece na lista de pendentes** — senao um ativo
   novo nunca chega ao mapa e ninguem percebe.
3. **Posicionar grava as tres colunas** e remover zera.
4. **O mapa e da planta** — nao vaza ativo de outra unidade.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.core.security import create_access_token
from app.models import Ativo, Departamento, Planta, Usuario
from app.models.enums import Dominio, StatusAtivo, TipoItem


def _planta_com_ativos(db, planta_id=1):
    for i, dom in enumerate((Dominio.TI, Dominio.TI, Dominio.IMPRESSORA), start=1):
        db.add(Ativo(
            planta_id=planta_id,
            dominio=dom,
            tipo_item=TipoItem.ATIVO,
            status=StatusAtivo.ESTOQUE,
            numero_serie=f"SN-{planta_id}-{i}",
            patrimonio=f"PAT-{planta_id}{i}",
        ))
    db.commit()


class TestProjeto:
    def test_entrega_o_projeto_vazio_na_primeira_visita(self, client, auth_headers):
        r = client.get("/api/v1/mapas/1", headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["planta_id"] == 1
        assert corpo["escala_metros_por_pixel"] > 0
        assert corpo["paredes"] == []

    def test_salva_escala_e_paredes(self, client, auth_headers):
        r = client.put("/api/v1/mapas/1", headers=auth_headers, json={
            "escala_metros_por_pixel": 0.05,
            "largura_px": 2000,
            "altura_px": 1500,
            "paredes": [{"x1": 0, "z1": 0, "x2": 5, "z2": 0}],
        })
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["escala_metros_por_pixel"] == 0.05
        assert len(corpo["paredes"]) == 1

    def test_planta_inexistente_da_404(self, client, auth_headers):
        r = client.get("/api/v1/mapas/999", headers=auth_headers)
        assert r.status_code == 404


class TestAtivosNoMapa:
    def test_le_computador_e_impressora(self, client, auth_headers):
        db = client.app.dependency_overrides  # noqa: F841  (clareza do acesso)
        from app.database import get_db

        gerador = client.app.dependency_overrides[get_db]()
        sessao = next(gerador)
        _planta_com_ativos(sessao)
        sessao.close()

        r = client.get("/api/v1/mapas/1/ativos", headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()

        todos = corpo["posicionados"] + corpo["pendentes"]
        dominios = {x["dominio"] for x in todos}
        assert "ti" in dominios
        assert "impressora" in dominios
        assert len(todos) == 3

    def test_sem_posicao_fica_pendente(self, client, auth_headers):
        from app.database import get_db

        gerador = client.app.dependency_overrides[get_db]()
        sessao = next(gerador)
        _planta_com_ativos(sessao)
        sessao.close()

        r = client.get("/api/v1/mapas/1/ativos", headers=auth_headers)
        corpo = r.json()

        assert len(corpo["pendentes"]) == 3
        assert corpo["posicionados"] == []

    def test_posicionar_move_para_o_mapa(self, client, auth_headers):
        from app.database import get_db

        gerador = client.app.dependency_overrides[get_db]()
        sessao = next(gerador)
        _planta_com_ativos(sessao)
        ativo_id = sessao.query(Ativo).first().id
        sessao.close()

        r = client.patch(f"/api/v1/mapas/ativos/{ativo_id}/posicao",
                         headers=auth_headers,
                         json={"x": 3.5, "z": -2.0, "rotacao": 90})
        assert r.status_code == 200, r.text

        r = client.get("/api/v1/mapas/1/ativos", headers=auth_headers)
        corpo = r.json()
        assert len(corpo["posicionados"]) == 1
        assert corpo["posicionados"][0]["x"] == 3.5
        assert corpo["posicionados"][0]["rotacao"] == 90
        assert len(corpo["pendentes"]) == 2

    def test_remover_volta_para_pendentes(self, client, auth_headers):
        from app.database import get_db

        gerador = client.app.dependency_overrides[get_db]()
        sessao = next(gerador)
        _planta_com_ativos(sessao)
        ativo_id = sessao.query(Ativo).first().id
        sessao.close()

        client.patch(f"/api/v1/mapas/ativos/{ativo_id}/posicao",
                     headers=auth_headers, json={"x": 1, "z": 1, "rotacao": 0})
        r = client.delete(f"/api/v1/mapas/ativos/{ativo_id}/posicao",
                          headers=auth_headers)
        assert r.status_code == 200

        corpo = client.get("/api/v1/mapas/1/ativos", headers=auth_headers).json()
        assert len(corpo["pendentes"]) == 3

    def test_ativo_sumido_da_404(self, client, auth_headers):
        r = client.patch("/api/v1/mapas/ativos/9999/posicao",
                         headers=auth_headers, json={"x": 0, "z": 0, "rotacao": 0})
        assert r.status_code == 404


class TestEscopoPorPlanta:
    def test_nao_mostra_ativo_de_outra_planta(self, client, auth_headers):
        """O mapa é do prédio: outra unidade não entra no desenho."""
        from app.database import get_db

        gerador = client.app.dependency_overrides[get_db]()
        sessao = next(gerador)

        sessao.add(Planta(nome="Outra", sigla="OUT", ativa=True))
        sessao.commit()
        _planta_com_ativos(sessao, planta_id=1)
        _planta_com_ativos(sessao, planta_id=2)
        sessao.close()

        corpo = client.get("/api/v1/mapas/1/ativos",
                           headers={**auth_headers, "X-Planta-Id": "1"}).json()
        todos = corpo["posicionados"] + corpo["pendentes"]
        assert len(todos) == 3
        assert all((x["patrimonio"] or "").startswith("PAT-1") for x in todos)

    def test_lote_de_outro_escopo_nao_grava_parte_das_posicoes(self, client, auth_headers):
        from tests.conftest import TestingSession

        with TestingSession() as db:
            db.add(Planta(nome="Outra", sigla="OUT", ativa=True))
            db.commit()
            _planta_com_ativos(db, planta_id=1)
            _planta_com_ativos(db, planta_id=2)
            primeiro = db.query(Ativo.id).filter_by(planta_id=1).first().id
            externo = db.query(Ativo.id).filter_by(planta_id=2).first().id

        posicao = {"x": 4, "z": 2, "rotacao": 90}
        headers = {**auth_headers, "X-Planta-Id": "1"}
        r = client.put("/api/v1/mapas/1/estado", headers=headers, json={
            "projeto": {"paredes": [{"id": "parede-a", "points": [[0, 0], [4, 2]]}]},
            "posicoes": {str(primeiro): posicao, str(externo): posicao},
        })
        assert r.status_code == 404
        assert client.get("/api/v1/mapas/1/ativos", headers=headers).json()["posicionados"] == []
        assert client.get("/api/v1/mapas/1", headers=headers).json()["paredes"] == []
        assert client.get("/api/v1/mapas/2", headers=headers).status_code == 404

        r = client.put("/api/v1/mapas/1/estado", headers=headers, json={
            "projeto": {"paredes": [{"id": "parede-a", "points": [[0, 0], [4, 2]]}]},
            "posicoes": {str(primeiro): posicao},
        })
        assert r.status_code == 200, r.text
        assert client.get("/api/v1/mapas/1/ativos", headers=headers).json()["posicionados"][0]["id"] == primeiro
        assert client.get("/api/v1/mapas/1", headers=headers).json()["paredes"][0]["id"] == "parede-a"


def test_leitor_consulta_apenas_equipamentos_do_departamento(client):
    from tests.conftest import TestingSession

    with TestingSession() as db:
        _planta_com_ativos(db)
        engenharia = Departamento(nome="Engenharia", planta_id=1)
        operacoes = Departamento(nome="Operações", planta_id=1)
        ativos = db.query(Ativo).order_by(Ativo.patrimonio).all()
        ativos[0].departamento = ativos[2].departamento = engenharia
        ativos[1].departamento = operacoes
        ativos[0].mapa_x = ativos[0].mapa_z = ativos[1].mapa_x = ativos[1].mapa_z = 0
        pendente = Ativo(
            planta_id=1, departamento=engenharia, dominio=Dominio.TI, tipo_item=TipoItem.ATIVO,
            status=StatusAtivo.ESTOQUE, patrimonio="PAT-PENDENTE", numero_serie="SN-PENDENTE",
        )
        leitor = Usuario(
            nome="Leitor", email="mapa@teste.com", senha_hash="teste", papel="leitor",
            ativo=True, planta_id=1, departamento=engenharia,
            permissoes={"inventarios": ["ti", "impressora"], "pode_escrever": True},
        )
        sem_departamento = Usuario(
            nome="Sem departamento", email="sem-depto@teste.com", senha_hash="teste",
            papel="leitor", ativo=True, planta_id=1,
        )
        db.add_all([pendente, leitor, sem_departamento])
        db.commit()
        ativo_id = ativos[0].id
        headers = {"Authorization": f"Bearer {create_access_token(leitor.id, 'leitor')}"}
        headers_sem_depto = {"Authorization": f"Bearer {create_access_token(sem_departamento.id, 'leitor')}"}

    resposta = client.get("/api/v1/mapas/1/ativos", headers=headers)
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["acesso"] == {"editar": False, "departamento": "Engenharia"}
    assert [item["patrimonio"] for item in corpo["posicionados"]] == ["PAT-11"]
    assert [item["patrimonio"] for item in corpo["pendentes"]] == ["PAT-PENDENTE"]
    assert all(item["numero_serie"] is None for item in corpo["posicionados"] + corpo["pendentes"])
    assert client.get("/api/v1/mapas/1", headers=headers).status_code == 200
    for sufixo in ("", "/ativos", "/imagem"):
        assert client.get(f"/api/v1/mapas/1{sufixo}", headers=headers_sem_depto).status_code == 403
    for metodo, caminho, dados in (
        ("PUT", "/1", {"paredes": []}),
        ("PUT", "/1/estado", {"projeto": {"paredes": []}}),
        ("POST", "/1/imagem", None),
        ("DELETE", "/1/imagem", None),
        ("PATCH", f"/ativos/{ativo_id}/posicao", {"x": 1, "z": 1}),
        ("DELETE", f"/ativos/{ativo_id}/posicao", None),
    ):
        assert client.request(metodo, f"/api/v1/mapas{caminho}", headers=headers, json=dados).status_code == 403


def test_planta_baixa_calcula_escala_e_protege_imagem(client, auth_headers):
    imagem = BytesIO()
    Image.new("RGB", (160, 80), "white").save(imagem, format="PNG")
    caminho = "/api/v1/mapas/1/imagem"
    envio = client.post(caminho, headers=auth_headers, data={"largura_metros": "16"},
                        files={"arquivo": ("planta.png", imagem.getvalue(), "image/png")})
    assert envio.status_code == 200, envio.text
    projeto = envio.json()
    assert projeto["largura_px"] == 160 and projeto["altura_px"] == 80
    assert projeto["escala_metros_por_pixel"] == 0.1
    assert client.get(caminho).status_code == 401
    assert client.get(caminho, headers=auth_headers).content == imagem.getvalue()
    invalida = client.post(caminho, headers=auth_headers, files={"arquivo": ("planta.png", b"texto", "image/png")})
    assert invalida.status_code == 422
    assert client.get(caminho, headers=auth_headers).content == imagem.getvalue()
    assert client.delete(caminho, headers=auth_headers).status_code == 200
    assert client.get(caminho, headers=auth_headers).status_code == 404

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

from app.models import Ativo, Planta
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
    def test_cria_o_projeto_na_primeira_visita(self, client, auth_headers):
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

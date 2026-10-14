"""Certificado de descarte — emissão e conferência.

O motor (`descarte_service`) já existia com 30 testes. O que faltava era
**ligar**: emitir o certificado a partir de um ativo real, e conferir um
documento apresentado depois.

Duas coisas precisam estar certas:

1. **A validação por motivo.** Venda exige nota fiscal; sucata exige licença
   ambiental do receptor; perda exige número de ocorrência. Emitir sem isso
   produz um documento sem valor.
2. **O selo denuncia alteração.** Conferir recalcula e compara.
"""
from __future__ import annotations

from app.database import get_db
from app.main import app
from app.models.core import Ativo, Categoria, Planta
from app.services import descarte_service as servico


def _db(client):
    return next(app.dependency_overrides[get_db]())


def _ativo(client, patrimonio="DESC-1", categoria=None, numero_serie=None):
    db = _db(client)
    planta = Planta(nome="Planta T", sigla="T")
    db.add(planta)
    db.commit()
    db.refresh(planta)

    categoria_id = None
    if categoria:
        cat = Categoria(nome=categoria)
        db.add(cat)
        db.commit()
        db.refresh(cat)
        categoria_id = cat.id

    a = Ativo(dominio="ti", tipo_item="ativo", patrimonio=patrimonio,
              numero_serie=numero_serie or f"NS-{patrimonio}",
              planta_id=planta.id, status="estoque", categoria_id=categoria_id)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a.id


def _venda(ativo_id, **campos):
    base = {
        "ativo_id": ativo_id, "motivo": "venda",
        "destinador_nome": "Leilão Silva",
        "destinador_documento": "12.345.678/0001-90",
        "documento_fiscal": "NF-e 1234",
    }
    base.update(campos)
    return base


class TestMotivos:
    def test_lista_os_motivos(self, client, auth_headers):
        r = client.get("/api/v1/descarte/motivos", headers=auth_headers)
        assert r.status_code == 200, r.text
        valores = {m["valor"] for m in r.json()["motivos"]}
        assert valores == set(servico.MOTIVOS)

    def test_cada_motivo_traz_o_que_exige_e_o_fundamento(self, client, auth_headers):
        """A tela monta o formulário a partir daqui — e o fundamento é o que
        dá valor jurídico ao documento."""
        r = client.get("/api/v1/descarte/motivos", headers=auth_headers)
        for m in r.json()["motivos"]:
            assert "exige" in m
            assert m["fundamento"], f"{m['valor']} sem fundamento"

    def test_exige_autenticacao(self, client):
        assert client.get("/api/v1/descarte/motivos").status_code == 401


class TestEmissao:
    def test_emite_venda_completa(self, client, auth_headers):
        r = client.post("/api/v1/descarte", json=_venda(_ativo(client)), headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["conferido"] is True
        assert d["certificado"]["numero"]
        assert d["texto"]

    def test_venda_sem_nota_fiscal_e_recusada(self, client, auth_headers):
        """Saída com nota fiscal: sem ela, o documento não vale."""
        corpo = _venda(_ativo(client))
        corpo.pop("documento_fiscal")
        r = client.post("/api/v1/descarte", json=corpo, headers=auth_headers)
        assert r.status_code == 400
        assert "documento_fiscal" in str(r.json()["detail"])

    def test_sucata_exige_licenca_do_receptor(self, client, auth_headers):
        """PNRS Art. 33 — quem recebe resíduo eletrônico precisa de licença."""
        r = client.post("/api/v1/descarte", json={
            "ativo_id": _ativo(client), "motivo": "sucata",
            "destinador_nome": "Recicladora X",
        }, headers=auth_headers)
        assert r.status_code == 400
        detalhe = str(r.json()["detail"])
        assert "destinador_cnpj" in detalhe or "destinador_licenca" in detalhe

    def test_perda_exige_numero_de_ocorrencia(self, client, auth_headers):
        r = client.post("/api/v1/descarte", json={
            "ativo_id": _ativo(client), "motivo": "perda",
        }, headers=auth_headers)
        assert r.status_code == 400
        assert "numero_ocorrencia" in str(r.json()["detail"])

    def test_transferencia_nao_exige_nada(self, client, auth_headers):
        r = client.post("/api/v1/descarte", json={
            "ativo_id": _ativo(client), "motivo": "transferencia",
        }, headers=auth_headers)
        assert r.status_code == 200, r.text

    def test_o_erro_lista_TODAS_as_pendencias(self, client, auth_headers):
        """Uma por tentativa obrigaria a pessoa a descobrir o formulário
        errando."""
        r = client.post("/api/v1/descarte", json={
            "ativo_id": _ativo(client), "motivo": "sucata",
        }, headers=auth_headers)
        pendencias = r.json()["detail"]["pendencias"]
        assert len(pendencias) >= 2, pendencias

    def test_o_erro_traz_o_fundamento(self, client, auth_headers):
        """Quem preenche precisa saber POR QUE o campo é exigido."""
        r = client.post("/api/v1/descarte", json={
            "ativo_id": _ativo(client), "motivo": "sucata",
        }, headers=auth_headers)
        assert r.json()["detail"]["fundamento"]

    def test_ativo_inexistente_da_404(self, client, auth_headers):
        r = client.post("/api/v1/descarte", json=_venda(99999), headers=auth_headers)
        assert r.status_code == 404

    def test_campo_desconhecido_e_recusado(self, client, auth_headers):
        """`extra=forbid`: erro de digitação não vira campo ignorado."""
        corpo = _venda(_ativo(client), destinatario="errado")
        r = client.post("/api/v1/descarte", json=corpo, headers=auth_headers)
        assert r.status_code == 422

    def test_o_responsavel_vem_do_usuario_logado(self, client, auth_headers):
        r = client.post("/api/v1/descarte", json=_venda(_ativo(client)), headers=auth_headers)
        assert r.json()["certificado"].get("responsavel")

    def test_o_patrimonio_entra_no_certificado(self, client, auth_headers):
        # O certificado ANINHA os dados: `equipamento` traz o bem, e
        # `destinacao` traz para onde foi. Achatado, um documento com dois
        # blocos ficaria ambíguo (`nome` de quem?).
        aid = _ativo(client, patrimonio="PAT-999", numero_serie="NS-PAT-999")
        r = client.post("/api/v1/descarte", json=_venda(aid), headers=auth_headers)
        assert r.json()["certificado"]["equipamento"]["patrimonio"] == "PAT-999"

    def test_o_destinatario_entra_na_destinacao(self, client, auth_headers):
        corpo = _venda(_ativo(client))
        r = client.post("/api/v1/descarte", json=corpo, headers=auth_headers)
        dest = r.json()["certificado"]["destinacao"]
        assert dest["destinador_nome"] == corpo["destinador_nome"]
        assert dest["documento_fiscal"] == corpo["documento_fiscal"]

    def test_logistica_reversa_detectada_pela_categoria(self, client, auth_headers):
        """O operador não precisa saber de cor quais resíduos exigem PNRS."""
        aid = _ativo(client, categoria="Eletrônico")
        r = client.post("/api/v1/descarte", json=_venda(aid), headers=auth_headers)
        assert r.json()["certificado"].get("logistica_reversa") is True

    def test_categoria_comum_nao_exige_logistica(self, client, auth_headers):
        aid = _ativo(client, categoria="Mobiliário")
        r = client.post("/api/v1/descarte", json=_venda(aid), headers=auth_headers)
        assert r.json()["certificado"].get("logistica_reversa") is False


class TestConferencia:
    def _certificado(self, client, headers):
        r = client.post("/api/v1/descarte", json=_venda(_ativo(client)), headers=headers)
        return r.json()["certificado"]

    def test_certificado_intacto_confere(self, client, auth_headers):
        cert = self._certificado(client, auth_headers)
        r = client.post("/api/v1/descarte/conferir", json=cert, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["integro"] is True

    def test_alteracao_do_conteudo_e_detectada(self, client, auth_headers):
        """É o que o selo existe para pegar: editar o destino num documento
        já emitido e reapresentá-lo."""
        cert = self._certificado(client, auth_headers)
        cert["destinador_nome"] = "Outro Destinatário"

        r = client.post("/api/v1/descarte/conferir", json=cert, headers=auth_headers)
        assert r.json()["integro"] is False
        assert "NÃO CONFERE" in r.json()["mensagem"]

    def test_corpo_vazio_e_recusado(self, client, auth_headers):
        r = client.post("/api/v1/descarte/conferir", json={}, headers=auth_headers)
        assert r.status_code == 400

    def test_documento_de_fora_nao_confere(self, client, auth_headers):
        """Um documento inventado não pode passar por emitido pelo sistema."""
        r = client.post("/api/v1/descarte/conferir", json={
            "numero": "FAKE-1", "motivo": "venda", "patrimonio": "X", "numero_serie": "NS-X",
        }, headers=auth_headers)
        assert r.json()["integro"] is False

    def test_exige_autenticacao(self, client):
        assert client.post("/api/v1/descarte/conferir", json={}).status_code == 401

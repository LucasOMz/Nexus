import hashlib
import hmac
import json
from base64 import b64encode
from datetime import timedelta
from io import BytesIO

from PIL import Image
from pypdfium2 import PdfDocument
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select

from app.config import settings
from app.models.agente import TokenAgente
from app.models.core import ConfiguracaoSistema
from app.models.termo_entrega import EntregaTermo
from app.routers import termo_entrega as rotas
from app.services import email_service, ldap_service
from app.services.agente_service import hash_segredo
from app.services.termo_entrega import agora, hash_codigo
from tests.conftest import TestingSession


def _pdf():
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(595, 842))
    canvas.drawString(80, 750, "TERMO DE ENTREGA QA")
    canvas.drawString(80, 655, "Matrícula")
    canvas.drawString(80, 568, "Li o termo")
    canvas.drawString(80, 488, "Assinatura")
    canvas.save()
    return buffer.getvalue()


def _campos():
    return [{"id": id_, "tipo": tipo, "rotulo": rotulo, "pagina": 1, "x": 30, "y": y, "largura": 40, "altura": 5}
            for id_, tipo, rotulo, y in (("id", "matricula", "Matrícula", 20), ("ok", "leitura", "Li o termo", 30),
                                        ("assinatura", "assinatura", "Assinatura", 40))]


def _configurar(client, headers, monkeypatch, tmp_path, exigir_agente=False):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    monkeypatch.setattr(rotas._TENTATIVAS, "is_allowed", lambda _: True)
    monkeypatch.setattr(rotas._AGENTE, "is_allowed", lambda _: True)
    monkeypatch.setattr(email_service, "pronto", lambda _: (True, "OK"))
    emails = []
    monkeypatch.setattr(email_service, "enviar", lambda db, email, assunto, texto: emails.append((email, texto)))
    monkeypatch.setattr(ldap_service, "buscar_usuario", lambda cfg, login: (
        True, "OK", {"login": login, "nome": "João Exemplo", "email": "joao@empresa.com"},
    ))
    monkeypatch.setattr(ldap_service, "autenticar", lambda cfg, login, senha: ldap_service.ResultadoLDAP(
        senha == "senha-de-teste", "OK", login=login, email="joao@empresa.com",
    ))
    with TestingSession() as db:
        cfg = db.get(ConfiguracaoSistema, 1) or ConfiguracaoSistema(id=1)
        cfg.ldap_ativo = True
        cfg.ldap_servidor = "dc.empresa.local"
        cfg.ldap_base_dn = "DC=empresa,DC=local"
        db.add(cfg)
        db.commit()
    config = {"nome": "Termo QA", "url_publica": "https://nexus.empresa.com", "prazo_horas": 12,
              "exigir_agente": exigir_agente, "campos": _campos()}
    salvo = client.put("/api/v1/admin/termo-entrega", data={"configuracao": json.dumps(config)},
                       files={"arquivo": ("qa.pdf", _pdf(), "application/pdf")}, headers=headers)
    assert salvo.status_code == 200, salvo.text
    ativo_res = client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-TERMO", "numero_serie": "QA-TERMO"}, headers=headers)
    assert ativo_res.status_code == 201, ativo_res.text
    ativo_id = ativo_res.json()["id"]
    atribuir = client.post(f"/api/v1/ativos/{ativo_id}/atribuir", json={"login_ad": "joao"}, headers=headers)
    assert atribuir.status_code == 200, atribuir.text
    rota = f"/api/v1/ativos/{ativo_id}/termo-entrega"
    termo_id = client.get(rota, headers=headers).json()["termo_atual"]
    return rota, termo_id, ativo_id, emails


def _enviar(client, headers, rota, termo_id, emails):
    preparo = client.post(f"{rota}/{termo_id}/preparar", headers=headers)
    assert preparo.json()["email"] == "joao@empresa.com"
    assert client.post(f"{rota}/{termo_id}/enviar", json={"email": "outro@empresa.com"}, headers=headers).status_code == 409
    envio = client.post(f"{rota}/{termo_id}/enviar", json={"email": "joao@empresa.com"}, headers=headers)
    assert envio.status_code == 201, envio.text
    codigo = emails[0][1].split("termo-entrega.html#")[1].strip()
    return envio.json()["id"], {"Authorization": f"Bearer {codigo}"}


def _autenticar(client, convite):
    rota = "/api/v1/termo-entrega"
    assert client.get(rota + "/pagina/1", headers=convite).status_code == 401
    assert client.post(rota + "/autenticar", headers=convite,
                       json={"login": "outro", "senha": "senha-de-teste"}).status_code == 401
    identidade = client.post(rota + "/autenticar", headers=convite, json={"login": "joao", "senha": "senha-de-teste"})
    assert identidade.status_code == 200, identidade.text
    return {**convite, "X-Termo-Sessao": identidade.json()["sessao"]}


def test_assinatura_ad_sem_agente_pdf_e_link_reaberto(client, auth_headers, monkeypatch, tmp_path):
    rota, termo_id, ativo_id, emails = _configurar(client, auth_headers, monkeypatch, tmp_path)
    entrega_id, convite = _enviar(client, auth_headers, rota, termo_id, emails)
    sessao = _autenticar(client, convite)
    assert client.get("/api/v1/termo-entrega/pagina/1", headers=sessao).headers["content-type"] == "image/png"
    assert client.post("/api/v1/termo-entrega/assinar", headers=sessao, json={"campos": {"id": "123", "ok": False}}).status_code == 422
    assinado = client.post("/api/v1/termo-entrega/assinar", headers=sessao, json={"campos": {"id": "123", "ok": True}})
    assert assinado.status_code == 200, assinado.text
    assert assinado.json()["estado"] == "assinado"
    pdf = client.get(f"{rota}/{entrega_id}/pdf", headers=auth_headers).content
    lido = PdfDocument(pdf)
    try:
        assert len(lido) == 2
        folha = lido[0].get_textpage().get_text_range()
        assert "123" in folha and "João Exemplo" in folha
        assert "Aceite validado pelo AD" in lido[1].get_textpage().get_text_range()
    finally:
        lido.close()
    item = client.get(rota, headers=auth_headers).json()["entregas"][0]
    assert item["comprovante"]["hash_pdf"] == hashlib.sha256(pdf).hexdigest()
    assert client.get("/api/v1/ativos", headers=auth_headers).json()["items"][0]["termo_entrega_assinado"]
    assert client.get(f"/api/v1/ativos/{ativo_id}", headers=auth_headers).json()["termo_entrega_assinado"]
    with TestingSession() as db:
        db.get(EntregaTermo, entrega_id).expira_em = agora() - timedelta(hours=1)
        db.commit()
    assert client.get("/api/v1/termo-entrega/estado", headers=convite).json()["estado"] == "assinado"
    assert client.post("/api/v1/termo-entrega/assinar", headers=sessao, json={"campos": {"id": "123", "ok": True}}).status_code == 409


def test_confirmacao_do_agente_exige_credencial_do_ativo_e_prova_unica(client, auth_headers, monkeypatch, tmp_path):
    rota, termo_id, ativo_id, emails = _configurar(client, auth_headers, monkeypatch, tmp_path, exigir_agente=True)
    token = "credencial-do-agente-de-teste"
    outro_token = "credencial-de-outra-maquina"
    outro_ativo = client.post("/api/v1/ativos", json={"dominio": "ti", "numero_serie": "OUTRO-QA"},
                              headers=auth_headers).json()["id"]
    with TestingSession() as db:
        db.add(TokenAgente(ativo_id=ativo_id, token_hash=hash_segredo(token), prefixo="teste"))
        db.add(TokenAgente(ativo_id=outro_ativo, token_hash=hash_segredo(outro_token), prefixo="outro"))
        db.commit()
    entrega_id, convite = _enviar(client, auth_headers, rota, termo_id, emails)
    sessao = _autenticar(client, convite)
    aceito = client.post("/api/v1/termo-entrega/assinar", headers=sessao, json={"campos": {"id": "456", "ok": True}})
    assert aceito.status_code == 200, aceito.text
    assert aceito.json()["estado"] == "aguardando_agente"
    assert client.get(f"{rota}/{entrega_id}/pdf", headers=auth_headers).status_code == 404
    codigo = aceito.json()["codigo"]
    identidade = "EMPRESA\\joao"
    assinatura = hmac.digest(token.encode(), f"nexus.termo.v1\n{codigo}\n{identidade}".encode(), "sha256").hex()
    api = "/api/v1/agente/termo-entrega/confirmar"
    headers = {"Authorization": f"Bearer {token}"}
    dados = {"codigo": codigo, "usuario_windows": identidade, "assinatura": assinatura}
    assert client.post(api, headers=headers, json={**dados, "assinatura": "0" * 64}).status_code == 401
    outra_assinatura = hmac.digest(outro_token.encode(), f"nexus.termo.v1\n{codigo}\n{identidade}".encode(), "sha256").hex()
    assert client.post(api, headers={"Authorization": f"Bearer {outro_token}"},
                       json={**dados, "assinatura": outra_assinatura}).status_code == 404
    res = client.post(api, headers=headers, json=dados)
    assert res.status_code == 200, res.text
    assert client.post(api, headers=headers, json=dados).status_code == 404
    assert client.get(rota, headers=auth_headers).json()["entregas"][0]["comprovante"]["agente"]["ativo_id"] == ativo_id


def test_link_pendente_expira_e_pode_ser_reenviado_com_novo_codigo(client, auth_headers, monkeypatch, tmp_path):
    rota, termo_id, _, emails = _configurar(client, auth_headers, monkeypatch, tmp_path)
    entrega_id, convite = _enviar(client, auth_headers, rota, termo_id, emails)
    with TestingSession() as db:
        db.get(EntregaTermo, entrega_id).expira_em = agora() - timedelta(hours=1)
        db.commit()
    assert client.get("/api/v1/termo-entrega/estado", headers=convite).json()["estado"] == "expirado"
    assert client.post("/api/v1/termo-entrega/autenticar", headers=convite,
                       json={"login": "joao", "senha": "senha-de-teste"}).status_code == 409
    novo = client.post(f"{rota}/{termo_id}/enviar", json={"email": "joao@empresa.com"}, headers=auth_headers)
    assert novo.status_code == 201 and len(emails) == 2 and emails[0] != emails[1]
    token = emails[-1][1].split("termo-entrega.html#")[1].strip()
    sessao = _autenticar(client, {"Authorization": f"Bearer {token}"})
    png = BytesIO()
    Image.new("RGBA", (100, 40), (10, 30, 84, 255)).save(png, "PNG")
    res = client.post("/api/v1/termo-entrega/assinar", headers=sessao, json={
        "campos": {"id": "1234", "ok": True}, "assinatura_png": b64encode(png.getvalue()).decode(),
    })
    assert res.status_code == 200, res.text
    assert client.get(f"{rota}/{novo.json()['id']}/pdf", headers=auth_headers).content.startswith(b"%PDF-")


def test_em_producao_aceita_credenciais_do_ad_pela_origem_configurada(client, auth_headers, monkeypatch, tmp_path):
    rota, termo_id, _, emails = _configurar(client, auth_headers, monkeypatch, tmp_path)
    _, convite = _enviar(client, auth_headers, rota, termo_id, emails)
    monkeypatch.setattr(settings, "env", "production")
    body = {"login": "joao", "senha": "senha-de-teste"}
    endpoint = "/api/v1/termo-entrega/autenticar"
    assert client.post(endpoint, headers={**convite, "Origin": "http://nexus.empresa.com"}, json=body).status_code == 403
    autorizado = client.post(endpoint, headers={**convite, "Origin": "https://nexus.empresa.com"}, json=body)
    assert autorizado.status_code == 200, autorizado.text

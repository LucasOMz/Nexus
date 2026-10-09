"""Testes da administração: dispositivos de impressão e banco de fotos."""
from __future__ import annotations

# Conteúdo mínimo com assinatura PNG (o endpoint valida o content-type).
PNG_FALSO = b"\x89PNG\r\n\x1a\n" + b"conteudo-de-teste"


def test_dispositivo_compartilhamento(client, auth_headers):
    payload = {
        "nome": "Recepcao",
        "tipo": "compartilhamento",
        "hostname": "RTAT0001",
        "compartilhamento": "\\\\RTAT0001\\sip",
        "formato": "zpl",
        "padrao": True,
    }
    res = client.post("/api/v1/admin/dispositivos", json=payload, headers=auth_headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["hostname"] == "RTAT0001"
    assert body["compartilhamento"] == "\\\\RTAT0001\\sip"
    assert body["padrao"] is True

    lista = client.get("/api/v1/admin/dispositivos", headers=auth_headers).json()
    assert len(lista) == 1


def test_dispositivo_tipo_invalido(client, auth_headers):
    res = client.post(
        "/api/v1/admin/dispositivos",
        json={"nome": "X", "tipo": "invalido"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_apenas_admin_gerencia_dispositivos(client, auth_headers):
    client.post(
        "/api/v1/usuarios",
        json={"nome": "Op", "email": "op2@teste.com", "papel": "leitor", "senha": "senha123"},
        headers=auth_headers,
    )
    tok = client.post("/api/v1/auth/login", data={"username": "op2@teste.com", "password": "senha123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    res = client.post("/api/v1/admin/dispositivos", json={"nome": "Nao pode", "tipo": "cups"}, headers=h)
    assert res.status_code == 403


def test_upload_e_vinculo_de_foto(client, auth_headers):
    ativo_id = client.post(
        "/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-FOTO"}, headers=auth_headers
    ).json()["id"]

    res = client.post(
        "/api/v1/admin/fotos",
        headers=auth_headers,
        data={"nome": "Notebook padrao", "tags": "notebook", "dominio": "ti"},
        files={"file": ("notebook.png", PNG_FALSO, "image/png")},
    )
    assert res.status_code == 201, res.text
    foto = res.json()
    assert foto["nome"] == "Notebook padrao"
    assert foto["url"].endswith("/arquivo")

    # Vincula a foto ao ativo.
    upd = client.put(f"/api/v1/ativos/{ativo_id}", json={"foto_id": foto["id"]}, headers=auth_headers)
    assert upd.status_code == 200
    assert upd.json()["foto_id"] == foto["id"]

    # A imagem exige autenticação.
    assert client.get(f"/api/v1/admin/fotos/{foto['id']}/arquivo").status_code == 401
    assert client.get(f"/api/v1/admin/fotos/{foto['id']}/arquivo", headers=auth_headers).status_code == 200


def test_upload_rejeita_nao_imagem(client, auth_headers):
    res = client.post(
        "/api/v1/admin/fotos",
        headers=auth_headers,
        data={"nome": "Arquivo ruim"},
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert res.status_code == 400

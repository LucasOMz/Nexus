"""Testes da administração: dispositivos de impressão e banco de fotos."""
from __future__ import annotations

import re
from io import BytesIO

import pytest
from PIL import Image

from app.core import uploads
from tests.conftest import marcar_primeiro_acesso_concluido


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
    marcar_primeiro_acesso_concluido("op2@teste.com")
    tok = client.post("/api/v1/auth/login", data={"username": "op2@teste.com", "password": "senha123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    res = client.post("/api/v1/admin/dispositivos", json={"nome": "Nao pode", "tipo": "cups"}, headers=h)
    assert res.status_code == 403


def test_upload_e_vinculo_de_foto(client, auth_headers):
    imagem = BytesIO()
    Image.new("RGB", (12, 10), "white").save(imagem, format="PNG")
    png = imagem.getvalue()
    ativo_id = client.post(
        "/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-FOTO", "numero_serie": "NS-TI-FOTO"}, headers=auth_headers
    ).json()["id"]

    res = client.post(
        "/api/v1/admin/fotos",
        headers=auth_headers,
        data={"nome": "Notebook padrao", "tags": "notebook", "dominio": "ti"},
        files={"file": ("notebook.jpg", png, "application/octet-stream")},
    )
    assert res.status_code == 201, res.text
    foto = res.json()
    assert foto["nome"] == "Notebook padrao"
    assert foto["url"].endswith("/arquivo")

    # Vincula a foto ao ativo.
    upd = client.put(f"/api/v1/ativos/{ativo_id}", json={"foto_id": foto["id"]}, headers=auth_headers)
    assert upd.status_code == 200
    assert upd.json()["foto_id"] == foto["id"]

    # Somente o cabeçalho autentica o download, inclusive para URLs antigas.
    url = foto["url"]
    assert client.get(url).status_code == 401
    assert client.get(url, params={"token": auth_headers["Authorization"].split()[1]}).status_code == 401
    arquivo = client.get(url, headers=auth_headers)
    assert arquivo.status_code == 200
    assert arquivo.content == png
    assert arquivo.headers["content-type"] == "image/png"
    assert arquivo.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(("nome", "conteudo", "mime"), [
    ("doc.pdf", b"%PDF-1.4", "application/pdf"),
    ("invalido.png", b"formato anunciado pelo cliente", "image/png"),
    ("desenho.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml"),
])
def test_upload_rejeita_nao_imagem(client, auth_headers, nome, conteudo, mime):
    res = client.post(
        "/api/v1/admin/fotos",
        headers=auth_headers,
        data={"nome": "Arquivo ruim"},
        files={"file": (nome, conteudo, mime)},
    )
    assert res.status_code == 400


def test_upload_rejeita_arquivo_acima_do_limite(client, auth_headers, monkeypatch):
    from app.routers import admin

    monkeypatch.setattr(admin, "MAX_FOTO", 8)
    res = client.post(
        "/api/v1/admin/fotos", headers=auth_headers, data={"nome": "Foto grande"},
        files={"file": ("grande.png", b"x" * 9, "image/png")},
    )
    assert res.status_code == 413


def test_limite_de_corpo_interrompe_upload_sem_content_length(client, auth_headers, monkeypatch):
    monkeypatch.setattr(uploads, "_ROTAS", ((re.compile("/api/v1/admin/fotos"), 256),))
    monkeypatch.setattr(uploads, "MIB", 128)
    blocos = iter([
        b'--teste\r\nContent-Disposition: form-data; name="file"; filename="grande.png"\r\n\r\n',
        b"x" * 500, b"\r\n--teste--\r\n",
    ])
    res = client.post("/api/v1/admin/fotos", content=blocos,
                      headers={**auth_headers, "Content-Type": "multipart/form-data; boundary=teste"})
    assert res.status_code == 413, res.text

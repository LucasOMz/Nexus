"""Testes de autenticação (JWT + roles)."""
from __future__ import annotations


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

"""Cifragem simétrica para segredos gravados no banco.

Hoje é usada para a senha da conta de serviço do LDAP: guardar isso em texto
puro no banco seria um problema de segurança/compliance.

A chave é derivada do `JWT_SECRET`. Consequência importante (documentada no
README): **trocar o `JWT_SECRET` torna os valores cifrados ilegíveis** — basta
recadastrar o segredo na tela de Administração.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_PREFIXO = "enc:v1:"


def _chave() -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest())


def cifrar(texto: str | None) -> str | None:
    """Cifra um texto. Retorna None se o texto for vazio."""
    if not texto:
        return None
    token = Fernet(_chave()).encrypt(texto.encode("utf-8")).decode("ascii")
    return _PREFIXO + token


def decifrar(valor: str | None) -> str | None:
    """Decifra um texto. Valores sem o prefixo são tratados como legado (texto puro)."""
    if not valor:
        return None
    if not valor.startswith(_PREFIXO):
        return valor
    try:
        return Fernet(_chave()).decrypt(valor[len(_PREFIXO):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def esta_cifrado(valor: str | None) -> bool:
    return bool(valor) and valor.startswith(_PREFIXO)

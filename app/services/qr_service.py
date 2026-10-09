"""Serviço de QR Code com assinatura HMAC-SHA256 (assinatura configurável).

Payload assinado:
    TIATIVO:{id}:{timestamp}:{hmac_base64url}

A assinatura cobre `TIATIVO:{id}:{timestamp}`.

A leitura segue esta ordem (ver `resolver_codigo`):

1. Se o código tem o prefixo `TIATIVO:`, o **ID é extraído sempre** — é ele que
   resolve o ativo, garantindo que etiquetas já impressas continuem válidas
   mesmo que o segredo mude.
2. A assinatura é conferida contra o segredo atual **e** contra os segredos
   anteriores (`QR_HMAC_SECRETS_ANTERIORES`), permitindo trocar o segredo sem
   reimprimir etiquetas.
3. Se `QR_EXIGIR_ASSINATURA=false`, uma assinatura divergente/ausente **não
   bloqueia** a leitura (fica registrado na auditoria).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import time

import qrcode

from app.config import settings

# Prefixo mágico do payload (constante para facilitar troca futura).
QR_PREFIX = "TIATIVO"

# Prefixo das etiquetas EM BRANCO (geradas sem ativo, para cadastrar depois).
QR_PREFIX_ZERADO = "TIZERADO"

# Alfabeto sem caracteres ambíguos (sem I, O, 0 e 1), para leitura e digitação.
_ALFABETO_ZERADO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _hmac_com(segredo: str, ativo_id: int, ts: int) -> str:
    msg = f"{QR_PREFIX}:{ativo_id}:{ts}".encode()
    digest = hmac.new(segredo.encode("utf-8"), msg, hashlib.sha256).digest()
    # base64url sem padding, mais compacto para impressão térmica.
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _hmac(ativo_id: int, ts: int) -> str:
    """Assinatura com o segredo ATUAL (usada ao gerar etiquetas)."""
    return _hmac_com(settings.qr_hmac_secret, ativo_id, ts)


def build_payload(ativo_id: int, ts: int | None = None) -> str:
    """Gera o payload assinado completo."""
    ts = ts if ts is not None else int(time.time())
    return f"{QR_PREFIX}:{ativo_id}:{ts}:{_hmac(ativo_id, ts)}"


def extrair_ativo_id(codigo: str) -> int | None:
    """Extrai o ID do ativo do payload, **sem validar a assinatura**.

    Aceita tanto o formato assinado (`TIATIVO:12:1700:abc`) quanto um formato
    mais curto (`TIATIVO:12`). Retorna None se não for um payload nosso.
    """
    if not codigo or not codigo.startswith(f"{QR_PREFIX}:"):
        return None
    partes = codigo.split(":")
    if len(partes) < 2:
        return None
    try:
        return int(partes[1])
    except ValueError:
        return None


def validar_assinatura(codigo: str) -> bool:
    """Confere o HMAC contra o segredo atual e os anteriores."""
    if not codigo:
        return False
    partes = codigo.split(":")
    if len(partes) != 4 or partes[0] != QR_PREFIX:
        return False
    try:
        ativo_id = int(partes[1])
        ts = int(partes[2])
    except ValueError:
        return False
    assinatura = partes[3]
    return any(
        hmac.compare_digest(_hmac_com(segredo, ativo_id, ts), assinatura)
        for segredo in settings.segredos_qr
    )


def verify_payload(payload: str) -> int | None:
    """Valida a assinatura e retorna o id do ativo, ou None se inválida.

    Mantida para compatibilidade: é a validação estrita (assinatura obrigatória),
    usada pelo endpoint `/qrcode/validate`.
    """
    if validar_assinatura(payload):
        return extrair_ativo_id(payload)
    return None


def resolver_codigo(codigo: str) -> tuple[int | None, bool]:
    """Resolve o ID do ativo a partir de um código lido.

    Retorna `(ativo_id, assinatura_valida)`.

    * `(12, True)`  → payload nosso com assinatura conferida
    * `(12, False)` → payload nosso, mas assinatura ausente/divergente
                      (aceito ou não conforme `QR_EXIGIR_ASSINATURA`)
    * `(None, False)` → não é um payload nosso (aí o chamador tenta
                        ID numérico / patrimônio / nº de série)
    """
    ativo_id = extrair_ativo_id(codigo)
    if ativo_id is None:
        return None, False

    assinatura_ok = validar_assinatura(codigo)
    if assinatura_ok or not settings.qr_exigir_assinatura:
        return ativo_id, assinatura_ok
    return None, False


def qr_png_bytes(payload: str, box_size: int = 8, ecc: str = "M") -> bytes:
    """Renderiza o payload como imagem PNG (bytes).

    `ecc` é o nível de correção de erro: L, M, Q ou H (maior = mais robusto a
    rasgo/sujeira, porém QR maior).
    """
    niveis = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }
    qr = qrcode.QRCode(border=2, box_size=box_size, error_correction=niveis.get(ecc.upper(), niveis["M"]))
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_png_data_url(payload: str, box_size: int = 8, ecc: str = "M") -> str:
    """Retorna o QR como data URL (para exibição no frontend)."""
    b64 = base64.b64encode(qr_png_bytes(payload, box_size, ecc)).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Etiquetas EM BRANCO (sem ativo) — `TIZERADO:{codigo}:{ts}:{hmac}`
# ---------------------------------------------------------------------------
def gerar_codigo_zerado(tamanho: int = 10) -> str:
    """Gera um código curto e legível, sem caracteres ambíguos."""
    import secrets

    return "".join(secrets.choice(_ALFABETO_ZERADO) for _ in range(tamanho))


def _hmac_zerado_com(segredo: str, codigo: str, ts: int) -> str:
    msg = f"{QR_PREFIX_ZERADO}:{codigo}:{ts}".encode()
    digest = hmac.new(segredo.encode("utf-8"), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_payload_zerado(codigo: str, ts: int | None = None) -> str:
    """Monta o payload assinado de uma etiqueta em branco."""
    ts = ts if ts is not None else int(time.time())
    assinatura = _hmac_zerado_com(settings.qr_hmac_secret, codigo, ts)
    return f"{QR_PREFIX_ZERADO}:{codigo}:{ts}:{assinatura}"


def extrair_codigo_zerado(payload: str) -> str | None:
    """Extrai o código em branco SEM validar a assinatura (None se não for um)."""
    if not payload or not payload.startswith(f"{QR_PREFIX_ZERADO}:"):
        return None
    partes = payload.split(":")
    if len(partes) < 2 or not partes[1]:
        return None
    return partes[1]


def validar_assinatura_zerado(payload: str) -> bool:
    """Confere o HMAC da etiqueta em branco (segredo atual e anteriores)."""
    if not payload:
        return False
    partes = payload.split(":")
    if len(partes) != 4 or partes[0] != QR_PREFIX_ZERADO:
        return False
    codigo, ts_texto, assinatura = partes[1], partes[2], partes[3]
    if not codigo:
        return False
    try:
        ts = int(ts_texto)
    except ValueError:
        return False
    return any(
        hmac.compare_digest(_hmac_zerado_com(segredo, codigo, ts), assinatura)
        for segredo in settings.segredos_qr
    )


def eh_payload_zerado(payload: str) -> bool:
    """True se o texto é uma etiqueta em branco (mesmo de outro sistema)."""
    return bool(payload) and payload.startswith(f"{QR_PREFIX_ZERADO}:")
